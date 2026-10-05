"""
engine_adapters/blender/runtime/players/movement.py

Turn a player's pending input into a transform change for one tick.

Kinematic, not physics: positions are set directly, there is no collision, and
the ground is the Z = 0 plane. The question a preview runtime answers is "does
this character read correctly moving through this space" — anything needing real
collision belongs in the game engine `../../import_generated/` feeds.


将玩家的待处理输入转换为一个时间步长内的位姿变化。

这属于运动学模拟而非物理模拟：位置是直接设定的，不存在碰撞检测，地面被定义为Z=0平面。预览运行时所要回答的问题是：“这个角色在该空间中移动时的表现是否正常？”——任何需要真实碰撞检测的场景都应交由游戏引擎处理，相关数据会通过`../../import_generated/`路径导入。
"""

from enum import Enum
from math import radians

#: m/s². Blender's own default, so a jump here reads like a jump in the viewport.
GRAVITY = -9.8

#: Below this height the character counts as standing on the ground.
GROUND_EPSILON = 1e-3


class LocomotionState(Enum):
    IDLE = "idle"
    WALK = "walk"
    RUN = "run"
    JUMP = "jump"


def advance(player, delta_seconds: float) -> LocomotionState:
    """
    Move `player` by one tick and report what it is doing.

    Returns the state so a caller can drive an animation from it; nothing in
    this package does yet, and the clip is chosen by command instead.
    """
    obj = player.obj
    speed = player.run_speed if player.run else player.walk_speed
    dx = player.move_x * speed * delta_seconds
    dy = player.move_y * speed * delta_seconds

    obj.location.x += dx
    obj.location.y += dy

    # Yaw and pitch are absolute, not deltas: the sender owns the camera-relative
    # facing and this end should not accumulate its own drift.
    obj.rotation_euler.z = radians(player.yaw)
    obj.rotation_euler.x = radians(player.pitch)

    grounded = obj.location.z <= GROUND_EPSILON
    if player.jump and grounded and player.z_velocity == 0.0:
        player.z_velocity = player.jump_velocity
    player.z_velocity += GRAVITY * delta_seconds
    obj.location.z = max(0.0, obj.location.z + player.z_velocity * delta_seconds)
    if obj.location.z <= 0.0:
        obj.location.z = 0.0
        player.z_velocity = 0.0

    if obj.location.z > GROUND_EPSILON:
        return LocomotionState.JUMP
    if (dx * dx + dy * dy) ** 0.5 < 1e-4:
        return LocomotionState.IDLE
    return LocomotionState.RUN if player.run else LocomotionState.WALK
