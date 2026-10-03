#!/usr/bin/env python3
"""Gen-motion world-space retargeting for a Puppeteer target skeleton.

For each mapped bone and frame:

    delta_ws  = source_pose_ws @ inverse(source_rest_ws)
    target_ws = delta_ws @ target_rest_ws

The target rotation is then converted back through its posed parent into a
local pose quaternion.  This avoids depending on matching local bone roll.
"""

import argparse
import json
import math
import os
from pathlib import Path
from typing import Dict, List, Tuple

import bpy  # type: ignore
from mathutils import Quaternion, Vector  # type: ignore

from .rig_io import (
    assign_vertex_weights,
    build_rigged_mesh_objects,
    clear_bpy_data,
    import_mesh,
    load_rigged_mesh_data,
    parent_to_armature,
)


SOURCE_ROOT = "mixamorig:Hips"
TARGET_ROOT = "joint23"


def load_mapping(path: str) -> tuple[dict, Dict[str, str]]:
    with open(path, encoding="utf-8-sig") as handle:
        data = json.load(handle)
    bone_map = data.get("bone_map")
    if not isinstance(bone_map, dict) or not bone_map:
        raise ValueError(f"Mapping has no non-empty bone_map: {path}")
    return data, bone_map


def resolve_roots(
    mapping_data: dict,
    src_override: str = "",
    dst_override: str = "",
) -> Tuple[str, str]:
    roots = mapping_data.get("root_bones", {})
    source = (
        src_override
        or roots.get("source")
        or roots.get("mixamo")
        or SOURCE_ROOT
    )
    target = (
        dst_override
        or roots.get("puppeteer")
        or roots.get("target")
        or TARGET_ROOT
    )
    return source, target


def stabilize(
    quaternion: Quaternion,
    previous: Quaternion | None,
) -> Quaternion:
    """Keep consecutive quaternion keys on one hemisphere."""
    quaternion = quaternion.normalized()
    if previous is not None and quaternion.dot(previous) < 0.0:
        quaternion = Quaternion(
            (
                -quaternion.w,
                -quaternion.x,
                -quaternion.y,
                -quaternion.z,
            )
        )
    return quaternion


def clamp_delta_deg(quaternion: Quaternion, maximum: float) -> Quaternion:
    """Optionally clamp a world-space delta magnitude."""
    if maximum <= 0:
        return quaternion
    quaternion = quaternion.normalized()
    theta = 2.0 * math.acos(max(-1.0, min(1.0, abs(quaternion.w))))
    maximum_rad = math.radians(maximum)
    if theta <= maximum_rad:
        return quaternion
    return Quaternion((1.0, 0.0, 0.0, 0.0)).slerp(
        quaternion,
        maximum_rad / theta,
    ).normalized()


