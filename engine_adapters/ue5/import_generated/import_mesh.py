"""
engine_adapters/ue5/import_generated/import_mesh.py

Imports a mesh produced by `models/gen_3d_object` (Trellis2 / Tripo / Meshy)
into an Unreal Engine 5 project and validates what landed.

**This module runs inside Unreal's Python**, where `import unreal` exists. It is
deliberately importable outside the editor too (the `unreal` import is deferred),
so the host-side launcher and tests can read its constants without UE installed.

Import route: UE 5.x hands glTF/GLB, FBX, OBJ and USD to the **Interchange**
framework, so one `AssetImportTask` covers every format the generators emit.
Options that Interchange exposes (`import_offset_translation`,
`import_offset_uniform_scale`, `combine_static_meshes`) are set through an
`InterchangePipelineStackOverride`; every one of them is probed with `getattr`
first, because the exact property set moves between 5.x releases. Anything the
running engine does not expose becomes a warning in the report rather than a
crash.

Coordinate systems: GLB is Y-up and metric, UE is Z-up and centimetre. The
glTF translator applies that conversion itself — do not pre-rotate the file.
Verify it on the first real asset anyway and record the outcome in the report.

CLI (what the host-side launcher calls):
    UnrealEditor-Cmd.exe <project>.uproject -run=pythonscript \\
        -script="engine_adapters/ue5/import_generated/import_mesh.py \\
                 --src <abs path to model.glb> \\
                 --dest /Game/Generated/Meshes \\
                 --name Sword_001 \\
                 --usage asset \\
                 --report <abs path to import_report.json>"

Batch mode reads a `*_results_summary.json` written by
`pipeline/assets_gen/gen_3d_object/run.py`:
    ... -script="... --summary <path to 3d_object_results_summary.json>"
"""

import json
import os
from pathlib import Path
from typing import Any, Optional

#: Usage tiers — task 7 part B4. The default is a plain game asset, **not** VFX.
USAGE_ASSET = "asset"
USAGE_VFX_STANDALONE = "vfx_standalone"
USAGE_VFX_PARTICLE = "vfx_particle"
USAGES = (USAGE_ASSET, USAGE_VFX_STANDALONE, USAGE_VFX_PARTICLE)

#: Formats the generators emit that UE can ingest.
SUPPORTED_SUFFIXES = (".glb", ".gltf", ".fbx", ".obj", ".usd", ".usda", ".usdz")

DEFAULT_DEST_PACKAGE = "/Game/Generated/Meshes"


def _unreal():
    """Import `unreal` with a message that says where this script has to run."""
    try:
        import unreal  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - only true outside the editor
        raise RuntimeError(
            "import_mesh.py must run inside Unreal Engine's Python.\n"
            "  UnrealEditor-Cmd.exe <project>.uproject -run=pythonscript "
            '-script="engine_adapters/ue5/import_generated/import_mesh.py --src ..."\n'
            "  (or paste it into the editor's Output Log > Cmd > Python)"
        ) from e
    return unreal


def sanitize_asset_name(name: str) -> str:
    """UE asset names allow letters, digits and underscore."""
    cleaned = "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
    return cleaned or "GeneratedMesh"


# ── Import ────────────────────────────────────────────────────────────────────


