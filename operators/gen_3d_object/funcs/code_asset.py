"""Build GLB assets from declarative part specs.

Specs combine primitives and imported meshes with explicit units, transforms
and part names. Validation checks geometry, scale, orientation and provenance;
bounded revision attempts return a stop reason.

构建器只依赖 Python 3.10+ 标准库。`fit_wearable_asset`
使用一个可选的、隔离的 Blender worker 完成服装拟合与蒙皮。

几何检查改编自 https://github.com/img2threejs/img2threejs
"""

import re
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

# --------------------------------------------------------------------------
# 规范词汇表
# --------------------------------------------------------------------------

# 求值器必须支持的基本体种类。刻意保持精简：这是一套硬表面词汇表，每新增一项都是给规范出错新增一种可能。
# `lathe` 与 `extrude`承载了基于轮廓的形状（瓶身、刀刃、线脚），否则这些形状得靠几十个专门的基本体才能表达。
PRIMITIVES = ("box", "cylinder", "cone", "sphere", "torus", "lathe", "extrude")

# `mesh`是从磁盘上的 GLB 读进来的零件，而不是由公式推导出来的，通常就是云端模型生成的某个组件。
# 之所以与解析类基本体分开列出，因为它是唯一一种光看规范无法知道三角面数、尺寸范围和是否合法的种类：
# 必须真的把那个文件打开。
# 读进来之后，下游的一切都把它和box一样对待，这正是'组合'而非'整体生成'的意义：
# 生成的零件同样要摆放、测量和过检。
MESH_KIND = "mesh"

# `validate_spec` 接受的全部种类。
KINDS = PRIMITIVES + (MESH_KIND,)

# `forward` 接受的轴名。写成数据是因为网格无法声明自己朝向哪一边，
# 而每个消费方都得被告知。
AXES = ("+x", "-x", "+y", "-y", "+z", "-z")

# 规范唯一使用的单位。glTF 按定义就是米，而混用单位的规范会把
# 换算的负担甩给导入它的人。
UNITS = "metres"

# 标记左右一对之中一半的后缀，与 img2threejs [1] 保持一致，
# 这样规范才能在两者之间移植。
LEFT_SUFFIX = "-l"
RIGHT_SUFFIX = "-r"

# `(x, y, z)` 三元组中左右轴的下标：矢状面镜像唯一会取负的那根轴。
# 命名而不内联，是因为内联正是那个被记录下来的旋转 bug 的成因。
LATERAL_AXIS = 0

# 镜像坐标来自对同一个原始数值取负，所以它们要么在浮点噪声范围内吻合，
# 要么在结构上就不一致。夹在两者之间的中间状态本身就是值得看见的缺陷，
# 这就是它不该做成可调参数的原因。
MIRROR_TOLERANCE = 1e-6

# 以米计，比这更薄的零件就是一个假装成实体的平面。取十分之一毫米：
# 比游戏中会建模的任何真实钣金都薄，又比退化零件的浮点噪声更厚。
MIN_PART_THICKNESS = 1e-4

# box 的 `chamfer` 是其半尺寸的一个比例，取到 0.5 时倒角把它本要
# 削回去的那个面都吃掉了，剩下一个八面体。这里保持左闭右开，
# 好让 box 永远还留着六个面。
MAX_CHAMFER = 0.5

# lathe 轮廓的端点要多靠近轴，才算已经封盖。在单位尺度下取十分之一毫米：
# 紧到能抓出真正开口的管子，又宽到容得下写成 1e-9 而不是 0 的半径。
LATHE_AXIS_TOLERANCE = 1e-4

# 一个组合至少要自述多少个零件，`provenance` 才不会把它算成
# 披着组合外皮的生成资产。取 2，因为这是能表达一种关联关系的最小数量：
# 一块板加一个模塑垫片，是有两件答案的组合；而单个基本体摆在
# 拉取来的网格旁边，只是在整体拉取的东西上加装饰。
MIN_STATED_PARTS = 2

# 组合出的高度可以偏离声明值多远，而规范和它声明的尺寸仍在描述同一个物体。
# 25% 足以容忍一个姿势或一个没盖严的盖子；超出这个范围两者必有一错。
SCALE_TOLERANCE = 0.25

# 某个用途下合理的高度区间（米），只用来抓数量级错误——比如一扇 30 厘米的门、
# 一支 12 米的步枪。区间刻意放宽：这道关是给放错的小数点准备的，
# 不是给美术方向准备的。
PLAUSIBLE_HEIGHT_M: dict[str, tuple[float, float]] = {
    "avatar": (0.3, 4.0),
    "weapon": (0.05, 3.0),
    "prop": (0.02, 6.0),
    "scenery": (0.05, 40.0),
    "landmark": (0.5, 200.0),
}

# 路由策略，import 它们是为了触发注册副作用。
#
# 下面的决策委托给已注册的策略，而注册它们的各个包自己拥有各自领域的
# 词汇表。声明与解析方式见 `code_asset_templates.routing`。
from operators.gen_3d_object.funcs import code_asset_templates as _templates  # noqa: F401
from operators.gen_3d_object.funcs.code_asset_templates import routing as _routing


class SpecError(ValueError):
    """规范无法求值。与关卡失败是两回事：关卡失败是对一个已存在的网格的
    评判，而这是一个压根没描述出网格的规范。"""


# --------------------------------------------------------------------------
# 路由：规范究竟是不是该用的工具？
# --------------------------------------------------------------------------


def suits_code_asset(
    subject: str,
    *,
    asset_type: str = "prop",
    strategies: Any | None = None,
) -> dict[str, Any]:
    """`subject` 应该由规范构建，还是交给生成。

    返回 `{"suitable", "confidence", "reason", "route"}`，外加
    `{"topology", "claimed_by", "builder", "detail", "competing"}`，其中
    `route` 为 `"code"`、`"generate"` 或 `"ambiguous"`。

    拒绝才是重点。img2threejs [1] 对超出自身范围的 subject 会报
    `unsupported-family`，而不是硬着头皮尝试；它自己的 README 也承认
    角色出来是风格化的重建，而非相似还原。一个没法描述五官的规范，
    应该在一次调用里就说清楚，而不是花掉一整轮纠错循环去发现这件事。

    对于读起来两可的 subject，返回 `ambiguous` 而不替它猜——比如
    「石头魔像」在轮廓上是硬表面、在质感上却是有机的——因为调用方才知道
    这个资产出镜的镜头里，哪一面更要紧。

    真正的决策委托给已注册的策略，这才是本函数的实质内容。步枪与一套
    盔甲都是硬表面，路由却不同，原因是结构性的，不是任何形容词能概括的：
    步枪的零件并排放在同一个坐标系里，而盔甲要穿在一个必须先存在、
    先被测量的载体上。所以 subject 是按*装配拓扑*分类的——组合型、
    嵌套型、表皮型——而每个领域包自己拥有它能构建什么的词汇表。
    新增一个领域是注册一个策略，而不是改这个函数。

    `strategies` 是 `(name, strategy)` 的可迭代对象，用于在单次调用中
    覆盖注册表：调用方据此按自己的分类法路由而不触碰全局状态，
    测试也据此断言某个策略的效果而不留下注册残留。

    `topology` 与 `builder` 是调用方在混合构建时据以行动的两个字段。
    `nested` 的声明会路由到 `generate`，因为下一步是生成*载体*，
    而载体上的每一层仍然是很好的规范 subject——reason 与 builder
    会指出哪个模块适合它们。
    """

    return _routing.resolve(subject, asset_type, strategies=strategies)


