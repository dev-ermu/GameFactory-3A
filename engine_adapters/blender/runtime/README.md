# `runtime/` — the playable Blender session

Everything else under `engine_adapters/blender/` is batch work: a file goes in,
a conditioned file comes out, the process exits. This is the other mode — one
long-lived Blender process holding a scene that commands mutate while it runs.

That exists because some questions a report cannot answer. `import_mesh.py`
will tell you a world has 240k triangles and no cracks; it will not tell you
that the doorway is too narrow to walk through, or that the floor the repair
closed is a metre above where the character spawns. Those need something to
walk around in, and answering them here is much cheaper than answering them
after a UE5 import.

## Talking to it

Start a session, then send it JSON over UDP:

```bash
# needs bpy — Blender's own Python, or a 3.11 env with the pip wheel
python -m engine_adapters.blender.runtime.serve --port 30021

# the sender needs nothing; it is a socket and a JSON file
python -m engine_adapters.blender.runtime.send_command \
    engine_adapters/blender/runtime/examples/walk_a_generated_world.json

python -m engine_adapters.blender.runtime.send_command \
    --type render_snapshot --payload '{"samples": 16}'
```

One datagram is one command, `{"type": ..., "payload": {...}}`. UDP because the
usual sender is a controller emitting input at frame rate, where a dropped
packet beats a stalled one — and because it means the sender needs no Blender,
no shared filesystem, and no library beyond `socket`.

Set `BLENDER_ASSET_ROOT` to use `/Library/...` paths, which resolve against it.
Anything else is taken as a real path, so a command file written on one machine
runs on another.

## Commands

| type | payload |
|---|---|
| `ensure_player` | `entity_id`, `obj_path`, `spawn_location?`, `rotation?` — idempotent by `entity_id` |
| `destroy_player` | `entity_id` |
| `load_action` | `entity_id`, `action_path`, `loop?`, `play_rate?` |
| `apply_input` | `entity_id`, `move_x`, `move_y`, `run`, `jump`, `yaw`, `pitch` |
| `load_scene` | `scene_path` (`.blend` only), `link?` |
| `import_scene` | `scene_path` (generated mesh/USD), `collection_name?`, `scale?`, `location?`, `replace_existing?` |
| `clear_scene` | — removes `player_*` and `vfx_*`, leaves the set |
| `set_preview_character` | `obj_path`, `scale?`, `yaw?`, `reframe?` |
| `play_preview_action` | `action_path`, `loop?`, `play_rate?` |
| `apply_camera_input` | `yaw_delta`, `pitch_delta`, `zoom_delta`, `pan_y?`, `pan_z?` |
| `trigger_vfx` | `vfx_kind`, `entity_id?`, `location?`, `params` |
| `clear_vfx` | `name?` — omit to clear everything spawned |
| `join_world` / `leave_world` / `destroy_session` | session lifecycle |
| `render_snapshot` | `filepath?`, `resolution?`, `engine?`, `samples?` |
| `save_blend` | `filepath?` |
| `dump_scene_report` | `filepath?` |

Rotations and camera deltas are **degrees**; positions and distances are
**metres**. Commands get written by hand as often as generated, and radians in
JSON are unreadable.

## Layout

```
runtime/
├── serve.py            # start + tick loop; the whole program is three lines
├── send_command.py     # the client; no bpy
├── selftest.py         # one full pass, headless
├── snapshot.py         # render / save / describe the LIVE scene
├── subsystem.py        # owns the parts and the thread boundary
├── input/              # receiver (UDP thread) + dispatcher (command table)
├── players/            # player, manager, kinematic movement
├── assets/             # path resolver, importers, animation clips
├── scene/              # .blend sets, generated worlds, preview stage, camera
├── vfx/                # manager + particles / geo-nodes / grease pencil / fluid
└── examples/           # command files to send at a running session
```

### The one structural rule

`bpy` is not thread-safe. The UDP receiver never touches Blender — it parses a
datagram and queues it. `Subsystem.drain_pending()` runs on the main thread and
is the only place a command reaches a `bpy.ops` call. Every deadlock and silent
corruption this package could have comes from crossing that line, so the
receiver does not even import `bpy`.

### What is shared rather than copied

- The suffix → importer-operator table is `import_generated/import_mesh.py`'s
  `import_file`. A build that reads `.usdz` offline reads it here too.
- Grease-pencil hiding and Cycles enabling are `../render_preview.py`'s
  `hide_gl_only_objects` and `enable_cycles`. Getting those wrong is not an
  exception, it is a process abort, so there is one copy of each.

## Headless rendering

Same rules as `../render_preview.py`, for the same reasons:

- **Cycles on CPU** is the default and the fallback. EEVEE and Workbench render
  through a GL/EGL context that a machine with no display does not have, and
  the failure is an abort, not an exception.
- **Grease pencil is hidden from the render.** It goes through GL even under
  Cycles and takes the process with it, uncatchably.
- **`save_blend` is the way out of both.** Everything the headless renderer
  skipped is in the file and draws when it is opened in the Blender GUI.

## Verified

`selftest.py` runs a full pass — fixtures, a `.blend` set, a generated `.glb`
world, a spawned character that actually moves, all five effect backends, a
Cycles-CPU render, a `.blend`, a scene report, then cleanup:

```bash
python -m engine_adapters.blender.runtime.selftest
OUT_DIR=D:/scratch/runtime python -m engine_adapters.blender.runtime.selftest
```

Against **Blender 5.0.1** (pip `bpy` wheel, Python 3.11, no display, no GPU):
17/17 steps and 5/5 effect backends, exit 0.

It is a diagnostic for a Blender installation, not a unit test — what it checks
is a property of the machine. The host-side logic that has no `bpy` in it is
covered by `tests/test_world_asset.py`.

### Two Blender 5.0.1 findings worth keeping

Both were measured here, and both look like bugs in this code until you check:

- **A fluid simulation breaks Blender's exit.** Once a Mantaflow domain and a
  flow object have coexisted, teardown faults — after all work is done, so it
  reads as a failed run to anything checking an exit code. The bundled Mantaflow
  scripts are out of step with the compiled module (`LevelsetGrid has no
  attribute setConst`). Deleting the objects does not undo it and neither does
  removing the modifiers; emptying the file does, which is what
  `Subsystem.shutdown()` is for. Call it, or `serve.py` and `selftest.py` will.
- **`os._exit` is not a safe shortcut.** With `bpy` loaded it faults on Windows,
  so using it to skip a messy teardown *creates* the crash it was meant to dodge.
  Exit normally and remove what teardown cannot handle.

### Grease pencil changed generation in 4.3

Strokes used to hang off the frame (`frame.strokes.new()`, points with `.co`);
they now hang off a drawing the frame owns (`frame.drawing.add_strokes([...])`,
points with `.position`). Blender 5.0 dropped the old API entirely.
`vfx/grease_pencil.py` writes both, because the retargeting side of this adapter
still supports 4.2.
