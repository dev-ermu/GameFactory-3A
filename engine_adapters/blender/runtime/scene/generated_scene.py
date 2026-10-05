"""
engine_adapters/blender/runtime/scene/generated_scene.py

Drop a model-generated environment into the running session.

The runtime's end of the world pipeline: `scripts/prepare_world_asset.py` turns
a world export into one repaired `world.glb`, and this imports it into the
process the characters are already standing in, so "can this be walked around"
is answered before an engine is involved.

Everything lands under one collection below a single root empty, giving the
environment one transform to scale or offset and one thing to delete when the
next world replaces it — a generated scene is routinely hundreds of objects.

将模型生成的环境导入到正在运行的会话中。

运行时的世界加载流程如下：`scripts/prepare_world_asset.py`会将导出的世界数据修复为单个完整的`world.glb`文件，随后该文件会被导入到角色所处的场景中，这样在引擎介入之前就能确定“该场景是否可行走”。

所有生成的物体都会被归入一个根空集合下的同一个集合中，这样一来，只需调整该集合的变换参数就能实现环境的缩放或偏移；当下个世界替换当前环境时，直接删除这个集合即可——毕竟生成场景通常会包含数百个物体。
"""

from pathlib import Path
from typing import Tuple

from ...import_generated.import_mesh import SUPPORTED_SUFFIXES, import_file
from ..assets.resolver import resolve

DEFAULT_COLLECTION = "generated_scene"

__all__ = ["SUPPORTED_SUFFIXES", "import_generated_scene", "remove_collection"]


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


def import_generated_scene(scene_path: str,
                           collection_name: str = DEFAULT_COLLECTION,
                           scale: float = 1.0,
                           location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                           replace_existing: bool = True) -> dict:
    """
    Import a generated environment and group it under one collection. Returns a
    dict with `collection`, `root`, `objects` and `path`.

    `scene_path` is real or `/Library/...`, in any `SUPPORTED_SUFFIXES` format —
    in practice a `.glb` from the world preparer or a raw `.ply` off a generator.
    `scale` is the knob that makes a character the right size relative to the
    set, since generated worlds arrive in whatever unit the generator felt like.
    `replace_existing=False` lets successive imports accumulate, which is
    occasionally what you want and never what you get by accident.
    """
    bpy = _bpy()
    real_path = Path(resolve(scene_path))
    if not real_path.is_file():
        raise FileNotFoundError(f"generated scene not found: {real_path}")

    if replace_existing:
        remove_collection(collection_name)

    added = import_file(bpy, real_path)
    if not added:
        raise RuntimeError(f"import produced no objects: {real_path}")
    existing = {o.name for o in bpy.data.objects} - {o.name for o in added}

    collection = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(collection)

    root = bpy.data.objects.new(f"{collection_name}_root", None)
    collection.objects.link(root)

    for obj in added:
        # Re-parent only what the file left at the top; a child already has a
        # parent inside the import and must keep it.
        if obj.parent is None or obj.parent.name in existing:
            obj.parent = root
        _move_to_collection(obj, collection)

    root.location = tuple(location)
    root.scale = (scale, scale, scale)

    print(f"[scene] imported {len(added)} object(s) from {real_path.name} "
          f"into {collection.name!r} (scale={scale})")
    return {
        "collection": collection.name,
        "root": root.name,
        "objects": [o.name for o in added],
        "path": str(real_path),
    }


def remove_collection(name: str) -> int:
    """Delete a collection and everything in it. Returns the object count."""
    bpy = _bpy()
    collection = bpy.data.collections.get(name)
    if collection is None:
        return 0
    doomed = list(collection.all_objects)
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)
    return len(doomed)


def _move_to_collection(obj, collection) -> None:
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)
