"""
Import a retargeted FBX into Unreal as SkeletalMesh + AnimSequence.

Do not use the static ``import_mesh.py`` sibling (it forces non-skeletal).

- Full character: leave ``existing_skeleton`` empty.
- Anim onto an existing Skeleton: set ``existing_skeleton`` / ``--no-mesh``.

    python scripts/import_generated_asset.py \\
        --src retargeted.fbx --engine ue5 --kind motion \\
        --uproject /path/to/MyGame.uproject
"""

import json
import os
from pathlib import Path
from typing import Any, Optional

USAGE_MOTION = "motion"
SUPPORTED_SUFFIXES = (".fbx",)
DEFAULT_DEST_PACKAGE = "/Game/Generated/Motion"
JOB_ENV_VAR = "AAAGF_IMPORT_JOB"


def _unreal():
    try:
        import unreal  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "import_motion.py must run inside Unreal Engine's Python.\n"
            "  UnrealEditor.exe <project>.uproject "
            "-ExecutePythonScript=engine_adapters/ue5/import_generated/import_motion.py"
        ) from e
    return unreal


def sanitize_asset_name(name: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
    return cleaned or "GeneratedMotion"


def import_retargeted_motion(
    src_path: str,
    dest_package: str = DEFAULT_DEST_PACKAGE,
    asset_name: Optional[str] = None,
    *,
    existing_skeleton: Optional[str] = None,
    import_mesh: bool = True,
    replace_existing: bool = True,
    save: bool = True,
) -> dict:
    """
    Import one FBX as skeletal content.

    Returns ``ok, skeletal_mesh, skeleton, animations, warnings, error``.
    """
    unreal = _unreal()
    src = Path(src_path)
    report: dict[str, Any] = {
        "ok": False,
        "source": str(src),
        "kind": "motion",
        "usage": USAGE_MOTION,
        "skeletal_mesh": None,
        "skeleton": None,
        "animations": [],
        "imported_assets": [],
        "warnings": [],
        "error": None,
    }
    if not src.is_file():
        raise FileNotFoundError(f"motion file not found: {src}")
    if src.suffix.lower() not in SUPPORTED_SUFFIXES:
        report["warnings"].append(
            f"unusual suffix {src.suffix!r}; motion import expects .fbx"
        )

    name = sanitize_asset_name(asset_name or src.stem)
    anim_only = bool(existing_skeleton) or not import_mesh
    before = set(_list_assets(unreal, dest_package))

    if anim_only:
        paths = _import_animation_onto_skeleton(
            unreal,
            src,
            dest_package,
            name,
            skeleton_path=existing_skeleton,
            replace_existing=replace_existing,
            report=report,
        )
    else:
        paths = _import_skeletal_with_animation(
            unreal,
            src,
            dest_package,
            name,
            replace_existing=replace_existing,
            report=report,
        )

    created = [p for p in _list_assets(unreal, dest_package) if p not in before]
    if not created:
        created = list(paths)
    report["imported_assets"] = created

    skeletal = None
    skeleton = existing_skeleton
    animations: list[str] = []
    for path in created:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if asset is None:
            continue
        class_name = asset.get_class().get_name()
        if class_name == "SkeletalMesh" and skeletal is None:
            skeletal = path
            try:
                skeleton = asset.get_editor_property("skeleton").get_path_name()
            except Exception:  # noqa: BLE001
                pass
        elif class_name == "Skeleton" and not skeleton:
            skeleton = path
        elif class_name in {"AnimSequence", "AnimSequenceBase"}:
            animations.append(path)

    report["skeletal_mesh"] = skeletal
    report["skeleton"] = skeleton.split(".")[0] if skeleton else None
    report["animations"] = animations

    if save:
        for path in created:
            try:
                unreal.EditorAssetLibrary.save_asset(path)
            except Exception as exc:  # noqa: BLE001
                report["warnings"].append(f"could not save {path}: {exc}")

    report["ok"] = bool(animations) and bool(report["skeleton"] or skeletal)
    if not report["ok"]:
        report["error"] = (
            "import produced no AnimSequence / Skeleton — check the Output "
            "Log for the FBX translator error, and that import_animations is on"
        )
    unreal.log(
        f"[import_retargeted_motion] mesh={report['skeletal_mesh']} "
        f"skeleton={report['skeleton']} anims={len(animations)} "
        f"ok={report['ok']}"
    )
    return report


def _import_skeletal_with_animation(
    unreal,
    src: Path,
    dest_package: str,
    name: str,
    *,
    replace_existing: bool,
    report: dict,
) -> list[str]:
    if not hasattr(unreal, "FbxImportUI"):
        raise RuntimeError(
            "this engine build has no FbxImportUI; cannot import skeletal FBX"
        )
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(src))
    task.set_editor_property("destination_path", dest_package)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("replace_existing", replace_existing)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", False)

    options = unreal.FbxImportUI()
    _set(options, "automated_import_should_detect_type", False, report)
    _set(options, "mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH, report)
    _set(options, "original_import_type", unreal.FBXImportType.FBXIT_SKELETAL_MESH, report)
    _set(options, "import_mesh", True, report)
    _set(options, "import_as_skeletal", True, report)
    _set(options, "import_animations", True, report)
    _set(options, "import_materials", True, report)
    _set(options, "import_textures", True, report)
    skeletal_data = options.get_editor_property("skeletal_mesh_import_data")
    if skeletal_data is not None:
        _set(skeletal_data, "import_morph_targets", False, report)
        _set(skeletal_data, "update_skeleton_reference_pose", False, report)
    anim_data = options.get_editor_property("anim_sequence_import_data")
    if anim_data is not None:
        _set(anim_data, "animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME, report)
        _set(anim_data, "import_meshes_in_bone_hierarchy", False, report)
    task.set_editor_property("options", options)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported = list(task.get_editor_property("imported_object_paths") or [])
    if not imported:
        raise RuntimeError(
            f"UE imported nothing from {src}. Enable the FBX importer plugin "
            "and check the Output Log."
        )
    return [str(p).split(".")[0] for p in imported]


def _import_animation_onto_skeleton(
    unreal,
    src: Path,
    dest_package: str,
    name: str,
    *,
    skeleton_path: Optional[str],
    replace_existing: bool,
    report: dict,
) -> list[str]:
    if not skeleton_path:
        raise ValueError(
            "anim-only import needs existing_skeleton=/Game/.../Skeleton"
        )
    skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)
    if skeleton is None:
        raise FileNotFoundError(f"existing skeleton not found: {skeleton_path}")

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(src))
    task.set_editor_property("destination_path", dest_package)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("replace_existing", replace_existing)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", False)

    options = unreal.FbxImportUI()
    _set(options, "automated_import_should_detect_type", False, report)
    _set(options, "mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION, report)
    _set(options, "original_import_type", unreal.FBXImportType.FBXIT_ANIMATION, report)
    _set(options, "import_mesh", False, report)
    _set(options, "import_as_skeletal", False, report)
    _set(options, "import_animations", True, report)
    _set(options, "skeleton", skeleton, report)
    anim_data = options.get_editor_property("anim_sequence_import_data")
    if anim_data is not None:
        _set(anim_data, "animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME, report)
    task.set_editor_property("options", options)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported = list(task.get_editor_property("imported_object_paths") or [])
    if not imported:
        raise RuntimeError(
            f"UE imported no animation from {src} onto {skeleton_path}"
        )
    return [str(p).split(".")[0] for p in imported]


def _set(obj, prop: str, value, report: dict) -> bool:
    if value is None:
        return False
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception as exc:  # noqa: BLE001
        report["warnings"].append(f"could not set {prop}: {exc}")
        return False


def _list_assets(unreal, package_path: str) -> list:
    try:
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            return []
        return list(
            unreal.EditorAssetLibrary.list_assets(
                package_path, recursive=True, include_folder=False
            )
            or []
        )
    except Exception:  # noqa: BLE001
        return []


def _args_from_job(job: dict) -> list[str]:
    argv: list[str] = []
    for key in ("src", "dest", "name", "report", "existing_skeleton"):
        flag = key.replace("_", "-")
        if job.get(key):
            argv += [f"--{flag}", str(job[key])]
    if job.get("no_mesh"):
        argv += ["--no-mesh"]
    if job.get("no_save"):
        argv += ["--no-save"]
    return argv


def _parse_args(argv: list[str]):
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        prog="import_motion.py",
        description="Import a retargeted motion FBX into UE5",
    )
    ap.add_argument("--src", required=True)
    ap.add_argument("--dest", default=DEFAULT_DEST_PACKAGE)
    ap.add_argument("--name", default=None)
    ap.add_argument(
        "--existing-skeleton",
        default=None,
        help="Import animation onto this Skeleton (anim-only FBX path).",
    )
    ap.add_argument("--no-mesh", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--report", default=None)
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    import sys  # noqa: PLC0415

    if argv is None:
        argv = sys.argv[1:]
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
            existing_skeleton=args.existing_skeleton,
            import_mesh=not args.no_mesh,
            save=not args.no_save,
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

    if os.environ.get("AAAGF_UE_QUIT_WHEN_DONE"):
        try:
            _unreal().SystemLibrary.quit_editor()
        except Exception as exc:  # noqa: BLE001
            print(f"[import_motion] could not quit the editor: {exc}")
    if os.environ.get("AAAGF_UE_EXIT_ON_DONE"):
        raise SystemExit(0 if report.get("ok") else 1)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