def import_generated_mesh(
    src_path: str,
    dest_package: str = DEFAULT_DEST_PACKAGE,
    asset_name: Optional[str] = None,
    *,
    usage: str = USAGE_ASSET,
    target_tris: Optional[int] = None,
    source_tris: Optional[int] = None,
    pivot: Optional[str] = None,
    normalize_scale: bool = False,
    replace_existing: bool = True,
    save: bool = True,
) -> dict:
    """
    Import one generated mesh and report what the engine actually produced.

    Args:
        src_path: Absolute path to the generated file (`.glb` by default).
        dest_package: UE package path, e.g. ``/Game/Generated/Meshes``.
        asset_name: Asset name; defaults to the sanitized source stem.
        usage: One of `USAGES`. ``asset`` (default) imports verbatim — no
            decimation, no pivot change, no rescale. The two ``vfx_*`` tiers are
            described in part B4; they differ in pivot and scale handling, not in
            some magic quality setting.
        target_tris: Advisory triangle budget. Exceeding it triggers a reduction
            attempt and always a warning — the cheaper fix is generating low-poly
            (`TripoModel(low_poly=True)`), because local decimation damages UVs.
        pivot: ``None`` (tier default) | ``"keep"`` | ``"center"`` | ``"bottom"``.
            Implemented as a re-import with an Interchange translation offset,
            so the pivot is baked into the asset rather than into one actor.
        normalize_scale: Uniformly scale so the largest bound is 100 uu (1 m).
        replace_existing: Overwrite an asset with the same path.
        save: Save the package after import.

    Returns:
        dict with keys ``ok, asset_path, tris, vertices, lods, bounds,
        materials, usage, source, warnings, error``.
    """
    unreal = _unreal()

    src = Path(src_path)
    report: dict[str, Any] = {
        "ok": False, "source": str(src), "usage": usage,
        "asset_path": None, "tris": None, "vertices": None, "lods": None,
        "source_tris": source_tris,
        "bounds": None, "materials": [], "warnings": [], "error": None,
    }
    if usage not in USAGES:
        raise ValueError(f"unknown usage {usage!r}; expected one of {USAGES}")
    if not src.is_file():
        raise FileNotFoundError(f"generated mesh not found: {src}")
    if src.suffix.lower() not in SUPPORTED_SUFFIXES:
        report["warnings"].append(
            f"unusual suffix {src.suffix!r}; UE may have no translator for it")

    name = sanitize_asset_name(asset_name or src.stem)
    pivot, normalize_scale = _tier_defaults(usage, pivot, normalize_scale, report)

    asset_path = _run_import_task(
        unreal, src, dest_package, name,
        replace_existing=replace_existing, save=save, report=report,
    )
    report["asset_path"] = asset_path

    mesh = unreal.EditorAssetLibrary.load_asset(asset_path)
    if mesh is None:
        raise RuntimeError(
            f"import reported success but {asset_path} does not exist. For .glb, "
            f"check that the 'Interchange glTF' / 'glTF Importer' plugin is "
            f"enabled in this project."
        )

    # Pivot needs the bounds, which only exist after an import — so measure, then
    # re-import once with the offset baked in. One extra import beats shipping an
    # asset whose pivot lives in a level actor nobody else inherits.
    if pivot and pivot != "keep":
        offset = _pivot_offset(unreal, mesh, pivot, report)
        if offset is not None:
            asset_path = _run_import_task(
                unreal, src, dest_package, name,
                replace_existing=True, save=save, report=report,
                offset_translation=offset,
            )
            mesh = unreal.EditorAssetLibrary.load_asset(asset_path)
            report["asset_path"] = asset_path

    if normalize_scale:
        _apply_normalize_scale(unreal, src, dest_package, name, mesh, report,
                               save=save)
        mesh = unreal.EditorAssetLibrary.load_asset(asset_path)

    _measure(unreal, mesh, report)

    if target_tris and report["tris"] and report["tris"] > target_tris:
        _apply_target_tris(unreal, mesh, target_tris, report)
        _measure(unreal, mesh, report)

    if usage == USAGE_VFX_STANDALONE:
        report["warnings"].append(
            "vfx_standalone: swap the material for emissive / translucent / "
            "fresnel and confirm the UVs tile seamlessly before scrolling them")
    if usage == USAGE_VFX_PARTICLE and report["tris"]:
        report["warnings"].append(
            f"vfx_particle: budget is per-mesh tris x instances — {report['tris']} "
            f"tris is fine for tens of instances, tight for hundreds. Nanite + GPU "
            f"sim relaxes this; measure the frame time, do not trust a fixed cap")

    # Interchange names the asset after the source file and buries it in
    # `<file>/StaticMeshes/`, ignoring the import task's destination_name. The
    # pipeline addresses assets by task_id, so normalize the path at the end,
    # once every re-import pass is done.
    asset_path = _normalize_asset_path(unreal, asset_path, dest_package, name, report)
    report["asset_path"] = asset_path

    if save:
        _save_all(unreal, asset_path, report)

    report["ok"] = True
    unreal.log(f"[import_generated_mesh] {asset_path} tris={report['tris']} "
               f"materials={len(report['materials'])} "
               f"warnings={len(report['warnings'])}")
    return report


