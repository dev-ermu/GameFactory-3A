"""
engine_adapters/blender/game/assets.py

Turning an asset reference in a spec into a path on this machine.

A generated game's spec has to be able to name an asset without naming a
filesystem: the same `spec.json` is read on the machine that generated it, on a
reviewer's laptop and in CI, and an absolute path pins it to the first of those.
Three forms are accepted, in the order a spec is likely to use them:

    /Library/hdris/city_night_2k.hdr    under the asset root (`BLENDER_ASSET_ROOT`)
    assets/textures/asphalt_01          relative to the repo, or to the cwd
    D:/refs/custom.hdr                  absolute, used as given

`/Library/` and `BLENDER_ASSET_ROOT` are the convention
`engine_adapters/blender/runtime/assets/resolver.py` already uses for the live
runtime; the same reference resolves the same way here, so an asset fetched once
is addressable from both.


engine_adapters/blender/game/assets.py

将配置文件中的资源引用转换为本机上的路径。

生成的游戏配置文件必须能够在不指定文件系统路径的情况下引用资源：同一个`spec.json`文件既会在生成它的机器上被读取，也会在审核员的笔记本电脑以及持续集成环境中被读取，而绝对路径会将资源绑定到其中第一个环境。系统接受三种形式的引用，其顺序与配置文件中使用它们的可能性一致：

    /Library/hdris/city_night_2k.hdr    位于资源根目录（`BLENDER_ASSET_ROOT`）下
    assets/textures/asphalt_01          相对于代码库或当前工作目录的路径
    D:/refs/custom.hdr                  直接使用的绝对路径

`/Library/`和`BLENDER_ASSET_ROOT`是约定俗成的命名方式，`engine_adapters/blender/runtime/assets/resolver.py`在运行时已经采用了这种约定；此处采用相同的解析逻辑，因此一旦获取的资源在两种场景下都能被访问。
"""

import os
import re
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

LIBRARY_PREFIX = "/Library/"

#: Imported models are parked in this collection, excluded from the view layer.
#: One import per file, however many instances use it.
# 导入的模型会被存放到此集合中，且不会显示在视图层中。
# 每个文件对应一个导入项，无论有多少个实例使用该模型。
SOURCE_COLLECTION = "aaagf_asset_sources"

#: `.../engine_adapters/blender/game/assets.py` -> the repo. Derived from this
#: file rather than from `AAAGF_REPO_ROOT`, because it is always right and the
#: environment variable is only sometimes set.
# `.../engine_adapters/blender/game/assets.py`对应的代码库根目录。
# 该值源自当前文件而非`AAAGF_REPO_ROOT`，因为前者始终准确，而环境变量有时并未设置。
_REPO_ROOT = Path(__file__).resolve().parents[3]


def asset_root() -> Path:
    """Where `/Library/...` references live. `<repo>/assets` unless overridden.
    `/Library/...`形式引用的资源所在位置。默认为`<代码库根目录>/assets`，除非被重新定义。
    """
    return Path(os.environ.get("BLENDER_ASSET_ROOT") or (_REPO_ROOT / "assets"))


def resolve(reference: str) -> Optional[Path]:
    """
    The path a reference names, or None when nothing is there.

    Returning None rather than raising is deliberate: every caller of this is
    decorating a scene — a sky, a road surface — and a missing file should cost
    the run its looks, not its result. The callers say what they fell back to.

    返回引用所对应的路径；若找不到对应资源则返回None。

    故意返回None而非抛出异常：所有调用此函数的场景都是为场景添加元素——比如天空、路面——文件缺失应仅导致渲染效果缺失，
    而非整个运行流程失败。调用方会自行处理回退方案。
    """
    if not reference:
        return None

    if reference.startswith(LIBRARY_PREFIX):
        candidates = [asset_root() / reference[len(LIBRARY_PREFIX):]]
    else:
        path = Path(reference)
        candidates = [path] if path.is_absolute() else [_REPO_ROOT / path, path]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


# ── Models ────────────────────────────────────────────────────────────────────

def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - host-side import guard
        raise RuntimeError(
            "engine_adapters.blender.game.assets must run inside a bpy interpreter"
        ) from e
    return bpy


