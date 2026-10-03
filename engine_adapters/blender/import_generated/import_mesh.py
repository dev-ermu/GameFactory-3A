"""
engine_adapters/blender/import_generated/import_mesh.py

Imports a mesh produced by `models/` into Blender, conditions it, and reports
what actually landed.

**This module runs inside a `bpy` interpreter** — either Blender itself
(`blender --background --python ...`) or a Python whose environment has the pip
`bpy` wheel. Like its UE5 sibling, the `bpy` import is deferred, so the host-side
launcher and tests can read its constants with no Blender installed.

Blender's role in the chain is not "another target engine". It is the neutral
ground between a generator and an engine: the only importer here that reads
`.ply` and `.usd`, applies a pivot or a decimation the generator did not, and
writes the result back out as the `.glb` / `.fbx` a game engine wants. A world
prepared by `scripts/prepare_world_asset.py` arrives as an ordinary `.glb` and
takes the same path as any other asset.

Units and axes: Blender is metres and Z-up, glTF is metres and Y-up. The glTF
importer converts on the way in and the exporter converts back, so a round trip
through this file is identity — which is exactly why `--export glb` is safe to
put between a generator and UE5.

CLI (what the host-side launcher calls):
    blender --background --factory-startup \\
        --python engine_adapters/blender/import_generated/import_mesh.py -- \\
        --src <abs path to model.glb> \\
        --dest <abs path to a library directory> \\
        --name Sword_001 \\
        --usage asset \\
        --report <abs path to import_report.json>

Batch mode reads a `<kind>_results_summary.json` written by a pipeline runner:
    ... -- --summary <path to 3d_object_results_summary.json>
"""

import json
import os
from pathlib import Path
from typing import Any, Optional

#: Usage tiers, matching `engine_adapters/ue5/import_generated/import_mesh.py`
#: so one `--usage` means the same thing whichever engine receives the asset.
USAGE_ASSET = "asset"
USAGE_VFX_STANDALONE = "vfx_standalone"
USAGE_VFX_PARTICLE = "vfx_particle"
USAGES = (USAGE_ASSET, USAGE_VFX_STANDALONE, USAGE_VFX_PARTICLE)

#: Formats the generators emit that Blender can ingest. Wider than UE5's list —
#: `.ply` is why a world export can be looked at before any engine is involved.
SUPPORTED_SUFFIXES = (".glb", ".gltf", ".fbx", ".obj", ".ply", ".stl",
                      ".usd", ".usda", ".usdc", ".usdz", ".abc")

#: Written next to wherever the launcher points; a plain directory, not a
#: `.blend`, so every artifact stays addressable by file path.
DEFAULT_DEST = "generated_blender_library"

#: `--normalize-scale` target. Blender is metric, so 1 m — the UE5 importer says
#: 100 for the same thing, because it works in centimetres.
NORMALIZE_TARGET_METRES = 1.0

#: Formats `--export` can write.
EXPORT_KINDS = ("glb", "fbx", "blend")


def _bpy():
    """Import `bpy` with a message that says where this script has to run."""
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - only true outside Blender
        raise RuntimeError(
            "import_mesh.py must run inside a bpy interpreter.\n"
            "  blender --background --factory-startup --python "
            "engine_adapters/blender/import_generated/import_mesh.py -- --src ...\n"
            "  (or `pip install bpy` into the environment and run it directly)"
        ) from e
    return bpy


def sanitize_asset_name(name: str) -> str:
    """Blender object names allow most characters; file names do not."""
    cleaned = "".join(c if (c.isalnum() or c in "_-") else "_" for c in name)
    return cleaned.strip("_") or "GeneratedMesh"


# ── Import ────────────────────────────────────────────────────────────────────


