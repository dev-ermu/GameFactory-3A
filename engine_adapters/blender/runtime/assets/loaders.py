"""
engine_adapters/blender/runtime/assets/loaders.py

Import a file and hand back a single object to hold on to.

The runtime tracks a player by one name but an import produces however many
objects the file contained, so this picks a root among them and parents the rest
to it. An armature wins that election when there is one: it is what an action
binds to and what the mesh is already skinned to, which keeps the transform and
animation hierarchies the same shape.

The suffix-to-operator table is shared from `import_generated/import_mesh.py`,
so a build that imports `.usdz` offline imports it into the runtime too.
"""

from typing import List, Optional

from ...import_generated.import_mesh import SUPPORTED_SUFFIXES, import_file
from .resolver import resolve

__all__ = ["SUPPORTED_SUFFIXES", "import_as_root", "import_objects"]


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - only true outside Blender
        raise RuntimeError(
            "the Blender runtime must run inside a bpy interpreter; "
            "see engine_adapters/blender/runtime/README.md"
        ) from e
    return bpy


def import_objects(file_path: str) -> List:
    """Import a file, resolving virtual paths, and return the new objects."""
    bpy = _bpy()
    real_path = resolve(file_path)
    if not real_path.is_file():
        raise FileNotFoundError(f"asset not found: {real_path}")

    # The FBX and glTF importers act on the active object when one is set, and
    # a leftover selection from a previous import is how you get a mesh
    # silently parented into the wrong character.
    _clear_selection(bpy)

    added = import_file(bpy, real_path)
    if not added:
        raise RuntimeError(f"import produced no objects: {real_path}")
    return added


def import_as_root(file_path: str, rename_to: Optional[str] = None,
                   prefer_armature: bool = True) -> str:
    """
    Import a real or `/Library/...` path and return its single root object's
    name, as Blender recorded it: `rename_to` is a request, and Blender appends
    `.001` if the name is taken, so the return value is the authoritative one.
    """
    added = import_objects(file_path)

    root = None
    if prefer_armature:
        root = next((o for o in added if o.type == "ARMATURE"), None)
    if root is None:
        root = added[0]

    for obj in added:
        # Only re-parent what the file left at the top level; anything that
        # already has a parent is being positioned by it.
        if obj is not root and obj.parent is None:
            obj.parent = root

    if rename_to:
        root.name = rename_to
    return root.name


def _clear_selection(bpy) -> None:
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except RuntimeError:
        # Raised when the context has no object mode to act in — an empty
        # scene, which is already the clean state this wants.
        pass
    bpy.context.view_layer.objects.active = None