def source(reference: str):
    """
    Import a model file **once** and return the collection holding it.

    Cached by file, for the same reason `prims` shares its unit meshes: three
    cars from one glTF should cost one glTF. The imported objects are parked in a
    collection that is excluded from the view layer, so the source itself neither
    renders nor draws — only the instances of it do.

    Returns None when the file is missing or has no importer, so a caller can
    fall back to the primitives it would otherwise have built.

    仅导入模型文件一次，然后返回存放该模型的集合。
    由于与`prims`共享单位网格的原因，文件会被缓存：一个glTF中的三辆汽车实际上只对应一个glTF。
    导入的对象会被存放到一个从视图层中排除的集合里，因此源模型本身既不会渲染也不会绘制——只有它的实例才会被显示。
    如果文件不存在或没有对应的导入器，该函数会返回None，这样调用方就可以转而使用原本会生成的基础几何图形。
    """
    path = resolve(reference)
    if path is None:
        print(f"[assets] no model at {reference}")
        return None

    bpy = _bpy()
    name = f"aaagf_src_{path.stem}"
    existing = bpy.data.collections.get(name)
    if existing is not None:
        return existing

    from ..import_generated.import_mesh import import_file  # noqa: PLC0415

    before = set(bpy.data.objects.keys())
    try:
        imported = import_file(bpy, path)
    except Exception as exc:                                 # noqa: BLE001
        print(f"[assets] could not import {path.name}: {exc}")
        return None
    imported = imported or [bpy.data.objects[k] for k in bpy.data.objects.keys()
                            if k not in before]
    if not imported:
        print(f"[assets] {path.name} imported nothing")
        return None

    collection = bpy.data.collections.new(name)
    _parked(bpy).children.link(collection)
    for obj in imported:
        for holder in list(obj.users_collection):
            holder.objects.unlink(obj)
        collection.objects.link(obj)
    return collection


def _parked(bpy):
    """
    The excluded parent collection every imported source hangs under.

    Returning this and not `scene.collection` is the whole point: getting it wrong
    links every source at the scene root, so one copy of every prop, wall and
    character in the library stands **piled up at the world origin**. That does not
    read as a bug — it reads as a stray asset or a broken texture, until a camera
    happens to point at (0, 0, 0).

    Excluded via the view layer rather than hidden per object: an excluded
    collection is out of the depsgraph entirely, so it cannot render, draw or be
    hit by `scene.ray_cast`, while a collection *instance* of it still resolves.

    所有导入的源模型都会存放在这个被排除的父集合下。

    选择返回这个集合而非`scene.collection`至关重要：一旦弄错，所有源模型都会被链接到场景根节点，导致库中的每个道具、墙壁和角色都在**世界原点处堆积**。这看起来不像是bug——只会让人以为是零散的资源或损坏的纹理，直到有摄像机恰好对准(0, 0, 0)时才会发现问题。

    这里是通过视图层排除而非对每个对象单独隐藏：被排除的集合完全不会出现在依赖图中，因此无法渲染、绘制，也无法被`scene.ray_cast`检测到，但它的集合实例仍然可以被正常解析。

    """
    scene = bpy.context.scene
    existing = bpy.data.collections.get(SOURCE_COLLECTION)
    if existing is None:
        existing = bpy.data.collections.new(SOURCE_COLLECTION)
        scene.collection.children.link(existing)
    layer = scene.view_layers[0].layer_collection.children.get(SOURCE_COLLECTION)
    if layer is not None:
        layer.exclude = True
    return existing


def bounds(collection) -> tuple:
    """`(low, high)` corners of everything in `collection`, in its own space.
    返回`collection`中所有物体在其自身坐标系下的边界角点，形式为`(low, high)`。
    """
    lows = [float("inf")] * 3
    highs = [float("-inf")] * 3
    for obj in collection.objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ _vector(corner)
            for axis in range(3):
                lows[axis] = min(lows[axis], point[axis])
                highs[axis] = max(highs[axis], point[axis])
    if lows[0] == float("inf"):
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    return (tuple(lows), tuple(highs))


