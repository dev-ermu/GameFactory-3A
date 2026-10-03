"""
engine_adapters/blender/game/recorder.py

Bake a simulation onto keyframes, then render it.

The simulation is authoritative and runs first; recording is a side effect. Each
tick the recorder writes the current transform of every registered object onto
frame N, so the finished `.blend` *is* the run — scrubbable, re-renderable at a
different resolution, and openable by somebody who wants to know why the car
left the track on lap two. Rendering from a live loop instead would give a video
and nothing else.

Keyframing per tick rather than storing and bulk-writing at the end is a
deliberate choice: `keyframe_insert` measures at ~100k inserts/second, which is
an order of magnitude more than a 30-second game at 30 fps needs, and it avoids
the version-specific channelbag API that bulk f-curve creation requires from
4.4 on (see `agent_skills/engine_context/blender_api.md` §3a).

Interpolation is set once at the end:

- transforms  -> LINEAR, because Bézier overshoots. A car easing past its own
  keyframe on a hairpin leaves the road it demonstrably stayed on in the
  simulation, and a bar eases past 100%.
- `hide_render` -> CONSTANT, so a spawned tracer is either there or not.
"""

import json
import os
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence

#: Channels baked when a caller does not name any.
DEFAULT_CHANNELS = ("location", "rotation_euler")

#: Tone mapping for a game frame; see `configure_render` for why not the default.
#: Lives here rather than at its use site because the interactive path has to set
#: the same value on the same scene setting, and a viewport that tone-maps
#: differently from the video makes a session useless as a preview of it.
VIEW_TRANSFORM = "Standard"

#: Curves that must step rather than blend.
_STEP_CHANNELS = {"hide_render", "hide_viewport"}


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("recorder must run inside a bpy interpreter") from e
    return bpy


def _action_fcurves(action) -> list:
    """
    Every f-curve of an action, on either side of the 4.4 slot rework.

    `action.fcurves` disappeared when actions became layered; the curves moved
    to layers -> strips -> channelbags. Insertion is unchanged, so this is only
    needed by code that walks the curves afterwards — here, to set interpolation.
    """
    direct = getattr(action, "fcurves", None)
    if direct is not None:
        try:
            curves = list(direct)
            if curves:
                return curves
        except (TypeError, AttributeError):
            pass
    return [fc
            for layer in getattr(action, "layers", ())
            for strip in getattr(layer, "strips", ())
            for bag in getattr(strip, "channelbags", ())
            for fc in bag.fcurves]