def _tier_defaults(usage: str, pivot: Optional[str], normalize_scale: bool,
                   report: dict) -> tuple[Optional[str], bool]:
    """Per-tier defaults (B4). An explicit argument always wins."""
    if usage == USAGE_ASSET:
        return (pivot or "keep"), normalize_scale
    if usage == USAGE_VFX_STANDALONE:
        return (pivot or "center"), normalize_scale
    # vfx_particle: instanced by a mesh renderer, so it wants a meaningful pivot
    # and a unit size — otherwise every instance is offset and mis-scaled.
    return (pivot or "center"), True


#: Import routes, tried in this order. Override with `$AAAGF_UE_IMPORT_ROUTE`.
#:
#: Measured on UE 5.7:
#:   automated    `AssetTools.import_assets_automated` — imports for real, takes
#:                no pipeline override, so it cannot carry a pivot/scale offset.
#:   task         `AssetTools.import_asset_tasks` — imports for real and carries
#:                offsets through an InterchangePipelineStackOverride.
#:   interchange  `InterchangeManager.import_asset` — returns before the assets
#:                exist (the scripted call is asynchronous), so it is last and
#:                only useful as a fallback on builds where AssetTools is absent.
#:
#: Both AssetTools routes finish the import and then sync the Content Browser,
#: which asserts in `FSlateApplication::Get()` when the engine runs as a
#: commandlet (`-run=pythonscript`). Launch the full editor instead
#: (`UnrealEditor.exe -ExecutePythonScript=...`, what
#: `scripts/import_generated_asset.py --ue-mode editor` does by default) and
#: Slate exists, so the sync is harmless.
IMPORT_ROUTES = ("automated", "task", "interchange")


class _RouteUnavailable(RuntimeError):
    """This engine build cannot take this import route; try the next one."""


def _run_import_task(unreal, src: Path, dest_package: str, name: str, *,
                     replace_existing: bool, save: bool, report: dict,
                     offset_translation=None, uniform_scale: Optional[float] = None) -> str:
    """
    Import `src` into `dest_package` and return the imported asset path.

    Tries each route in `IMPORT_ROUTES` until one produces an asset. Only a route
    being *unavailable* falls through; a translator error is raised as-is,
    because retrying it on another route would just hide the real problem.
    """
    forced = os.environ.get("AAAGF_UE_IMPORT_ROUTE")
    routes = (forced,) if forced else IMPORT_ROUTES

    wants_offset = offset_translation is not None or uniform_scale is not None
    errors = []
    for route in routes:
        try:
            if route == "automated":
                return _import_via_automated(
                    unreal, src, dest_package, name, report,
                    replace_existing=replace_existing, wants_offset=wants_offset)
            if route == "interchange":
                return _import_via_interchange(
                    unreal, src, dest_package, name, report,
                    offset_translation=offset_translation, uniform_scale=uniform_scale)
            if route == "task":
                return _import_via_asset_task(
                    unreal, src, dest_package, name, report,
                    replace_existing=replace_existing, save=save,
                    offset_translation=offset_translation, uniform_scale=uniform_scale)
            raise ValueError(f"unknown import route {route!r}; expected {IMPORT_ROUTES}")
        except _RouteUnavailable as e:
            errors.append(f"{route}: {e}")
            report["warnings"].append(f"import route {route!r} unavailable: {e}")

    raise RuntimeError(
        f"no usable import route for {src}. Tried: " + "; ".join(errors))


def _import_via_automated(unreal, src: Path, dest_package: str, name: str,
                          report: dict, *, replace_existing: bool,
                          wants_offset: bool) -> str:
    """
    `AssetTools.import_assets_automated` — the batch-safe route.

    It takes no pipeline override, so a pivot or scale offset cannot ride along;
    when one was asked for, this route declines and the caller falls through to
    a route that can carry it.
    """
    if wants_offset:
        raise _RouteUnavailable(
            "AutomatedAssetImportData carries no pipeline override, so it cannot "
            "apply an import offset")
    if not hasattr(unreal, "AutomatedAssetImportData"):
        raise _RouteUnavailable("no AutomatedAssetImportData in this engine build")

    data = unreal.AutomatedAssetImportData()
    data.set_editor_property("destination_path", dest_package)
    data.set_editor_property("filenames", [str(src)])
    data.set_editor_property("replace_existing", replace_existing)
    imported = unreal.AssetToolsHelpers.get_asset_tools().import_assets_automated(data)
    imported = [obj for obj in (imported or []) if obj is not None]
    if not imported:
        raise RuntimeError(
            f"UE imported nothing from {src}. Check the Output Log for the "
            f"translator error, and that the format's plugin is enabled.")
    return _pick_imported(unreal, [obj.get_path_name() for obj in imported],
                          name, report)


