"""
Re-import an exported FBX and check that it actually animates.

Structural validity is not enough — evaluate the mesh/bones on several frames
and require a measurable pose change (``pose_animated``).

    python -m operators.gen_motion.funcs.retarget_utils.inspect_fbx \\
        --input retargeted.fbx --output fbx_inspection.json

Use ``--allow-no-mesh`` for armature-only exports.
"""

import argparse
import json
from pathlib import Path


# Metres of travel before we count the clip as animated (noise floor).
DEFORM_EPSILON = 1e-3
# Sample across the clip — ends alone often look like rest pose.
MOTION_SAMPLES = 8


def inspect_fbx(input_path: str, *, require_mesh: bool = True) -> dict:
    """Import one FBX into an empty scene and report what an engine will see."""
    import bpy
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(
        filepath=str(Path(input_path).resolve()),
        anim_offset=0.0,
    )
    scene = bpy.context.scene
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    actions = list(bpy.data.actions)
    keyframes = sorted(
        {
            int(round(point.co.x))
            for action in actions
            for curve in action.fcurves
            for point in curve.keyframe_points
        }
    )

    report = {
        "input": str(Path(input_path).resolve()),
        "mesh_count": len(meshes),
        "armature_count": len(armatures),
        "action_count": len(actions),
        "keyframe_count": len(keyframes),
        "frame_range": [keyframes[0], keyframes[-1]] if keyframes else None,
        "fps": int(scene.render.fps),
        "bone_count": len(armatures[0].data.bones) if armatures else 0,
        "vertex_group_count": (
            len(meshes[0].vertex_groups) if meshes else 0
        ),
        "skinned": bool(
            meshes
            and any(
                modifier.type == "ARMATURE" for modifier in meshes[0].modifiers
            )
        ),
    }
    report.update(_measure_motion(bpy, meshes, armatures, keyframes))
    report.update(_measure_scale(Vector, meshes or armatures))

    # pose_animated: root slide alone is not enough (T-pose sliding fails).
    report["valid"] = bool(
        (meshes or not require_mesh)
        and armatures
        and actions
        and keyframes
        and report["pose_animated"]
        and (report["skinned"] or not require_mesh)
    )
    return report


def _measure_motion(bpy, meshes, armatures, keyframes) -> dict:
    """Measure total vs pose-only displacement across sampled frames."""
    blank = {
        "mesh_displacement_m": None,
        "pose_displacement_m": None,
        "bone_displacement_m": None,
        "root_travel_m": None,
        "animated": False,
        "pose_animated": False,
    }
    if not keyframes or not armatures:
        return blank

    step = max(1, len(keyframes) // MOTION_SAMPLES)
    frames = sorted({*keyframes[::step], keyframes[-1]})
    armature = armatures[0]

    def sample(frame: int):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        root = armature.matrix_world.translation.copy()
        bones = [
            armature.matrix_world @ bone.head.copy()
            for bone in armature.pose.bones
        ]
        points = None
        if meshes:
            evaluated = meshes[0].evaluated_get(
                bpy.context.evaluated_depsgraph_get()
            )
            mesh = evaluated.to_mesh()
            points = [
                evaluated.matrix_world @ vertex.co.copy()
                for vertex in mesh.vertices
            ]
            evaluated.to_mesh_clear()
        return root, bones, points

    def spread(rest, posed, offset):
        if rest is None or posed is None or len(rest) != len(posed):
            return 0.0
        return max((a - (b - offset)).length for a, b in zip(rest, posed))

    rest_root, rest_bones, rest_points = sample(frames[0])
    travel = mesh_move = pose_move = bone_move = 0.0
    zero = rest_root - rest_root

    for frame in frames[1:]:
        root, bones, points = sample(frame)
        shift = root - rest_root
        travel = max(travel, shift.length)
        mesh_move = max(mesh_move, spread(rest_points, points, zero))
        pose_move = max(pose_move, spread(rest_points, points, shift))
        bone_move = max(bone_move, spread(rest_bones, bones, shift))

    pose_change = max(pose_move, bone_move)
    return {
        "mesh_displacement_m": (
            round(mesh_move, 6) if rest_points is not None else None
        ),
        "pose_displacement_m": (
            round(pose_move, 6) if rest_points is not None else None
        ),
        "bone_displacement_m": round(bone_move, 6),
        "root_travel_m": round(travel, 6),
        "animated": max(mesh_move, bone_move, travel) > DEFORM_EPSILON,
        "pose_animated": pose_change > DEFORM_EPSILON,
    }


def _measure_scale(Vector, objects) -> dict:
    """Imported height / AABB (metres) for unit sanity checks."""
    if not objects:
        return {"height_m": None, "bounds_m": None}
    lows, highs = [], []
    for obj in objects:
        corners = [
            obj.matrix_world @ Vector(corner) for corner in obj.bound_box
        ]
        lows.append([min(corner[axis] for corner in corners) for axis in range(3)])
        highs.append([max(corner[axis] for corner in corners) for axis in range(3)])
    low = [min(values[axis] for values in lows) for axis in range(3)]
    high = [max(values[axis] for values in highs) for axis in range(3)]
    return {
        "height_m": round(high[2] - low[2], 6),
        "bounds_m": [
            [round(value, 6) for value in low],
            [round(value, 6) for value in high],
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--allow-no-mesh",
        action="store_true",
        help="Validate an animation-only FBX containing no mesh.",
    )
    args = parser.parse_args()
    report = inspect_fbx(args.input, require_mesh=not args.allow_no_mesh)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["valid"]:
        raise RuntimeError(f"FBX failed structural validation: {report}")


if __name__ == "__main__":
    main()


__all__ = ["DEFORM_EPSILON", "inspect_fbx"]