def size(collection) -> tuple:
    """The bounding box extent of everything in `collection`."""
    low, high = bounds(collection)
    return tuple(high[axis] - low[axis] for axis in range(3))


def footing(collection, anchor: str = "base") -> tuple:
    """
    The offset from a model's origin to the point it should be placed by:
    horizontally its centre, vertically whichever face `anchor` names.

    Needed because an origin is a modelling artifact, not a handle. Kit assets are
    built to tile on a grid, so theirs tend to sit on a **corner** of the tile —
    every one of Kenney's props measures the same (-0.35, 0.65) — and one authored
    inside a larger scene can be anywhere at all. Placing by the origin puts the
    geometry that far off the mark, multiplied by whatever the model was scaled by:
    a barrier normalised from 0.25 to 2 metres is scaled eight times, so a
    centimetres-long offset lands it metres away from the kerb it was aimed at.

    `anchor="base"` is the default because most props stand on something: a spec
    says a barrier is 2.4 m to the side of the track, meaning where it *lands*.
    `anchor="top"` is for the ones that are described by the surface they present —
    a floor tile or a platform slab, where what matters is the height you stand on
    and the thickness underneath is the model's business, not the caller's.


        返回从模型原点到其应放置点的偏移量：
    水平方向上为模型中心，垂直方向上为`anchor`所指定的面所在位置。

    之所以需要这个计算，是因为原点只是建模时的参考点，并非实际放置基准。Kit素材为了能在网格上拼接，通常放置在网格的**角落**——比如Kenney的所有道具模型的偏移量都是(-0.35, 0.65)；而在一个较大场景中制作的模型，其原点可能位于任意位置。如果直接按原点放置，会导致几何图形偏离目标位置，且这种偏差还会随模型的缩放比例放大：比如一个原本标准长度为0.25到2米的护栏，若被放大8倍，那么原本几厘米级的偏移量就会导致它偏离目标位置数米之远。

    `anchor="base"`是默认选项，因为大多数道具都是放置在某个面上的：比如规范中要求护栏放置在轨道旁2.4米处，这里指的是护栏的落地位置。`anchor="top"`适用于那些由其所呈现的表面来定义的物体——比如地砖或平台石板，此时重要的是人站立的高度，下方的厚度属于模型自身的属性，而非调用方的需求。
    """
    low, high = bounds(collection)
    return ((low[0] + high[0]) * 0.5, (low[1] + high[1]) * 0.5,
            high[2] if anchor == "top" else low[2])


def _vector(values):
    import mathutils  # noqa: PLC0415

    return mathutils.Vector(values)


def _anchored(collection, location: Sequence[float], rotation: Sequence[float],
              factor: Sequence[float], anchor: str) -> tuple:
    """
    Where to put the object so the *model* lands on `location`.

    The correction is scaled and then rotated, in that order, because it is
    measured in the model's own space and the transform it has to survive is the
    object's own scale and rotation. `factor` is per axis, so a model squashed to
    fit a box is still anchored by the face it ends up presenting.

        计算将模型放置在`location`处时，物体应有的位置。

    修正量是先缩放再旋转，因为这些数值是在模型自身坐标系中测量的，而模型最终要经历的变换就是自身的缩放和旋转。`factor`是按轴分别指定的，因此即使模型被压缩以适应某个边界框，仍能以其最终呈现的面为基准进行定位。
    """
    if anchor == "origin":
        return tuple(location)

    measured = footing(collection, anchor)
    offset = _vector(tuple(measured[axis] * factor[axis] for axis in range(3)))
    offset.rotate(_euler(rotation))
    return tuple(location[axis] - offset[axis] for axis in range(3))


def _euler(rotation: Sequence[float]):
    import mathutils  # noqa: PLC0415

    return mathutils.Euler(tuple(rotation), "XYZ")


