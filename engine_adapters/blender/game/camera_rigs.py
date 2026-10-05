"""
engine_adapters/blender/game/camera_rigs.py

The three camera behaviours the generated genres need, and the yaw convention
they all share.

## Yaw

Yaw is **degrees**, and it agrees with `../runtime/scene/camera.py`, which
places its orbit camera at `(d·sin y, −d·cos y)` looking at the pivot. Reading
the forward direction off that:

    forward(yaw) = (−sin yaw,  cos yaw, 0)      yaw = 0  faces +Y
    right(yaw)   = ( cos yaw,  sin yaw, 0)      yaw = 90 faces −X

A camera at `rotation_euler = (radians(90 + pitch), 0, radians(yaw))` looks
along `forward(yaw)`, because Blender cameras look down their local −Z and +90°
about X swings that onto +Y.

Actors are modelled **facing +Y**, so an actor's `rotation_euler.z =
radians(yaw)` points it the same way the same yaw points a camera. Getting this
consistent once is why the shooting code can aim with the camera's own numbers.


生成的游戏类型所需的三种摄像机行为，以及它们共有的偏航角约定。

## 偏航角

偏航角以**度**为单位，其与 `../runtime/scene/camera.py` 中的设定一致——该文件中轨道摄像机的位置为 `(d·sin y, −d·cos y)`，且朝向枢轴点。据此可得出前进方向：

    前进方向(yaw) = (−sin yaw,  cos yaw, 0)，当yaw=0时指向+Y轴
    右方向(yaw)   = ( cos yaw,  sin yaw, 0)，当yaw=90时指向−X轴

当摄像机的 `rotation_euler = (radians(90 + pitch), 0, radians(yaw))` 时，其观察方向即为 `前进方向(yaw)`：因为Blender摄像机沿其局部−Z轴观察，而绕X轴旋转+90°后，观察方向会转向+Y轴。
角色模型默认**面向+Y轴**，因此角色的 `rotation_euler.z = radians(yaw)` 会使角色朝向与摄像机在同样偏航角下的朝向一致。正是为了维持这种一致性，射击代码才能直接使用摄像机自身的数值来确定瞄准方向。
"""

from math import cos, radians, sin
from typing import Optional, Sequence

#: Straight up and straight down gimbal-lock a yaw-then-pitch camera.
PITCH_LIMIT = 88.0


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("camera_rigs must run inside a bpy interpreter") from e
    return bpy


def forward(yaw_deg: float) -> tuple:
    y = radians(yaw_deg)
    return (-sin(y), cos(y), 0.0)


def right(yaw_deg: float) -> tuple:
    y = radians(yaw_deg)
    return (cos(y), sin(y), 0.0)


def aim_vector(yaw_deg: float, pitch_deg: float) -> tuple:
    """Unit vector along the look direction, including pitch (up is +pitch)."""
    y, p = radians(yaw_deg), radians(pitch_deg)
    horizontal = cos(p)
    return (-sin(y) * horizontal, cos(y) * horizontal, sin(p))


def make_camera(name: str, lens: float = 40.0, clip_start: float = 0.05):
    """Create the scene camera. Short `lens` = wide angle; 28 mm reads as an FPS."""
    bpy = _bpy()
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.clip_start = clip_start
    data.clip_end = 2000.0
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.scene.camera = obj
    return obj


class _Rig:
    """Common state: a camera object plus the yaw/pitch it is pointed with."""

    def __init__(self, camera, yaw: float = 0.0, pitch: float = 0.0):
        self.camera = camera
        self.yaw = yaw
        self.pitch = pitch

    def _point(self, location: Sequence[float]) -> None:
        self.pitch = max(-PITCH_LIMIT, min(PITCH_LIMIT, self.pitch))
        self.camera.location = tuple(location)
        self.camera.rotation_euler = (radians(90.0 + self.pitch), 0.0, radians(self.yaw))