def _import_via_interchange(unreal, src: Path, dest_package: str, name: str,
                            report: dict, *, offset_translation=None,
                            uniform_scale: Optional[float] = None) -> str:
    """
    `InterchangeManager.import_asset` with `is_automated=True`.

    The route Epic documents for commandlets. Offsets ride along on a duplicate
    of the project's default pipeline asset, because `override_pipelines` takes
    asset paths — a pipeline object built in Python has no path to reference.
    """
    manager_cls = getattr(unreal, "InterchangeManager", None)
    if manager_cls is None or not hasattr(unreal, "ImportAssetParameters"):
        raise _RouteUnavailable("no Interchange scripted API in this engine build")

    manager = manager_cls.get_interchange_manager_scripted()
    source_data = manager_cls.create_source_data(str(src))
    params = unreal.ImportAssetParameters()
    params.set_editor_property("is_automated", True)

    if offset_translation is not None or uniform_scale is not None:
        pipeline_path = _make_offset_pipeline_asset(
            unreal, report, offset_translation=offset_translation,
            uniform_scale=uniform_scale)
        if pipeline_path is None:
            raise _RouteUnavailable("could not build a pipeline asset for the offset")
        for candidate in (unreal.SoftObjectPath(pipeline_path), pipeline_path):
            try:
                params.set_editor_property("override_pipelines", [candidate])
                break
            except Exception:  # noqa: BLE001 - the array element type moves across versions
                continue
        else:
            raise _RouteUnavailable("override_pipelines rejected the pipeline reference")

    before = set(_list_assets(unreal, dest_package))
    if not manager.import_asset(dest_package, source_data, params):
        raise RuntimeError(
            f"Interchange refused to import {src}. Check the Output Log for the "
            f"translator error, and that the format's plugin is enabled.")
    created = [p for p in _list_assets(unreal, dest_package) if p not in before]
    if not created:
        # A re-import of an existing asset creates nothing new.
        created = [p for p in _list_assets(unreal, dest_package)
                   if Path(p).stem.split(".")[0] in (name, src.stem)]
    if not created:
        raise RuntimeError(
            f"Interchange reported success but no asset appeared in {dest_package}")
    return _pick_imported(unreal, created, name, report)


def _import_via_asset_task(unreal, src: Path, dest_package: str, name: str,
                           report: dict, *, replace_existing: bool, save: bool,
                           offset_translation=None,
                           uniform_scale: Optional[float] = None) -> str:
    """
    `AssetTools.import_asset_tasks` — the interactive-editor route.

    Works from the editor's Python console. In a commandlet it can assert inside
    Slate *after* a successful import, which is why it is tried last.
    """
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(src))
    task.set_editor_property("destination_path", dest_package)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("replace_existing", replace_existing)
    task.set_editor_property("automated", True)     # never prompt in batch mode
    task.set_editor_property("save", save)

    options = _import_options(unreal, src, report,
                              offset_translation=offset_translation,
                              uniform_scale=uniform_scale)
    if options is not None:
        task.set_editor_property("options", options)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported = list(task.get_editor_property("imported_object_paths") or [])
    if not imported:
        raise RuntimeError(
            f"UE imported nothing from {src}. Check the Output Log for the "
            f"translator error, and that the format's plugin is enabled.")
    return _pick_imported(unreal, imported, name, report)


