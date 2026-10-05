"""
engine_adapters/blender/game/figures.py

Posing a humanoid model from numbers the rules already compute.

A generated mechanic drives a character with a handful of scalars — where it is,
which way it faces, how far it has walked, how committed its attack is. A capsule
shows none of that. A kit character has limbs, and each limb's origin sits on its
joint, so the same scalars can drive it: this module is the adapter between the
two, and it deliberately holds **no state of its own that the rules can see**.
Every pose is a pure function of arguments passed in, so a figure cannot change
what a metric reads — the same guarantee `prims` gives a level.

The model this is written against
---------------------------------
Kenney's blocky characters, whose glTF is six meshes in a hierarchy::

    root
      leg-left, leg-right          hang -Z from the hip, 0.667 m at 1.8 m tall
      torso                        pivots at hip height
        arm-left, arm-right        hang -Z from the shoulder
        head

Two properties of that layout are what make it usable, and both were measured
rather than assumed. Each limb's **origin is its joint**, so a swing is a local
rotation and needs no pivot arithmetic. And the arms and head are **children of
the torso**, so leaning the torso carries them — which is the difference between
a character bending at the waist and a character whose head stays behind while its
chest turns. (`assets.unpack` preserves that hierarchy for exactly this reason.)

Anything that is not that model degrades instead of failing: a missing part makes
the pose that would have used it a no-op, so a spec naming a prop as a character
gets a stiff figure rather than a traceback.

Facing
------
glTF is authored -Z forward and the importer maps that onto -Y, while actors here
face +Y at yaw 0 — the same half-turn the racing cars needed. `face()` applies it,
so callers work in the game's own yaw and never see the model's.


根据规则计算出的数值来设定人形模型的姿势。

生成的逻辑机制通过几个标量参数来驱动角色——包括角色的位置、朝向、行走距离以及攻击力度。胶囊体模型无法体现这些信息。一套角色模型包含各个肢体，每个肢体的原点都位于关节处，因此同样的标量参数就能用来控制它们：本模块正是这两者之间的适配器，且刻意不保存规则系统可感知的**任何自身状态**。每种姿势都是传入参数的纯函数，因此模型无法改变数值指标的结果——这与`prims`为关卡提供的保障机制一致。

本文所针对的模型
-----------------
Kenney的方块风格角色，其glTF文件由六个按层级排列的网格组成：

    根节点
      左腿、右腿          从髋部向下延伸-Z方向，身高1.8米时长度为0.667米
      躯干                以髋部高度为旋转中心
        左臂、右臂        从肩部向下延伸-Z方向
        头部

该模型的两种特性使其具备实用价值，且这些特性均经过实测而非凭假设得出。每个肢体的**原点即为其关节**，因此肢体摆动属于局部旋转，无需额外的枢轴计算。此外，手臂和头部是**躯干的子节点**，因此躯干倾斜时会带动它们——这正是角色弯腰与胸部转动时头部却保持不动的区别。（`assets.unpack`正是出于此原因才保留了这种层级结构。）

若模型不符合上述特征，程序不会报错而是会降级处理：缺失的部件会导致原本使用该部件的姿势设置操作被忽略，因此当规格要求将某道具视为角色时，最终呈现的会是僵硬的模型而非报错信息。

朝向
----
glTF模型默认以-Z方向为前方，导入器会将其映射为-Y方向，而此处角色在偏航角0度时面向+Y方向——这与赛车模型所需的半转逻辑一致。`face()`函数会处理这种映射关系，因此调用方只需使用游戏自身的偏航角参数，无需关心模型本身的朝向设定。
"""

from math import pi, radians, sin
from typing import Optional, Sequence

from . import assets, prims

#: Part names, by role. Tuples because kits disagree about hyphens and order, and
#: the first one present wins.
# 按功能分类的部件名称。使用元组是为了适配不同套件中名称的连字符用法和顺序差异，
# 只要存在第一个匹配的名称即可。
LEFT_ARM = ("arm-left", "armLeft", "arm_left")
RIGHT_ARM = ("arm-right", "armRight", "arm_right")
LEFT_LEG = ("leg-left", "legLeft", "leg_left")
RIGHT_LEG = ("leg-right", "legRight", "leg_right")
TORSO = ("torso", "body", "chest")
HEAD = ("head",)

