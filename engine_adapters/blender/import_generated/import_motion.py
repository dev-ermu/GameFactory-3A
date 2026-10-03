"""
Import a retargeted FBX (mesh + armature + action) into Blender.

Unlike ``import_mesh.py``, this keeps the armature and skin intact and checks
that the pose actually changes across the clip.

    blender --background --factory-startup \\
        --python engine_adapters/blender/import_generated/import_motion.py -- \\
        --src retargeted.fbx --dest out/ --report report.json
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

SUPPORTED_SUFFIXES = (".fbx", ".glb", ".gltf", ".bvh")
JOB_ENV_VAR = "AAAGF_IMPORT_JOB"
# Matches retarget_utils.inspect_fbx
POSE_EPSILON = 1e-3


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "import_motion.py must run inside a bpy interpreter.\n"
            "  blender --background --factory-startup --python "
            "engine_adapters/blender/import_generated/import_motion.py -- --src ...\n"
            "  (or a Python that can `import bpy`)"
        ) from e
    return bpy


def sanitize_asset_name(name: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "_-") else "_" for c in name)
    return cleaned.strip("_") or "GeneratedMotion"


def import_retargeted_motion(
    src_path: str,
    dest_dir: str = "generated_blender_library",
    asset_name: Optional[str] = None,
    *,
    export: tuple = (),
    preview: bool = False,
    preview_frames: int = 24,
    reset_scene: bool = True,
) -> dict:
    """Import one motion FBX; ``ok`` requires armature + action + pose change."""
    bpy = _bpy()
    from mathutils import Vector  # noqa: PLC0415

    src = Path(src_path)
    report: dict[str, Any] = {
        "ok": False,
        "source": str(src),
        "kind": "motion",
        "object": None,
        "armature": None,
        "action": None,
        "mesh_count": 0,
        "armature_count": 0,
        "bone_count": 0,
        "action_count": 0,
        "keyframe_count": 0,
        "frame_range": None,
        "fps": None,
        "skinned": False,
        "vertex_group_count": 0,
        "mesh_displacement_m": None,
        "pose_displacement_m": None,
        "bone_displacement_m": None,
        "root_travel_m": None,
        "pose_animated": False,
        "height_m": None,
        "exports": {},
        "preview": None,
        "warnings": [],
        "error": None,
    }
    if not src.is_file():
        raise FileNotFoundError(f"motion file not found: {src}")
    if src.suffix.lower() not in SUPPORTED_SUFFIXES:
        report["warnings"].append(
            f"unusual suffix {src.suffix!r}; expected one of {SUPPORTED_SUFFIXES}"
        )

    name = sanitize_asset_name(asset_name or src.stem)
    if reset_scene:
        bpy.ops.wm.read_factory_settings(use_empty=True)

    before = set(bpy.data.objects.keys())
    actions_before = set(bpy.data.actions.keys())
    _import_file(bpy, src)
    added = [
        bpy.data.objects[key]
        for key in bpy.data.objects.keys()
        if key not in before
    ]
    new_actions = [
        bpy.data.actions[key]
        for key in bpy.data.actions.keys()
        if key not in actions_before
    ]

    meshes = [obj for obj in added if obj.type == "MESH"]
    armatures = [obj for obj in added if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError(
            f"{src.name} imported without an armature — a static mesh FBX "
            "cannot carry a retargeted clip. Re-export with the motion "
            "pipeline's world_delta stage."
        )
    if not new_actions:
        # Some exporters attach the action without a new datablock name.
        attached = [
            arm.animation_data.action
            for arm in armatures
            if arm.animation_data and arm.animation_data.action
        ]
        new_actions = attached
    if not new_actions:
        raise RuntimeError(
            f"{src.name} has an armature but no Action — the export wrote a "
            "rest pose only."
        )

    armature = armatures[0]
    armature.name = name
    action = new_actions[0]
    if action.name != name:
        action.name = name
    if armature.animation_data is None:
        armature.animation_data_create()
    armature.animation_data.action = action

    for index, mesh in enumerate(meshes):
        mesh.name = name if index == 0 else f"{name}_mesh{index}"
        if mesh.parent is None:
            mesh.parent = armature
        if not any(mod.type == "ARMATURE" for mod in mesh.modifiers):
            mod = mesh.modifiers.new(name="Armature", type="ARMATURE")
            mod.object = armature
            report["warnings"].append(
                f"re-attached Armature modifier on {mesh.name}"
            )

    keyframes = sorted(
        {
            int(round(point.co.x))
            for curve in action.fcurves
            for point in curve.keyframe_points
        }
    )
    scene = bpy.context.scene
    if keyframes:
        scene.frame_start = keyframes[0]
        scene.frame_end = keyframes[-1]
    scene.render.fps = scene.render.fps or 30

    report.update(
        {
            "object": meshes[0].name if meshes else armature.name,
            "armature": armature.name,
            "action": action.name,
            "mesh_count": len(meshes),
            "armature_count": len(armatures),
            "bone_count": len(armature.data.bones),
            "action_count": len(new_actions),
            "keyframe_count": len(keyframes),
            "frame_range": (
                [keyframes[0], keyframes[-1]] if keyframes else None
            ),
            "fps": int(scene.render.fps),
            "skinned": bool(
                meshes
                and any(
                    mod.type == "ARMATURE" for mod in meshes[0].modifiers
                )
            ),
            "vertex_group_count": (
                len(meshes[0].vertex_groups) if meshes else 0
            ),
        }
    )
    report.update(_measure_motion(bpy, meshes, armature, keyframes))
    report["height_m"] = _measure_height(Vector, meshes or [armature])

    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if export:
        report["exports"] = _export(
            bpy,
            armature,
            meshes,
            dest,
            name,
            tuple(export),
            report,
        )
    if preview:
        report["preview"] = _render_preview(
            bpy,
            armature,
            meshes,
            dest,
            name,
            keyframes,
            preview_frames,
            report,
        )

    report["ok"] = bool(
        armatures
        and new_actions
        and keyframes
        and report["pose_animated"]
        and (report["skinned"] or not meshes)
    )
    if not report["ok"] and not report["error"]:
        report["error"] = (
            "imported structurally but pose did not change across the clip"
        )
    print(
        f"[import_retargeted_motion] {armature.name} "
        f"bones={report['bone_count']} keys={report['keyframe_count']} "
        f"pose={report['pose_displacement_m']} "
        f"root={report['root_travel_m']} ok={report['ok']}"
    )
    return report


def _import_file(bpy, src: Path) -> None:
    suffix = src.suffix.lower()
    if suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(src), anim_offset=0.0)
    elif suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(src))
    elif suffix == ".bvh":
        bpy.ops.import_anim.bvh(filepath=str(src))
    else:
        raise ValueError(f"no motion importer for {suffix!r}")


def _measure_motion(bpy, meshes, armature, keyframes) -> dict:
    blank = {
        "mesh_displacement_m": None,
        "pose_displacement_m": None,
        "bone_displacement_m": None,
        "root_travel_m": None,
        "pose_animated": False,
    }
    if not keyframes:
        return blank

    samples = sorted({*keyframes[:: max(1, len(keyframes) // 8)], keyframes[-1]})

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

    rest_root, rest_bones, rest_points = sample(samples[0])
    travel = mesh_move = pose_move = bone_move = 0.0
    zero = rest_root - rest_root
    for frame in samples[1:]:
        root, bones, points = sample(frame)
        shift = root - rest_root
        travel = max(travel, shift.length)
        mesh_move = max(mesh_move, spread(rest_points, points, zero))
        pose_move = max(pose_move, spread(rest_points, points, shift))
        bone_move = max(bone_move, spread(rest_bones, bones, shift))

    return {
        "mesh_displacement_m": (
            round(mesh_move, 6) if rest_points is not None else None
        ),
        "pose_displacement_m": (
            round(pose_move, 6) if rest_points is not None else None
        ),
        "bone_displacement_m": round(bone_move, 6),
        "root_travel_m": round(travel, 6),
        "pose_animated": max(pose_move, bone_move) > POSE_EPSILON,
    }


def _measure_height(Vector, objects) -> Optional[float]:
    if not objects:
        return None
    lows, highs = [], []
    for obj in objects:
        corners = [
            obj.matrix_world @ Vector(corner) for corner in obj.bound_box
        ]
        lows.append([min(c[i] for c in corners) for i in range(3)])
        highs.append([max(c[i] for c in corners) for i in range(3)])
    low = [min(v[i] for v in lows) for i in range(3)]
    high = [max(v[i] for v in highs) for i in range(3)]
    return round(high[2] - low[2], 6)


def _export(bpy, armature, meshes, dest, name, kinds, report) -> dict:
    exports = {}
    for kind in kinds:
        path = dest / f"{name}.{kind}"
        bpy.ops.object.select_all(action="DESELECT")
        armature.select_set(True)
        for mesh in meshes:
            mesh.select_set(True)
        bpy.context.view_layer.objects.active = armature
        if kind == "fbx":
            bpy.ops.export_scene.fbx(
                filepath=str(path),
                use_selection=True,
                add_leaf_bones=False,
                bake_anim=True,
                bake_anim_use_all_actions=False,
                bake_anim_use_nla_strips=False,
                bake_anim_simplify_factor=0.0,
                object_types={"ARMATURE", "MESH"} if meshes else {"ARMATURE"},
                axis_forward="-Z",
                axis_up="Y",
            )
        elif kind == "glb":
            bpy.ops.export_scene.gltf(
                filepath=str(path),
                use_selection=True,
                export_animations=True,
                export_apply=False,
            )
        elif kind == "blend":
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
        else:
            report["warnings"].append(f"unknown export kind {kind!r}")
            continue
        exports[kind] = str(path)
    return exports


def _render_preview(
    bpy,
    armature,
    meshes,
    dest,
    name,
    keyframes,
    preview_frames,
    report,
) -> Optional[str]:
    if not keyframes:
        report["warnings"].append("no keyframes; preview skipped")
        return None
    scene = bpy.context.scene
    scene.frame_start = keyframes[0]
    scene.frame_end = min(
        keyframes[-1],
        keyframes[0] + max(1, preview_frames) - 1,
    )
    # A fixed camera looking at the character from the front-right.
    bpy.ops.object.camera_add(location=(2.5, -2.5, 1.4))
    camera = bpy.context.object
    camera.rotation_euler = (1.1, 0.0, 0.785)
    scene.camera = camera
    if not scene.world:
        scene.world = bpy.data.worlds.new("World")
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.fps = scene.render.fps or 30
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    out = dest / f"{name}_preview.mp4"
    scene.render.filepath = str(out)
    try:
        bpy.ops.render.render(animation=True)
    except Exception as exc:  # noqa: BLE001 - preview is best-effort
        report["warnings"].append(f"preview render failed: {exc}")
        return None
    return str(out) if out.is_file() else None


def _args_from_job(job: dict) -> list[str]:
    argv: list[str] = []
    for key in ("src", "dest", "name", "report"):
        if job.get(key):
            argv += [f"--{key}", str(job[key])]
    if job.get("preview"):
        argv += ["--preview"]
    if job.get("preview_frames"):
        argv += ["--preview-frames", str(job["preview_frames"])]
    for kind in job.get("export") or ():
        argv += ["--export", str(kind)]
    return argv


def _parse_args(argv: list[str]):
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        prog="import_motion.py",
        description="Import a retargeted motion FBX into Blender",
    )
    ap.add_argument("--src", required=True, help="Retargeted .fbx / .glb / .bvh")
    ap.add_argument("--dest", default="generated_blender_library")
    ap.add_argument("--name", default=None)
    ap.add_argument("--export", action="append", default=[], choices=["fbx", "glb", "blend"])
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--preview-frames", type=int, default=24)
    ap.add_argument("--report", default=None)
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
        if "--" in argv:
            argv = argv[argv.index("--") + 1 :]
        job_path = os.environ.get(JOB_ENV_VAR)
        if job_path and not any(a.startswith("--") for a in argv):
            job = json.loads(Path(job_path).read_text(encoding="utf-8"))
            argv = _args_from_job(job)

    args = _parse_args(argv)
    try:
        report = import_retargeted_motion(
            args.src,
            args.dest,
            args.name,
            export=tuple(args.export),
            preview=args.preview,
            preview_frames=args.preview_frames,
        )
    except Exception as exc:  # noqa: BLE001
        report = {
            "ok": False,
            "source": args.src,
            "kind": "motion",
            "error": str(exc),
            "warnings": [],
        }

    text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    print(text)
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    code = main()
    if os.environ.get("AAAGF_BLENDER_EXIT_ON_DONE"):
        raise SystemExit(code)
