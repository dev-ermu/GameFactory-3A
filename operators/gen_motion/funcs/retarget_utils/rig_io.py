"""Puppeteer rig (.txt) to Blender armature helpers for motion retargeting.

Adapted from the Puppeteer ``export.py`` and ``export_glb.py`` utilities.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bpy  # type: ignore
import numpy as np
import trimesh
from mathutils import Vector  # type: ignore


from .formats import SUPPORTED_MESH_SUFFIXES


ROT = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
        [0.0, 1.0, 0.0],
    ]
)


def clear_bpy_data() -> None:
    """Wipe Blender datablocks so each subprocess starts from a clean scene."""
    for collection in (
        bpy.data.actions,
        bpy.data.armatures,
        bpy.data.cameras,
        bpy.data.collections,
        bpy.data.images,
        bpy.data.materials,
        bpy.data.meshes,
        bpy.data.objects,
        bpy.data.textures,
    ):
        for value in list(collection):
            collection.remove(value)


def load_rigged_mesh_data(
    mesh_path: str,
    rig_path: str,
    apply_coord_rot: bool = True,
) -> Dict[str, Any]:
    """Parse a Puppeteer rig and its matching mesh into Blender-ready arrays."""
    mesh = trimesh.load(
        mesh_path,
        force="mesh",
        process=False,
        maintain_order=True,
    )
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    raw_vertices = np.asarray(mesh.vertices)
    vertices = (ROT @ raw_vertices.T).T if apply_coord_rot else raw_vertices
    faces = np.asarray(mesh.faces)
    vertex_count = vertices.shape[0]

    def map_coord(x: float, y: float, z: float) -> np.ndarray:
        point = np.array([x, y, z])
        return ROT @ point if apply_coord_rot else point

    joint_pos: Dict[str, np.ndarray] = {}
    joint_hier: Dict[str, List[str]] = {}
    joint_skin: List[List[str]] = []
    id_mapping: Dict[str, int] = {}
    name_mapping: Dict[int, str] = {}
    parent_mapping: Dict[str, str] = {}
    root_name: Optional[str] = None

    with open(rig_path, "r", encoding="utf-8") as handle:
        for line in handle:
            words = line.split()
            if not words:
                continue
            if words[0] == "joints":
                if len(words) < 5:
                    raise ValueError(f"Malformed joints line in {rig_path}: {line}")
                joint_pos[words[1]] = map_coord(
                    float(words[2]),
                    float(words[3]),
                    float(words[4]),
                )
                index = len(id_mapping)
                id_mapping[words[1]] = index
                name_mapping[index] = words[1]
            elif words[0] == "root":
                root_name = words[1]
            elif words[0] == "hier":
                joint_hier.setdefault(words[1], []).append(words[2])
            elif words[0] == "skin":
                joint_skin.append(words[1:])

    if not joint_pos:
        raise ValueError(f"No joints found in Puppeteer rig: {rig_path}")
    if root_name not in id_mapping:
        raise ValueError(
            f"Puppeteer rig root {root_name!r} is missing from joints: {rig_path}"
        )

    joint_count = len(joint_pos)
    bones = np.zeros((joint_count, 6))
    parents: List[Optional[int]] = []
    names: List[str] = []
    for parent, children in joint_hier.items():
        if parent not in id_mapping:
            raise ValueError(f"Unknown parent joint {parent!r} in {rig_path}")
        for child in children:
            if child not in id_mapping:
                raise ValueError(f"Unknown child joint {child!r} in {rig_path}")
            parent_mapping[child] = parent

    children_by_id: defaultdict[int, list[int]] = defaultdict(list)
    for index in range(joint_count):
        name = name_mapping[index]
        names.append(name)
        if name == root_name:
            parents.append(None)
            continue
        if name not in parent_mapping:
            raise ValueError(f"Joint {name!r} has no parent in {rig_path}")
        parent_index = id_mapping[parent_mapping[name]]
        parents.append(parent_index)
        children_by_id[parent_index].append(index)

    for index in range(joint_count):
        name = name_mapping[index]
        head = joint_pos[name]
        tail = head + np.array([0.0, 0.0, 0.1])
        children = joint_hier.get(name, [])
        if len(children) == 1:
            tail = joint_pos[children[0]]
        elif name != root_name:
            parent_name = name_mapping[parents[index]]
            tail = head + (joint_pos[name] - joint_pos[parent_name]) * 0.5
        if np.linalg.norm(tail - head) < 1e-8:
            tail = head + np.array([0.0, 0.0, 0.01])
        bones[index, :3] = head
        bones[index, 3:] = tail

    skin = np.zeros((vertex_count, joint_count))
    for item in joint_skin:
        if not item:
            continue
        vertex_index = int(item[0])
        if vertex_index < 0 or vertex_index >= vertex_count:
            raise ValueError(
                f"Skin vertex index {vertex_index} is outside mesh bounds"
            )
        for offset in range(1, len(item), 2):
            if offset + 1 >= len(item):
                raise ValueError(f"Malformed skin line for vertex {vertex_index}")
            skin[vertex_index, id_mapping[item[offset]]] = float(item[offset + 1])

    dfs_order: List[int] = []
    stack = [id_mapping[root_name]]
    while stack:
        index = stack.pop()
        dfs_order.append(index)
        stack.extend(reversed(children_by_id[index]))
    if len(dfs_order) != joint_count:
        raise ValueError(
            f"Puppeteer rig is disconnected: visited {len(dfs_order)}/"
            f"{joint_count} joints"
        )

    return {
        "vertices": vertices,
        "faces": faces,
        "bones": bones,
        "parents": parents,
        "names": names,
        "vertex_group": skin,
        "dfs_order": dfs_order,
    }


def assign_vertex_weights(
    obj: bpy.types.Object,
    names: List[str],
    weights: np.ndarray,
    group_per_vertex: int = 4,
) -> None:
    """Assign normalized top-k weights to existing Blender vertex groups."""
    existing = {group.name for group in obj.vertex_groups}
    top_k = min(group_per_vertex, weights.shape[1])
    order = np.argsort(-weights, axis=1)
    selected = weights[np.arange(weights.shape[0])[..., None], order[:, :top_k]]
    totals = selected.sum(axis=1)

    for vertex_index in range(weights.shape[0]):
        if totals[vertex_index] <= 0:
            continue
        for rank in range(top_k):
            joint_index = int(order[vertex_index, rank])
            name = names[joint_index]
            if name not in existing:
                continue
            weight = float(selected[vertex_index, rank] / totals[vertex_index])
            if weight > 0:
                obj.vertex_groups[name].add(
                    [vertex_index],
                    weight,
                    "REPLACE",
                )


def build_rigged_mesh_objects(
    data: Dict[str, Any],
    mesh_name: str = "character",
    collection_name: str = "CA_collection",
) -> Tuple[bpy.types.Object, bpy.types.Object]:
    """Build a Blender proxy mesh and armature from Puppeteer rig data."""
    mesh = bpy.data.meshes.new("PuppeteerProxyMesh")
    mesh.from_pydata(data["vertices"], [], data["faces"])
    mesh.update()
    proxy = bpy.data.objects.new(mesh_name, mesh)

    collection = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(collection)
    collection.objects.link(proxy)

    bpy.ops.object.armature_add(enter_editmode=True)
    armature = bpy.context.object.data
    default_bone = armature.edit_bones.get("Bone")

    for order_index, joint_index in enumerate(data["dfs_order"]):
        name = data["names"][joint_index]
        parent_index = data["parents"][joint_index]
        bone = (
            default_bone
            if order_index == 0 and parent_index is None
            else armature.edit_bones.new(name)
        )
        bone.name = name
        bone.head = Vector(tuple(data["bones"][joint_index, :3]))
        bone.tail = Vector(tuple(data["bones"][joint_index, 3:]))
        if parent_index is not None:
            bone.parent = armature.edit_bones.get(data["names"][parent_index])
            bone.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    armature_object = bpy.context.object
    armature_object.name = "PuppeteerArmature"
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    armature_object.select_set(True)
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.parent_set(type="ARMATURE_NAME")
    assign_vertex_weights(proxy, data["names"], data["vertex_group"])
    return proxy, armature_object


def import_mesh(mesh_path: str) -> bpy.types.Object:
    """
    Import a character mesh in any format the rigging stage accepts.

    Everything is joined into one object, because the rig's skin weights are a
    single table indexed over one vertex array — a GLB that arrives as four
    material-split meshes has no vertex 9000 to bind until they are one.

    Import options are chosen so Blender's vertex order matches trimesh's, not
    for looks. ``load_rigged_mesh_data`` reads the same file through trimesh to
    get the weight table, and the two orders have to agree or the weights land
    on the wrong vertices — a rig that loads, poses, and deforms into garbage.
    Splitting by material or by sharp edges reorders vertices, so both are off.
    """
    path = Path(mesh_path)
    suffix = path.suffix.lower()
    before = set(bpy.context.scene.objects)

    if suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path), merge_vertices=False)
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(
            filepath=str(path),
            use_split_objects=False,
            use_split_groups=False,
            validate_meshes=False,
        )
    elif suffix == ".ply":
        bpy.ops.wm.ply_import(filepath=str(path))
    elif suffix == ".stl":
        bpy.ops.wm.stl_import(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise ValueError(
            f"Cannot import {suffix!r} as a character mesh; expected one of "
            f"{', '.join(SUPPORTED_MESH_SUFFIXES)}: {path}"
        )

    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj not in before and obj.type == "MESH"
    ]
    if not meshes:
        raise RuntimeError(f"No mesh found in {path}")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    result = bpy.context.view_layer.objects.active
    result.name = "TexturedMesh"
    return result


def import_glb(glb_path: str) -> bpy.types.Object:
    """Deprecated alias for `import_mesh`, kept for external callers."""
    return import_mesh(glb_path)


def parent_to_armature(
    mesh_obj: bpy.types.Object,
    armature_obj: bpy.types.Object,
) -> None:
    """Parent a textured mesh to an armature using existing group names."""
    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.parent_set(type="ARMATURE_NAME")
