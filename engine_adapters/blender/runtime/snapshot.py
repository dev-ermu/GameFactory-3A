"""
engine_adapters/blender/runtime/snapshot.py

Look at the running session: render it, save it, or describe it.

`../render_preview.py` loads a file into an empty scene and renders that; this
renders the scene *already* there — characters where the last command left them,
effects mid-flight. The headless rules are the same and the code enforcing them
is imported from there rather than copied.

`save_blend` is the escape hatch: everything the headless renderer had to skip,
grease pencil and unbaked smoke, is in the file and draws in the Blender GUI.
"""

import time
from pathlib import Path
from typing import Tuple

from ..render_preview import enable_cycles, hide_gl_only_objects

#: Where output lands when a command names no path. Under the runtime package
#: rather than the working directory, so a session started from anywhere leaves
#: its artifacts somewhere findable.
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "outputs"

#: Engines that need a GL context. Asking for one is honoured, but it falls
#: back rather than aborting when the context turns out not to exist.
GL_ENGINES = frozenset(("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"))


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


def _default_path(stem: str, suffix: str) -> str:
    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEFAULT_OUT_DIR / f"{stem}_{int(time.time())}{suffix}")


def render_snapshot(filepath: str = "", resolution: Tuple[int, int] = (1280, 720),
                    engine: str = "CYCLES", samples: int = 32) -> str:
    """
    Render the scene as it stands to a PNG, defaulting under `DEFAULT_OUT_DIR`.
    Returns the path written. `engine` is `CYCLES` or a `GL_ENGINES` id to try a
    rasteriser instead; `samples` only means anything to Cycles.
    """
    bpy = _bpy()
    scene = bpy.context.scene
    engine = (engine or "CYCLES").upper()

    if engine in GL_ENGINES:
        print(f"[snapshot] {engine} needs a GL context; falling back to Cycles "
              f"CPU if there is none")

    used = engine
    if used == "CYCLES":
        unavailable = enable_cycles(bpy)
        if unavailable is not None:
            raise RuntimeError(f"cycles unavailable: {unavailable}")
        _use_cycles_cpu(bpy, scene, samples)
    else:
        scene.render.engine = used

    scene.render.resolution_x, scene.render.resolution_y = (
        int(resolution[0]), int(resolution[1]))
    scene.render.image_settings.file_format = "PNG"

    path = Path(filepath) if filepath else Path(_default_path("snapshot", ".png"))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Blender resolves a relative render path against the .blend, which in a
    # runtime that has never saved one is not the working directory.
    path = path.resolve()
    scene.render.filepath = str(path)

    warnings: list = []
    hidden = hide_gl_only_objects(bpy, warnings)
    for warning in warnings:
        print(f"[snapshot] {warning}")
    try:
        try:
            bpy.ops.render.render(write_still=True)
        except Exception as e:  # noqa: BLE001 - typically a missing GL context
            if used == "CYCLES":
                raise
            print(f"[snapshot] {used} failed ({e}); retrying with Cycles CPU")
            if enable_cycles(bpy) is not None:
                raise
            _use_cycles_cpu(bpy, scene, samples)
            used = "CYCLES"
            bpy.ops.render.render(write_still=True)
    finally:
        for obj in hidden:
            obj.hide_render = False

    if not path.is_file():
        raise RuntimeError(f"render reported success but wrote nothing to {path}")
    print(f"[snapshot] rendered ({used}) -> {path}")
    return str(path)


def save_blend(filepath: str = "") -> str:
    """
    Write the session to a `.blend`. Returns the path.

    `copy=True` keeps this process pointed at its own unsaved state rather than
    adopting the file it just wrote, so a session can be snapshotted repeatedly
    without its relative paths shifting underneath it.
    """
    bpy = _bpy()
    path = Path(filepath) if filepath else Path(_default_path("session", ".blend"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path = path.resolve()
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    print(f"[snapshot] saved -> {path}")
    return str(path)


def dump_scene_report(filepath: str = "") -> str:
    """
    Write what is in the scene as text. Returns the path.

    Cheap enough to call between commands, and it answers what a picture cannot:
    whether an import landed, what an action is called, whether an effect went.
    """
    bpy = _bpy()
    path = Path(filepath) if filepath else Path(_default_path("report", ".txt"))
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# scene: {bpy.context.scene.name}",
             f"# blender: {bpy.app.version_string}",
             "",
             f"[objects] {len(bpy.data.objects)}"]
    for obj in bpy.data.objects:
        location = tuple(round(v, 3) for v in obj.location)
        parent = obj.parent.name if obj.parent else "-"
        lines.append(f"  - {obj.name}  type={obj.type}  loc={location}  parent={parent}")

    lines += ["", f"[collections] {len(bpy.data.collections)}"]
    for collection in bpy.data.collections:
        lines.append(f"  - {collection.name}  objects={len(collection.all_objects)}")

    lines += ["", f"[actions] {len(bpy.data.actions)}"]
    for action in bpy.data.actions:
        lines.append(f"  - {action.name}  frames={tuple(action.frame_range)}")

    lines += ["", f"[materials] {len(bpy.data.materials)}"]
    for material in bpy.data.materials:
        lines.append(f"  - {material.name}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[snapshot] report -> {path}")
    return str(path)


def _use_cycles_cpu(bpy, scene, samples: int) -> None:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = int(samples)