def import_generated_mesh(
    src_path: str,
    dest_dir: str = DEFAULT_DEST,
    asset_name: Optional[str] = None,
    *,
    usage: str = USAGE_ASSET,
    target_tris: Optional[int] = None,
    source_tris: Optional[int] = None,
    pivot: Optional[str] = None,
    normalize_scale: bool = False,
    export: tuple = ("glb",),
    preview: bool = False,
    reset_scene: bool = True,
) -> dict:
    """
    Import one generated mesh and report what Blender actually produced.

    Args:
        src_path: Absolute path to the generated file.
        dest_dir: Directory the conditioned copies are written into.
        asset_name: Object and file name; defaults to the sanitized source stem.
        usage: One of `USAGES`. `asset` (default) conditions nothing — no
            decimation, no pivot change, no rescale. The two `vfx_*` tiers differ
            in pivot and scale handling only.
        target_tris: Advisory triangle budget. Exceeding it adds a Decimate
            modifier and always a warning: decimating after the fact damages UVs,
            and generating low-poly does not.
        source_tris: Triangle count the caller read from the file, recorded so a
            mismatch is visible in the report.
        pivot: `None` (tier default) | `"keep"` | `"center"` | `"bottom"` |
            `"top"`. Applied to the mesh data, not the object transform, so it
            survives export.
        normalize_scale: Scale uniformly until the largest bound is
            `NORMALIZE_TARGET_METRES`.
        export: Any of `EXPORT_KINDS`. Empty tuple imports without writing.
        preview: Also render a single poster frame next to the exports.
        reset_scene: Start from an empty scene. Turn off to import several
            assets into one session.

    Returns:
        dict with keys `ok, object, source, usage, tris, vertices, materials,
        bounds, dimensions, exports, preview, warnings, error`.
    """
    bpy = _bpy()

    src = Path(src_path)
    report: dict[str, Any] = {
        "ok": False, "source": str(src), "usage": usage, "object": None,
        "tris": None, "vertices": None, "source_tris": source_tris,
        "bounds": None, "dimensions": None, "materials": [],
        "exports": {}, "preview": None, "warnings": [], "error": None,
    }
    if usage not in USAGES:
        raise ValueError(f"unknown usage {usage!r}; expected one of {USAGES}")
    if not src.is_file():
        raise FileNotFoundError(f"generated mesh not found: {src}")
    if src.suffix.lower() not in SUPPORTED_SUFFIXES:
        report["warnings"].append(
            f"unusual suffix {src.suffix!r}; Blender may have no importer for it")

    name = sanitize_asset_name(asset_name or src.stem)
    pivot, normalize_scale, target_tris = _tier_defaults(
        usage, pivot, normalize_scale, target_tris, report)

    if reset_scene:
        _reset_scene(bpy)

    imported = _run_import(bpy, src, report)
    obj = _join_meshes(bpy, imported, name, report)
    report["object"] = obj.name

    if pivot and pivot != "keep":
        _apply_pivot(bpy, obj, pivot, report)
    if normalize_scale:
        _apply_normalize_scale(bpy, obj, report)
    if target_tris:
        _apply_target_tris(bpy, obj, target_tris, report)

    _measure(bpy, obj, report)
    _tier_warnings(usage, report)

    # Absolute, because Blender resolves a relative output path against the
    # blend file — which a headless import does not have. The exporters fall
    # back to the working directory, but the render silently writes nothing.
    dest = Path(dest_dir).resolve()
    if export:
        report["exports"] = _export(bpy, obj, dest, name, tuple(export), report)
    if preview:
        report["preview"] = _render_preview(bpy, obj, dest, name, report)

    report["ok"] = True
    print(f"[import_generated_mesh] {obj.name} tris={report['tris']} "
          f"materials={len(report['materials'])} "
          f"warnings={len(report['warnings'])}")
    return report


def _tier_defaults(usage: str, pivot: Optional[str], normalize_scale: bool,
                   target_tris: Optional[int], report: dict):
    """Per-tier defaults. An explicit argument always wins."""
    if usage == USAGE_ASSET:
        return (pivot or "keep"), normalize_scale, target_tris
    if usage == USAGE_VFX_STANDALONE:
        return (pivot or "center"), normalize_scale, target_tris
    # vfx_particle is instanced by a particle system, so it wants a meaningful
    # pivot and a unit size — otherwise every instance is offset and mis-scaled.
    return (pivot or "center"), True, target_tris