def fit_wearable_asset(*, body: str, clothing: str, output: str,
                       coverage: Literal["full_body", "upper_body"] = "full_body",
                       sleeve_pose: Literal["down", "a", "t"] = "down",
                       footwear_mode: Literal["preserve", "replace"] = "preserve",
                       height_metres: float = 1.75, clearance_metres: float = 0.008,
                       headwear_offset_metres: float = 0.0,
                       blender_python: str | None = None,
                       source_heights: dict[str, float] | None = None,
                       clothing_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
                       save_blend: bool = True, timeout: float = 600.0) -> dict[str, Any]:
    """把一件连续的服装贴合到已绑骨的角色（FBX/GLB）上。"""
    return _templates.fit_wearable(
        body=body, clothing=clothing, output=output, coverage=coverage,
        sleeve_pose=sleeve_pose, footwear_mode=footwear_mode,
        height_metres=height_metres, clearance_metres=clearance_metres,
        headwear_offset_metres=headwear_offset_metres,
        blender_python=blender_python, source_heights=source_heights,
        clothing_rotation=clothing_rotation, save_blend=save_blend,
        timeout=timeout)


# --------------------------------------------------------------------------
# 规范校验
# --------------------------------------------------------------------------


def _as_vec3(value: Any, field: str, default: tuple[float, float, float]
             ) -> tuple[float, float, float]:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise SpecError(f"{field} must be three numbers, got {value!r}")
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{field} must be three numbers: {exc}") from exc


def _as_chamfer(value: Any, part_id: str) -> float:
    """校验 box 的边缘倒角，值为半尺寸的一个比例。

    这里拒绝而不是截断：取到 0.5 时倒角已经把它要削减的那个面吃掉了，
    box 变成了八面体；截断会把一个没人要求过的形状交回去，
    而规范里仍然写着这是 box。
    """

    if value is None:
        return 0.0
    try:
        chamfer = float(value)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{part_id}.chamfer must be a number: {exc}") from exc
    if not 0.0 <= chamfer < MAX_CHAMFER:
        raise SpecError(
            f"{part_id}.chamfer must be in [0, {MAX_CHAMFER}), got {chamfer}. "
            "It is a fraction of the half-extent, so 0.5 consumes the face "
            "it was bevelling and leaves an octahedron, not a box."
        )
    return chamfer


