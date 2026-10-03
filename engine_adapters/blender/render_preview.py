"""
engine_adapters/blender/render_preview.py

Headless turntable / still renders of a generated asset.

**This module runs inside a `bpy` interpreter.** It exists because "the asset
imported" and "the asset looks right" are different claims: an import report
counts triangles, and only a picture shows a mesh that came in inside out, a
texture that did not come in at all, or a world whose layers do not meet.

Two things make headless rendering work where it usually does not:

- **Cycles on CPU by default.** The pip `bpy` wheel drives EEVEE and Workbench
  through a GL/EGL context that a server without a display does not have, and
  the failure is a `libEGL` abort rather than an exception. Cycles needs no GL
  context, so it is the default and also the automatic fallback.
- **Grease-pencil objects are excluded.** They go through the GL pipeline even
  under Cycles and take the process down with them, uncatchably. They are hidden
  from the render and restored afterwards, and still render in the GUI.

CLI:
    blender --background --factory-startup \\
        --python engine_adapters/blender/render_preview.py -- \\
        --src model.glb --out previews/ --mode orbit --format mp4
"""

import json
import math
import os
from pathlib import Path
from typing import Any, Optional

#: `orbit` spins the camera around the asset; `still` renders one frame.
MODES = ("orbit", "still")

#: `mp4` needs ffmpeg, which Blender bundles; `png` writes the frame sequence;
#: `auto` takes mp4 and falls back to png when the encoder is missing.
FORMATS = ("auto", "mp4", "png")

#: Engine ids that need a GL context. Their names moved between 4.x releases,
#: so both are listed and whichever exists is used.
_EEVEE_IDS = ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
_WORKBENCH_ID = "BLENDER_WORKBENCH"

DEFAULT_FRAMES = 48
DEFAULT_FPS = 24
DEFAULT_RESOLUTION = (640, 640)


def _bpy():
    """Import `bpy` with a message that says where this script has to run."""
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - only true outside Blender
        raise RuntimeError(
            "render_preview.py must run inside a bpy interpreter.\n"
            "  blender --background --factory-startup --python "
            "engine_adapters/blender/render_preview.py -- --src model.glb"
        ) from e
    return bpy


# ── Scene ─────────────────────────────────────────────────────────────────────


def _import_mesh_module():
    """
    The sibling importer, whether this file was imported or run as a script.

    `blender --python <file>` executes the file with no package context, so the
    relative import that works for `engine_adapters.blender.render_preview` is
    not available and the directory has to go on the path instead.
    """
    try:
        from .import_generated import import_mesh  # noqa: PLC0415
    except ImportError:
        import sys  # noqa: PLC0415

        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        from import_generated import import_mesh  # noqa: PLC0415
    return import_mesh