def _tier_warnings(usage: str, report: dict) -> None:
    if usage == USAGE_VFX_STANDALONE:
        report["warnings"].append(
            "vfx_standalone: swap the material for emissive / transparent and "
            "confirm the UVs tile seamlessly before scrolling them")
    if usage == USAGE_VFX_PARTICLE and report.get("tris"):
        report["warnings"].append(
            f"vfx_particle: budget is per-mesh tris x instances -- "
            f"{report['tris']} tris is fine for tens of instances, tight for "
            f"hundreds. Measure the frame time, do not trust a fixed cap")


def _reset_scene(bpy) -> None:
    """Empty the file. `--factory-startup` still ships the default cube."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


#: Suffix -> the operator Blender 4.x exposes.
_IMPORTERS = {
    ".glb": "import_scene.gltf", ".gltf": "import_scene.gltf",
    ".fbx": "import_scene.fbx",
    ".obj": "wm.obj_import",
    ".ply": "wm.ply_import",
    ".stl": "wm.stl_import",
    ".usd": "wm.usd_import", ".usda": "wm.usd_import",
    ".usdc": "wm.usd_import", ".usdz": "wm.usd_import",
    ".abc": "wm.alembic_import",
}

#: The pre-4.0 name of the same operator. Blender moved OBJ, PLY and STL to new
#: C++ importers and kept the old Python ones around for a while; which of the
#: two exists depends on the build, so both are tried.
_LEGACY_IMPORTERS = {
    "wm.obj_import": "import_scene.obj",
    "wm.ply_import": "import_mesh.ply",
    "wm.stl_import": "import_mesh.stl",
}


def _resolve_operator(bpy, dotted: str):
    """`"wm.ply_import"` -> the callable, or None when this build lacks it."""
    group, _, operator = dotted.partition(".")
    namespace = getattr(bpy.ops, group, None)
    if namespace is None or not hasattr(namespace, operator):
        return None
    return getattr(namespace, operator)


def import_file(bpy, src: Path) -> list:
    """
    Run the right importer for `src` and return every object it added.

    Objects of all types come back — armatures, lights and cameras included —
    because the callers differ on what they want. This file keeps only meshes;
    the playable runtime under `../runtime/` needs the armatures too.
    """
    dotted = _IMPORTERS.get(Path(src).suffix.lower())
    if dotted is None:
        raise ValueError(
            f"no Blender importer for {Path(src).suffix!r}; supported: "
            f"{', '.join(SUPPORTED_SUFFIXES)}")

    candidates = [dotted]
    legacy = _LEGACY_IMPORTERS.get(dotted)
    if legacy:
        candidates.append(legacy)

    before = set(bpy.data.objects.keys())
    for candidate in candidates:
        operator = _resolve_operator(bpy, candidate)
        if operator is None:
            continue
        operator(filepath=str(src))
        break
    else:
        raise RuntimeError(
            f"this Blender build exposes none of {candidates} — enable the "
            f"matching Import-Export add-on, or convert the file first")

    return [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]


def _run_import(bpy, src: Path, report: dict) -> list:
    """Import `src` and return the mesh objects it added to the scene."""
    added = import_file(bpy, src)
    meshes = [o for o in added if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(
            f"Blender imported {len(added)} object(s) from {src} and none of them "
            f"is a mesh. Check the console for the importer's own error.")
    if len(added) != len(meshes):
        report["warnings"].append(
            f"{len(added) - len(meshes)} non-mesh object(s) imported "
            f"(armature / camera / light) and left out of the asset")
    return meshes


def _join_meshes(bpy, meshes: list, name: str, report: dict):
    """
    Collapse a multi-part import into one object.

    Generators routinely emit a mesh per material or per layer. A game asset is
    one object, and joining before measuring is what makes `tris` the number the
    engine will see.
    """
    for obj in bpy.data.objects:
        obj.select_set(False)
    for obj in meshes:
        obj.select_set(True)

    target = meshes[0]
    bpy.context.view_layer.objects.active = target
    if len(meshes) > 1:
        bpy.ops.object.join()
        report["warnings"].append(f"{len(meshes)} mesh parts joined into one object")

    target.name = name
    target.data.name = name
    return target


def _world_bounds(obj):
    """`(min, max)` corner of the object's world-space bounding box."""
    corners = [obj.matrix_world @ __import__("mathutils").Vector(c)
               for c in obj.bound_box]
    axes = list(zip(*[(c.x, c.y, c.z) for c in corners]))
    return tuple(min(a) for a in axes), tuple(max(a) for a in axes)


