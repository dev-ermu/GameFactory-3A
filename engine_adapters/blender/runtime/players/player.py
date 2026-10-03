"""
engine_adapters/blender/runtime/players/player.py

One character: the name of its Blender object, plus the input waiting to move it.

Input is recorded, not acted on — commands arrive whenever the sender sends them
and movement must advance by real elapsed time, so `apply_input` records and
`movement.advance` integrates.

The object is held by *name*, not by reference: Blender invalidates Python
object pointers whenever the underlying data is reallocated (undo, file load, a
`remove` elsewhere), and a stale pointer is a hard crash, not an exception.
"""

import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Player:
    entity_id: str
    obj_name: str
    action_name: Optional[str] = None

    #: Metres per second. Blender is metric, so these are literal speeds.
    walk_speed: float = 2.0
    run_speed: float = 5.0
    #: Initial upward speed of a jump, in m/s.
    jump_velocity: float = 4.0

    #: Input older than this is treated as "no input". Without it a character
    #: keeps walking forever when a controller disconnects mid-stride.
    input_timeout: float = 0.6
    last_input_time: float = 0.0

    move_x: float = 0.0
    move_y: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    run: bool = False
    jump: bool = False

    #: Vertical speed carried between ticks by the jump integrator.
    z_velocity: float = 0.0

    @property
    def obj(self):
        import bpy  # noqa: PLC0415

        return bpy.data.objects[self.obj_name]

    def exists(self) -> bool:
        import bpy  # noqa: PLC0415

        return self.obj_name in bpy.data.objects

    def apply_input(self, move_x: float = 0.0, move_y: float = 0.0,
                    run: bool = False, jump: bool = False,
                    yaw: float = 0.0, pitch: float = 0.0) -> None:
        self.move_x = float(move_x)
        self.move_y = float(move_y)
        self.run = bool(run)
        self.jump = bool(jump)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.last_input_time = time.time()

    def has_recent_input(self) -> bool:
        return (time.time() - self.last_input_time) < self.input_timeout

    def set_action(self, action_name: str, loop: bool = True,
                   play_rate: float = 1.0) -> None:
        from ..assets.actions import bind_action  # noqa: PLC0415

        bind_action(self.obj_name, action_name, loop=loop, play_rate=play_rate)
        self.action_name = action_name