def _pick_imported(unreal, object_paths: list, name: str, report: dict) -> str:
    """
    Choose the mesh among everything an import produced.

    A glTF file yields materials and textures next to the mesh; prefer the asset
    named like the import, then the first static mesh, then whatever came first.
    """
    # Paths come back as "/Game/X/Y.Y"; the package path is the part before the dot.
    packages = [str(p).split(".")[0] for p in object_paths]
    # A textured glTF yields a texture and a material next to the mesh. They are
    # separate packages and every one of them has to be saved, or the mesh ships
    # referencing a material that only ever existed in memory.
    report["imported_assets"] = packages
    if len(packages) > 1:
        report["warnings"].append(
            f"{len(packages)} assets imported ({', '.join(packages[:5])}"
            f"{'…' if len(packages) > 5 else ''})")

    named = [p for p in packages if p.rsplit("/", 1)[-1] == name]
    if named:
        return named[0]

    for path in packages:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if asset is not None and isinstance(asset, unreal.StaticMesh):
            return path
    return packages[0]


def _measure_nanite(unreal, mesh, report: dict) -> None:
    """
    Record whether Nanite is on, because it changes what `tris` means.

    With Nanite enabled, `get_num_triangles(0)` returns the **fallback** mesh,
    which UE builds at a fraction of the source density — a 19 k-triangle glTF
    imported as ~4.5 k. Reporting that number alone would understate the asset
    and quietly derail any per-instance triangle budget (part B4).
    """
    settings = None
    try:
        settings = mesh.get_editor_property("nanite_settings")
    except Exception:  # noqa: BLE001 - older builds, or not a StaticMesh
        return
    if settings is None:
        return

    info: dict[str, Any] = {}
    for prop in ("enabled", "fallback_percent_triangles", "fallback_relative_error",
                 "position_precision", "keep_percent_triangles"):
        try:
            info[prop] = settings.get_editor_property(prop)
        except Exception:  # noqa: BLE001 - the property set moves across versions
            continue
    if not info:
        return

    report["nanite"] = info
    if info.get("enabled"):
        source = report.get("source_tris")
        comparison = (f" The source file has {source} triangles."
                      if source else " Compare against the source file.")
        report["warnings"].append(
            f"Nanite is enabled: tris={report.get('tris')} is the fallback mesh, "
            f"not the source density.{comparison} Nanite also relaxes the "
            f"mesh-particle budget (B4)")


def _save_all(unreal, asset_path: str, report: dict) -> None:
    """
    Persist the mesh **and** everything the import created alongside it.

    Interchange emits the texture and the material as their own packages. Saving
    only the mesh leaves those dirty in memory, and the commandlet exits with a
    mesh whose material reference points at nothing.
    """
    saved, failed = [], []
    for path in dict.fromkeys(list(report.get("imported_assets", [])) + [asset_path]):
        if not unreal.EditorAssetLibrary.does_asset_exist(path):
            continue  # renamed away, or an intermediate that no longer exists
        try:
            unreal.EditorAssetLibrary.save_asset(path)
            saved.append(path)
        except Exception as e:  # noqa: BLE001 - one bad package must not lose the rest
            failed.append(f"{path} ({e})")
    report["saved_assets"] = saved
    if failed:
        report["warnings"].append("could not save: " + ", ".join(failed))


def _normalize_asset_path(unreal, asset_path: str, dest_package: str, name: str,
                          report: dict) -> str:
    """
    Move the imported asset to `<dest_package>/<name>` when it landed elsewhere.

    Returns the path the asset ends up at — the original one when the rename is
    not needed or not possible.
    """
    target = f"{dest_package.rstrip('/')}/{name}"
    if asset_path == target:
        return asset_path
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(target):
            unreal.EditorAssetLibrary.delete_asset(target)
        if unreal.EditorAssetLibrary.rename_asset(asset_path, target):
            report["warnings"].append(f"asset moved {asset_path} → {target}")
            return target
    except Exception as e:  # noqa: BLE001 - renaming is a convenience, not the import
        report["warnings"].append(f"could not rename to {target}: {e}")
        return asset_path
    report["warnings"].append(
        f"asset stayed at {asset_path}; the importer chose that name")
    return asset_path


def _list_assets(unreal, package_path: str) -> list:
    """Object paths directly under a package path; empty when it does not exist."""
    try:
        if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
            return []
        return list(unreal.EditorAssetLibrary.list_assets(
            package_path, recursive=False, include_folder=False) or [])
    except Exception:  # noqa: BLE001 - listing a fresh package path can throw
        return []


