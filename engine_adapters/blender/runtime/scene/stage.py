"""
engine_adapters/blender/runtime/scene/stage.py

A minimal set for looking at one character: floor, two lights, orbit camera.

`stage_pivot` is a camera rig, not a scene root: the camera is its only child,
so the controller orbits within the pivot's local space and `reframe` aims the
whole rig by moving the pivot to the character's centre. The character and floor
stay at the top level — parenting the subject to the thing that measures it
makes `reframe` chase its own tail, and parenting the floor would lift the
ground whenever the pivot rose to a character's chest.

The lighting is deliberately dull, a key and a fill: flattering light hides
exactly the seams and inverted normals this stage exists to catch.


这是一个用于查看单个角色的最小场景集合：包含地面、两盏灯光以及轨道摄像机。

`stage_pivot`是一个摄像机支架，并非场景根节点：摄像机是其唯一子物体。因此控制器会在该支架的局部空间内进行轨道运动，而`reframe`功能则是通过将支架移动到角色中心来调整整个支架的方向。角色和地面始终位于最顶层——如果将角色设为测量对象的子物体，`reframe`就会陷入无限循环；而如果把地面设为子物体，那么每当支架上升到角色胸部高度时，地面也会被一同抬高。

这里的灯光设置刻意调得较暗，采用主光与补光组合：这种柔和的光线恰好能掩盖该场景旨在捕捉的模型接缝和法线翻转问题。
"""

from math import radians
from typing import Optional

from ..assets.actions import bind_action, load_action
from ..assets.loaders import import_as_root

PIVOT = "stage_pivot"
CHARACTER = "stage_character"
CAMERA = "stage_camera"
FLOOR = "stage_floor"
KEY_LIGHT = "stage_key_light"
FILL_LIGHT = "stage_fill_light"

#: Metres. Big enough that a human-scale character is not standing on a coin.
FLOOR_SIZE = 10.0


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


class PreviewStage:
    def __init__(self) -> None:
        self.current_action: Optional[str] = None

    def ensure(self) -> None:
        """Build whatever is missing. Safe to call on every start."""
        bpy = _bpy()
        pivot = _get_or_create_empty(bpy, PIVOT)

        if FLOOR not in bpy.data.objects:
            bpy.ops.mesh.primitive_plane_add(size=FLOOR_SIZE)
            bpy.context.active_object.name = FLOOR

        if KEY_LIGHT not in bpy.data.objects:
            data = bpy.data.lights.new(KEY_LIGHT, type="SUN")
            data.energy = 3.0
            key = bpy.data.objects.new(KEY_LIGHT, data)
            bpy.context.scene.collection.objects.link(key)
            key.location = (4.0, -4.0, 6.0)
            key.rotation_euler = (radians(45), 0.0, radians(45))

        if FILL_LIGHT not in bpy.data.objects:
            data = bpy.data.lights.new(FILL_LIGHT, type="POINT")
            data.energy = 200.0
            fill = bpy.data.objects.new(FILL_LIGHT, data)
            bpy.context.scene.collection.objects.link(fill)
            fill.location = (-3.0, 3.0, 3.0)

        if CAMERA not in bpy.data.objects:
            data = bpy.data.cameras.new(CAMERA)
            camera = bpy.data.objects.new(CAMERA, data)
            bpy.context.scene.collection.objects.link(camera)
            camera.parent = pivot
            camera.location = (0.0, -6.0, 1.6)
            camera.rotation_euler = (radians(85), 0.0, 0.0)
            bpy.context.scene.camera = camera

    def set_character(self, asset_path: str, scale: float = 1.0,
                      yaw: float = 0.0) -> str:
        """Replace whatever is on the stage. Returns the new object's name."""
        bpy = _bpy()
        self.ensure()

        previous = bpy.data.objects.get(CHARACTER)
        if previous is not None:
            for obj in [previous] + list(previous.children_recursive):
                bpy.data.objects.remove(obj, do_unlink=True)

        name = import_as_root(asset_path, rename_to=CHARACTER)
        obj = bpy.data.objects[name]
        obj.scale = (scale, scale, scale)
        obj.rotation_euler = (0.0, 0.0, radians(yaw))
        return name

    def play_action(self, action_path: str, loop: bool = True,
                    play_rate: float = 1.0) -> str:
        bpy = _bpy()
        if CHARACTER not in bpy.data.objects:
            raise RuntimeError("nothing on the stage; send set_preview_character first")
        action = load_action(action_path)
        bind_action(CHARACTER, action, loop=loop, play_rate=play_rate)
        self.current_action = action
        return action

    def reframe(self) -> bool:
        """Move the camera rig to the character's centre, so the orbit is on it."""
        import mathutils  # noqa: PLC0415

        bpy = _bpy()
        obj = bpy.data.objects.get(CHARACTER)
        pivot = bpy.data.objects.get(PIVOT)
        if obj is None or pivot is None:
            return False

        # Blender does not refresh matrix_world until the depsgraph runs, and a
        # reframe right after an import would otherwise measure the old one.
        bpy.context.view_layer.update()

        corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
        pivot.location = (
            sum(v.x for v in corners) / len(corners),
            sum(v.y for v in corners) / len(corners),
            sum(v.z for v in corners) / len(corners),
        )
        return True


def _get_or_create_empty(bpy, name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
    return obj