def _apply_normalize_scale(bpy, obj, report: dict) -> None:
    """Scale uniformly until the largest dimension is `NORMALIZE_TARGET_METRES`."""
    largest = max(obj.dimensions)
    if largest <= 1e-6:
        report["warnings"].append("degenerate bounds; scale not normalized")
        return
    factor = NORMALIZE_TARGET_METRES / largest
    obj.scale = (factor, factor, factor)
    _apply_transform(bpy, obj)
    report["warnings"].append(
        f"normalized scale by {factor:.4f} (largest bound -> "
        f"{NORMALIZE_TARGET_METRES} m)")


def _apply_pivot(bpy, obj, pivot: str, report: dict) -> None:
    """
    Move the mesh so `pivot` sits on the object's origin.

    Blender is Z-up, so "bottom" is min Z — the base an energy pillar grows from.
    The vertices move rather than the object, because an object-level offset is
    dropped by every exporter that bakes transforms.
    """
    import mathutils  # noqa: PLC0415 - only exists inside bpy

    low, high = _world_bounds(obj)
    centre = [(low[i] + high[i]) / 2.0 for i in range(3)]
    pivot = pivot.lower()
    if pivot == "center":
        point = centre
    elif pivot == "bottom":
        point = [centre[0], centre[1], low[2]]
    elif pivot == "top":
        point = [centre[0], centre[1], high[2]]
    else:
        report["warnings"].append(f"unknown pivot {pivot!r}; left unchanged")
        return

    _translate_mesh(obj, mathutils.Vector((-point[0], -point[1], -point[2])))
    report["warnings"].append(
        f"pivot={pivot}: mesh moved by ({-point[0]:.3f}, {-point[1]:.3f}, "
        f"{-point[2]:.3f}) m")


def _translate_mesh(obj, delta) -> None:
    for vertex in obj.data.vertices:
        vertex.co += delta


