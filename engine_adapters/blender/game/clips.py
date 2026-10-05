"""
Play authored glTF clips on an unpacked character.

Procedural posing in `figures.Figure` is for kits whose parts are named boxes.
A generated or downloaded character arrives as a skinned mesh with an armature
and a set of actions (walk, punch, death). This module is the adapter for that
shape: pick a clip by a role name, evaluate it at a local time, and let the
recorder bake the pose bones the same way it bakes any other transform.

Clip names differ across packs, so roles map onto a list of aliases. A missing
clip is a no-op — the figure holds its rest pose rather than throwing, which is
the same degrade-don't-crash rule `figures.attach` uses for a missing mesh.

在解压后的角色上播放由Play创作的glTF动画片段。

在`figures.Figure`中的程序化姿态调整功能适用于那些部件被命名为“boxes”的套装。生成或下载的角色通常以带骨骼蒙皮的网格形式呈现，同时包含一套动作（如行走、出拳、死亡）。本模块正是用于适配这种角色的：根据角色名称选取对应的动画片段，在本地时间点上评估其姿态，再让记录器以与处理其他变换数据相同的方式记录下这些骨骼的姿态。

不同资源包中的动画片段名称各不相同，因此角色名称会对应一组别名。如果缺少某个动画片段，则不会执行任何操作——角色会保持休息姿态而非报错，这一机制与`figures.attach`函数在缺少网格数据时的处理方式一致，遵循“降级而不崩溃”的原则。
"""

import re
from typing import Optional

from . import assets, prims

#: role -> names a pack might have used. First match on the imported action wins.
ALIASES = {
    "idle": ("Idle", "idle", "Idle_A", "Idle_B", "Idle_Combat", "Standing",
             "Rest", "BreathingIdle", "Idle_Neutral", "Survey", "survey"),
    "walk": ("Walking", "Walk", "walk", "Walking_A", "Walking_B", "Walk_A",
             "WalkForward", "Walk_Forward"),
    "run": ("Running", "Run", "run", "Running_A", "Running_B", "Sprint", "Jog"),
    "punch": ("Punch", "punch", "Attack", "Jab", "Hook", "Melee",
              "Unarmed_Melee_Attack_Punch", "1H_Melee_Attack_Chop"),
    "kick": ("Kick", "kick", "FlyingKick", "HighKick", "Roundhouse"),
    "aim": ("Aim", "aim", "1H_Ranged_Aiming", "2H_Ranged_Aiming", "IdleAiming",
            "Aiming"),
    "shoot": ("Shoot", "shoot", "Firing", "RifleShoot", "PistolFire",
              "1H_Ranged_Shooting", "2H_Ranged_Shooting", "IdleAiming"),
    "hit": ("Hit", "hit", "Impact", "React", "Flinch", "Damage", "Hit_A",
            "sad_pose", "headShake"),
    "death": ("Death", "death", "Die", "Dying", "Dead", "Death_A", "Death_B",
              "Death_C"),
    "jump": ("Jump", "jump", "WalkJump", "Jump_Start"),
    "block": ("Block", "block", "Guard", "Blocking", "sneak_pose"),
    "slash": ("Slash", "slash", "Sword", "Melee", "Attack", "Punch",
              "1H_Melee_Attack_Chop", "1H_Melee_Attack_Slice_Horizontal",
              "1H_Melee_Attack_Slice_Diagonal", "2H_Melee_Attack_Chop",
              "Unarmed_Melee_Attack_Punch"),
    "pickup": ("Pickup", "pickup", "Interact", "OpenChest", "Reach",
               "PickUp", "Gather", "Open"),
}

_BONE_PATH = re.compile(r'^pose\.bones\["([^"]+)"\]\.(.+)$')


def _bpy():
    import bpy  # noqa: PLC0415
    return bpy


def _walk(root):
    stack = [root]
    while stack:
        obj = stack.pop()
        yield obj
        stack.extend(obj.children)


def _armature_under(root):
    for obj in _walk(root):
        if obj.type == "ARMATURE":
            return obj
    return None