def _normalised_scale(collection, reference: str, length: Optional[float],
                      height: Optional[float], scale: float) -> float:
    """
    The uniform scale that makes a model the size a spec asked for, in metres.

    `length` measures the longest horizontal side and `height` the vertical one; a
    lamp post is described by its height and a car by its length, and quoting the
    wrong one of the two is how a post ends up as wide as a building.

    用于计算使模型达到指定尺寸的均匀缩放系数，结果单位为米。

    `length` 表示模型最长的水平边长，`height` 表示垂直边长；例如路灯的尺寸由高度决定，汽车则由长度决定。如果选错了对应的参数，就会导致路灯的尺寸被放大到和建筑物一样大。
    """
    if length is None and height is None:
        return scale
    extent = size(collection)
    wanted, measured = ((length, max(extent[0], extent[1])) if length is not None
                        else (height, extent[2]))
    if measured <= 1e-6:
        print(f"[assets] {reference} has no size to normalise; "
              f"scale left at {scale}")
        return scale
    return scale * (float(wanted) / measured)


def _fitted_scale(collection, reference: str, fit: Sequence[float]) -> tuple:
    """
    The per-axis scale that makes a model exactly `fit` metres in each direction.

    Deliberately **not** uniform, which is the one case where distorting a model
    is the right answer: a prop standing in for a collider the rules already cast
    against has to *be* that collider's size. Sized uniformly it is either smaller
    than its collider, and bullets stop in the air beside it, or larger, and they
    pass through its visible edge. Neither is fixable by choosing a nicer model,
    because the collider's proportions come out of the level's own random stream.

    So the crate is stretched and its bevels stretch with it, which on a box reads
    as a differently-sized box. Do not reach for this for anything whose shape
    carries meaning — a wheel, a figure, a barrel.

    用于计算使模型在三个轴上分别达到 `fit` 指定尺寸的独立缩放系数。

    这种缩放并非均匀的，这是唯一需要扭曲模型的情况：用来替代已有碰撞体的道具，其尺寸必须与碰撞体完全一致。如果采用均匀缩放，要么模型比碰撞体小，导致子弹会在其旁边空中停止；要么模型比碰撞体大，子弹会直接穿过其可见边缘。这两种情况都无法通过更换更合适的模型来解决，因为碰撞体的比例是由关卡生成时的随机算法决定的。

    因此木箱会被拉伸，其倒角也会随之拉伸，在视觉上看起来就像是一个尺寸不同的盒子。但对于那些形状本身具有特定含义的物体——比如车轮、人物、桶——切勿使用这种方式处理。
    """
    extent = size(collection)
    factors = []
    for axis in range(3):
        if extent[axis] <= 1e-6:
            print(f"[assets] {reference} is flat on axis {axis}; fit left at 1.0")
            factors.append(1.0)
        else:
            factors.append(float(fit[axis]) / extent[axis])
    return tuple(factors)