def _make_offset_pipeline_asset(unreal, report: dict, *, offset_translation=None,
                                uniform_scale: Optional[float] = None) -> Optional[str]:
    """
    Duplicate the default Interchange pipeline and bake an import offset into it.

    `override_pipelines` references pipelines by asset path, so the override has
    to exist as an asset. The duplicate is transient project content and is
    overwritten on every import that needs it.
    """
    dup_path = "/Game/Generated/_ImportPipelines/AAAGF_OffsetPipeline"
    for source in ("/Interchange/Pipelines/DefaultAssetsPipeline",
                   "/Interchange/Pipelines/DefaultGraphInspectorPipeline"):
        if not unreal.EditorAssetLibrary.does_asset_exist(source):
            continue
        if unreal.EditorAssetLibrary.does_asset_exist(dup_path):
            unreal.EditorAssetLibrary.delete_asset(dup_path)
        pipeline = unreal.EditorAssetLibrary.duplicate_asset(source, dup_path)
        if pipeline is None:
            continue
        _try_set(pipeline, "import_offset_translation", offset_translation, report)
        _try_set(pipeline, "import_offset_uniform_scale", uniform_scale, report)
        unreal.EditorAssetLibrary.save_asset(dup_path)
        return dup_path
    report["warnings"].append(
        "no default Interchange pipeline asset found to duplicate; the import "
        "offset was not applied")
    return None


def _import_options(unreal, src: Path, report: dict, *,
                    offset_translation=None, uniform_scale: Optional[float] = None):
    """
    Build the import options for this file type.

    Interchange (glTF / OBJ / USD, and FBX in newer releases) takes a pipeline
    stack override; legacy FBX takes `FbxImportUI`. Every property is probed
    before it is set, because their names move between 5.x versions — a missing
    one becomes a warning, not an exception.
    """
    if src.suffix.lower() == ".fbx" and hasattr(unreal, "FbxImportUI"):
        ui = unreal.FbxImportUI()
        ui.set_editor_property("import_mesh", True)
        ui.set_editor_property("import_as_skeletal", False)
        ui.set_editor_property("import_materials", True)
        ui.set_editor_property("import_textures", True)
        data = ui.get_editor_property("static_mesh_import_data")
        if data is not None:
            if offset_translation is not None:
                data.set_editor_property("import_translation", offset_translation)
            if uniform_scale is not None:
                data.set_editor_property("import_uniform_scale", float(uniform_scale))
            data.set_editor_property("combine_meshes", True)
        return ui

    if not hasattr(unreal, "InterchangeGenericAssetsPipeline"):
        if offset_translation is not None or uniform_scale is not None:
            report["warnings"].append(
                "this engine build has no InterchangeGenericAssetsPipeline; "
                "pivot / scale offsets were NOT applied")
        return None

    pipeline = unreal.InterchangeGenericAssetsPipeline()
    _try_set(pipeline, "import_offset_translation", offset_translation, report)
    _try_set(pipeline, "import_offset_uniform_scale", uniform_scale, report)
    mesh_pipeline = getattr(pipeline, "mesh_pipeline", None)
    if mesh_pipeline is not None:
        # Generated assets arrive as many small meshes; one static mesh is what a
        # game asset should be.
        _try_set(mesh_pipeline, "combine_static_meshes", True, report)

    if not hasattr(unreal, "InterchangePipelineStackOverride"):
        report["warnings"].append(
            "no InterchangePipelineStackOverride in this engine build; importing "
            "with the project's default pipeline stack instead")
        return None
    override = unreal.InterchangePipelineStackOverride()
    override.add_pipeline(pipeline)
    return override


def _try_set(obj, prop: str, value, report: dict) -> bool:
    """Set an editor property when the running engine exposes it."""
    if value is None:
        return False
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception as e:  # noqa: BLE001 - property set is engine-version dependent
        report["warnings"].append(f"could not set {prop}: {e}")
        return False


# ── Post-import ───────────────────────────────────────────────────────────────