def _as_profile(value: Any, part_id: str, kind: str
                ) -> tuple[tuple[float, float], ...] | None:
    """校验 lathe 或 extrude 的轮廓，其他种类原样返回 None。

    lathe 绕局部 Y 轴旋转 `(radius, height)`，只有当轮廓的起点与终点
    都*落在轴上*时才围出体积。否则它就是一根两头开口的管子——这里最容易
    犯的错，因为沿着一段桶身列半径看上去完全合理，而在有东西挡在后面之前
    那个洞根本看不见。负半径同样被拒：它会反向扫过轴线并自交。

    extrude 沿 Z 轴推出一条闭合的 `(x, y)` 轮廓并封上两端，所以它需要
    三个点来围出面积，但没有哪根轴需要触及。

    在这里拒绝而不是留给关卡检查：与比例不同，不闭合的 lathe 不存在
    「本来就是这个意思」的版本。
    """

    if kind not in ("lathe", "extrude"):
        return value if value is None else tuple(
            (float(a), float(b)) for a, b in value
        )

    if not isinstance(value, (list, tuple)) or not value:
        raise SpecError(
            f"{part_id}: a {kind} needs a `profile`; without one there is no "
            "shape to revolve or push, only a size"
        )

    points: list[tuple[float, float]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise SpecError(
                f"{part_id}.profile[{index}] must be two numbers, got {entry!r}"
            )
        try:
            points.append((float(entry[0]), float(entry[1])))
        except (TypeError, ValueError) as exc:
            raise SpecError(f"{part_id}.profile[{index}]: {exc}") from exc

    minimum = 2 if kind == "lathe" else 3
    if len(points) < minimum:
        raise SpecError(
            f"{part_id}.profile needs at least {minimum} points for a {kind}, "
            f"got {len(points)}"
        )

    if kind == "extrude":
        return tuple(points)

    negative = [
        f"[{index}]={radius}"
        for index, (radius, _height) in enumerate(points)
        if radius < 0.0
    ]
    if negative:
        raise SpecError(
            f"{part_id}.profile has a negative radius at {', '.join(negative)}. "
            "A lathe profile is (radius, height) and a negative radius sweeps "
            "back through the axis, so the surface intersects itself."
        )

    open_ends = [
        name
        for name, radius in (("first", points[0][0]), ("last", points[-1][0]))
        if radius > LATHE_AXIS_TOLERANCE
    ]
    if open_ends:
        raise SpecError(
            f"{part_id}.profile does not close on the axis: its "
            f"{' and '.join(open_ends)} point(s) have a non-zero radius "
            f"({points[0][0]}, {points[-1][0]}). A revolved profile only "
            "encloses a volume if it begins and ends at radius 0; otherwise "
            "it is a pipe with two open ends, which has no interior and shows "
            "it once anything is behind it. Add (0.0, "
            f"{points[0][1]}) and (0.0, {points[-1][1]}) to cap it."
        )

    return tuple(points)


# 零件可以据以贴附的面。`"min"` 是该轴的低侧，
# `"max"` 是高侧，`"mid"` 是中央。
ATTACH_FACES = ("min", "mid", "max")

# 两个面可以相距多远仍算贴附。取十分之一毫米：
# 紧到不会把肉眼可见的缝叫作接触，宽到能扛过一次旋转的浮点运算。
ATTACH_TOLERANCE = 1e-4


def _as_attach(value: Any, part_id: str) -> dict[str, Any] | None:
    """校验 `attach`：把这个零件贴到另一个零件的表面上。

    `{"to": "shin-l", "axis": "y", "my": "max", "their": "min", "gap": 0.0}`
    读作「把我的 +y 面贴到 shin-l 的 -y 面上」。两个面默认相对
    （`my="min"`、`their="max"`），这是常见情形：一个零件叠在另一个之上。

    之所以有这个东西，是因为「绝对摆放」对于「关系」来说是错误的原语。
    迄今建出的资产里，每一处间隙都源于一个已经过期的绝对 `at`
    ——枪口离枪管 9 毫米、胫甲低于小腿 16 毫米——每一处都由连通性关卡
    找出、手工测量，然后用一个数字修好；而邻件一移动，这个数字又过期了。
    声明关系，意味着求值器会重新计算它。

    `offset` 随后沿另外两根轴平移，因为「在上方，且向前 20 毫米」
    是一种关系而不是两种。
    """

    if value is None:
        return None
    if not isinstance(value, dict):
        raise SpecError(
            f"{part_id}.attach must be a dict like "
            '{"to": "other-part", "axis": "y"}; got ' f"{type(value).__name__}"
        )

    target = str(value.get("to") or "").strip()
    if not target:
        raise SpecError(f"{part_id}.attach needs `to`, the id of the part to sit against")

    axis = str(value.get("axis") or "y").strip().lower()
    if axis not in ("x", "y", "z"):
        raise SpecError(f"{part_id}.attach.axis must be 'x', 'y' or 'z'; got {axis!r}")

    mine = str(value.get("my") or "min").strip().lower()
    theirs = str(value.get("their") or "max").strip().lower()
    for name, face in (("my", mine), ("their", theirs)):
        if face not in ATTACH_FACES:
            raise SpecError(
                f"{part_id}.attach.{name} must be one of {ATTACH_FACES}; got {face!r}"
            )

    try:
        gap = float(value.get("gap") or 0.0)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{part_id}.attach.gap must be a number: {exc}") from exc

    offset = _as_vec3(value.get("offset"), f"{part_id}.attach.offset", (0.0, 0.0, 0.0))

    return {"to": target, "axis": axis, "my": mine, "their": theirs,
            "gap": gap, "offset": offset}


def _as_trim(value: Any, part_id: str) -> tuple[float, float] | None:
    """把 `(keep_from, keep_to)` 校验为源高度的两个比例。

    只声明，不检测。生成器总会附加一些东西——拉取回来的胸甲连着人台支架
    一起到了——而靠测量来决定「物体在哪里结束、支架从哪里开始」，
    两个方向都会猜错：被要求存在的基座被切掉，或者一片铠甲札叶
    被读成底座而留在原地。写规范的人能看到渲染图。
    """

    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SpecError(
            f"{part_id}.trim must be two fractions (keep_from, keep_to); "
            f"got {value!r}"
        )
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{part_id}.trim must be numbers: {exc}") from exc
    if not 0.0 <= low < high <= 1.0:
        raise SpecError(
            f"{part_id}.trim must satisfy 0 <= keep_from < keep_to <= 1; got "
            f"({low}, {high}). An inverted or empty band removes the whole "
            "mesh, and a part with no triangles is not a part."
        )
    return (low, high)


def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """检查规范是否可求值，并把它规范化。

    凡是会让网格变得毫无意义（而不只是不好看）的情况，都抛
    :class:`SpecError`：缺 subject、没有零件、未知的基本体、
    某个零件尺寸非正、零件 id 重复。

    `units` 与 `forward` 必填且没有默认值。在这里给默认值，
    恰恰就是 `orientation_review` 要抓的那种「静默给出错误答案」：
    一个朝向是被假定的网格，看起来完全正确，直到它在场景里倒着走。
    """

    if not isinstance(spec, dict):
        raise SpecError(f"a spec must be a dict, got {type(spec).__name__}")

    subject = str(spec.get("subject") or "").strip()
    if not subject:
        raise SpecError("spec.subject is required: it is what the gates report against")

    units = str(spec.get("units") or "").strip().lower()
    if units != UNITS:
        raise SpecError(
            f"spec.units must be {UNITS!r} (glTF is metres by definition); got {units!r}"
        )

    forward = str(spec.get("forward") or "").strip().lower()
    if forward not in AXES:
        raise SpecError(
            f"spec.forward must be one of {AXES}; got {forward!r}. It is "
            "required because a mesh cannot state which way it faces, and "
            "an assumed facing is the defect orientation_review exists for."
        )

    raw_parts = spec.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise SpecError("spec.parts must be a non-empty list")

    parts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_parts):
        if not isinstance(raw, dict):
            raise SpecError(f"parts[{index}] must be a dict, got {type(raw).__name__}")
        part_id = str(raw.get("id") or "").strip()
        if not part_id:
            raise SpecError(
                f"parts[{index}].id is required: named parts are what lets "
                "gameplay drive a wheel after export"
            )
        if part_id in seen:
            raise SpecError(f"duplicate part id {part_id!r}")
        seen.add(part_id)

        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in KINDS:
            raise SpecError(
                f"{part_id}: unknown kind {kind!r}; expected one of {KINDS}"
            )

        source = raw.get("source")
        long_axis = raw.get("long_axis")
        if kind == MESH_KIND:
            if not source:
                raise SpecError(
                    f"{part_id}: a {MESH_KIND!r} part needs `source`, the path to "
                    "a self-contained GLB. Without it there is no geometry — "
                    "unlike the primitives, this kind has nothing to derive."
                )
            source = str(source)
            if not Path(source).is_file():
                raise SpecError(
                    f"{part_id}.source does not exist: {source!r}. Refused here "
                    "rather than at write time, because a spec whose parts "
                    "cannot all be read has no meaningful bounds or triangle "
                    "count, so every gate after this would be measuring an "
                    "asset with a hole in it."
                )
            if long_axis is not None:
                long_axis = str(long_axis).strip().lower()
                if long_axis not in ("x", "y", "z"):
                    raise SpecError(
                        f"{part_id}.long_axis must be 'x', 'y' or 'z'; got "
                        f"{long_axis!r}. It names which of the asset's axes the "
                        "part's longest dimension should end up along, and the "
                        "orientation gate checks the placed mesh against it."
                    )
            trim = _as_trim(raw.get("trim"), part_id)
        elif source is not None:
            raise SpecError(
                f"{part_id}: `source` is only meaningful for a {MESH_KIND!r} part, "
                f"but this one is a {kind!r}. Silently ignoring it would hide a "
                "part that was meant to be a generated component."
            )
        elif long_axis is not None or raw.get("trim") is not None:
            raise SpecError(
                f"{part_id}: `long_axis` and `trim` are only meaningful for a "
                f"{MESH_KIND!r} part, but this one is a {kind!r}. A primitive's "
                "axes and extent follow from its kind and size, so there is "
                "nothing to declare and nothing to trim."
            )

        size = _as_vec3(raw.get("size"), f"{part_id}.size", (1.0, 1.0, 1.0))
        if any(value <= 0 for value in size):
            raise SpecError(
                f"{part_id}.size must be positive in every axis, got {size}. "
                "A zero extent is a plane pretending to be a solid, and it "
                "vanishes when seen edge-on."
            )

        # `mirror` 让零件的几何体绕它自身的一根轴做镜像反射。
        #
        # 之所以存在，是因为生成出来的一对常常只到一只手。拉取回来的护肩
        # 有 0.412 半宽中的 0.131 偏向 -x——它是一个*左*肩——而把同一个网格
        # 放到两个肩膀上，结果是一个护肩正确，另一个的札叶朝内垂，
        # 盖在肋骨上而不是手臂上。镜像位置（chirality 关卡检查的也只是位置）
        # 修不了这个：几何体自带手性。
        #
        # 它没法用旋转表达，这正是它必须单独存在的原因：绕 y 轴转 180 度
        # 能让札叶朝外，但同时会把正反颠倒。也没法用负的 `size` 表达，
        # 因为那在上面已经被拒了——而悄悄放行会让每一个法线都翻转。
        mirror = raw.get("mirror")
        if mirror is not None:
            mirror = str(mirror).strip().lower()
            if mirror not in ("x", "y", "z"):
                raise SpecError(
                    f"{part_id}.mirror must be 'x', 'y' or 'z'; got "
                    f"{raw.get('mirror')!r}. It names the axis to reflect the "
                    "part's own geometry across, for the case where a generated "
                    "pair arrived as one hand."
                )

        parts.append({
            "id": part_id,
            "kind": kind,
            "size": size,
            "at": _as_vec3(raw.get("at"), f"{part_id}.at", (0.0, 0.0, 0.0)),
            "rotation": _as_vec3(
                raw.get("rotation"), f"{part_id}.rotation", (0.0, 0.0, 0.0)
            ),
            "material": str(raw.get("material") or "default"),
            "profile": _as_profile(raw.get("profile"), part_id, kind),
            "segments": int(raw.get("segments") or 16),
            "chamfer": _as_chamfer(raw.get("chamfer"), part_id),
            "source": source,
            "long_axis": long_axis,
            "trim": trim if kind == MESH_KIND else None,
            "mirror": mirror,
            # 嵌套与贴附。两者都在所有零件读完之后才解析，
            # 因为它们都可能指名一个后面才声明的零件——若要求零件必须
            # 按依赖顺序书写，就等于把依赖图塞进作者脑子里，
            # 而它本来就在那儿。
            "parent": (
                str(raw["parent"]).strip() if raw.get("parent") else None
            ),
            "attach": _as_attach(raw.get("attach"), part_id),
        })

    validated = {
        "subject": subject,
        "units": units,
        "forward": forward,
        "asset_type": str(spec.get("asset_type") or "prop"),
        "height_metres": (
            float(spec["height_metres"])
            if spec.get("height_metres") is not None
            else None
        ),
        "parts": parts,
        "materials": dict(spec.get("materials") or {}),
        "notes": str(spec.get("notes") or ""),
    }
    # 关系在这里变成坐标，这样下游不可能忘记解析它们。
    # 一道关卡去测一个未解析的规范，测到的就是堆在原点的一堆零件，
    # 然后自信地报出胡话。
    return resolve_placement(validated)


# --------------------------------------------------------------------------
# 几何：不借助渲染器，直接从规范推导
# --------------------------------------------------------------------------