def import_source_animation(
    path: str,
    global_scale: float = 1.0,
) -> Tuple[bpy.types.Object, bpy.types.Action]:
    """Import a BVH or FBX source armature and return its active action."""
    extension = Path(path).suffix.lower()
    if extension not in {".bvh", ".fbx"}:
        raise ValueError(f"Source animation must be .bvh or .fbx: {path}")
    before = set(bpy.data.objects)
    if extension == ".bvh":
        bpy.ops.import_anim.bvh(
            filepath=path,
            axis_forward="-Z",
            axis_up="Y",
            global_scale=global_scale,
        )
    else:
        bpy.ops.import_scene.fbx(filepath=path)
    new_objects = [obj for obj in bpy.data.objects if obj not in before]
    armatures = [obj for obj in new_objects if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError(f"No armature found in source animation: {path}")
    source_armature = armatures[0]
    for obj in new_objects:
        if obj.type == "MESH":
            obj.hide_viewport = True
            obj.hide_render = True
    source_armature.name = "AnimSource"
    if (
        source_armature.animation_data is None
        or source_armature.animation_data.action is None
    ):
        raise RuntimeError(f"No animation action found in source: {path}")
    return source_armature, source_armature.animation_data.action


def build_puppeteer_rig(
    mesh_path: str,
    rig_path: str,
) -> Tuple[bpy.types.Object, bpy.types.Object]:
    """
    Build the Puppeteer armature and bind the character mesh to it.

    The mesh is imported twice on purpose. Blender's importer gives the
    *presentable* copy — materials, UVs, textures, everything a game needs —
    while trimesh gives the plain vertex array the rig's weight table is
    indexed over. The weights are computed against the second and assigned to
    the first, then the plain copy is thrown away.

    Any format `rig_io.import_mesh` accepts works here, which is what lets a
    task retarget onto the OBJ the rigging model actually consumed rather than
    onto a GLB that has been through one more conversion than the rig has.
    """
    textured = import_mesh(mesh_path)
    data = load_rigged_mesh_data(
        mesh_path,
        rig_path,
        apply_coord_rot=True,
    )
    proxy, armature = build_rigged_mesh_objects(
        data,
        mesh_name="RigProxy",
        collection_name="RigProxy_collection",
    )
    for name in data["names"]:
        if name not in textured.vertex_groups:
            textured.vertex_groups.new(name=name)
    assign_vertex_weights(textured, data["names"], data["vertex_group"])
    bpy.data.objects.remove(proxy, do_unlink=True)
    parent_to_armature(textured, armature)

    armature.name = "PuppeteerArmature"
    textured.name = "PuppeteerMesh"
    for modifier in textured.modifiers:
        if modifier.type == "ARMATURE":
            modifier.object = armature
    textured.parent = armature
    return textured, armature


def cache_rest_world_quaternions(
    armature: bpy.types.Object,
) -> Dict[str, Quaternion]:
    armature_quaternion = armature.matrix_world.to_quaternion()
    return {
        bone.name: (
            armature_quaternion @ bone.matrix_local.to_quaternion()
        ).normalized()
        for bone in armature.data.bones
    }


def cache_local_rest_quaternions(
    armature: bpy.types.Object,
) -> Dict[str, Quaternion]:
    result = {}
    for bone in armature.data.bones:
        matrix = (
            bone.parent.matrix_local.inverted() @ bone.matrix_local
            if bone.parent is not None
            else bone.matrix_local
        )
        result[bone.name] = matrix.to_quaternion().normalized()
    return result


def validate_mapping_bones(
    mapping: Dict[str, str],
    source: bpy.types.Object,
    target: bpy.types.Object,
) -> None:
    missing_source = sorted(set(mapping) - set(source.pose.bones.keys()))
    missing_target = sorted(set(mapping.values()) - set(target.pose.bones.keys()))
    if missing_source or missing_target:
        raise ValueError(
            "Mapping references bones absent from the imported armatures. "
            f"Missing source={missing_source[:12]}, "
            f"missing target={missing_target[:12]}"
        )


def order_mapping_parent_first(
    mapping: Dict[str, str],
    target: bpy.types.Object,
) -> List[Tuple[str, str]]:
    depths: Dict[str, int] = {}

    def depth(name: str) -> int:
        if name in depths:
            return depths[name]
        bone = target.data.bones[name]
        depths[name] = (
            0 if bone.parent is None else depth(bone.parent.name) + 1
        )
        return depths[name]

    return sorted(mapping.items(), key=lambda pair: depth(pair[1]))


def reset_target_pose(armature: bpy.types.Object) -> None:
    for pose_bone in armature.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
        pose_bone.location = Vector((0.0, 0.0, 0.0))
        pose_bone.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
        pose_bone.scale = Vector((1.0, 1.0, 1.0))


def retarget_frame(
    source: bpy.types.Object,
    target: bpy.types.Object,
    ordered_mapping: List[Tuple[str, str]],
    source_rest_world: Dict[str, Quaternion],
    target_rest_world: Dict[str, Quaternion],
    target_rest_local: Dict[str, Quaternion],
    max_delta_deg: float,
) -> None:
    source_object_quaternion = source.matrix_world.to_quaternion()
    target_object_quaternion = target.matrix_world.to_quaternion()

    for source_name, target_name in ordered_mapping:
        source_pose = source.pose.bones[source_name]
        target_pose = target.pose.bones[target_name]
        target_bone = target.data.bones[target_name]

        source_pose_world = (
            source_object_quaternion @ source_pose.matrix.to_quaternion()
        ).normalized()
        delta_world = (
            source_pose_world @ source_rest_world[source_name].inverted()
        ).normalized()
        delta_world = clamp_delta_deg(delta_world, max_delta_deg)
        desired_world = (
            delta_world @ target_rest_world[target_name]
        ).normalized()

        if target_bone.parent is not None:
            parent_pose = target.pose.bones[target_bone.parent.name]
            parent_world = (
                target_object_quaternion @ parent_pose.matrix.to_quaternion()
            ).normalized()
        else:
            parent_world = target_object_quaternion
        without_self = (
            parent_world @ target_rest_local[target_name]
        ).normalized()
        target_pose.rotation_quaternion = (
            without_self.inverted() @ desired_world
        ).normalized()
        bpy.context.view_layer.update()


def apply_root_translation(
    source: bpy.types.Object,
    target: bpy.types.Object,
    source_root: str,
    target_root: str,
    bake_to_bone: bool,
    root_scale: float,
) -> Vector:
    source_pose = source.matrix_world @ source.pose.bones[source_root].matrix
    source_rest = (
        source.matrix_world @ source.data.bones[source_root].matrix_local
    )
    offset = (source_pose.translation - source_rest.translation) * root_scale
    if bake_to_bone:
        target.location = Vector((0.0, 0.0, 0.0))
        target.pose.bones[target_root].location = offset
    else:
        target.location = offset
        target.pose.bones[target_root].location = Vector((0.0, 0.0, 0.0))
    return offset


def bake_action(
    source: bpy.types.Object,
    target: bpy.types.Object,
    mapping: Dict[str, str],
    *,
    source_root: str,
    target_root: str,
    action_name: str,
    frame_start: int,
    frame_end: int,
    bake_root_to_bone: bool,
    root_scale: float,
    max_delta_deg: float,
) -> bpy.types.Action:
    source_rest_world = cache_rest_world_quaternions(source)
    target_rest_world = cache_rest_world_quaternions(target)
    target_rest_local = cache_local_rest_quaternions(target)
    ordered_mapping = order_mapping_parent_first(mapping, target)

    action = bpy.data.actions.new(action_name)
    if target.animation_data is None:
        target.animation_data_create()
    target.animation_data.action = action
    scene = bpy.context.scene
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="POSE")

    previous: Dict[str, Quaternion] = {}
    target_bones = [bone.name for bone in target.data.bones]
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        reset_target_pose(target)
        bpy.context.view_layer.update()
        retarget_frame(
            source,
            target,
            ordered_mapping,
            source_rest_world,
            target_rest_world,
            target_rest_local,
            max_delta_deg,
        )
        apply_root_translation(
            source,
            target,
            source_root,
            target_root,
            bake_root_to_bone,
            root_scale,
        )
        if not bake_root_to_bone:
            target.keyframe_insert(data_path="location", frame=frame)
        for name in target_bones:
            pose_bone = target.pose.bones[name]
            quaternion = stabilize(
                pose_bone.rotation_quaternion.copy(),
                previous.get(name),
            )
            pose_bone.rotation_quaternion = quaternion
            previous[name] = quaternion
            pose_bone.keyframe_insert(
                data_path="rotation_quaternion",
                frame=frame,
            )
            if bake_root_to_bone and name == target_root:
                pose_bone.keyframe_insert(data_path="location", frame=frame)
    bpy.ops.object.mode_set(mode="OBJECT")
    return action


