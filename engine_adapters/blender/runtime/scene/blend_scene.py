"""
engine_adapters/blender/runtime/scene/blend_scene.py

Pull a hand-authored `.blend` into the running session.

`.blend` is the only format that round-trips everything Blender knows — node
materials, modifiers, lighting rigs — so it is what an authored set arrives as.
Generated environments arrive as `.glb` or `.ply` and go through
`generated_scene.py` instead.

Appending copies the data in, linking references the original: link when the set
is shared and still being edited, append when the session must be
self-contained, since `save_blend` of a linked scene writes a file full of
pointers to a machine that may not be there later.
"""

from pathlib import Path

from ..assets.resolver import resolve

#: Name prefixes owned by the runtime rather than by the loaded scene.
RUNTIME_PREFIXES = ("player_", "vfx_")


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


def load_scene(scene_path: str = "", link: bool = False) -> str:
    """
    Append or link a `.blend` into the active scene. Returns the scene's name.

    Every recoverable problem — no path, missing file, wrong format — leaves the
    current scene standing and says so, because a live session losing its world
    to a typo is worse than a session that ignored one command.
    """
    bpy = _bpy()
    scene = bpy.context.scene

    if not scene_path:
        print("[scene] no scene_path; keeping the current scene")
        _ensure_default_light(bpy, scene)
        return scene.name

    real_path = Path(resolve(scene_path))
    if not real_path.is_file():
        print(f"[scene] not found ({real_path}); keeping the current scene")
        _ensure_default_light(bpy, scene)
        return scene.name

    if real_path.suffix.lower() != ".blend":
        print(f"[scene] {real_path.name} is not a .blend — use import_scene for "
              f"generated meshes; keeping the current scene")
        _ensure_default_light(bpy, scene)
        return scene.name

    with bpy.data.libraries.load(str(real_path), link=link) as (source, target):
        target.collections = list(source.collections)
        target.objects = list(source.objects)
        # Only adopt the file's world when this scene has none, so loading a
        # prop library does not repaint the lighting of the set already loaded.
        if scene.world is None:
            target.worlds = list(source.worlds)

    collections = [c for c in target.collections if c is not None]
    for collection in collections:
        scene.collection.children.link(collection)

    # An object inside a linked collection is already in the scene; linking it
    # again raises. Only the loose ones need it.
    already_linked = {o.name for c in collections for o in c.all_objects}
    loose = 0
    for obj in target.objects:
        if obj is None or obj.name in already_linked:
            continue
        try:
            scene.collection.objects.link(obj)
            loose += 1
        except RuntimeError:
            pass

    if scene.world is None:
        world = next((w for w in getattr(target, "worlds", []) or [] if w is not None), None)
        if world is not None:
            scene.world = world
            print(f"[scene] adopted world {world.name!r}")

    _ensure_default_light(bpy, scene)
    print(f"[scene] {'linked' if link else 'appended'} {len(collections)} "
          f"collection(s) + {loose} loose object(s) from {real_path.name}")
    return scene.name


def clear_runtime_objects() -> int:
    """
    The reset between takes: remove what the runtime spawned and leave the
    loaded set standing. Returns how many objects went.
    """
    bpy = _bpy()
    doomed = [o for o in bpy.data.objects if o.name.startswith(RUNTIME_PREFIXES)]
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    return len(doomed)


def _ensure_default_light(bpy, scene) -> None:
    """A scene with no light renders black, which reads as a broken import."""
    if "default_sun" in bpy.data.objects:
        return
    if any(o.type == "LIGHT" for o in scene.objects):
        return
    data = bpy.data.lights.new("default_sun", type="SUN")
    data.energy = 3.0
    sun = bpy.data.objects.new("default_sun", data)
    scene.collection.objects.link(sun)
    sun.location = (5.0, -5.0, 8.0)