class Recorder:
    """
    Registers objects, bakes them per tick, and renders the result.

    Args:
        fps: simulation *and* playback rate. One tick is one frame, which keeps
             an event log indexed by tick directly comparable to the video.
        resolution: `(x, y)` pixels.
    """

    def __init__(self, fps: int = 30, resolution: Sequence[int] = (960, 540)):
        self.fps = fps
        self.resolution = tuple(resolution)
        self.frames = 0
        self._tracked: list[tuple] = []
        self._seen: set = set()

    # ── registration ──────────────────────────────────────────────────────────

    def track(self, obj, channels: Iterable[str] = DEFAULT_CHANNELS) -> None:
        """
        Bake `channels` of `obj` from now on.

        Naming channels matters for size and for correctness: a crate that only
        ever moves needs no rotation curves, and baking `scale` on an object
        whose scale is meaningful only as a HUD fill would fight the widget.
        """
        key = (obj.name, tuple(channels))
        if key in self._seen:
            return
        self._seen.add(key)
        self._tracked.append((obj, tuple(channels)))

    @property
    def tracked_count(self) -> int:
        return len(self._tracked)

    # ── baking ────────────────────────────────────────────────────────────────

    def capture(self, frame: int) -> None:
        """Write every registered channel onto `frame`. Call once per tick."""
        for obj, channels in self._tracked:
            for channel in channels:
                obj.keyframe_insert(data_path=channel, frame=frame)
        self.frames = max(self.frames, frame)

    def finish(self) -> None:
        """Set interpolation on everything baked, and frame the scene's range."""
        bpy = _bpy()
        for obj, _ in self._tracked:
            anim = obj.animation_data
            if anim is None or anim.action is None:
                continue
            for fc in _action_fcurves(anim.action):
                mode = "CONSTANT" if fc.data_path in _STEP_CHANNELS else "LINEAR"
                for kp in fc.keyframe_points:
                    kp.interpolation = mode
                fc.update()

        scene = bpy.context.scene
        scene.frame_start = 1
        scene.frame_end = max(1, self.frames)
        scene.render.fps = self.fps

    # ── output ────────────────────────────────────────────────────────────────

    def configure_render(
        self,
        *,
        samples: int = 24,
        device: str = "CPU",
        film_transparent: bool = False,
        view_transform: str = VIEW_TRANSFORM,
    ) -> dict:
        """
        Put the scene on Cycles and report what was actually selected.

        Cycles rather than EEVEE because EEVEE needs a GL/EGL context that a
        headless box does not have, and the failure is an abort with no
        exception to catch. Availability is decided by *assigning* the engine,
        never by reading the enum — an add-on engine is not an enum member even
        when it is present.
        """
        bpy = _bpy()
        scene = bpy.context.scene
        info: dict = {"engine": None, "device": "CPU", "samples": samples,
                      "warnings": []}

        if "cycles" not in bpy.context.preferences.addons:
            try:
                bpy.ops.preferences.addon_enable(module="cycles")
            except RuntimeError as e:
                info["warnings"].append(f"cycles addon_enable failed: {e}")

        try:
            scene.render.engine = "CYCLES"
            info["engine"] = "CYCLES"
        except TypeError as e:
            info["warnings"].append(f"CYCLES unavailable ({e}); left on "
                                    f"{scene.render.engine}")
            info["engine"] = scene.render.engine
            return info

        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        scene.cycles.use_adaptive_sampling = True
        # Secondary rays are what make a Cycles frame expensive, and a game shot
        # lit by one sun does not need them; two bounces keeps the ambient fill.
        scene.cycles.max_bounces = 2
        scene.cycles.diffuse_bounces = 2
        scene.cycles.glossy_bounces = 1
        scene.cycles.transmission_bounces = 1
        scene.cycles.volume_bounces = 0
        scene.cycles.transparent_max_bounces = 2

        info["device"] = self._select_device(bpy, scene, device, info["warnings"])

        # Every frame of a session has identical geometry and differs only in
        # transforms, so Cycles' default per-frame rebuild is waste — and on a GPU
        # it dominates, because it re-uploads geometry and rebuilds the BVH across
        # PCIe every frame. Measured on the dressed shooter at 960x540/16spp:
        # 3.7 s/frame on 2x H100 without it, 1.18 s with. Costs memory (the scene
        # stays resident), which at a few hundred MB is not worth a switch.
        scene.render.use_persistent_data = True

        # Blender defaults to AgX, a filmic transform that desaturates hard and
        # rolls highlights off. It flatters a photoreal render and washes out a
        # game frame built from saturated flat colours and emissive HUD, which
        # then reads as fog. "Standard" is the one that looks like the palette.
        try:
            scene.view_settings.view_transform = view_transform
            scene.view_settings.look = "None"
        except TypeError:
            info["warnings"].append(
                f"view transform {view_transform!r} unavailable; kept "
                f"{scene.view_settings.view_transform!r}")

        scene.render.resolution_x, scene.render.resolution_y = self.resolution
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = film_transparent
        return info

    @staticmethod
    def _select_device(bpy, scene, device: str, warnings: list) -> str:
        """
        Pick a Cycles device, falling back to CPU whenever a GPU is not usable.

        CPU is the default because it always works, not because it is always
        faster. What a GPU is worth depends on how much work a frame is, and the
        numbers cross over — measured on 2x H100 against a Xeon Silver 4410Y, on
        the dressed shooter, with `use_persistent_data` on:

            960x540,   16 spp    1.5 s CPU    1.18 s CUDA    1.3x
            1920x1080, 128 spp  29.5 s CPU     8.7 s CUDA    3.4x

        An earlier note here claimed a GPU was forty times slower. That was real,
        and it was measured before `use_persistent_data` — a per-frame fixed cost
        is invisible when a benchmark renders one frame and dominant over five
        hundred.

        A GPU that is *listed* is not a GPU that works, hence the check below:
        enabling a backend with no devices behind it renders on the CPU anyway
        while reporting GPU. OptiX needs ray-tracing cores a Hopper compute card
        does not have, so both H100s enumerate under CUDA and none under OptiX.
        """
        if device == "CPU":
            scene.cycles.device = "CPU"
            return "CPU"

        prefs = bpy.context.preferences.addons.get("cycles")
        if prefs is None:
            scene.cycles.device = "CPU"
            warnings.append("cycles preferences unavailable; using CPU")
            return "CPU"
        prefs = prefs.preferences

        wanted = ["OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"] if device == "AUTO" else [device]
        for backend in wanted:
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            prefs.get_devices()
            usable = [d for d in prefs.devices if d.type == backend]
            if not usable:
                continue
            for d in prefs.devices:
                d.use = (d.type == backend)
            scene.cycles.device = "GPU"
            return f"GPU:{backend}({len(usable)})"

        scene.cycles.device = "CPU"
        warnings.append("no usable GPU backend; using CPU")
        return "CPU"

    def render_video(self, out_path: str | Path, *, quality: str = "HIGH") -> dict:
        """
        Render the baked range to MP4, or to a PNG sequence when there is no
        FFMPEG writer (the pip `bpy` wheel has none; the application does).

        Returns a report rather than raising: a missing video is a degraded run,
        not a failed one, and the metrics and `.blend` are still worth having.
        """
        bpy = _bpy()
        scene = bpy.context.scene
        # Blender resolves a relative render path against the blend file, and a
        # headless run has none: the render then writes nothing and still
        # reports FINISHED.
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        report: dict = {"video": None, "frames_dir": None, "format": None,
                        "seconds": None, "warnings": []}

        settings = scene.render.image_settings
        use_ffmpeg = True
        try:
            settings.file_format = "FFMPEG"
        except TypeError:
            use_ffmpeg = False
            report["warnings"].append(
                "no FFMPEG writer in this build; wrote a PNG sequence instead")

        if use_ffmpeg:
            scene.render.ffmpeg.format = "MPEG4"
            scene.render.ffmpeg.codec = "H264"
            scene.render.ffmpeg.constant_rate_factor = quality
            scene.render.ffmpeg.ffmpeg_preset = "GOOD"
            scene.render.ffmpeg.audio_codec = "NONE"
            scene.render.filepath = str(out_path.with_suffix(""))
            report["format"] = "mp4"
        else:
            settings.file_format = "PNG"
            frames_dir = out_path.with_suffix("") / "frame_"
            frames_dir.parent.mkdir(parents=True, exist_ok=True)
            scene.render.filepath = str(frames_dir)
            report["format"] = "png_sequence"
            report["frames_dir"] = str(frames_dir.parent)

        started = time.time()
        bpy.ops.render.render(animation=True)
        report["seconds"] = round(time.time() - started, 1)

        if use_ffmpeg:
            # Blender appends the frame range to a video filename; find it back
            # rather than guessing, and only report a file confirmed on disk.
            #
            # Two traps, both of which only bite when the directory already holds
            # a video from a previous run — that is, on every re-render:
            # `gameplay*.mp4` also matches the destination `gameplay.mp4`, which
            # sorts *before* `gameplay0001-0354.mp4` because "." < "0", so
            # promoting `produced[0]` promotes the old file over itself and the
            # report cites the previous run. And if the render wrote nothing at
            # all, a stale file left in place looks like a success. So the
            # destination is excluded from the search and every candidate has to
            # be newer than this render.
            stem = out_path.with_suffix("").name
            fresh = started - 1.0
            produced = sorted(p for p in out_path.parent.glob(f"{stem}*.mp4")
                              if p != out_path and p.stat().st_mtime >= fresh)
            if produced:
                produced[0].replace(out_path)
                report["video"] = str(out_path)
            elif out_path.is_file() and out_path.stat().st_mtime >= fresh:
                report["video"] = str(out_path)   # written under the exact name
            else:
                report["warnings"].append("ffmpeg produced no file")
        return report

    def render_still(self, out_path: str | Path, frame: Optional[int] = None) -> Optional[str]:
        """One frame, for a thumbnail. Returns the path only once it exists."""
        bpy = _bpy()
        scene = bpy.context.scene
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if frame is not None:
            scene.frame_set(frame)
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(out_path)
        bpy.ops.render.render(write_still=True)
        return str(out_path) if out_path.is_file() else None

    def save_blend(self, out_path: str | Path) -> Optional[str]:
        """
        Save the baked scene.

        This is the artifact that outlives the video: everything the headless
        renderer had to skip is in it and draws when it is opened in the GUI.
        """
        bpy = _bpy()
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(out_path), copy=True)
        return str(out_path) if out_path.is_file() else None


def write_report(path: str | Path, report: dict) -> str:
    """Write a run report as JSON. Reporting is the contract, not the log."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return str(path)


def exit_code(ok: bool) -> None:
    """
    Make the shell see the result.

    `blender --background --python x.py` exits 0 whatever the script did, so a
    caller checking the return code sees success after a total failure. Gated on
    an environment variable so an interactive run does not kill the application.
    """
    if os.environ.get("AAAGF_BLENDER_EXIT_ON_DONE"):
        raise SystemExit(0 if ok else 1)