def export_animated_fbx(
    path: str,
    target_armature: bpy.types.Object,
    *,
    fps: int,
    frame_start: int,
    frame_end: int,
    action_name: str,
    anim_only: bool,
) -> None:
    """Export a deterministic frame range with a UE-friendly take name."""
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    target_armature.animation_data.action.name = action_name

    bpy.ops.object.select_all(action="DESELECT")
    target_armature.select_set(True)
    if not anim_only:
        for obj in bpy.data.objects:
            if obj.type == "MESH" and not obj.hide_viewport:
                obj.select_set(True)
    bpy.context.view_layer.objects.active = target_armature
    bpy.ops.export_scene.fbx(
        filepath=path,
        check_existing=False,
        use_selection=True,
        add_leaf_bones=False,
        path_mode="COPY",
        embed_textures=not anim_only,
        mesh_smooth_type="FACE",
        use_mesh_modifiers=False,
        bake_anim=True,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=False,
        bake_anim_step=1,
        bake_anim_simplify_factor=0.0,
        bake_anim_force_startend_keying=True,
        apply_scale_options="FBX_SCALE_ALL",
        axis_forward="-Z",
        axis_up="Y",
        bake_space_transform=False,
        use_armature_deform_only=True,
        object_types={"ARMATURE"} if anim_only else {"ARMATURE", "MESH"},
    )


