"""
engine_adapters/blender/runtime/selftest.py

Drive the whole runtime once, headless, and say what worked.

A diagnostic for a Blender installation rather than part of the repository's
test suite: it answers whether this box has a Blender that can import, simulate
and render without a display, which is a property of the machine, not the code.
Commands go through the real dispatcher, so the path exercised is the one a UDP
packet takes; only the socket is skipped.

Critical steps fail the run and VFX kinds do not, on purpose — a build without
Mantaflow is a usable runtime for everything else, and a diagnostic that reports
"broken" for a missing optional backend gets ignored.

    python -m engine_adapters.blender.runtime.selftest
    OUT_DIR=D:/scratch/runtime python -m engine_adapters.blender.runtime.selftest
"""

import os
import sys
import tempfile
from pathlib import Path


def _ensure_importable() -> None:
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_ensure_importable()

import bpy  # noqa: E402

from engine_adapters.blender.runtime.subsystem import Subsystem  # noqa: E402


def _reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def build_fixtures(work: Path) -> tuple:
    """
    Write the three files the run needs: a set, an environment, a character.

    Built here rather than committed so the check has no asset dependency and
    stays honest about what this Blender can read — a fixture it exported is a
    fixture it can import.
    """
    work.mkdir(parents=True, exist_ok=True)
    blend_path = work / "set.blend"
    env_path = work / "generated_env.glb"
    character_path = work / "character.glb"

    # A set: a torus in its own collection, plus a light, saved as .blend.
    _reset()
    collection = bpy.data.collections.new("set_geometry")
    bpy.context.scene.collection.children.link(collection)
    bpy.ops.mesh.primitive_torus_add(location=(0, 0, 0.5))
    torus = bpy.context.active_object
    torus.name = "set_torus"
    for current in list(torus.users_collection):
        current.objects.unlink(torus)
    collection.objects.link(torus)
    sun_data = bpy.data.lights.new("set_sun", type="SUN")
    sun = bpy.data.objects.new("set_sun", sun_data)
    collection.objects.link(sun)
    sun.location = (3, -3, 6)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), copy=True)

    # A generated environment: ground plus a block, as a world preparer emits.
    _reset()
    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0, 0, 0))
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.5, 0, 0.5))
    bpy.ops.export_scene.gltf(filepath=str(env_path), export_format="GLB",
                              use_selection=False)

    # A character: one mesh, roughly person-sized.
    _reset()
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.9))
    bpy.context.active_object.scale = (0.3, 0.3, 0.9)
    bpy.ops.export_scene.gltf(filepath=str(character_path), export_format="GLB",
                              use_selection=False)

    return blend_path, env_path, character_path


# ── Run ───────────────────────────────────────────────────────────────────────


def main() -> int:
    out_dir = Path(os.environ.get("OUT_DIR") or tempfile.mkdtemp(prefix="bruntime_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[selftest] blender {bpy.app.version_string}")
    print(f"[selftest] outputs -> {out_dir}")

    blend_set, env, character = build_fixtures(out_dir / "fixtures")

    _reset()
    Subsystem.reset()
    subsystem = Subsystem.get()
    subsystem.start(listen=False)
    dispatcher = subsystem.dispatcher

    results: dict = {}

    def step(tag: str, command: str, payload: dict, critical: bool = False) -> bool:
        try:
            ok = bool(dispatcher.dispatch(command, payload))
            results[tag] = "ok" if ok else "returned False"
            return ok
        except Exception as e:  # noqa: BLE001 - the report is the deliverable
            results[tag] = f"{type(e).__name__}: {e}"
            if critical:
                raise
            return False

    step("load_scene", "load_scene", {"scene_path": str(blend_set)}, critical=True)
    assert "set_torus" in bpy.data.objects, "the .blend's contents did not arrive"

    step("import_scene", "import_scene",
         {"scene_path": str(env), "collection_name": "generated_env"}, critical=True)
    assert bpy.data.collections.get("generated_env"), "no collection for the import"

    step("ensure_player", "ensure_player",
         {"entity_id": "p0", "obj_path": str(character),
          "spawn_location": [0.0, 0.0, 0.0]}, critical=True)
    step("apply_input", "apply_input",
         {"entity_id": "p0", "move_y": 1.0, "run": True})
    subsystem.players.tick(0.5)
    moved = subsystem.players.get("p0").obj.location.y
    results["movement"] = "ok" if moved > 0.1 else f"did not move (y={moved:.3f})"

    step("set_preview_character", "set_preview_character",
         {"obj_path": str(character), "scale": 1.0})
    step("apply_camera_input", "apply_camera_input",
         {"yaw_delta": 35.0, "pitch_delta": -5.0, "zoom_delta": -1.0})

    vfx_kinds = [
        ("particle", {"location": [0, 0, 1.0], "params": {"count": 200, "lifetime": 40}}),
        ("geometry_nodes", {"location": [1, 1, 0.5], "params": {}}),
        ("grease_pencil", {"location": [-1, 0, 1.0], "params": {"template": "impact_lines"}}),
        ("smoke", {"location": [2, 2, 0.0], "params": {"resolution": 32}}),
        ("fire", {"location": [-2, 2, 0.0], "params": {"resolution": 32}}),
    ]
    for kind, extra in vfx_kinds:
        step(f"vfx:{kind}", "trigger_vfx", {"vfx_kind": kind, **extra})

    png = out_dir / "snapshot.png"
    step("render_snapshot", "render_snapshot",
         {"filepath": str(png), "resolution": [640, 400], "samples": 16},
         critical=True)

    blend_out = out_dir / "session.blend"
    step("save_blend", "save_blend", {"filepath": str(blend_out)}, critical=True)
    report = out_dir / "scene_report.txt"
    step("dump_scene_report", "dump_scene_report", {"filepath": str(report)})

    spawned = len(subsystem.vfx.spawned())
    step("clear_vfx", "clear_vfx", {})
    results["clear_vfx"] = ("ok" if not subsystem.vfx.spawned()
                            else f"{len(subsystem.vfx.spawned())}/{spawned} left behind")
    step("destroy_player", "destroy_player", {"entity_id": "p0"})

    # ── Report ────────────────────────────────────────────────────────────────

    print("\n[selftest] steps")
    for tag, status in results.items():
        print(f"  [{'PASS' if status == 'ok' else 'FAIL'}] {tag}: {status}")

    artifacts = {"PNG": png, "BLEND": blend_out, "REPORT": report}
    print("\n[selftest] artifacts")
    written = {}
    for label, path in artifacts.items():
        size = path.stat().st_size if path.is_file() else 0
        written[label] = size > 0
        print(f"  {label:<7}{path}  ({size} bytes)" if size
              else f"  {label:<7}{path}  MISSING")

    vfx_ok = sum(1 for tag, status in results.items()
                 if tag.startswith("vfx:") and status == "ok")
    print(f"\n[selftest] vfx backends: {vfx_ok}/{len(vfx_kinds)}")

    ok = all(written.values()) and results.get("movement") == "ok"
    print(f"[selftest] {'SUCCESS' if ok else 'FAILURE'}")
    sys.stdout.flush()

    # Not cleanup for its own sake: without it the fluid simulation this run
    # created takes Blender's teardown down with it and the exit code reports a
    # crash instead of the result printed above.
    subsystem.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    # Exit normally. Short-circuiting with os._exit looks like the safe way to
    # dodge a messy Blender teardown, but with bpy loaded it faults on Windows
    # and turns a clean run into an access violation. Removing the objects that
    # make teardown unhappy — which the run already does — is the fix.
    sys.exit(main())