#: Metres of ground covered per full stride cycle. Set from the model rather than
#: chosen: a leg 0.667 m long swinging 30 degrees each way covers about 0.7 m, and
#: a phase that advances faster than that is the skating that gives away a fake.
# 完成一次完整迈步周期所前进的地面距离（单位：米）。该数值根据模型实际测量得出而非主观设定：
# 长度为0.667米的腿向两侧各摆动30度时，前进距离约为0.7米；若迈步速度超过该数值，就会呈现出虚假的滑行效果。
STRIDE_PER_LEG_LENGTH = 1.05

#: How far a leg swings at a walk, in degrees. Sprinting scales this up.
# 步行状态下腿部摆动的角度（单位：度）。冲刺时会放大该数值。
LEG_SWING = 26.0

#: Arms counter-swing at a fraction of the legs, which is what stops a walk
#: reading as a march.
# 手臂摆动的幅度仅为腿部的一半左右，正是这一特性避免了步行动作看起来像行军步伐。
ARM_SWING_RATIO = 0.55


def _first(parts: dict, names: Sequence[str]):
    for name in names:
        if name in parts:
            return parts[name]
    return None


class Figure:
    """
    A model hung on a transform the rules move, plus the poses they imply.

    Construction measures the figure — where its shoulders are, how long its arms
    are — because those numbers are what a pose has to be expressed in and every
    one of them differs per model. Nothing is cached about *state*: the caller
    passes the phase, the lean and the commitment every tick.

    挂载在可移动变换节点上的模型，以及该模型对应的姿态数据。

    构建模型时会测量其各项参数——比如肩膀位置、手臂长度——因为这些数值是表达姿态所必需的，且每个模型的参数都不尽相同。该类不会缓存任何*状态*信息：调用方需要在每一帧传入相位、倾斜度以及动作指令。
    """

    def __init__(self, model: assets.Unpacked, *, yaw_offset: float = 180.0):
        self.model = model
        self.root = model.root
        self.parts = dict(model.parts)
        self.yaw_offset = yaw_offset

        self.torso = _first(self.parts, TORSO)
        self.head = _first(self.parts, HEAD)
        self.arm_left = _first(self.parts, LEFT_ARM)
        self.arm_right = _first(self.parts, RIGHT_ARM)
        self.leg_left = _first(self.parts, LEFT_LEG)
        self.leg_right = _first(self.parts, RIGHT_LEG)

        self.arms = [a for a in (self.arm_left, self.arm_right) if a is not None]
        self.legs = [leg for leg in (self.leg_left, self.leg_right) if leg is not None]

        # Rest transforms, so a pose is always expressed as a departure from the
        # way the model was authored rather than as an absolute. A limb that is
        # authored with a bend keeps it.
        self._rest = {part: (tuple(part.rotation_euler), tuple(part.scale))
                      for part in self.parts.values()}

        self.leg_length = self._limb_length(self.legs)
        self.arm_length = self._limb_length(self.arms)
        self.stride = max(0.35, self.leg_length * STRIDE_PER_LEG_LENGTH)
        self.shoulder_z = self._joint_z(self.arms)
        self.hip_z = self._joint_z(self.legs)
        self.base_z = float(self.root.location[2])

    # ── measurement ───────────────────────────────────────────────────────────

    def _limb_length(self, limbs: list) -> float:
        """
        How far a limb reaches from its joint, in world metres.

        Taken off the mesh for the same reason the racing wheels' radius is: it
        sets how far a punch travels and how long a stride is, and a guess shows
        up as a limb that misses what the rules say it hit.

        肢体从关节处延伸的距离，单位为世界单位中的米。

        之所以从网格中提取该数值，原因与赛车车轮半径的测量逻辑一致：它决定了出拳的距离和步幅大小；若采用估算值，会导致肢体无法准确击中规则所指定的目标。
        """
        if not limbs:
            return 0.6
        limb = limbs[0]
        depth = max(abs(corner[2]) for corner in limb.bound_box)
        return max(1e-3, depth * self._world_scale(limb))

    def _joint_z(self, limbs: list) -> float:
        if not limbs:
            return 1.0
        return float(limbs[0].matrix_world.translation[2])

    def _world_scale(self, part) -> float:
        return abs(part.matrix_world.to_scale()[2])

    # ── the transforms the rules drive ────────────────────────────────────────

    def face(self, yaw: float, *, tilt: float = 0.0) -> None:
        """
        Turn the figure to the game's yaw, absorbing the model's own convention.

        `tilt` is a rotation about the model's own side axis, applied *inside* the
        yaw — a topple that follows the figure rather than a fixed world axis.

        将角色转向游戏中的偏航角，同时适配模型自身的坐标系规则。

        `tilt` 是围绕模型自身侧轴的旋转，该旋转会在偏航旋转之后生效——这种倾斜是随角色本体同步的，而非围绕固定的世界坐标轴。
        """
        self.root.rotation_euler = (radians(tilt), 0.0,
                                    radians(yaw + self.yaw_offset))

    def rest(self) -> None:
        """Return every limb to the pose it was authored in.
        将所有肢体恢复到建模时的初始姿态。
        """
        for part, (rotation, scale) in self._rest.items():
            part.rotation_euler = rotation
            part.scale = scale

    def walk(self, distance: float, *, swing: float = LEG_SWING) -> None:
        """
        A stride cycle driven by **distance travelled**, not by a clock.

        A phase advanced by time keeps the legs moving while the character stands
        still, which is the most obvious tell in a generated animation. Distance
        also stays correct when the rules change speed: a sprint takes bigger
        steps rather than the same steps faster.

        这是一个由**移动距离**驱动的迈步周期，而非基于时间的驱动。
        若按时间推进相位，会导致角色静止时双腿仍会持续运动，这正是生成动画中最明显的破绽。此外，当移动规则改变速度时，距离参数也能保证运动逻辑的正确性：冲刺时会迈出更大的步幅，而非让相同步幅以更快速度移动。
        """
        angle = radians(swing) * sin((distance / self.stride) * 2.0 * pi)
        if self.leg_left is not None:
            self._swing_part(self.leg_left, angle)
        if self.leg_right is not None:
            self._swing_part(self.leg_right, -angle)

        arm_angle = -angle * ARM_SWING_RATIO
        if self.arm_left is not None:
            self._swing_part(self.arm_left, arm_angle)
        if self.arm_right is not None:
            self._swing_part(self.arm_right, -arm_angle)

    def _swing_part(self, part, angle: float) -> None:
        """
        Rotate a limb about its joint, on top of however it was authored.

        A limb hangs along -Z, so a rotation about local X sweeps it forward and
        back: Rx(θ) takes (0, 0, -1) to (0, sin θ, -cos θ), and the model's
        forward is -Y, so a negative angle swings the limb forward.

        在肢体原有建模姿态的基础上，围绕其关节进行旋转。

        肢体默认沿-Z轴延伸，因此围绕局部X轴的旋转会使其前后摆动：Rx(θ)会将坐标(0, 0, -1)转换为(0, sin θ, -cos θ)；由于模型的朝向为-Y轴，负角度会使肢体向前摆动。
        """
        rest, _ = self._rest[part]
        part.rotation_euler = (rest[0] + angle, rest[1], rest[2])

    def reach(self, side: int, extend: float, distance: Optional[float] = None) -> None:
        """
        Push one arm out in front, optionally landing the hand on `distance`.

        `extend` runs 0 (hanging) to 1 (straight out in front), and negative for a
        wind-up. `distance` is how far forward of the figure's centre the hand must
        end up, in metres; given it, the arm is **stretched** to get there.

        Stretching is deliberate. The hitbox is a computed point that reaches
        further than any limb on a kit character, so something has to give, and the
        rules own the number — a rubber-limbed punch is the cheaper concession and
        the one that reads at a glance.

        将一只手臂向前伸出，可选择让手部落在指定`distance`位置。

        `extend`的取值范围为0（手臂下垂）到1（手臂完全伸直向前），负值则表示手臂先回缩再伸出。`distance`指手部最终需到达的角色中心前方距离，单位为米；一旦指定该值，手臂会被**拉伸**以达到目标位置。

        这种拉伸设计是有意为之。碰撞盒的计算结果会比角色模型上任何肢体的实际长度都要远，因此必须做出妥协，而规则系统会直接控制这个数值——采用可伸缩的肢体来实现这一效果，既成本更低，视觉上也更容易理解。
        """
        arm = self.arm_right if side >= 0 else self.arm_left
        if arm is None:
            return
        rest, rest_scale = self._rest[arm]

        commitment = max(-1.0, min(1.0, extend))
        arm.rotation_euler = (rest[0] - radians(90.0) * commitment,
                              rest[1], rest[2])

        factor = 1.0
        if distance is not None and self.arm_length > 1e-6 and commitment > 0.0:
            # The shoulder is not on the figure's centre line; what has to reach
            # `distance` is the hand, so the shoulder's own forward offset comes
            # off first.
            shoulder_forward = -float(arm.matrix_local.translation[1])
            wanted = (distance - shoulder_forward) / self.arm_length
            factor = 1.0 + (max(0.6, wanted) - 1.0) * commitment
        arm.scale = (rest_scale[0], rest_scale[1], rest_scale[2] * factor)

    def guard(self, amount: float = 1.0) -> None:
        """Both forearms up and across — the pose that reads as blocking.
        双臂抬起并向外展开——这种姿势看起来像是在格挡。
        """
        for side, arm in ((1, self.arm_right), (-1, self.arm_left)):
            if arm is None:
                continue
            rest, _ = self._rest[arm]
            arm.rotation_euler = (rest[0] - radians(74.0) * amount,
                                  rest[1] + radians(26.0) * amount * side,
                                  rest[2])

    def aim(self, amount: float = 1.0) -> None:
        """Both arms levelled forward, for a character holding a weapon."""
        for arm in self.arms:
            rest, _ = self._rest[arm]
            arm.rotation_euler = (rest[0] - radians(84.0) * amount,
                                  rest[1], rest[2])

    def lean(self, degrees_forward: float, *, crouch: float = 0.0) -> None:
        """
        Bend at the waist, and sink by `crouch` metres.

        The torso pivot is the model's own hip joint, so this bends the figure over
        planted feet instead of tipping it like a skittle — and because the arms
        and head are the torso's children they come along, which is what makes the
        bend read as a body rather than as a rotating box.

        腰部弯曲，并向下沉降`crouch`米。
        躯干的旋转中心是模型自身的髋关节，因此这种动作会让角色在双脚固定的状态下弯腰，而不会像保龄球一样倾倒——由于手臂和头部都是躯干的子物体，它们会随躯干一同移动，这正是该动作看起来像是身体弯曲而非简单旋转方块的原因。
        """
        if self.torso is None:
            return
        rest, _ = self._rest[self.torso]
        self.torso.rotation_euler = (rest[0] + radians(degrees_forward),
                                     rest[1], rest[2])
        if crouch:
            self.root.location = (self.root.location[0], self.root.location[1],
                                  self.base_z - crouch)

    def look(self, pitch: float) -> None:
        """Tilt the head. Cheap, and it is what makes a figure seem to be aiming.
        倾斜头部。这种方式成本低廉，却能让角色看起来像是在瞄准。
        """
        if self.head is None:
            return
        rest, _ = self._rest[self.head]
        self.head.rotation_euler = (rest[0] - radians(pitch), rest[1], rest[2])

    def hold(self, side: int, reference: str, name: str, *, length: float,
             rotation: Sequence[float] = (0.0, 0.0, 0.0), grip: float = 0.92,
             into: str = "Actors"):
        """
        Put a model in one hand, sized in **world** metres, and let the arm aim it.

        Hung off the arm, not the root, so no aiming code is needed: the limb's
        local -Z runs down its length, so a model laid along that axis points
        wherever the arm points and `aim()` carries it for free.

        Both divisions by `factor` are load-bearing and fail silently if skipped —
        the arm inherits the figure's normalising scale, so a length asked for in
        metres would arrive multiplied by it, and the offset down the limb is in the
        arm's own units.

        `grip` is how far down the limb the hand sits; 1.0 is the mesh tip, past
        where a fist would close.

        将一个模型握在一只手中，其尺寸以**世界单位**的米来衡量，并让手臂将其对准目标。”它悬挂在手臂上而非根部，因此无需专门的瞄准代码：肢体自身的局部-Z轴沿其长度方向延伸，只要模型沿该轴放置，就会随手臂指向任何方向，而`aim()`函数会自动处理定位问题。

        两次除以`factor`的操作至关重要，一旦省略就会导致静默错误——手臂会继承角色的归一化缩放比例，因此以米为单位指定的长度实际会被该比例乘上，而沿肢体的偏移量则是以手臂自身单位计量的。

        `grip`参数表示手在肢体上的位置；值为1.0时对应网格末端，也就是拳头无法再闭合的位置。

        """
        arm = self.arm_right if side >= 0 else self.arm_left
        if arm is None:
            return None
        factor = self._world_scale(arm)
        if factor <= 1e-6:
            return None
        return assets.instance(reference, name, parent=arm,
                               location=(0.0, 0.0, -self.arm_length * grip / factor),
                               rotation=tuple(rotation),
                               length=length / factor, into=into, anchor="origin")

    # ── plumbing ──────────────────────────────────────────────────────────────

    def track(self, recorder) -> None:
        """
        Register every transform a pose touches with the recorder.

        Scale is included for the arms because a punch stretches one, and a
        channel that is not baked simply holds its first value — a punch that
        never extends in the video while extending in the window.

        将姿态涉及的所有变换信息记录到recorder中。
        手臂的缩放信息也会被记录，因为出拳动作会导致手臂拉伸；而未经过烘焙的通道会保留其初始值——即视频中未出现伸展动作，但窗口中却显示伸展状态的情况。
        """
        recorder.track(self.root, channels=("location", "rotation_euler"))
        for part in self.parts.values():
            channels = ["rotation_euler"]
            if part in self.arms:
                channels.append("scale")
            if part is self.torso:
                channels.append("location")
            recorder.track(part, channels=tuple(channels))