def run(args: argparse.Namespace) -> None:
    clear_bpy_data()
    mapping_data, mapping = load_mapping(args.mapping)
    source_root, target_root = resolve_roots(
        mapping_data,
        args.src_root,
        args.dst_root,
    )
    _, target_armature = build_puppeteer_rig(args.mesh, args.rig)
    source_armature, source_action = import_source_animation(
        args.source_anim,
        global_scale=args.global_scale,
    )
    validate_mapping_bones(mapping, source_armature, target_armature)
    if source_root not in source_armature.pose.bones:
        raise ValueError(f"Source root bone not found: {source_root}")
    if target_root not in target_armature.pose.bones:
        raise ValueError(f"Target root bone not found: {target_root}")

    frame_start = int(source_action.frame_range[0])
    frame_end = int(source_action.frame_range[1])
    action_name = args.action_name or Path(args.source_anim).stem
    root_scale = 1.0 if args.root_scale is None else args.root_scale
    action = bake_action(
        source_armature,
        target_armature,
        mapping,
        source_root=source_root,
        target_root=target_root,
        action_name=action_name,
        frame_start=frame_start,
        frame_end=frame_end,
        bake_root_to_bone=args.bake_root_to_bone,
        root_scale=root_scale,
        max_delta_deg=args.max_delta_deg,
    )
    source_bone_count = len(source_armature.data.bones)
    target_bone_count = len(target_armature.data.bones)
    bpy.data.objects.remove(source_armature, do_unlink=True)

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    export_animated_fbx(
        str(output),
        target_armature,
        fps=args.fps,
        frame_start=frame_start,
        frame_end=frame_end,
        action_name=args.action_name or "Take 001",
        anim_only=args.anim_only,
    )

    if args.info_output:
        info = {
            "source_animation": str(Path(args.source_anim).resolve()),
            "source_type": Path(args.source_anim).suffix.lower().lstrip("."),
            "target_mesh": str(Path(args.mesh).resolve()),
            "target_mesh_type": Path(args.mesh).suffix.lower().lstrip("."),
            "target_skeleton": str(Path(args.mesh).resolve()),
            "rig": str(Path(args.rig).resolve()),
            "mapping": str(Path(args.mapping).resolve()),
            "output": str(output),
            "anim_only": bool(args.anim_only),
            "action_name": action.name,
            "source_frame_range": [frame_start, frame_end],
            "output_frame_range": [frame_start, frame_end],
            "fps": args.fps,
            "retarget_method": "world_conjugation_delta",
            "src_root": source_root,
            "dst_root": target_root,
            "global_scale": args.global_scale,
            "bake_root_to_bone": args.bake_root_to_bone,
            "root_scale": root_scale,
            "max_delta_deg": args.max_delta_deg,
            "source_bone_count": source_bone_count,
            "target_bone_count": target_bone_count,
            "mapped_source_bone_count": len(set(mapping)),
            "mapped_target_bone_count": len(set(mapping.values())),
            "bone_map": mapping,
        }
        info_path = Path(args.info_output).resolve()
        info_path.parent.mkdir(parents=True, exist_ok=True)
        info_path.write_text(
            json.dumps(info, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mesh",
        "--glb",
        dest="mesh",
        required=True,
        help="Character mesh: .glb, .gltf, .obj, .ply, .stl or .fbx.",
    )
    parser.add_argument("--rig", required=True)
    parser.add_argument("--source-anim", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--info-output", default="")
    parser.add_argument("--action-name", default="")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--src-root", default="")
    parser.add_argument("--dst-root", default="")
    parser.add_argument("--global-scale", type=float, default=1.0)
    parser.add_argument("--root-scale", type=float, default=None)
    parser.add_argument("--max-delta-deg", type=float, default=0.0)
    parser.add_argument("--bake-root-to-bone", action="store_true")
    parser.add_argument("--anim-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