def instance(
    reference: str,
    name: str,
    *,
    parent=None,
    location: Sequence[float] = (0.0, 0.0, 0.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    length: Optional[float] = None,
    height: Optional[float] = None,
    fit: Optional[Sequence[float]] = None,
    scale: float = 1.0,
    into: Optional[str] = None,
    anchor: str = "base",
):
    """
    An empty that instances a model's collection — the cheap way to reuse one.

    A collection instance is a single object holding a reference, so twenty of
    them cost twenty transforms rather than twenty copies of the mesh. It is also
    why this returns an empty and not the model: the rules move the empty, and
    the geometry follows.

    `length` and `height` normalise scale by a real-world measurement, so a spec
    can size an asset without knowing anything about how it was authored — a car
    is 4.2 m long whether it was modelled in metres, centimetres or arbitrary
    units. `fit=(x, y, z)` instead makes it exactly that box, per axis and
    therefore distorting: for a prop that has to match a collider, see
    `_fitted_scale`.

    Use `unpack` instead when a part of the model has to move on its own: an
    instance is one object holding a reference, and there is nothing inside it to
    animate.

    `location` is where the *model* goes, not where its origin goes — see
    `footing`. `anchor="top"` places it by its upper face instead, for a floor
    tile whose thickness the caller should not have to know; `anchor="origin"`
    places by the origin as authored.

    `rotation` is in radians, matching `prims`.

    创建一个空物体来实例化模型的集合——这是复用模型的低成本方式。
    集合实例是一个持有引用的单一对象，因此二十个此类实例只会占用二十个变换数据，而非复制二十份网格数据。这也是为何该函数返回的是空物体而非模型本身：规则会移动空物体，而几何图形会随之变动。

    `length`和`height`参数通过现实世界的测量值来标准化缩放比例，因此规范文档无需知晓资产的建模方式即可确定其尺寸——无论汽车是以米、厘米还是任意单位建模的，其长度始终为4.2米。`fit=(x, y, z)`则会按照各轴向的尺寸将其严格限定在指定盒状范围内，从而导致形变；对于需要与碰撞器匹配的物体，可参考`_fitted_scale`函数。

    当模型的某个部件需要独立移动时，应使用`unpack`函数：因为实例只是持有引用的单一对象，其内部没有可动画的元素。

    `location`参数指定的是*模型*的位置，而非其原点位置——可参考`footing`参数。`anchor="top"`会将物体以其上表面为基准进行定位，适用于无需让调用者知晓其厚度的地砖类物体；`anchor="origin"`则会将物体定位在建模时所设定的原点位置。

    `rotation`参数以弧度为单位，与`prims`的参数格式保持一致。
    """
    collection = source(reference)
    if collection is None:
        return None

    bpy = _bpy()
    obj = bpy.data.objects.new(name, None)
    obj.instance_type = "COLLECTION"
    obj.instance_collection = collection
    obj.empty_display_size = 0.01

    if fit is not None:
        factors = _fitted_scale(collection, reference, fit)
    else:
        uniform = _normalised_scale(collection, reference, length, height, scale)
        factors = (uniform, uniform, uniform)
    obj.scale = factors
    obj.rotation_euler = tuple(rotation)
    obj.location = _anchored(collection, location, rotation, factors, anchor)

    target = bpy.data.collections.get(into) if into else None
    (target or bpy.context.scene.collection).objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


class Unpacked(NamedTuple):
    """A model brought in as separate objects. `parts` is keyed by node name.
    将模型拆分为独立物体后的结果。`parts`字典的键为节点名称。
    """

    root: object
    parts: dict
    scale: float


#: Blender's answer to a name that is already taken: `body` then `body.001`.
_SUFFIXED = re.compile(r"\.\d{3}$")


def unpack(
    reference: str,
    name: str,
    *,
    parent=None,
    location: Sequence[float] = (0.0, 0.0, 0.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    length: Optional[float] = None,
    height: Optional[float] = None,
    scale: float = 1.0,
    into: Optional[str] = None,
    anchor: str = "base",
) -> Optional[Unpacked]:
    """
    A model as individual objects under one empty, so its parts can be animated.

    The counterpart to `instance`, and the choice between them is whether anything
    inside has to move. A collection instance is a single object holding a
    reference — twenty of them cost twenty transforms, which is why props use it —
    but there is no wheel inside one to turn. Copying the objects gives something
    per-part addressable; the copies **share their mesh data**, so three cars from
    one file still cost one file's worth of geometry, and the extra outlay is a
    handful of object headers.

    The model's **own hierarchy is kept**, and that is not a detail. A car kit
    names five meshes side by side, so flattening them costs nothing and it is
    what this used to do; a character parents its arms and head to its torso, and
    flattening that reads every one of those local offsets against the wrong
    parent — a figure asked for at 1.8 m arrived at 1.33 m with its head inside its
    chest. Keeping the chain also hands the caller a rig for free: rotating the
    torso takes the arms and head with it, which is exactly the joint a lean or a
    punch turns about.

    The root empty carries the normalising scale and the rotation, so a part's own
    `rotation_euler` stays its own — no unpicking a parent's orientation to work
    out which way a wheel spins.

    Keys have Blender's `.001` de-duplication suffix stripped, so a lookup by node
    name keeps working once a second model in the same scene brings in its own
    `body`.

    `location` is where the model goes rather than where its origin goes, as in
    `instance`; for a vehicle that means centred on the transform the rules move,
    with its wheels on the ground.

    将模型拆分为多个独立物体并置于一个空物体下，以便对模型的各个部件进行动画处理。`instance`的反面就是它，二者之间的选择取决于内部物体是否需要移动。集合实例是一个保存引用的单一对象——二十个这样的实例会占用二十个变换数据，这正是道具使用它的原因——但其中一个实例里并没有可转动的轮子。复制这些对象则能实现对每个部件的单独寻址；这些副本**共享网格数据**，因此从同一个文件中生成的三辆汽车仍只占用一个文件的几何数据量，额外的开销仅仅是几个对象头而已。

    模型的**原有层级结构会被保留**，这绝非无关紧要的细节。汽车模型会将五个网格并排命名，因此展平它们无需额外成本，这也是它过去的处理方式；而角色模型会将手臂和头部作为子节点挂载到躯干上，若展平这种结构，系统就会基于错误的父节点来计算所有局部偏移量——原本要求生成身高1.8米的角色，最终却变成了1.33米，且头部还嵌在胸腔内。保留层级结构还能为调用方免费提供骨骼系统：旋转躯干时，手臂和头部会随之转动，而这正是身体倾斜或出拳时所绕动的关节。

    根空物体负责存储归一化缩放参数和旋转信息，因此部件自身的`rotation_euler`属性仍能保持独立——无需先解析父物体的朝向，就能确定轮子的旋转方向。

    键名中Blender特有的`.001`重复后缀会被剔除，因此即使同一场景中引入第二个带有自身`body`模型的场景，通过节点名进行的查找仍能正常工作。

    与`instance`不同，`location`指定的是模型的位置，而非其原点的位置；对于车辆而言，这意味着模型会居中于规则所定义的变换中心，且车轮刚好接触地面。
    """
    collection = source(reference)
    if collection is None:
        return None

    bpy = _bpy()
    root = bpy.data.objects.new(name, None)
    root.empty_display_size = 0.01
    factor = _normalised_scale(collection, reference, length, height, scale)
    root.scale = (factor, factor, factor)
    root.rotation_euler = tuple(rotation)
    root.location = _anchored(collection, location, rotation,
                              (factor, factor, factor), anchor)

    target = bpy.data.collections.get(into) if into else None
    target = target or bpy.context.scene.collection
    target.objects.link(root)
    if parent is not None:
        root.parent = parent

    # Everything is copied, including the empties a glTF brings in for its scene
    # and node roots, because they are the joints the meshes hang off. They cost
    # an object header each and dropping them is what broke the offsets.
    # 所有内容都会被复制，包括glTF为场景生成的空节点以及节点根节点——因为网格正是挂载在这些节点上的。每个此类节点都会占用一个对象头空间，而删除它们正是导致偏移量出错的原因。
    copies = {}
    for original in collection.objects:
        obj = original.copy()          # shares mesh data with the source
        # glTF nodes arrive in quaternion mode, where `rotation_euler` is stored
        # and **ignored** — it reads back exactly as set and the object never
        # turns. Everything that drives a part writes Euler angles, so this is the
        # point of unpacking. Blender converts the existing rotation on the mode
        # change, so nothing authored is lost.

        # glTF节点默认采用四元数模式，此时`rotation_euler`属性会被存储但**被忽略**——它读取时的值与设置值完全一致，物体永远不会发生旋转。由于驱动部件运动的参数都是欧拉角，因此这正是我们需要解包的原因。Blender会在模式切换时转换现有的旋转数据，因此不会丢失任何原始设定。
        obj.rotation_mode = "XYZ"
        target.objects.link(obj)
        copies[original.name] = obj

    for original in collection.objects:
        obj = copies[original.name]
        parent = original.parent
        obj.parent = copies[parent.name] if parent is not None else root
        # Carried over rather than left at identity: Blender stores the offset a
        # parenting was made at here, and the local matrix is only correct when
        # read against it.
        # 此处保留的是父级关系建立时的偏移量而非将其设为默认值：Blender会将这一偏移量存储在这里，只有结合该偏移量读取时，局部矩阵才是正确的。
        obj.matrix_parent_inverse = original.matrix_parent_inverse.copy()

    parts = {_SUFFIXED.sub("", original.name): copies[original.name]
             for original in collection.objects if original.type == "MESH"}
    if not parts:
        print(f"[assets] {reference} unpacked no meshes")
    return Unpacked(root, parts, factor)
