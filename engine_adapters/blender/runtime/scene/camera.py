"""
engine_adapters/blender/runtime/scene/camera.py

Orbit, zoom and pan the stage camera.

State lives here in degrees and metres rather than being read back out of
Blender: deriving yaw from a rotation matrix each frame accumulates error and
goes wrong at the poles, and the pitch clamp only holds if the spherical
coordinates are the source of truth.

The camera is a child of `stage.PIVOT`, so all of this is local to the rig and
`PreviewStage.reframe` can re-aim the orbit without disturbing it.
"""

from math import cos, radians, sin

from .stage import CAMERA, PIVOT

#: Straight up and straight down are where a yaw-then-pitch camera gimbal locks.
PITCH_LIMIT = 89.0

#: Metres. Stops a scroll wheel from pushing the camera through the subject.
MIN_DISTANCE = 0.3


class CameraController:
    def __init__(self, yaw: float = 0.0, pitch: float = -6.0,
                 distance: float = 6.0) -> None:
        self.yaw = yaw
        self.pitch = pitch
        self.distance = distance
        self.pan_y = 0.0
        #: Starts at eye height rather than at the pivot, which is on the floor.
        self.pan_z = 1.0

    def apply_input(self, yaw_delta: float = 0.0, pitch_delta: float = 0.0,
                    zoom_delta: float = 0.0, pan_y_delta: float = 0.0,
                    pan_z_delta: float = 0.0) -> None:
        """Deltas, in degrees and metres, as a mouse or stick would send them."""
        self.yaw += yaw_delta
        self.pitch = max(-PITCH_LIMIT, min(PITCH_LIMIT, self.pitch + pitch_delta))
        self.distance = max(MIN_DISTANCE, self.distance + zoom_delta)
        self.pan_y += pan_y_delta
        self.pan_z += pan_z_delta
        self.push()

    def push(self) -> bool:
        """Write the current state onto the camera. Returns False if there is none."""
        import bpy  # noqa: PLC0415

        camera = bpy.data.objects.get(CAMERA)
        if camera is None or bpy.data.objects.get(PIVOT) is None:
            return False

        yaw = radians(self.yaw)
        pitch = radians(self.pitch)
        camera.location = (
            self.distance * cos(pitch) * sin(yaw),
            -self.distance * cos(pitch) * cos(yaw) + self.pan_y,
            self.distance * sin(-pitch) + self.pan_z,
        )
        # Blender's camera looks down its local -Z, so a camera level with its
        # subject is pitched 90 degrees off its rest orientation.
        camera.rotation_euler = (radians(90.0 + self.pitch), 0.0, yaw)
        return True