def _load_asset(bpy, src: Path) -> list:
    """Import `src` into an empty scene and return its mesh objects."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return _import_mesh_module()._run_import(bpy, src, {"warnings": []})


def _scene_bounds(bpy, objects: list):
    """`(centre, radius)` of everything being rendered, in world space."""
    import mathutils  # noqa: PLC0415

    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for obj in objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ mathutils.Vector(corner)
            for axis in range(3):
                low[axis] = min(low[axis], point[axis])
                high[axis] = max(high[axis], point[axis])
    if low[0] == float("inf"):
        return mathutils.Vector((0.0, 0.0, 0.0)), 1.0

    centre = mathutils.Vector([(low[i] + high[i]) / 2.0 for i in range(3)])
    radius = max(max(high[i] - low[i] for i in range(3)) / 2.0, 1e-3)
    return centre, radius


def _setup_world(bpy, strength: float = 1.0) -> None:
    """A neutral grey dome, so nothing depends on a light rig being right."""
    world = bpy.data.worlds.get("AAAGF_Preview") or bpy.data.worlds.new("AAAGF_Preview")
    if world.node_tree is None:
        # Before 5.0 the shader tree is built on demand; from 5.0 a new world
        # already has one and `use_nodes` is deprecated.
        world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.05, 0.05, 0.06, 1.0)
        background.inputs[1].default_value = strength
    bpy.context.scene.world = world


def _setup_lights(bpy, centre, radius: float) -> None:
    """Key and fill, placed relative to the asset rather than to the origin."""
    import mathutils  # noqa: PLC0415

    for name, energy, offset in (
        ("AAAGF_Key", 6.0, (1.0, -1.2, 1.6)),
        ("AAAGF_Fill", 2.0, (-1.4, 0.8, 0.6)),
    ):
        data = bpy.data.lights.new(name, type="SUN")
        data.energy = energy
        light = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(light)
        light.location = centre + mathutils.Vector(offset) * radius * 3.0
        _look_at(light, centre)


def _look_at(obj, target) -> None:
    """Point an object's -Z axis at `target`, which is where cameras look."""
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _setup_camera(bpy, centre, radius: float, mode: str, frames: int,
                  elevation_deg: float = 20.0):
    """
    Frame the asset, and for `orbit` key a full revolution around it.

    The camera is parented to an empty at the asset's centre and the *empty*
    spins, which keeps the framing identical on every frame — rotating the camera
    itself would need the look-at recomputed per frame and drifts.
    """
    import mathutils  # noqa: PLC0415

    pivot = bpy.data.objects.new("AAAGF_Pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.location = centre

    data = bpy.data.cameras.new("AAAGF_PreviewCam")
    camera = bpy.data.objects.new(data.name, data)
    bpy.context.scene.collection.objects.link(camera)
    camera.parent = pivot

    elevation = math.radians(elevation_deg)
    distance = radius * 3.2
    camera.location = mathutils.Vector((
        0.0, -distance * math.cos(elevation), distance * math.sin(elevation)))
    _look_at(camera, mathutils.Vector((0.0, 0.0, 0.0)))
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    if mode == "orbit":
        scene.frame_start, scene.frame_end = 1, frames
        for frame, angle in ((1, 0.0), (frames + 1, 2.0 * math.pi)):
            pivot.rotation_euler = (0.0, 0.0, angle)
            pivot.keyframe_insert("rotation_euler", frame=frame)
        # Bezier easing would make the turntable slow at both ends and hurry
        # through the middle, which reads as a stutter in a loop.
        for curve in _action_fcurves(pivot.animation_data.action):
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"
    else:
        scene.frame_start = scene.frame_end = 1
    return camera


def _action_fcurves(action) -> list:
    """
    Every F-curve in an action, on either animation system.

    Blender 4.4 replaced the flat `action.fcurves` with slotted actions, where
    the curves sit under layers → strips → channelbags. Both shapes are alive in
    the wild, so ask for whichever this build has.
    """
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    curves: list = []
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for channelbag in getattr(strip, "channelbags", ()):
                curves += list(channelbag.fcurves)
    return curves


def _resolve_engine(bpy, requested: str, report: dict) -> str:
    """
    Pick a render engine this build can actually run.

    `auto` means Cycles, which is the only one guaranteed to work without a
    display. Asking for EEVEE or Workbench is honoured when the id exists, and
    the render call falls back to Cycles if it then dies on a missing context.
    """
    requested = (requested or "auto").lower()
    if requested in ("auto", "cycles"):
        return "CYCLES"
    if requested == "workbench":
        return _WORKBENCH_ID
    if requested == "eevee":
        for candidate in _EEVEE_IDS:
            try:
                bpy.context.scene.render.engine = candidate
                return candidate
            except TypeError:
                continue
        report["warnings"].append("no EEVEE in this build; using Cycles")
        return "CYCLES"
    report["warnings"].append(f"unknown engine {requested!r}; using Cycles")
    return "CYCLES"


# ── Render ────────────────────────────────────────────────────────────────────


def render_preview(
    src_path: str,
    out_dir: str,
    *,
    name: Optional[str] = None,
    mode: str = "orbit",
    output_format: str = "auto",
    frames: int = DEFAULT_FRAMES,
    fps: int = DEFAULT_FPS,
    resolution: tuple = DEFAULT_RESOLUTION,
    samples: int = 24,
    engine: str = "auto",
    poster: bool = True,
) -> dict:
    """
    Render a generated asset and report what was written.

    Args:
        src_path: Any file `import_generated/import_mesh.py` can import.
        out_dir: Directory for the video / frames / poster / sidecar.
        name: Stem for the outputs; defaults to the source file's.
        mode: One of `MODES`.
        output_format: One of `FORMATS`. Ignored in `still` mode.
        frames: Frames in one revolution.
        fps: Frame rate written into the video.
        resolution: `(width, height)` in pixels.
        samples: Cycles samples per pixel. 24 is enough to judge a silhouette.
        engine: `auto` | `cycles` | `eevee` | `workbench`.
        poster: Also write a single frame, for a contact sheet or a report.

    Returns:
        dict with keys `ok, source, mode, engine, frames, triangles, video,
        poster, sidecar, warnings, error`.
    """
    bpy = _bpy()

    src = Path(src_path)
    # Absolute, because Blender resolves a relative render path against the
    # blend file, and headless there is none — the render then writes nothing
    # and still reports FINISHED.
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = name or src.stem
    report: dict[str, Any] = {
        "ok": False, "source": str(src), "mode": mode, "engine": None,
        "frames": 0, "triangles": None, "video": None, "poster": None,
        "sidecar": None, "warnings": [], "error": None,
    }
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    if output_format not in FORMATS:
        raise ValueError(f"unknown format {output_format!r}; expected {FORMATS}")
    if not src.is_file():
        raise FileNotFoundError(f"asset not found: {src}")

    objects = _load_asset(bpy, src)
    report["triangles"] = _total_triangles(bpy, objects)

    centre, radius = _scene_bounds(bpy, objects)
    _setup_world(bpy)
    _setup_lights(bpy, centre, radius)
    _setup_camera(bpy, centre, radius, mode, frames)

    scene = bpy.context.scene
    used = _resolve_engine(bpy, engine, report)
    if used == "CYCLES":
        unavailable = enable_cycles(bpy)
        if unavailable is not None:
            report["error"] = f"cycles unavailable: {unavailable}"
            return report
    scene.render.engine = used
    if used == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = int(samples)
    report["engine"] = used

    scene.render.resolution_x, scene.render.resolution_y = (
        int(resolution[0]), int(resolution[1]))
    scene.render.fps = int(fps)
    scene.render.film_transparent = False

    hidden = hide_gl_only_objects(bpy, report["warnings"])
    try:
        if mode == "still":
            report["poster"] = _render_poster(bpy, out, name, 1, report)
            report["frames"] = 1
        else:
            wanted = output_format if output_format != "auto" else "mp4"
            if wanted == "mp4":
                report["video"] = _render_mp4(bpy, out, name, report)
            if report["video"] is None:
                report["video"] = _render_png_sequence(bpy, out, name, report)
            report["frames"] = frames
            if poster:
                report["poster"] = _render_poster(bpy, out, name, 1, report)
    finally:
        for obj in hidden:
            obj.hide_render = False

    report["ok"] = True
    report["sidecar"] = _write_sidecar(out, name, report)
    print(f"[render_preview] {name} {report['mode']} "
          f"engine={report['engine']} frames={report['frames']}")
    return report


#: Object types drawn through GL even under Cycles; they abort a headless render.
GL_ONLY_TYPES = frozenset(("GPENCIL", "GREASEPENCIL"))


def hide_gl_only_objects(bpy, warnings: list) -> list:
    """
    Hide what a headless render cannot survive. Returns the objects to restore.

    Shared with the playable runtime's `runtime/snapshot.py`, because getting
    this wrong is not an exception — it is an abort inside the graphics driver
    that takes the process with it.
    """
    changed = []
    for obj in bpy.data.objects:
        if obj.type in GL_ONLY_TYPES and not obj.hide_render:
            obj.hide_render = True
            changed.append(obj)
    if changed:
        warnings.append(
            f"{len(changed)} grease-pencil object(s) excluded from the headless "
            f"render; they still draw in the Blender GUI")
    return changed


def enable_cycles(bpy) -> Optional[str]:
    """
    Turn on the Cycles add-on. Returns None, or why it could not be enabled.

    The pip `bpy` wheel ships Cycles disabled, so the one engine that renders
    without a display is the one that is off until asked for.
    """
    if "cycles" in bpy.context.preferences.addons:
        return None
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
    except Exception as e:  # noqa: BLE001 - a build without Cycles at all
        return str(e)
    return None


def _total_triangles(bpy, objects: list) -> int:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    total = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            total += len(mesh.loop_triangles)
        finally:
            evaluated.to_mesh_clear()
    return total


def _render_png_sequence(bpy, out: Path, name: str, report: dict) -> Optional[str]:
    """Frames as `<name>_0001.png` …, the fallback when ffmpeg is unavailable."""
    scene = bpy.context.scene
    frames_dir = out / f"{name}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(frames_dir / f"{name}_")
    bpy.ops.render.render(animation=True)
    if not any(frames_dir.glob("*.png")):
        report["warnings"].append(
            f"frame render reported success but wrote nothing to {frames_dir}")
        return None
    return str(frames_dir)


def _render_mp4(bpy, out: Path, name: str, report: dict) -> Optional[str]:
    """One H.264 file. Returns None when this build cannot encode video."""
    scene = bpy.context.scene
    path = out / f"{name}.mp4"
    try:
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.filepath = str(path)
        bpy.ops.render.render(animation=True)
    except Exception as e:  # noqa: BLE001 - build without ffmpeg, or no codec
        report["warnings"].append(f"mp4 unavailable ({e}); writing PNG frames")
        return None
    # Blender appends the frame range to the name when it feels like it.
    if path.is_file():
        return str(path)
    produced = sorted(out.glob(f"{name}*.mp4"))
    return str(produced[0]) if produced else None


def _render_poster(bpy, out: Path, name: str, frame: int,
                   report: dict) -> Optional[str]:
    scene = bpy.context.scene
    path = out / f"{name}_poster.png"
    scene.frame_set(frame)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file():
        report["warnings"].append(
            f"poster render reported success but wrote no file at {path}")
        return None
    return str(path)


def _write_sidecar(out: Path, name: str, report: dict) -> str:
    """The report next to the pictures, so a batch is greppable."""
    path = out / f"{name}_preview.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return str(path)


# ── Batch ─────────────────────────────────────────────────────────────────────


def render_from_results_summary(summary_path: str, out_dir: str, **kwargs) -> list:
    """Render every artifact listed in a `<kind>_results_summary.json`."""
    results = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    reports = []
    for entry in results:
        src = entry.get("glb_path")
        if not src:
            continue
        try:
            reports.append(render_preview(
                src, out_dir, name=entry.get("task_id"), **kwargs))
        except Exception as e:  # noqa: BLE001 - one bad asset must not stop a batch
            reports.append({"ok": False, "source": src, "error": str(e),
                            "warnings": []})
    return reports


# ── CLI ───────────────────────────────────────────────────────────────────────


def _script_argv() -> list:
    """Arguments after Blender's bare `--`, or the whole tail under pip `bpy`."""
    import sys  # noqa: PLC0415

    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return [a for a in sys.argv[1:] if a != Path(__file__).name]


def _parse_args(argv: list):
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        prog="render_preview.py",
        description="Render a generated asset headlessly (runs inside bpy)")
    ap.add_argument("--src", help="Asset to render")
    ap.add_argument("--summary", help="A <kind>_results_summary.json — render every entry")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--name", default=None)
    ap.add_argument("--mode", default="orbit", choices=MODES)
    ap.add_argument("--format", dest="output_format", default="auto", choices=FORMATS)
    ap.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS)
    ap.add_argument("--resolution", type=int, nargs=2, default=list(DEFAULT_RESOLUTION),
                    metavar=("W", "H"))
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--engine", default="auto",
                    choices=["auto", "cycles", "eevee", "workbench"])
    ap.add_argument("--no-poster", action="store_true")
    ap.add_argument("--report", default=None, help="Write the JSON report here")
    return ap.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(_script_argv() if argv is None else argv)
    if not args.src and not args.summary:
        raise SystemExit("either --src or --summary is required")

    common = dict(
        mode=args.mode, output_format=args.output_format, frames=args.frames,
        fps=args.fps, resolution=tuple(args.resolution), samples=args.samples,
        engine=args.engine, poster=not args.no_poster,
    )
    if args.summary:
        payload: Any = render_from_results_summary(args.summary, args.out, **common)
        ok = all(r.get("ok") for r in payload)
    else:
        try:
            payload = render_preview(args.src, args.out, name=args.name, **common)
            ok = payload["ok"]
        except Exception as e:  # noqa: BLE001 - the report is the contract
            payload = {"ok": False, "source": args.src, "error": str(e), "warnings": []}
            ok = False

    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    print(text)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    code = main()
    if os.environ.get("AAAGF_BLENDER_EXIT_ON_DONE"):
        raise SystemExit(code)