def _index_actions(armature) -> dict[str, object]:
    """Actions that belong to *this* armature, keyed by clip name.

    Scanning every action in the .blend would mix two Mixamo humans that share
    bone names, and evaluating A's walk on B's bind pose is another way to get
    stretched triangles. The importer parks each file's clips on that
    armature's NLA tracks; we only read those.

    属于该骨骼的动作，以动画片段名称为键存储。
    扫描.blend文件中的所有动作时，可能会混合两个骨骼名称相同的Mixamo人体模型；而在B的绑定姿势上播放A的行走动画，也会导致三角形拉伸问题。导入器会将每个文件的动画片段挂载到对应骨骼动画器的NLA轨道上，我们仅读取这些轨道上的数据。
    """
    found = {}

    def add(action) -> None:
        if action is None:
            return
        clip = action.name.split("|")[-1].split(".")[0]
        found.setdefault(clip, action)

    ad = armature.animation_data
    if ad is None:
        return found
    add(ad.action)
    for track in ad.nla_tracks:
        for strip in track.strips:
            add(strip.action)
    return found


def _rest_pose(armature) -> None:
    """清除残留的姿势数据，避免拳击动作继承行走动画中未设置关键帧的骨骼状态。"""
    for bone in armature.pose.bones:
        bone.matrix_basis.identity()


def _assign(armature, data_path: str, index: int, value: float) -> None:
    match = _BONE_PATH.match(data_path)
    if match is None:
        return
    bone = armature.pose.bones.get(match.group(1))
    if bone is None:
        return
    prop = match.group(2)
    current = getattr(bone, prop, None)
    if current is None:
        return
    try:
        current[index] = value
        setattr(bone, prop, current)
    except (TypeError, IndexError, AttributeError):
        try:
            setattr(bone, prop, value)
        except (TypeError, AttributeError):
            return


