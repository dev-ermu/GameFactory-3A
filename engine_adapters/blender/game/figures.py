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
"""

from math import pi, radians, sin
from typing import Optional, Sequence

from . import assets, prims

#: Part names, by role. Tuples because kits disagree about hyphens and order, and
#: the first one present wins.
LEFT_ARM = ("arm-left", "armLeft", "arm_left")
RIGHT_ARM = ("arm-right", "armRight", "arm_right")
LEFT_LEG = ("leg-left", "legLeft", "leg_left")
RIGHT_LEG = ("leg-right", "legRight", "leg_right")
TORSO = ("torso", "body", "chest")
HEAD = ("head",)

#: Metres of ground covered per full stride cycle. Set from the model rather than
#: chosen: a leg 0.667 m long swinging 30 degrees each way covers about 0.7 m, and
#: a phase that advances faster than that is the skating that gives away a fake.
STRIDE_PER_LEG_LENGTH = 1.05

#: How far a leg swings at a walk, in degrees. Sprinting scales this up.
LEG_SWING = 26.0

#: Arms counter-swing at a fraction of the legs, which is what stops a walk
#: reading as a march.
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
        """
        self.root.rotation_euler = (radians(tilt), 0.0,
                                    radians(yaw + self.yaw_offset))

    def rest(self) -> None:
        """Return every limb to the pose it was authored in."""
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
        """Both forearms up and across — the pose that reads as blocking."""
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
        """Tilt the head. Cheap, and it is what makes a figure seem to be aiming."""
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
    """
    model = assets.unpack(reference, name, parent=host, height=height, into=into)
    if model is None:
        return None
    for part in veil:
        prims.veil(part)
    return Figure(model, yaw_offset=yaw_offset)