def _apply_transform(bpy, obj) -> None:
    """Bake the object's transform into its mesh data."""
    for other in bpy.data.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def _apply_target_tris(bpy, obj, target_tris: int, report: dict) -> None:
    """
    Bring the mesh down to `target_tris` with a Decimate modifier.

    This is the fallback, not the plan: generating low-poly keeps UVs and normals
    intact and decimating a two-million-face mesh afterwards does not. Whatever
    happens is recorded as a warning.
    """
    current = _count_triangles(bpy, obj)
    if current <= target_tris:
        return

    ratio = max(0.01, min(1.0, float(target_tris) / float(current)))
    modifier = obj.modifiers.new(name="AAAGF_Decimate", type="DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = ratio
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    except RuntimeError as e:
        report["warnings"].append(f"decimation failed ({e}); mesh left untouched")
        return
    report["warnings"].append(
        f"decimated {current} -> ~{target_tris} tris (ratio {ratio:.3f}). UVs and "
        f"normals degrade here; regenerate low-poly instead when you can")


def _count_triangles(bpy, obj) -> int:
    """
    Triangles the renderer will see, modifiers included.

    `len(polygons)` would undercount a quad mesh by half, so the evaluated mesh
    is asked for its loop triangles instead.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    finally:
        evaluated.to_mesh_clear()


def _measure(bpy, obj, report: dict) -> None:
    """Fill the validation fields — existence alone is not proof of an import."""
    try:
        report["tris"] = _count_triangles(bpy, obj)
        report["vertices"] = len(obj.data.vertices)
    except Exception as e:  # noqa: BLE001 - a broken mesh must still report
        report["warnings"].append(f"could not read mesh statistics: {e}")

    try:
        low, high = _world_bounds(obj)
        report["bounds"] = {"min": list(low), "max": list(high)}
        report["dimensions"] = [round(v, 6) for v in obj.dimensions]
    except Exception as e:  # noqa: BLE001
        report["warnings"].append(f"could not read bounds: {e}")

    report["materials"] = [slot.material.name for slot in obj.material_slots
                           if slot.material is not None]

    if not report.get("tris"):
        report["warnings"].append("imported object reports 0 triangles")
    if not report.get("materials"):
        report["warnings"].append("imported object has no material slots")
    source_tris = report.get("source_tris")
    if source_tris and report.get("tris") and source_tris != report["tris"]:
        report["warnings"].append(
            f"source file has {source_tris} triangles, Blender reports "
            f"{report['tris']} -- conditioning changed the mesh")


def _export(bpy, obj, dest: Path, name: str, kinds: tuple, report: dict) -> dict:
    """Write the conditioned object back out, one file per requested kind."""
    dest.mkdir(parents=True, exist_ok=True)
    for other in bpy.data.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    written: dict[str, str] = {}
    for kind in kinds:
        path = dest / f"{name}.{kind}"
        try:
            if kind == "glb":
                bpy.ops.export_scene.gltf(
                    filepath=str(path), export_format="GLB", use_selection=True)
            elif kind == "fbx":
                bpy.ops.export_scene.fbx(
                    filepath=str(path), use_selection=True,
                    apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y")
            elif kind == "blend":
                bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
            else:
                report["warnings"].append(
                    f"unknown export kind {kind!r}; expected {EXPORT_KINDS}")
                continue
        except (RuntimeError, AttributeError) as e:
            report["warnings"].append(f"{kind} export failed: {e}")
            continue
        if not path.is_file():
            report["warnings"].append(
                f"{kind} export reported success but wrote no file at {path}")
            continue
        written[kind] = str(path)
    return written


def _render_preview(bpy, obj, dest: Path, name: str, report: dict) -> Optional[str]:
    """
    One poster frame, for eyeballing a batch without opening anything.

    Cycles on CPU, because the pip `bpy` wheel renders EEVEE through a GL context
    that a headless box does not have. `render_preview.py` next door does the
    same thing with turntables and more control; this is the cheap version that
    comes free with an import.
    """
    import mathutils  # noqa: PLC0415

    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{name}_preview.png"

    scene = bpy.context.scene
    if "cycles" not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module="cycles")
        except Exception as e:  # noqa: BLE001
            report["warnings"].append(f"no preview: cycles unavailable ({e})")
            return None
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.render.resolution_x, scene.render.resolution_y = 640, 640
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)

    low, high = _world_bounds(obj)
    centre = mathutils.Vector([(low[i] + high[i]) / 2.0 for i in range(3)])
    radius = max(max(h - l for l, h in zip(low, high)), 1e-3)

    camera_data = bpy.data.cameras.new(f"{name}_preview_cam")
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = centre + mathutils.Vector((radius * 2.0, -radius * 2.2,
                                                 radius * 1.5))
    _look_at(camera, centre)
    scene.camera = camera

    light_data = bpy.data.lights.new(f"{name}_preview_key", type="SUN")
    light_data.energy = 4.0
    light = bpy.data.objects.new(light_data.name, light_data)
    bpy.context.scene.collection.objects.link(light)
    light.location = centre + mathutils.Vector((radius, -radius, radius * 3.0))
    _look_at(light, centre)

    try:
        bpy.ops.render.render(write_still=True)
    except Exception as e:  # noqa: BLE001 - a missing preview is not a failed import
        report["warnings"].append(f"preview render failed: {e}")
        return None
    if not path.is_file():
        report["warnings"].append(
            f"preview render reported success but wrote no file at {path}")
        return None
    return str(path)


def _look_at(obj, target) -> None:
    """Point an object's -Z axis at `target`, which is where cameras look."""
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


# ── Batch ─────────────────────────────────────────────────────────────────────


def import_from_results_summary(summary_path: str, dest_dir: str = DEFAULT_DEST,
                                **kwargs) -> list:
    """
    Import every artifact listed in a `<kind>_results_summary.json`.

    That file is what a pipeline runner — and `scripts/prepare_world_asset.py` —
    writes, so this is the whole generate-then-import chain in one call. One
    failing task does not abort the rest; its error lands in that entry's report.
    """
    results = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    reports = []
    for entry in results:
        src = entry.get("glb_path")
        if not src:
            continue
        try:
            reports.append(import_generated_mesh(
                src, dest_dir, asset_name=entry.get("task_id"), **kwargs))
        except Exception as e:  # noqa: BLE001 - one bad asset must not stop a batch
            reports.append({"ok": False, "source": src, "error": str(e),
                            "object": None, "warnings": []})
    return reports


# ── CLI ───────────────────────────────────────────────────────────────────────

#: Environment variable holding a JSON job file, used instead of CLI arguments.
#: Kept identical to the UE5 importer so the host-side launcher builds one job
#: shape for every engine.
JOB_ENV_VAR = "AAAGF_IMPORT_JOB"


def _args_from_job(job: dict) -> list:
    """Turn a job dict into the argv `_parse_args` expects."""
    argv: list = []
    for key in ("src", "summary", "dest", "name", "usage", "pivot", "report"):
        if job.get(key):
            argv += [f"--{key}", str(job[key])]
    for key in ("target_tris", "source_tris"):
        if job.get(key):
            argv += [f"--{key.replace('_', '-')}", str(job[key])]
    if job.get("export"):
        argv += ["--export", *[str(k) for k in job["export"]]]
    if job.get("normalize_scale"):
        argv += ["--normalize-scale"]
    if job.get("preview"):
        argv += ["--preview"]
    return argv


def _script_argv() -> list:
    """
    Arguments meant for this script.

    `blender --python file.py -- --src x` hands the whole command line to the
    script, so everything before the bare `--` belongs to Blender. Run under a
    pip `bpy` instead and there is no separator and no Blender arguments.
    """
    import sys  # noqa: PLC0415

    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return [a for a in sys.argv[1:] if a != Path(__file__).name]


def _parse_args(argv: list):
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        prog="import_mesh.py",
        description="Import a generated mesh into Blender (runs inside bpy)")
    ap.add_argument("--src", help="Generated .glb / .fbx / .obj / .ply to import")
    ap.add_argument("--summary", help="A <kind>_results_summary.json — import every entry")
    ap.add_argument("--dest", default=DEFAULT_DEST, help="Output library directory")
    ap.add_argument("--name", default=None, help="Asset name (default: file stem)")
    ap.add_argument("--usage", default=USAGE_ASSET, choices=USAGES)
    ap.add_argument("--target-tris", type=int, default=None)
    ap.add_argument("--source-tris", type=int, default=None,
                    help="Triangle count of the source file, so the report can "
                         "flag conditioning that changed the mesh")
    ap.add_argument("--pivot", default=None, choices=["keep", "center", "bottom", "top"])
    ap.add_argument("--normalize-scale", action="store_true")
    ap.add_argument("--export", nargs="*", default=["glb"], choices=EXPORT_KINDS,
                    help="Formats to write; pass none to import without exporting")
    ap.add_argument("--preview", action="store_true", help="Render a poster frame")
    ap.add_argument("--report", default=None, help="Write the JSON report here")
    return ap.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = _script_argv()
        job_path = os.environ.get(JOB_ENV_VAR)
        if job_path and not any(a.startswith("--") for a in argv):
            job = json.loads(Path(job_path).read_text(encoding="utf-8"))
            argv = _args_from_job(job)

    args = _parse_args(argv)
    if not args.src and not args.summary:
        raise SystemExit(
            f"either --src or --summary is required (or set {JOB_ENV_VAR} to a job file)")

    common = dict(
        usage=args.usage, target_tris=args.target_tris, source_tris=args.source_tris,
        pivot=args.pivot, normalize_scale=args.normalize_scale,
        export=tuple(args.export), preview=args.preview,
    )
    if args.summary:
        payload: Any = import_from_results_summary(args.summary, args.dest, **common)
        ok = all(r.get("ok") for r in payload)
    else:
        try:
            payload = import_generated_mesh(args.src, args.dest, args.name, **common)
            ok = payload["ok"]
        except Exception as e:  # noqa: BLE001 - the report is the contract
            payload = {"ok": False, "source": args.src, "error": str(e), "warnings": []}
            ok = False

    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    print(text)
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    code = main()
    # `blender --background --python x.py` exits 0 whatever the script returned;
    # the launcher sets this so a failed import is a failed process.
    if os.environ.get("AAAGF_BLENDER_EXIT_ON_DONE"):
        raise SystemExit(code)