def attach(reference: str, name: str, *, host, height: float,
           into: str = "Actors", veil: Sequence = (),
           yaw_offset: float = 180.0) -> Optional[Figure]:
    """
    Hang a character model on an actor's root and stop drawing the blocks under it.

    `veil` is the block figure being replaced, veiled rather than hidden: those
    blocks stay the hurtbox, so the pose behind them has to keep being computed.
    See `prims.veil`.

    `height` normalises the figure — quote the **collider's** height, not a
    person's, so the silhouette agrees with the shape being shot at.

    Returns None when the model is missing, having veiled nothing, so a bad
    reference degrades to the primitive figure.

    将角色模型挂载到演员的根节点上，并停止绘制其下方的方块。

    `veil`参数指定的是被替换的方块模型，这些方块只是被遮蔽而非隐藏：它们仍会作为碰撞体存在，因此背后的姿态仍需持续计算。详情参见`prims.veil`。

    `height`参数用于归一化角色模型——应填写**碰撞体**的高度，而非人物本身的高度，这样才能确保轮廓与受击判定形状一致。

    若模型缺失，则不会进行任何遮蔽操作，返回None，此时错误的引用会退化为基础模型。
    """
    model = assets.unpack(reference, name, parent=host, height=height, into=into)
    if model is None:
        return None
    for part in veil:
        prims.veil(part)
    return Figure(model, yaw_offset=yaw_offset)
