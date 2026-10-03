"""
engine_adapters/blender/runtime/assets/actions.py

Load animation out of a file and put it on a character.

Blender has no "import just the animation" operator — an FBX or BVH brings in a
skeleton too — so `load_action` imports, keeps the Action datablock and deletes
the objects that came with it.

Keeping the clip separate from the character is what lets one walk cycle drive
every character whose skeleton it fits, which is why they were retargeted
through gen_motion (`operators/.../retarget_utils`) first.
"""

from typing import Optional

from .resolver import resolve

#: Files that carry animation. FBX is what the retargeter writes; BVH is what
#: most motion generators emit.
ACTION_SUFFIXES = (".fbx", ".bvh")


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - only true outside Blender
        raise RuntimeError(
            "the Blender runtime must run inside a bpy interpreter; "
            "see engine_adapters/blender/runtime/README.md"
        ) from e
    return bpy


def load_action(file_path: str, rename_to: Optional[str] = None) -> str:
    """
    Import an animation file and return the name of the Action it produced.

    The skeleton that arrived with it is deleted; only the Action survives.
    """
    bpy = _bpy()
    real_path = resolve(file_path)
    if not real_path.is_file():
        raise FileNotFoundError(f"action file not found: {real_path}")

    suffix = real_path.suffix.lower()
    if suffix not in ACTION_SUFFIXES:
        raise ValueError(
            f"cannot read animation from {suffix!r}; expected one of "
            f"{', '.join(ACTION_SUFFIXES)}")

    actions_before = set(bpy.data.actions.keys())
    objects_before = set(bpy.data.objects.keys())

    try:
        bpy.ops.object.select_all(action="DESELECT")
    except RuntimeError:
        pass
    bpy.context.view_layer.objects.active = None

    if suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(real_path))
    else:
        bpy.ops.import_anim.bvh(filepath=str(real_path))

    new_actions = [n for n in bpy.data.actions.keys() if n not in actions_before]
    for name in [n for n in bpy.data.objects.keys() if n not in objects_before]:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    if not new_actions:
        raise RuntimeError(
            f"{real_path.name} imported but carried no animation — check that "
            f"the exporter wrote keyframes and not just a rest pose")

    action = bpy.data.actions[new_actions[0]]
    if rename_to:
        action.name = rename_to
    return action.name


def bind_action(obj_name: str, action_name: str, loop: bool = True,
                play_rate: float = 1.0) -> str:
    """
    Attach an Action to the character rooted at `obj_name` and widen the scene's
    frame range to fit. Returns the object it actually landed on, which is the
    armature underneath the root when there is one.

    `loop` and `play_rate` are recorded for the tick loop rather than applied:
    Blender has no per-action loop flag outside the NLA, and retiming through
    the NLA would rebuild the strip on every input change.
    """
    bpy = _bpy()
    obj = bpy.data.objects[obj_name]

    target = obj if obj.type == "ARMATURE" else None
    if target is None:
        target = next((c for c in obj.children_recursive if c.type == "ARMATURE"), obj)

    if target.animation_data is None:
        target.animation_data_create()
    action = bpy.data.actions[action_name]
    target.animation_data.action = action

    start, end = (int(v) for v in action.frame_range)
    scene = bpy.context.scene
    scene.frame_start = min(scene.frame_start, start)
    scene.frame_end = max(scene.frame_end, end)

    target["play_rate"] = float(play_rate)
    target["action_loop"] = bool(loop)
    return target.name