def _pivot_offset(unreal, mesh, pivot: str, report: dict):
    """
    Translation that moves `pivot` onto the origin.

    UE is Z-up, so "bottom" is min Z — the base an energy pillar grows from.
    """
    bounds = mesh.get_bounds()
    origin, extent = bounds.origin, bounds.box_extent
    pivot = pivot.lower()
    if pivot == "center":
        point = origin
    elif pivot == "bottom":
        point = unreal.Vector(origin.x, origin.y, origin.z - extent.z)
    elif pivot == "top":
        point = unreal.Vector(origin.x, origin.y, origin.z + extent.z)
    else:
        report["warnings"].append(f"unknown pivot {pivot!r}; left unchanged")
        return None
    offset = unreal.Vector(-point.x, -point.y, -point.z)
    report["warnings"].append(
        f"pivot={pivot}: re-imported with offset ({offset.x:.2f}, {offset.y:.2f}, "
        f"{offset.z:.2f}) uu")
    return offset


def _apply_normalize_scale(unreal, src: Path, dest_package: str, name: str,
                           mesh, report: dict, *, save: bool) -> None:
    """Re-import scaled so the largest bound is 100 uu (1 m)."""
    extent = mesh.get_bounds().box_extent
    largest = 2.0 * max(extent.x, extent.y, extent.z)
    if largest <= 1e-3:
        report["warnings"].append("degenerate bounds; scale not normalized")
        return
    scale = 100.0 / largest
    _run_import_task(unreal, src, dest_package, name, replace_existing=True,
                     save=save, report=report, uniform_scale=scale)
    report["warnings"].append(f"normalized scale by {scale:.4f} (largest bound → 100 uu)")


def _apply_target_tris(unreal, mesh, target_tris: int, report: dict) -> None:
    """
    Try to bring LOD0 down to `target_tris`.

    B4.3: this is the fallback, not the plan. Generating low-poly keeps UVs and
    normals intact; decimating a 2M-face mesh afterwards does not. Whatever
    happens here is recorded as a warning so the caller can see it.
    """
    current = report.get("tris") or 0
    ratio = max(0.01, min(1.0, float(target_tris) / float(current)))
    subsystem = getattr(unreal, "StaticMeshEditorSubsystem", None)
    if subsystem is None:
        report["warnings"].append(
            f"{current} tris > target {target_tris}, and this engine build has no "
            f"StaticMeshEditorSubsystem; regenerate low-poly instead")
        return

    sms = subsystem()
    settings_cls = getattr(unreal, "StaticMeshReductionSettings", None)
    options_cls = getattr(unreal, "StaticMeshReductionOptions", None)
    if settings_cls is None or options_cls is None:
        report["warnings"].append(
            f"{current} tris > target {target_tris}; reduction classes missing in "
            f"this engine build, mesh left untouched")
        return

    settings = settings_cls()
    _try_set(settings, "percent_triangles", ratio, report)
    _try_set(settings, "screen_size", 1.0, report)
    options = options_cls()
    _try_set(options, "reduction_settings", [settings], report)
    _try_set(options, "auto_compute_lod_screen_size", True, report)
    try:
        sms.set_lods(mesh, options)
        report["warnings"].append(
            f"reduction requested at {ratio:.3f} of {current} tris. Note UE keeps "
            f"LOD0 at full density — verify which LOD your renderer uses, or "
            f"regenerate the asset low-poly (B4.3)")
    except Exception as e:  # noqa: BLE001 - reduction API differs across versions
        report["warnings"].append(f"reduction failed ({e}); mesh left untouched")


def _measure(unreal, mesh, report: dict) -> None:
    """Fill the validation fields — existence alone is not proof of an import."""
    try:
        report["lods"] = mesh.get_num_lods()
        report["tris"] = mesh.get_num_triangles(0)
        report["vertices"] = mesh.get_num_vertices(0)
    except Exception as e:  # noqa: BLE001 - non-StaticMesh assets lack these
        report["warnings"].append(f"could not read mesh statistics: {e}")

    _measure_nanite(unreal, mesh, report)

    try:
        bounds = mesh.get_bounds()
        report["bounds"] = {
            "origin": [bounds.origin.x, bounds.origin.y, bounds.origin.z],
            "box_extent": [bounds.box_extent.x, bounds.box_extent.y, bounds.box_extent.z],
            "sphere_radius": bounds.sphere_radius,
        }
    except Exception as e:  # noqa: BLE001
        report["warnings"].append(f"could not read bounds: {e}")

    try:
        report["materials"] = [
            str(m.material_slot_name) for m in mesh.get_editor_property("static_materials")
        ]
    except Exception as e:  # noqa: BLE001
        report["warnings"].append(f"could not read materials: {e}")

    if not report.get("tris"):
        report["warnings"].append("imported asset reports 0 triangles")
    if not report.get("materials"):
        report["warnings"].append("imported asset has no material slots")