class FirstPersonRig(_Rig):
    """
    Eye-height camera on the actor's own transform.

    `eye_height` is where the camera sits, not where the actor's origin is; the
    actor origin is on the floor so that jumping is a Z the movement code can
    clamp at zero.
    """

    def __init__(self, camera, eye_height: float = 1.65, forward_offset: float = 0.0):
        super().__init__(camera)
        self.eye_height = eye_height
        self.forward_offset = forward_offset

    def update(self, actor_pos: Sequence[float], yaw: float, pitch: float,
               bob: float = 0.0) -> None:
        self.yaw, self.pitch = yaw, pitch
        f = forward(yaw)
        self._point((
            actor_pos[0] + f[0] * self.forward_offset,
            actor_pos[1] + f[1] * self.forward_offset,
            actor_pos[2] + self.eye_height + bob,
        ))

    def eye(self, actor_pos: Sequence[float]) -> tuple:
        return (actor_pos[0], actor_pos[1], actor_pos[2] + self.eye_height)


class ChaseRig(_Rig):
    """
    Third-person follow camera, smoothed.

    The camera lags its target rather than being welded behind it: a car that
    snaps its yaw would otherwise snap the whole frame, and the sense of speed
    in a racing shot comes almost entirely from the camera settling *after* the
    turn. `stiffness` is the fraction of the remaining gap closed per tick.

    
    平滑处理的第三人称跟随相机。

    该相机会滞后于目标物体，而非直接绑定在目标后方：如果汽车突然改变航向，直接绑定的相机也会瞬间转动，而赛车场景中速度感几乎完全来自于转弯后相机的缓慢调整。`stiffness`参数表示每帧闭合的剩余间距比例。
    """

    def __init__(self, camera, distance: float = 7.5, height: float = 2.8,
                 pitch: float = -10.0, stiffness: float = 0.18,
                 look_ahead: float = 4.0):
        super().__init__(camera, pitch=pitch)
        self.distance = distance
        self.height = height
        self.stiffness = stiffness
        self.look_ahead = look_ahead
        self._yaw: Optional[float] = None

    def update(self, target_pos: Sequence[float], target_yaw: float,
               speed_ratio: float = 0.0) -> None:
        if self._yaw is None:
            self._yaw = target_yaw
        else:
            # Take the short way round, so crossing 360 does not spin the camera.
            delta = (target_yaw - self._yaw + 180.0) % 360.0 - 180.0
            self._yaw += delta * self.stiffness
        self.yaw = self._yaw

        # Pull back and drop as it speeds up: a cheap, readable speed cue.
        distance = self.distance * (1.0 + 0.22 * speed_ratio)
        f = forward(self.yaw)
        self._point((
            target_pos[0] - f[0] * distance,
            target_pos[1] - f[1] * distance,
            target_pos[2] + self.height,
        ))


class SideViewRig(_Rig):
    """
    The fighting-game camera: a fixed side-on view that frames both fighters.

    It tracks the midpoint and pulls back as they separate, clamped so a corner
    knockdown does not push the camera through the stage wall. Yaw is fixed at
    0°, which looks along +Y and puts **+X on screen-right** — so the fight line
    is the X axis and Y is depth into the stage.

    
    格斗游戏专用相机：固定的侧面视角，可同时框住两名格斗角色。

    它会追踪两人的中点位置，当两人分开时相机便会后退，同时会限制相机位置，防止角色被击倒到角落时相机穿透过舞台墙壁。相机的偏航角固定为0°，此时视角沿+Y轴方向，屏幕右侧对应+X轴——因此战斗路线即为X轴，Y轴代表进入舞台的深度。
    """

    def __init__(self, camera, height: float = 2.0, distance: float = 12.0,
                 min_distance: float = 9.0, max_distance: float = 18.0,
                 stiffness: float = 0.12, margin: float = 3.2):
        super().__init__(camera, yaw=0.0, pitch=-4.0)
        self.height = height
        self.distance = distance
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.stiffness = stiffness
        self.margin = margin
        self._centre = 0.0

    def update(self, a_pos: Sequence[float], b_pos: Sequence[float]) -> None:
        centre = (a_pos[0] + b_pos[0]) * 0.5
        spread = abs(a_pos[0] - b_pos[0])
        self._centre += (centre - self._centre) * self.stiffness

        wanted = max(self.min_distance, min(self.max_distance, spread + self.margin * 2.0))
        self.distance += (wanted - self.distance) * self.stiffness

        # yaw 0 looks along +Y, so the camera stands off the -Y side of the stage.
        self._point((self._centre, -self.distance, self.height))