def local_bounds(part: dict[str, Any]) -> tuple[tuple[float, float, float],
                                               tuple[float, float, float]]:
    """零件相对自身原点的范围，忽略 `at`。

    贴附需要先知道一个零件有多大，才知道它放到哪去，
    而绝对边界无法回答这一点，除非形成循环依赖。
    """

    from models.common.glb_writer import rotated_bounds

    return rotated_bounds(
        part["size"], (0.0, 0.0, 0.0), part["rotation"],
        profile=part.get("profile"), kind=part["kind"],
        source=part.get("source"), trim=part.get("trim"),
    )


def _dependency_order(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对零件排序，使每个 `parent` 与 `attach.to` 都排在前面。

    遇到环会拒绝，并指出环里的零件。环并不是一个难以优雅处理的特例
    ——它是一个压根没描述出位置的规范，因为两个互相贴附的零件无解。
    """

    by_id = {part["id"]: part for part in parts}
    for part in parts:
        for field, target in (("parent", part.get("parent")),
                              ("attach", (part.get("attach") or {}).get("to"))):
            if target and target not in by_id:
                raise SpecError(
                    f"{part['id']}.{field} names {target!r}, which is not a "
                    f"part of this spec. Known parts: "
                    f"{', '.join(sorted(by_id)[:8])}"
                    f"{'...' if len(by_id) > 8 else ''}"
                )
            if target == part["id"]:
                raise SpecError(
                    f"{part['id']}.{field} refers to itself, which describes "
                    "no position"
                )

    ordered: list[dict[str, Any]] = []
    state: dict[str, str] = {}

    def visit(part_id: str, trail: list[str]) -> None:
        mark = state.get(part_id)
        if mark == "done":
            return
        if mark == "visiting":
            cycle = " -> ".join(trail[trail.index(part_id):] + [part_id])
            raise SpecError(
                f"parent/attach form a cycle: {cycle}. Each part in it waits "
                "for the next, so none of them has a position."
            )
        state[part_id] = "visiting"
        part = by_id[part_id]
        for target in (part.get("parent"),
                       (part.get("attach") or {}).get("to")):
            if target:
                visit(target, trail + [part_id])
        state[part_id] = "done"
        ordered.append(part)

    for part in parts:
        visit(part["id"], [])
    return ordered


def resolve_placement(spec: dict[str, Any]) -> dict[str, Any]:
    """把 `parent` 与 `attach` 变成绝对的 `at`，取代原来的关系表述。

    返回的规范中，零件带着世界坐标 `at`，嵌套零件还额外带一个
    `local_at`，写出器用它来维持 glTF 层级。要在所有关卡之前运行，
    因为一道关卡去测未解析的规范，测的就是堆在原点的一堆零件。

    两种关系，按依赖顺序解析：

    `parent` 让 `at` 相对于父节点的坐标系，也就是当前臂移动时
    护臂能留在前臂上的原因。父节点的旋转在这里*不会*施加到子节点上
    ——glTF 会在加载时施加，而施加两次就是典型的双重变换。
    解析器所需的只是子节点的世界位置，好让关卡能测出它最终会落在哪。

    `attach` 从表面关系反解位置：沿一根轴把我的面贴到它的面上，
    再加上一个间隙与一个偏移。在引入它之前建出的资产里，每一处间隙
    都源于一个已经过期的绝对 `at`；声明关系就杜绝了这一点。
    """

    parts = [dict(part) for part in spec["parts"]]
    resolved: dict[str, dict[str, Any]] = {}
    world_at: dict[str, tuple[float, float, float]] = {}

    for part in _dependency_order(parts):
        local_at = tuple(float(value) for value in part["at"])
        part["local_at"] = local_at

        origin = (0.0, 0.0, 0.0)
        if part.get("parent"):
            origin = world_at[part["parent"]]

        attach = part.get("attach")
        if attach is None:
            placed = tuple(origin[axis] + local_at[axis] for axis in range(3))
        else:
            target = resolved[attach["to"]]
            target_low, target_high = part_bounds(target)
            my_low, my_high = local_bounds(part)

            axis = "xyz".index(attach["axis"])
            their_face = {
                "min": target_low[axis],
                "mid": (target_low[axis] + target_high[axis]) / 2.0,
                "max": target_high[axis],
            }[attach["their"]]
            my_face = {
                "min": my_low[axis],
                "mid": (my_low[axis] + my_high[axis]) / 2.0,
                "max": my_high[axis],
            }[attach["my"]]

            # 间隙的正负取决于呈现的是哪一面：用 `min` 面贴附的零件在上方，
            # 所以正间隙会把它抬起来。
            direction = 1.0 if attach["my"] == "min" else -1.0
            values = list(local_at)
            values[axis] = their_face - my_face + direction * attach["gap"]
            # 另外两根轴沿用 `at` 所说的值，但把它当作相对目标中心的偏移，
            # 而非相对世界原点——否则贴附动作会悄悄把零件横向挪动。
            for other in range(3):
                if other == axis:
                    continue
                centre = (target_low[other] + target_high[other]) / 2.0
                values[other] = centre + local_at[other]
            placed = tuple(
                values[axis_index] + attach["offset"][axis_index]
                for axis_index in range(3)
            )
            if part.get("parent"):
                # 贴附型子节点的位置已经是绝对坐标，因此写出器不能再加上父节点的平移。
                # 记下差值即可保持 glTF 层级正确。
                part["local_at"] = tuple(
                    placed[index] - origin[index] for index in range(3)
                )

        part["at"] = placed
        world_at[part["id"]] = placed
        resolved[part["id"]] = part

    out = dict(spec)
    # 按作者书写的顺序输出，而非依赖顺序：一份重命名或重排过零件的报告，
    # 会更难与产出它的规范逐项对照。
    out["parts"] = [resolved[part["id"]] for part in spec["parts"]]
    return out


def part_bounds(part: dict[str, Any]) -> tuple[tuple[float, float, float],
                                               tuple[float, float, float]]:
    """单个零件的轴对齐 `(low, high)`，单位为米。

    委托给写出器的 :func:`~models.common.glb_writer.rotated_bounds`，
    而不是在这里自己解旋转。这不只是为了整洁：本函数的第一版
    在遇到直角旋转时就交换了尺寸范围——这在 90 度时精确，在 30 度时
    却静默出错，于是关卡测的就会是另一个物体，而不是正在写出的那个。
    只有一份实现，才不会自相矛盾。
    """

    from models.common.glb_writer import rotated_bounds

    return rotated_bounds(
        part["size"], part["at"], part["rotation"],
        profile=part.get("profile"), kind=part["kind"],
        source=part.get("source"), trim=part.get("trim"),
    )


def spec_bounds(spec: dict[str, Any]) -> dict[str, Any]:
    """所有零件组合后的边界：`low`、`high`、`extents`、`centre`。"""

    lows: list[tuple[float, float, float]] = []
    highs: list[tuple[float, float, float]] = []
    for part in spec["parts"]:
        low, high = part_bounds(part)
        lows.append(low)
        highs.append(high)

    low = tuple(min(value[axis] for value in lows) for axis in range(3))
    high = tuple(max(value[axis] for value in highs) for axis in range(3))
    return {
        "low": [round(value, 6) for value in low],
        "high": [round(value, 6) for value in high],
        "extents": [round(high[axis] - low[axis], 6) for axis in range(3)],
        "centre": [round((low[axis] + high[axis]) / 2.0, 6) for axis in range(3)],
    }


def estimate_triangles(spec: dict[str, Any]) -> int:
    """这个规范求值后会得到的三角面数。

    在任何东西被建出来之前就能拿到，这正是重点：三角面预算没法事后补救
    ——在生成器之外对一个带贴图的网格做减面会把 UV 丢掉——所以一个会超预算
    的规范应该被修改，而不是被减面。

    这些公式与写出器的细分完全一致，测试也会断言两者吻合。本函数的第一版
    对圆形基本体用了 `segments ** 2`，而写出器是按 `segments // 2` 分环的，
    那一版多算了一倍，会让本来在预算内的网格也撞上预算关
    ——会拒掉好成果的关卡最后会被关掉，然后就什么也保护不了了。
    """

    total = 0
    for part in spec["parts"]:
        segments = max(3, int(part["segments"]))
        rings = max(3, segments // 2)
        kind = part["kind"]
        if kind == "box":
            # 6 个内缩的面 + 12 条棱的倒角，每个面两个三角形，
            # 再加每个角一个。带倒角的 box 并不免费：它要 44 个而非 12 个，
            # 这正是预算关必须知道这件事的原因。
            total += 44 if part.get("chamfer") else 12
        elif kind == "cylinder":
            total += segments * 4          # 侧壁 (2) + 两端封盖 (各 1)
        elif kind == "cone":
            total += segments * 2          # 斜面 + 底面
        elif kind in ("sphere", "torus"):
            total += segments * rings * 2
        elif kind == "lathe":
            points = len(part.get("profile") or ()) or 2
            total += max(1, points - 1) * segments * 2
        elif kind == "extrude":
            points = len(part.get("profile") or ()) or 4
            total += points * 2 + max(0, points - 2) * 2   # 侧壁 + 两端封盖
        elif kind == MESH_KIND:
            # 读出来，而非推导。这是唯一一种规范不声明其成本的种类，
            # 而且它通常是最大的一项：一个生成的握把有几千个三角形，
            # 而带倒角的 box 只有 44 个。这种不对称正是「把生成件限制在
            # 公式表达不了的形状上」的全部理由——它们每一个消耗的都是
            # 关卡所强制执行的同一份预算。
            from models.common.glb_writer import load_mesh_asset

            total += load_mesh_asset(
                str(part["source"]), part.get("trim")
            )["triangles"]
    return total


# --------------------------------------------------------------------------
# 关卡（gates）
# --------------------------------------------------------------------------


def _mirror(point: Sequence[float]) -> tuple[float, float, float]:
    """一个位置的矢状面镜像：只对左右轴取负。

    单独写成函数，是因为人的本能是以为「方向」变换起来不一样，
    而在这里伸手去拿一个旋转，正是那个被记录下来的 bug。
    """

    values = [float(value) for value in point]
    values[LATERAL_AXIS] = -values[LATERAL_AXIS]
    return (values[0], values[1], values[2])


def _pair_stem(part_id: str) -> tuple[str, str] | None:
    for suffix, side in ((LEFT_SUFFIX, "l"), (RIGHT_SUFFIX, "r")):
        if part_id.endswith(suffix):
            return part_id[: -len(suffix)], side
    return None


def check_chirality(spec: dict[str, Any]) -> dict[str, Any]:
    """每一对 `-l`/`-r` 必须是镜像反射，而不是旋转。

    这就是那个被记录下来的失败。img2threejs [1] 把镜像肢体放在
    `[side*along, height, side*across]`，同时对 x 与 z 取负。
    两次取负等于绕 Y 轴转 180 度，而旋转保持手性，
    于是左手成了右手转了个身。在拇指尖上量到的是：一侧 z +0.288，
    另一侧 -0.288，而镜像本不该动 z。

    它被报成 `rotation` 而不是笼统的「不匹配」，因为两者极易混淆：
    对任何位于中线上的零件它们都完全一致——这正是对称的身体永远暴露不出
    这问题、而一对车灯会暴露出来的原因。
    """

    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for part in spec["parts"]:
        parsed = _pair_stem(part["id"])
        if parsed:
            stem, side = parsed
            pairs.setdefault(stem, {})[side] = part

    failures: list[str] = []
    checked = 0
    for stem, sides in sorted(pairs.items()):
        if "l" not in sides or "r" not in sides:
            failures.append(
                f"{stem}: only the {'left' if 'l' in sides else 'right'} half "
                "is present. A lateral pair with one half missing is a "
                "modelling omission, not a style choice."
            )
            continue
        checked += 1
        right = sides["r"]["at"]
        left = sides["l"]["at"]
        expected = _mirror(right)

        def close(a: Sequence[float], b: Sequence[float]) -> bool:
            return all(abs(x - y) <= MIRROR_TOLERANCE for x, y in zip(a, b))

        if close(expected, left):
            if sides["r"]["size"] != sides["l"]["size"]:
                failures.append(
                    f"{stem}: the halves are mirrored in position but differ "
                    f"in size ({sides['r']['size']} against "
                    f"{sides['l']['size']})."
                )
            continue
        if close((-right[0], right[1], -right[2]), left):
            failures.append(
                f"{stem}: the left half is the right half ROTATED about the "
                f"vertical axis, not mirrored. A rotation preserves "
                f"handedness, so both halves are the same hand. right "
                f"{tuple(round(v, 6) for v in right)} should mirror to "
                f"{tuple(round(v, 6) for v in expected)}, but the left is "
                f"{tuple(round(v, 6) for v in left)}. Negate the lateral "
                f"axis only."
            )
        elif close(right, left):
            failures.append(
                f"{stem}: both halves sit at the same place — the left is the "
                f"right translated, not mirrored at all. Expected "
                f"{tuple(round(v, 6) for v in expected)}."
            )
        else:
            failures.append(
                f"{stem}: the halves are not a sagittal mirror. right "
                f"{tuple(round(v, 6) for v in right)} mirrors to "
                f"{tuple(round(v, 6) for v in expected)}, but the left is "
                f"{tuple(round(v, 6) for v in left)}."
            )

    return {
        "gate": "chirality",
        "ok": not failures,
        "pairs_checked": checked,
        "failures": failures,
    }


def check_solidity(spec: dict[str, Any]) -> dict[str, Any]:
    """任何零件都不该薄到侧视时消失。

    某个尺寸落在浮点零上的零件，正面看是个形状，侧看就没了。这是
    img2threejs [1] 记录的那类缺陷——它挺过了八轮评审：那块秃斑
    位于*内部*，而轮廓一致性是从落在边界上的约 11% 单元算出来的，
    所以一个基于轮廓的指标看不见它。采样点能看见，而且在任何渲染器
    启动之前就能拿到——这就是「先关几何」的全部理由。

    从 :func:`part_bounds` 测量而非从 `size`，因为对其中三种种类而言
    两者是不同的数。`mesh` 零件按单一比例被拟合进 `size`，
    只在**一张**轴上把它填满，所以一个厚度为长度 3% 的生成件
    厚度是 `size` 的 3%，不是 100%；而 lathe 或 extrude 的轮廓
    根本不受 `size` 约束。在这里读 `size` 会让这道关恰好对那些
    规范不声明厚度的种类失明——也就是说，恰恰是最值得检查的那些。
    """

    failures: list[str] = []
    for part in spec["parts"]:
        low, high = part_bounds(part)
        extents = tuple(high[axis] - low[axis] for axis in range(3))
        thinnest = min(extents)
        if thinnest < MIN_PART_THICKNESS:
            axis = "xyz"[extents.index(thinnest)]
            failures.append(
                f"{part['id']}: {thinnest:.2e} m thick on {axis} — below "
                f"{MIN_PART_THICKNESS:.0e} m this is a plane pretending to "
                "be a solid and disappears when seen edge-on. Give it real "
                "thickness or model it as a decal."
            )
    return {"gate": "solidity", "ok": not failures, "failures": failures}


def check_scale(spec: dict[str, Any]) -> dict[str, Any]:
    """组合出的网格必须是规范所说的尺寸。

    这是两种不同的错误，而通常只有第一种会被去找。

    小数点放错会得到一扇 30 厘米的门：它会被
    :data:`PLAUSIBLE_HEIGHT_M` 抓住，而这个区间刻意放宽，
    因为这道关是给数量级准备的，不是给美术方向准备的。

    更糟的是规范声明的 `height_metres` 与它自己的零件互相矛盾。
    下游没有任何东西能发现这一点，因为一个被归一化到单位盒的网格
    自身没有尺寸——声明的高度是这东西有多大唯一的记录，
    而如果零件说的是另一个数，那两者必有一方在说谎。
    一把 3 米的椅子和一扇 1.6 米的门，就是让场景显得像玩具的东西。
    """

    bounds = spec_bounds(spec)
    height = bounds["extents"][1]
    declared = spec.get("height_metres")
    role = spec.get("asset_type") or "prop"

    failures: list[str] = []
    warnings: list[str] = []

    low, high = PLAUSIBLE_HEIGHT_M.get(role, PLAUSIBLE_HEIGHT_M["prop"])
    if not (low <= height <= high):
        failures.append(
            f"composed height {height:.3f} m is outside the plausible range "
            f"for a {role} ({low}–{high} m). This range is wide on purpose: "
            "being outside it means a decimal point, not a style."
        )

    if declared is not None:
        if declared <= 0:
            failures.append(f"height_metres must be positive, got {declared}")
        elif height > 0:
            drift = abs(height - declared) / declared
            if drift > SCALE_TOLERANCE:
                failures.append(
                    f"the parts compose to {height:.3f} m but the spec "
                    f"declares {declared:.3f} m ({drift:.0%} apart). The "
                    "declared height is the only record of how big this is "
                    "once the mesh is normalised, so one of the two is "
                    "wrong — fix the parts or fix the declaration."
                )
            elif drift > SCALE_TOLERANCE / 2:
                warnings.append(
                    f"composed height {height:.3f} m against a declared "
                    f"{declared:.3f} m ({drift:.0%})"
                )

    return {
        "gate": "scale",
        "ok": not failures,
        "height_metres": height,
        "declared_metres": declared,
        "bounds": bounds,
        "failures": failures,
        "warnings": warnings,
    }


def check_budget(spec: dict[str, Any], *, limit: int | None = None) -> dict[str, Any]:
    """规范求值后必须落在它所属用途的三角面预算之内。

    在规范上而不是在网格上检查，因为这是唯一还能便宜修掉的时机：
    超预算靠调低 `segments` 来修，而事后减面会把 UV 丢掉。
    预算取自 `art_plan.BUDGET_BY_ROLE`——按用途而非资产类型索引，
    因为真正吃掉帧时间的是一件东西被绘制的*频率*。
    """

    if limit is None:
        try:
            from .art_plan import BUDGET_BY_ROLE
        except ImportError:  # 独立使用（无 art_plan 上下文）
            BUDGET_BY_ROLE = {"prop": (20_000, 1024)}
        role = spec.get("asset_type") or "prop"
        limit = BUDGET_BY_ROLE.get(role, BUDGET_BY_ROLE["prop"])[0]

    triangles = estimate_triangles(spec)
    over = triangles > limit
    return {
        "gate": "budget",
        "ok": not over,
        "triangles": triangles,
        "limit": limit,
        "failures": (
            [
                f"the spec evaluates to {triangles} triangles against a "
                f"budget of {limit}. Lower `segments` on the round parts: "
                "a triangle budget cannot be fixed after export, because "
                "decimating a textured mesh outside its generator discards "
                "the UVs."
            ]
            if over
            else []
        ),
    }


def check_connectivity(spec: dict[str, Any]) -> dict[str, Any]:
    """报告那些不与任何其它零件接触的零件。

    只报告，不判失败。一个悬空的零件通常是错误——轮子装偏在轴外，
    把手放在门旁边——但它也可能是正当的设计：悬浮的晶体、环绕的环、
    枪口焰的插槽。让这道关失败，会让它对一整类资产都是错的；
    而报告它只在评审里花掉一行，却能抓住那个轮子。
    """

    parts = spec["parts"]
    boxes = [part_bounds(part) for part in parts]
    isolated: list[str] = []
    for index, part in enumerate(parts):
        if len(parts) == 1:
            break
        low_a, high_a = boxes[index]
        touching = False
        for other in range(len(parts)):
            if other == index:
                continue
            low_b, high_b = boxes[other]
            gap = max(
                max(low_a[axis] - high_b[axis], low_b[axis] - high_a[axis])
                for axis in range(3)
            )
            if gap <= MIN_PART_THICKNESS:
                touching = True
                break
        if not touching:
            isolated.append(part["id"])

    return {
        "gate": "connectivity",
        "ok": True,
        "isolated_parts": isolated,
        "warnings": (
            [
                f"{len(isolated)} part(s) touch nothing else "
                f"({', '.join(isolated)}). Intentional for a hovering or "
                "orbiting element; otherwise a misplaced part."
            ]
            if isolated
            else []
        ),
    }


# 关卡按成本升序运行，这也是「某个失败会让后续关卡失去意义」的顺序：
# 一个无法求值的规范没有边界，而边界正是 scale 关要读的东西。
def check_windings(spec: dict[str, Any]) -> dict[str, Any]:
    """每个零件都必须是一个闭合实体，且其面朝外。

    这里唯一一个求值网格而非规范的关卡，也是唯一一个事后才补上的关卡。
    七种基本体里有四种出厂时是内外翻转的：它们的四边形绕成了 (a, b, b+1)，
    而朝外应该是 (a, b+1, b)，于是一个单位圆柱围出的体积是 -0.26，
    真实值是 +0.785。没有任何东西察觉。GLB 是合法的，三角面数对得上，
    边界也对，其它每道关都过了，而这个缺陷在任何不做背面剔除的查看器里
    都是不可见的——所以它本会最先在引擎里暴露，在交接的另一侧。

    这就是在这里花掉求值开销的理由。其它关卡检查的是规范的*意图*：
    比例、摆放、声明尺寸。这一个检查的是「对该意图的求值结果到底是不是
    一个实体」，而这是读再多规范也无法确立的。

    每个零件两项度量：

    * 有符号体积，由三角形上的散度定理算出。为正即朝外。绝对值也要查，
      而不只是查符号，这才能抓住「侧壁绕对了但端盖绕反了」的零件
      ——那两者会部分抵消。
    * 边界边：任何只被一个三角形（而非两个）使用的边就是一个洞，
      而有洞的表面没有「内部」可言，也就无所谓朝内还是朝外。

    判失败而不只是警告。与悬空零件不同，不存在「内外翻转的实体」
    恰好就是意图的资产。
    """

    from models.common.glb_writer import build_part

    failures: list[str] = []
    warnings: list[str] = []
    inverted: list[str] = []
    open_parts: list[str] = []
    open_generated: list[str] = []

    for part in spec["parts"]:
        positions, _normals, indices = build_part(part)

        volume = 0.0
        edges: dict[frozenset, int] = {}
        for triangle in range(len(indices) // 3):
            a, b, c = [positions[indices[triangle * 3 + k]] for k in range(3)]
            volume += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            ) / 6.0
            keys = [tuple(round(value, 7) for value in point) for point in (a, b, c)]
            for first, second in ((0, 1), (1, 2), (2, 0)):
                edge = frozenset((keys[first], keys[second]))
                edges[edge] = edges.get(edge, 0) + 1

        boundary = sum(1 for count in edges.values() if count == 1)
        if boundary:
            # 按来源分开处理，因为同一个度量在这里意味着两件不同的事。
            # 未闭合的基本体是一个在规范里就有修法的缺陷——几乎总是
            # lathe 的轮廓没有回到轴上——所以判它失败是有据可依的。
            # 未闭合的生成网格则是生成器原本返回的东西；没有任何规范改动
            # 能修好它，而为了握把上几条边界边就拦下整个资产，
            # 只会导致这道关被绕过，而不是网格被改进。
            # 两种情况都记录下来，好让这个决定是有依据的，而不是无声的。
            if part["kind"] == MESH_KIND:
                open_generated.append(f"{part['id']} ({boundary} boundary edge(s))")
            else:
                open_parts.append(f"{part['id']} ({boundary} boundary edge(s))")
        if volume <= 0.0:
            inverted.append(f"{part['id']} ({volume:+.6g})")

    if inverted:
        failures.append(
            f"{len(inverted)} part(s) are inside-out, enclosing a negative "
            f"volume: {', '.join(inverted)}. Their faces point inward, so "
            "they will be invisible or hollow in any engine that culls "
            "backfaces — and identical to a correct solid in a viewer that "
            "does not, which is why this is checked here and not by eye."
        )
    if open_parts:
        failures.append(
            f"{len(open_parts)} part(s) are not closed: {', '.join(open_parts)}. "
            "An edge belonging to one triangle instead of two is a hole. For a "
            "lathe this usually means the profile does not return to radius 0 "
            "at both ends, leaving a tube with open ends."
        )
    if open_generated:
        warnings.append(
            f"{len(open_generated)} generated part(s) are not closed: "
            f"{', '.join(open_generated)}. Warned rather than failed: this "
            "came out of the generator and no spec edit repairs it. It "
            "matters if the hole is where the camera looks, and not "
            "otherwise — regenerate that part if it shows."
        )

    return {
        "gate": "windings",
        "ok": not failures,
        "parts_checked": len(spec["parts"]),
        "inverted": inverted,
        "unclosed": open_parts,
        "unclosed_generated": open_generated,
        "warnings": warnings,
        "failures": failures,
    }


def check_provenance(spec: dict[str, Any]) -> dict[str, Any]:
    """报告一个组合把哪些部分委托给了生成器，以及代价是什么。

    其它每道关都把 `mesh` 零件当成 box 对待，这正是组合得以成立的原因。
    这一道记录的是关于生成件的两件别处无处安放的事实。

    **三角面去哪了。** 一个生成件有几千个三角形，而带倒角的 box 只有 44 个，
    所以它会独占预算。当它承载的是公式给不出的细节时，这没问题；
    当它顶替了某个 lathe 能精确表达的东西时就有问题——那是用一百倍的代价
    换来一个近似，而这个近似事后还改不动。

    **规范在对着一个它没有写过的文件做断言。** `size`、`at` 和 `rotation`
    都是关于一个轴向来自生成器的网格的声明。记下这些声明，能让一个装偏的
    零件变成一条待纠正的陈述，而不是一个谜。

    默认只警告，例外是：三角面几乎全是生成的*并且*几乎没有自述零件
    ——那是一个带装饰的生成资产，它应该走生成流程的评审，
    而不是挂一个规范的标签。
    """

    warnings: list[str] = []
    failures: list[str] = []

    generated = [part for part in spec["parts"] if part["kind"] == MESH_KIND]
    total_triangles = estimate_triangles(spec)
    parts: list[dict[str, Any]] = []

    if not generated:
        return {
            "gate": "provenance",
            "ok": True,
            "generated_parts": [],
            "generated_triangles": 0,
            "total_triangles": total_triangles,
            "warnings": [],
            "failures": [],
        }

    from models.common.glb_writer import load_mesh_asset

    generated_triangles = 0
    for part in generated:
        asset = load_mesh_asset(str(part["source"]), part.get("trim"))
        triangles = asset["triangles"]
        generated_triangles += triangles
        low, high = part_bounds(part)
        extents = tuple(high[axis] - low[axis] for axis in range(3))
        requested = part["size"]

        parts.append({
            "id": part["id"],
            "source": part["source"],
            "triangles": triangles,
            "share": triangles / total_triangles if total_triangles else 1.0,
            "requested_size": [round(value, 4) for value in requested],
            "actual_extent": [round(value, 4) for value in extents],
            "rotation": list(part["rotation"]),
        })

        # 生成件上一个不均匀的 `size`，是一个无法被满足的请求。
        # 网格是按单一比例拟合的，以保住它生成时的比例关系，
        # 因此两根较短的轴由最长的那根决定，多余的数字被丢弃
        # ——这是正确的行为（把模塑的握把拉伸去填满一个盒子，
        # 比一个比预期薄 4 毫米的握把是更糟的缺陷），但它是一个无声的行为。
        # 在这里把它说出来，因为作者写了三个数字、拿回一个，
        # 而消失的那两个多半是有意为之。
        widest = max(requested)
        ignored = [
            f"{'xyz'[axis]} {requested[axis]:.3f} m"
            for axis in range(3)
            if widest > 0 and abs(requested[axis] - widest) / widest > 0.02
        ]
        if ignored:
            warnings.append(
                f"{part['id']}: `size` is not uniform ({', '.join(ignored)} "
                f"against {widest:.3f} m), and only the largest value is used. "
                "A generated mesh is fitted by a single factor so its own "
                f"proportions survive, giving {extents[0]:.3f} x "
                f"{extents[1]:.3f} x {extents[2]:.3f} m. Write one number "
                "three times to say so deliberately, and place neighbours "
                "against `actual_extent`."
            )

    share = generated_triangles / total_triangles if total_triangles else 1.0
    primitives = len(spec["parts"]) - len(generated)
    # 只在「组合几乎没话可说」时才判失败：三角面几乎全是生成的，
    # **并且**几乎没有自述零件。两个条件缺一不可。只看三角面占比会误伤
    # 一件正当的武器——一个握把加一个枪托在数量级上就压过四十个小基本体，
    # 而这是正确的取舍。只看零件数会误伤一个「一块板加一个模塑垫片」的
    # 支架，那是一个有两件答案的组合。真正错的是那种把物体拉取回来
    # 再往上加装饰的规范，因为它会被记成「已由规范验证」，
    # 而承载整个资产的那个网格的朝向，却没有任何东西验证过。
    if share > 0.9 and primitives < MIN_STATED_PARTS:
        failures.append(
            f"{generated_triangles} of {total_triangles} triangles "
            f"({share:.0%}) are generated, and only {primitives} part(s) are "
            f"stated as primitives. At that point this is a generated asset "
            "with decoration attached, not a composition — and it inherits "
            "generation's problem without its review: nothing here verifies "
            "the facing of a mesh this route would report as "
            "`verified_by=\"spec\"`. Either generate the whole thing and run "
            "orientation_review, or state more of it as primitives."
        )
    elif share > 0.5:
        warnings.append(
            f"{share:.0%} of the triangles are generated. Reasonable when "
            "those parts carry shapes no formula states; worth re-reading if "
            "any of them is something a lathe or extrude would have got "
            "exactly right, since a generated part cannot afterwards be "
            "adjusted by a number."
        )

    return {
        "gate": "provenance",
        "ok": not failures,
        "generated_parts": parts,
        "generated_triangles": generated_triangles,
        "total_triangles": total_triangles,
        "generated_share": round(share, 4),
        "warnings": warnings,
        "failures": failures,
    }


def check_orientation(spec: dict[str, Any]) -> dict[str, Any]:
    """生成件的轴向必须最终落在规范所说的位置。

    这道关是在步枪握把横着出来、而其它每道关都通过之后补上的
    ——边界、缠绕、缩放全都正确，只有零件是错的。它自身最长的轴是 *x*，
    于是 `rotation: [-8, 0, 0]`，也就是那个直觉上的「往后仰」，
    实际上是在它本来就平躺着的那个平面里把它倾斜了。

    这就是 `forward` 存在的那个缺陷，往下一层：拉取回来的文件
    压根没声明哪根轴是长度轴，因此唯一能让它落位的旋转
    只能靠测量顶点找出来。`long_axis` 就是把这个测量写下来，
    再拿它与摆放后的几何对照。

    可选，因为接近立方体的零件其最长轴只是噪声。这里警告而不判失败，
    因为这个度量只是个代理——一个立着但前后镜像的零件，最长轴是一样的
    ——而一道关若在代理指标上判失败，就等于声称了比它实际检查的更多东西。
    """

    warnings: list[str] = []
    checked: list[dict[str, Any]] = []

    for part in spec["parts"]:
        if part["kind"] != MESH_KIND:
            continue
        declared = part.get("long_axis")
        low, high = part_bounds(part)
        extents = [high[axis] - low[axis] for axis in range(3)]
        longest = extents.index(max(extents))
        entry = {
            "id": part["id"],
            "declared_long_axis": declared,
            "measured_long_axis": "xyz"[longest],
            "extents": [round(value, 4) for value in extents],
        }
        checked.append(entry)

        if declared is None:
            continue

        # 接近立方体的零件是被排除而不是被放行：当两根轴相差在几个百分点内时，
        # 哪根「最长」是由网格噪声决定的，而一道会被噪声触发的关卡
        # 就是一道会被无视的关卡。
        ordered = sorted(extents, reverse=True)
        if ordered[0] > 0 and (ordered[0] - ordered[1]) / ordered[0] < 0.1:
            entry["skipped"] = "no dominant axis"
            continue

        if "xyz"[longest] != str(declared).strip().lower():
            warnings.append(
                f"{part['id']}: `long_axis` says {declared!r} but the placed "
                f"mesh is longest on {'xyz'[longest]} "
                f"({extents[0]:.3f} x {extents[1]:.3f} x {extents[2]:.3f} m). "
                "A generated file states nothing about which of its axes is "
                "length, so `rotation` is the only thing putting it right — "
                "and the intuitive axis is often not the one that works. "
                "Measure the source's own extents before choosing."
            )

    return {
        "gate": "orientation",
        "ok": True,
        "parts_checked": checked,
        "warnings": warnings,
        "failures": [],
    }


GATES: tuple[Callable[[dict[str, Any]], dict[str, Any]], ...] = (
    check_solidity,
    check_chirality,
    check_scale,
    check_budget,
    check_connectivity,
    check_provenance,
    check_orientation,
    # 放最后：唯一一个求值网格的关卡，因此也是唯一一个开销随三角面数
    # 而非零件数增长的关卡。
    check_windings,
)


def run_gates(spec: dict[str, Any]) -> dict[str, Any]:
    """运行全部关卡。返回 `{"ok", "reports", "failures", "warnings"}`。

    即使某道关失败，其余关卡也全部照跑，因为修正循环需要完整的缺陷清单：
    每轮只修一个缺陷，正是一个有着三个缺陷的规范会把有界循环耗尽的方式。
    """

    reports = [gate(spec) for gate in GATES]
    failures = [
        message for report in reports for message in report.get("failures", ())
    ]
    warnings = [
        message for report in reports for message in report.get("warnings", ())
    ]
    return {
        "ok": not failures,
        "reports": reports,
        "failures": failures,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# 有界修正循环
# --------------------------------------------------------------------------

# 放弃之前的尝试次数上限。取 3，与 img2threejs [1] 一致，理由也相同：
# 一个挺过三次针对性修正的缺陷，是没被理解，而不是第四次尝试会有什么不同。
MAX_ATTEMPTS = 3


def correct_spec(
    spec: dict[str, Any],
    revise: Callable[[dict[str, Any], list[str]], dict[str, Any]],
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    """过关 → 修订 → 再过关，带硬性停止与明确的停止原因。

    `revise(spec, failures) -> spec` 是模型修改规范的地方。

    这就是本函数的形状所依据的那次失败。img2threejs [1] 里一个无界循环
    花了 45 分钟录制一辆从来没动过的车：某次查找返回 `None`，
    循环在优化一个看不见它的指标，而什么都没有抛错。所以这里在
    循环不收敛的全部四种方式上都会停下，并用 `stop_reason` 区分它们：

        `passed`      每道关都绿。
        `exhausted`   尝试预算用尽。
        `repeating`   完全相同的一组缺陷又回来了。什么都没修好，
                      所以再试一次也没用。
        `oscillating` 两次尝试之前见过的一组缺陷又回来了。修订在
                      拿一个缺陷换另一个缺陷。
        `no_progress` 数量没有下降。与 `repeating` 不同：
                      缺陷不同，但一个都没少。
        `revise_failed` 修订方抛了错。这是被报告出来的，不是被吞掉的
                      ——一个产不出规范的修订方，就是那个静默提前返回的
                        大声版本。
    """

    history: list[tuple[str, ...]] = []
    current = spec
    attempts = 0
    best: dict[str, Any] = {**run_gates(current), "spec": current}

    def stop(reason: str, detail: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": False,
            "spec": best["spec"],
            "attempts": attempts,
            "stop_reason": reason,
            "gates": best,
        }
        if detail:
            out["detail"] = detail
        return out

    while True:
        result = run_gates(current)
        fingerprint = tuple(sorted(result["failures"]))
        if len(result["failures"]) < len(best["failures"]):
            best = {**result, "spec": current}

        if result["ok"]:
            return {
                "ok": True,
                "spec": current,
                "attempts": attempts,
                "stop_reason": "passed",
                "gates": result,
            }

        # 循环不收敛的三种方式，刻意分开，因为对每一种的应对不同：
        # 更用力地改、换个方向改、或者停下并报告规范本身是错的。
        # 只在已经有一次尝试可供对比时才检查——拿首轮去和「什么都没有」比较，
        # 正是循环在开始之前就停下的方式。
        if history:
            if fingerprint == history[-1]:
                return stop(
                    "repeating",
                    "the identical defect set came back, so the last "
                    "revision addressed none of it",
                )
            if fingerprint in history:
                return stop(
                    "oscillating",
                    "a defect set from an earlier attempt has returned: "
                    "defects are being traded for one another",
                )
            if len(fingerprint) >= len(history[-1]):
                return stop(
                    "no_progress",
                    f"{len(fingerprint)} defect(s) after attempt {attempts}, "
                    f"no fewer than the {len(history[-1])} before it",
                )

        history.append(fingerprint)

        if attempts >= max_attempts:
            return stop(
                "exhausted",
                f"{len(best['failures'])} defect(s) left after "
                f"{max_attempts} attempt(s)",
            )

        attempts += 1
        try:
            current = validate_spec(revise(current, list(result["failures"])))
        except Exception as exc:  # noqa: BLE001 —— 报告，不吞掉
            return stop("revise_failed", f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def build_code_asset(
    spec: dict[str, Any],
    out_path: str,
    *,
    revise: Callable[[dict[str, Any], list[str]], dict[str, Any]] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """校验、过关并把一个规范写成 GLB。

    返回一份报告，携带 `ok`、`glb_path`、`spec`、`gates`、
    `triangles`、`bounds`、`forward_axis`、`scale_hint_metres` 与 `warnings`。

    `forward_axis` 与 `scale_hint_metres` 直接取自规范，
    而非从网格反推——这就是这条路线在实践中的回报：
    `asset_import` 两者都要，而对生成网格来说它们只能从输入视角去猜
    ——而这个猜测恰恰会被记成 `heuristic`，正是为了不让任何人
    把它误当成事实。

    `strict` 会拒绝写出一个未通过关卡的网格。默认开启：
    一个存在着的错误资产，是会被用起来的。
    """

    validated = validate_spec(spec)

    if revise is not None:
        outcome = correct_spec(validated, revise)
    else:
        gates_once = run_gates(validated)
        outcome = {
            "ok": gates_once["ok"],
            "spec": validated,
            "attempts": 0,
            "stop_reason": "passed" if gates_once["ok"] else "not_attempted",
            "gates": gates_once,
        }
    final = outcome["spec"]
    gates = outcome["gates"]

    report: dict[str, Any] = {
        "ok": bool(outcome["ok"]),
        "glb_path": None,
        "spec": final,
        "subject": final["subject"],
        "gates": gates,
        "attempts": outcome["attempts"],
        "stop_reason": outcome["stop_reason"],
        "triangles": estimate_triangles(final),
        "bounds": spec_bounds(final),
        "forward_axis": final["forward"],
        "scale_hint_metres": final.get("height_metres"),
        "part_ids": [part["id"] for part in final["parts"]],
        "warnings": list(gates.get("warnings", ())),
        "failures": list(gates.get("failures", ())),
    }
    if outcome.get("detail"):
        report["detail"] = outcome["detail"]

    if not report["ok"] and strict:
        report["warnings"].append(
            f"nothing was written: {len(report['failures'])} gate failure(s), "
            f"stopped as {report['stop_reason']}. Pass strict=False to "
            "inspect the mesh anyway."
        )
        return report

    from models.common.glb_writer import write_spec_glb

    report["glb_path"] = write_spec_glb(final, out_path)
    return report