# ── Batch ─────────────────────────────────────────────────────────────────────


def import_from_results_summary(summary_path: str,
                                dest_package: str = DEFAULT_DEST_PACKAGE,
                                **kwargs) -> list[dict]:
    """
    Import every artifact listed in a `<kind>_results_summary.json`.

    That file is what `pipeline/assets_gen/gen_3d_object/run.py` writes, so this
    is the whole generate → import chain in one call. One failing task does not
    abort the rest; its error lands in that entry's report.
    """
    results = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    reports = []
    for entry in results:
        src = entry.get("glb_path")
        if not src:
            continue
        try:
            reports.append(import_generated_mesh(
                src, dest_package, asset_name=entry.get("task_id"), **kwargs))
        except Exception as e:  # noqa: BLE001 - one bad asset must not stop a batch
            reports.append({"ok": False, "source": src, "error": str(e),
                            "asset_path": None, "warnings": []})
    return reports


# ── CLI ───────────────────────────────────────────────────────────────────────


#: Environment variable holding a JSON job file, used instead of CLI arguments.
#: UE's `-run=pythonscript -script="file.py --a b"` has to survive two rounds of
#: command-line splitting (Windows shell, then UE's own parser), and paths with
#: spaces do not always come out intact. An environment variable does.
JOB_ENV_VAR = "AAAGF_IMPORT_JOB"


def _args_from_job(job: dict) -> list[str]:
    """Turn a job dict into the argv `_parse_args` expects."""
    argv: list[str] = []
    for key in ("src", "summary", "dest", "name", "usage", "pivot", "report"):
        if job.get(key):
            argv += [f"--{key}", str(job[key])]
    if job.get("target_tris"):
        argv += ["--target-tris", str(job["target_tris"])]
    if job.get("source_tris"):
        argv += ["--source-tris", str(job["source_tris"])]
    if job.get("normalize_scale"):
        argv += ["--normalize-scale"]
    if job.get("no_save"):
        argv += ["--no-save"]
    return argv


def _parse_args(argv: list[str]):
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        prog="import_mesh.py",
        description="Import a generated mesh into UE5 (runs inside Unreal Python)")
    ap.add_argument("--src", help="Generated .glb / .fbx to import")
    ap.add_argument("--summary", help="A <kind>_results_summary.json — import every entry")
    ap.add_argument("--dest", default=DEFAULT_DEST_PACKAGE, help="UE package path")
    ap.add_argument("--name", default=None, help="Asset name (default: file stem)")
    ap.add_argument("--usage", default=USAGE_ASSET, choices=USAGES)
    ap.add_argument("--target-tris", type=int, default=None)
    ap.add_argument("--source-tris", type=int, default=None,
                    help="Triangle count of the source file, so the report can "
                         "flag Nanite's fallback mesh against it")
    ap.add_argument("--pivot", default=None, choices=["keep", "center", "bottom", "top"])
    ap.add_argument("--normalize-scale", action="store_true")
    ap.add_argument("--report", default=None, help="Write the JSON report here")
    ap.add_argument("--no-save", action="store_true")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    import sys  # noqa: PLC0415

    if argv is None:
        argv = sys.argv[1:]
        # UE strips or mangles script arguments depending on how the commandlet
        # was invoked; the job file is the reliable channel.
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
        save=not args.no_save,
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
    # Full-editor mode (`UnrealEditor.exe -ExecutePythonScript=...`) keeps
    # running after the script; the launcher sets this so the process ends.
    # In the editor's Python console it is unset, so nothing is closed.
    if os.environ.get("AAAGF_UE_QUIT_WHEN_DONE"):
        try:
            _unreal().SystemLibrary.quit_editor()
        except Exception as e:  # noqa: BLE001 - best effort, the report is written
            print(f"[import_mesh] could not quit the editor: {e}")
    if os.environ.get("AAAGF_UE_EXIT_ON_DONE"):
        raise SystemExit(code)