class Animated:
    """
    An unpacked skinned character whose pose comes from named clips.

    `play(role, time)` is the whole public surface. Time is seconds of *that
    clip*, not of the match, so a punch that starts at t=4.2 is `play("punch",
    0.0)` on the first tick of the attack.

    一种已解包的血缘蒙皮角色，其姿势由命名后的动画片段驱动。
    `play(role, time)`是全部的公开接口。这里的time指的是*该动画片段*内的时间，而非整个匹配过程的时间——因此，起始时间为t=4.2的拳击动作，在攻击开始的第一帧只需调用`play("punch", 0.0)`即可。
    """

    def __init__(self, unpacked: assets.Unpacked, yaw_offset: float = 180.0):
        self.root = unpacked.root
        self.scale = unpacked.scale
        self.yaw_offset = yaw_offset
        # Keep the importer's Rx/Ry (glTF Y-up -> Z-up). Overwriting them with
        # (0, 0, yaw) is how a standing Mixamo ended up on its back.
        self._bind_rx = float(self.root.rotation_euler[0])
        self._bind_ry = float(self.root.rotation_euler[1])
        self.armature = _armature_under(unpacked.root)
        self.actions = _index_actions(self.armature) if self.armature else {}
        # glTF import parks the last take as the active action. If it stays
        # assigned, the depsgraph re-applies it after play() writes a pose and
        # the mesh deforms against two clips at once.
        if self.armature is not None and self.armature.animation_data is not None:
            ad = self.armature.animation_data
            ad.action = None
            for track in ad.nla_tracks:
                track.mute = True
        self._role = None
        self._started = 0.0

    def has(self, role: str) -> bool:
        return self._action(role) is not None

    def face(self, yaw: float) -> None:
        from math import radians  # noqa: PLC0415
        self.root.rotation_euler = (self._bind_rx, self._bind_ry,
                                    radians(yaw + self.yaw_offset))

    def play(self, role: str, time: float, *, loop: bool = True, fps: float = 30.0) -> bool:
        """Evaluate `role` at `time` seconds. False if the pack has no such clip."""
        action = self._action(role)
        if action is None or self.armature is None:
            return False
        _rest_pose(self.armature)
        start, end = float(action.frame_range[0]), float(action.frame_range[1])
        span = max(end - start, 1.0)
        frame = start + time * fps
        if loop:
            frame = start + (frame - start) % span
        else:
            frame = min(end, max(start, frame))
        for fcurve in action.fcurves:
            _assign(self.armature, fcurve.data_path, fcurve.array_index,
                    fcurve.evaluate(frame))
        return True

    def track(self, recorder) -> None:
        recorder.track(self.root, channels=("location", "rotation_euler"))
        if self.armature is None:
            return
        recorder.track(self.armature, channels=("location", "rotation_euler"))
        paths = []
        for bone in self.armature.pose.bones:
            paths.append(f'pose.bones["{bone.name}"].rotation_quaternion')
            paths.append(f'pose.bones["{bone.name}"].location')
        # One track() per path so capture's keyframe_insert gets a real data_path.
        for path in paths:
            recorder.track(self.armature, channels=(path,))

    def _bone(self, *names):
        if self.armature is None:
            return None
        bones = self.armature.pose.bones
        lowered = {bone.name.lower(): bone for bone in bones}
        for name in names:
            if name in bones:
                return bones[name]
            hit = lowered.get(name.lower())
            if hit is not None:
                return hit
            needle = name.lower().replace(":", "")
            for bone in bones:
                if needle in bone.name.lower().replace(":", ""):
                    return bone
        return None

    def locomote(self, distance: float, *, speed: float = 0.0, clock: float = 0.0) -> bool:
        """
        Pick idle / walk / run from the pack and evaluate it.

        `distance` is metres travelled (drives the stride). `speed` is m/s so a
        sprint can use the run clip. Idle is on the clock so a standing figure
        does not freeze on frame one of the walk.

        从动作序列中选择闲置/行走/奔跑动作并进行播放。
        `distance`表示移动的距离（用于驱动步幅）；`speed`为每秒移动米数，因此冲刺时可播放奔跑动作。闲置动作会基于时钟播放，这样站立的角色不会在行走动作的第一帧就静止不动。
        """
        if speed < 0.28:
            return self.play("idle", clock)
        if speed >= 3.4 and self.has("run"):
            return self.play("run", distance / 2.4)
        return self.play("walk", distance / 1.4)

    def _mul_local(self, bone, extra) -> None:
        if bone.rotation_mode == "QUATERNION":
            bone.rotation_quaternion = extra @ bone.rotation_quaternion
            return
        current = bone.rotation_euler.to_quaternion()
        bone.rotation_euler = (extra @ current).to_euler(bone.rotation_mode)

    def overlay_slash(self, phase: float, side: int = 1) -> None:
        """
        Additive cut on Mixamo arm/spine bones, on top of the clip just played.

        Soldier / Xbot have no slash action. Without this the attack is a still
        frame of idle while the VFX arc swings, which reads as a freeze.

        在刚刚播放的动画基础上，对Mixamo手臂/脊椎骨骼添加额外的切割动作。
        Soldier和Xbot角色没有挥砍动作。如果没有这个处理，攻击时会停留在待机状态的静止帧，而特效弧线仍在摆动，看起来就像画面卡住了一样。
        """
        from math import radians  # noqa: PLC0415
        import mathutils  # noqa: PLC0415

        arm = self._bone("mixamorig:RightArm", "RightArm", "arm_r", "upperarm.r")
        if side < 0:
            arm = self._bone("mixamorig:LeftArm", "LeftArm", "arm_l",
                             "upperarm.l") or arm
        forearm = self._bone("mixamorig:RightForeArm", "RightForeArm",
                             "lowerarm.r") if side >= 0 \
            else self._bone("mixamorig:LeftForeArm", "LeftForeArm", "lowerarm.l")
        spine = self._bone("mixamorig:Spine", "Spine", "spine")
        p = max(0.0, min(1.0, phase))
        if p < 0.22:
            u = p / 0.22
            lift, swing = 0.30 + 0.70 * u, -0.15 * u
        elif p < 0.72:
            u = (p - 0.22) / 0.50
            s = u * u * (3.0 - 2.0 * u)
            lift, swing = 1.00 - 0.35 * s, -0.15 + 1.05 * s
        else:
            u = (p - 0.72) / 0.28
            lift, swing = 0.65 * (1.0 - u), 0.90 * (1.0 - u)
        sign = 1.0 if side >= 0 else -1.0
        # Mixamo RightArm: +Z is the across-the-body reach (see overlay_switch).
        # A positive Z here folded the hand through the ribs. Keep Z negative
        # (abducted) and cap X near the gun-ready angle so the cut stays in
        # front of the torso instead of wrapping through it.
        if arm is not None:
            extra = mathutils.Euler(
                (radians(-48.0 * lift - 32.0 * swing),
                 radians(-10.0 * lift * sign),
                 radians(-26.0 * lift * sign)), "XYZ").to_quaternion()
            self._mul_local(arm, extra)
        if forearm is not None:
            extra = mathutils.Euler(
                (radians(-10.0 * lift), 0.0, radians(-6.0 * sign)),
                "XYZ").to_quaternion()
            self._mul_local(forearm, extra)
        if spine is not None:
            extra = mathutils.Euler(
                (radians(6.0 * swing), 0.0, radians(-8.0 * swing * sign)),
                "XYZ").to_quaternion()
            self._mul_local(spine, extra)

    def overlay_aim(self, amount: float = 1.0) -> None:
        """Raise both Mixamo arms to a gun-ready pose on top of idle/walk.
        在待机/行走动画基础上，将Mixamo的双臂抬至准备持枪的姿态。
        """
        from math import radians  # noqa: PLC0415
        import mathutils  # noqa: PLC0415

        amount = max(0.0, min(1.0, amount))
        extra = mathutils.Euler((radians(-70.0 * amount), 0.0, 0.0), "XYZ").to_quaternion()
        for name in ("mixamorig:RightArm", "mixamorig:LeftArm",
                     "mixamorig:RightForeArm", "mixamorig:LeftForeArm"):
            bone = self._bone(name)
            if bone is None:
                continue
            self._mul_local(bone, extra)

    def overlay_draw(self, amount: float = 1.0) -> None:
        """Bow draw: left arm straight out, right arm pulled back to the cheek.
        拉弓动作：左臂伸直，右臂向后拉至脸颊处。
        """
        from math import radians  # noqa: PLC0415
        import mathutils  # noqa: PLC0415

        a = max(0.0, min(1.0, amount))
        left = self._bone("mixamorig:LeftArm", "LeftArm", "upperarm.l", "UpperArm.L")
        left_f = self._bone("mixamorig:LeftForeArm", "LeftForeArm",
                            "lowerarm.l", "ForeArm.L")
        right = self._bone("mixamorig:RightArm", "RightArm", "upperarm.r", "UpperArm.R")
        right_f = self._bone("mixamorig:RightForeArm", "RightForeArm",
                             "lowerarm.r", "ForeArm.R")
        spine = self._bone("mixamorig:Spine", "Spine", "spine")
        if left is not None:
            self._mul_local(left, mathutils.Euler(
                (radians(-85.0 * a), 0.0, radians(-12.0 * a)), "XYZ").to_quaternion())
        if left_f is not None:
            self._mul_local(left_f, mathutils.Euler(
                (radians(-8.0 * a), 0.0, 0.0), "XYZ").to_quaternion())
        if right is not None:
            self._mul_local(right, mathutils.Euler(
                (radians(-55.0 * a), radians(18.0 * a), radians(55.0 * a)),
                "XYZ").to_quaternion())
        if right_f is not None:
            self._mul_local(right_f, mathutils.Euler(
                (radians(-70.0 * a), 0.0, 0.0), "XYZ").to_quaternion())
        if spine is not None:
            self._mul_local(spine, mathutils.Euler(
                (0.0, 0.0, radians(-8.0 * a)), "XYZ").to_quaternion())

    def overlay_switch(self, phase: float) -> None:
        """A short across-the-body reach while swapping weapons.
        切换武器时的横向伸手动作。
        """
        from math import radians  # noqa: PLC0415
        import mathutils  # noqa: PLC0415

        p = max(0.0, min(1.0, phase))
        u = p * 2.0 if p < 0.5 else (1.0 - p) * 2.0
        arm = self._bone("mixamorig:RightArm", "RightArm")
        forearm = self._bone("mixamorig:RightForeArm", "RightForeArm")
        if arm is not None:
            self._mul_local(arm, mathutils.Euler(
                (radians(-40.0 * u), 0.0, radians(50.0 * u)), "XYZ").to_quaternion())
        if forearm is not None:
            self._mul_local(forearm, mathutils.Euler(
                (radians(-25.0 * u), 0.0, 0.0), "XYZ").to_quaternion())

    def overlay_knockdown(self, phase: float) -> None:
        """
        Crumple a Mixamo (or similarly named) stand into a knockdown.

        Soldier / Michelle / Xbot ship without a Death clip. Playing a missing
        role left them frozen upright; this folds hips, spine and knees on top
        of idle so a kill reads as a fall, not a pause.

        将Mixamo（或命名类似的模型）的站立姿态转变为倒地姿态。
        士兵/米歇尔/Xbot飞船角色缺少死亡动画片段。由于缺失对应的动画角色，这些角色会保持直立冻结状态；这种状态下，髋部、脊椎和膝盖会在闲置动作的基础上进一步弯曲，导致死亡动作被识别为摔倒而非暂停。
        """
        from math import radians  # noqa: PLC0415
        import mathutils  # noqa: PLC0415

        p = max(0.0, min(1.0, phase))
        s = p * p * (3.0 - 2.0 * p)
        folds = (
            (("mixamorig:Hips", "Hips"), (38.0 * s, 0.0, 16.0 * s)),
            (("mixamorig:Spine", "Spine"), (46.0 * s, 0.0, 0.0)),
            (("mixamorig:Spine1", "Spine1"), (18.0 * s, 0.0, 0.0)),
            (("mixamorig:Spine2", "Spine2"), (20.0 * s, 0.0, 0.0)),
            (("mixamorig:Neck", "Neck"), (26.0 * s, 0.0, 0.0)),
            (("mixamorig:LeftUpLeg", "LeftUpLeg"), (-52.0 * s, 0.0, -10.0 * s)),
            (("mixamorig:RightUpLeg", "RightUpLeg"), (-52.0 * s, 0.0, 10.0 * s)),
            (("mixamorig:LeftLeg", "LeftLeg"), (68.0 * s, 0.0, 0.0)),
            (("mixamorig:RightLeg", "RightLeg"), (68.0 * s, 0.0, 0.0)),
            (("mixamorig:LeftArm", "LeftArm"), (-25.0 * s, 0.0, 28.0 * s)),
            (("mixamorig:RightArm", "RightArm"), (-25.0 * s, 0.0, -28.0 * s)),
        )
        for names, euler in folds:
            bone = self._bone(*names)
            if bone is None:
                continue
            extra = mathutils.Euler((radians(euler[0]), radians(euler[1]),
                                     radians(euler[2])), "XYZ").to_quaternion()
            self._mul_local(bone, extra)

    def _action(self, role: str):
        for name in ALIASES.get(role, (role,)):
            if name in self.actions:
                return self.actions[name]
        lowered = {k.lower(): v for k, v in self.actions.items()}
        for name in ALIASES.get(role, (role,)):
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None


def attach(reference: str, name: str, *, host, height: float,
           into: str = "Actors", veil=(), yaw_offset: float = 180.0) -> Optional[Animated]:
    """Unpack a skinned character onto `host`. None if the file is missing.
    将蒙皮角色模型加载到`host`上。若对应文件不存在则返回None。
    """
    model = assets.unpack(reference, name, parent=host, height=height, into=into)
    if model is None:
        return None
    for part in veil:
        prims.veil(part)
    animated = Animated(model, yaw_offset=yaw_offset)
    if animated.armature is None:
        print(f"[clips] {reference} unpacked with no armature — clips will no-op")
    elif not animated.actions:
        print(f"[clips] {reference} has an armature but no actions")
    else:
        print(f"[clips] {reference} clips: {sorted(animated.actions)}")
    return animated
