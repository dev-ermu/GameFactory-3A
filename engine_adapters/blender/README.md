# engine_adapters/blender

Blender (`bpy`) reference code — asset import, headless preview, and a
playable session.

> Blender is not a fourth target engine. It is the neutral step between a
> generator and one: the only adapter here that reads `.ply` and `.usd`, that can
> re-pivot or decimate an asset the generator got wrong, and that can render a
> picture of the result — or let you walk around it — without a project, a
> licence or a GPU.

## Files

| Path | Runs where | Purpose |
|------|-----------|---------|
| `import_generated/import_mesh.py` | a `bpy` interpreter | import → condition → measure → re-export → report |
| `import_generated/import_motion.py` | a `bpy` interpreter | import a retargeted FBX and check pose animation |
| `render_preview.py` | a `bpy` interpreter | turntable / still render of an asset, headless |
| `game/` | a `bpy` interpreter | the gameplay kit a generated mechanic is written against |
| `examples/` | a `bpy` interpreter | genre mechanics (FPS / racing / fighting / RPG) owned by this adapter |
| `playtest/` | host Python + a `bpy` interpreter | discover actions, drive `Controls`, write `frames/` / `video.mp4` / `report.json` |
| `runtime/` | a `bpy` interpreter | a live session driven by JSON over UDP — spawn, move, effects, snapshot |
| `../../scripts/import_generated_asset.py` | host Python | finds Blender, launches the importer, reads the report |
| `../../scripts/prepare_world_asset.py` | host Python | world export → one continuous `.glb` (needs no Blender) |

Motion rig / retarget is **not** here — use
`operators/gen_motion/funcs/retarget_utils/` via the gen_motion pipeline.

Everything except `runtime/` is batch: a file in, a file out, the process exits.
`runtime/` is the other mode — one long-lived process holding a scene that
commands mutate — and it is the answer to questions a report cannot settle, like
whether a repaired world can actually be walked through. See its own README.

`game/` is a third mode again, and the distinction is worth keeping straight:
`runtime/` drives a live Blender so a *person* can look around a scene, while
`game/` plays a whole match with nobody watching, bakes it to keyframes and
renders it. One is for inspection, the other is for evidence.

`game/` also has a live mode of its own — `--play`, which steps the same rules in
a window from a keyboard rather than baking them. That is not a third
implementation: it is the same `tick()` at the same fixed timestep, and a played
session records its input so it can be re-rendered offline into the same run. See
the two sections below.

`playtest/` is unattended `--play`: discovered keys, then `report.json` + clip.

## Running

Two interpreters can run everything here, and the code does not care which:

```bash
# a Blender application
blender --background --factory-startup \
    --python engine_adapters/blender/import_generated/import_mesh.py -- \
    --src out/model.glb --dest library/ --name Sword_001 --preview

# or a Python that has the wheel
pip install bpy==4.2.0
python engine_adapters/blender/import_generated/import_mesh.py \
    --src out/model.glb --dest library/ --name Sword_001 --preview
```

`blender --python x.py -- ...` hands the *whole* command line to the script, so
everything after the bare `--` is the script's. Under the pip wheel there is no
separator; `_script_argv()` handles both.

The host-side launcher finds either one for you and speaks the same
`--usage / --pivot / --target-tris` vocabulary as the UE5 and Unity routes:

```bash
python scripts/import_generated_asset.py --engine blender \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --blender-preview
```

## Units and axes

Blender is metres and **Z-up**; glTF is metres and **Y-up**; UE is centimetres
and Z-up. The glTF importer and exporter convert in both directions, so a round
trip `glb → Blender → glb` is identity — which is what makes Blender safe to put
between a generator and UE5. The FBX exporter is set to `-Z` forward / `Y` up for
the same reason.

The `.ply` importer applies **no** conversion, because a PLY has no axis
metadata to convert from. `scripts/prepare_world_asset.py --up z` is where a
Z-up world export gets rotated, once, before anything else sees it.

## Rig and retarget

Character rigging and motion retarget live under
`operators/gen_motion/funcs/retarget_utils/` (host driver:
`operators/gen_motion/funcs/retarget_motion.py`). See
`agent_skills/asset_qa/motion_gen_skills.md`.

After a retargeted FBX is written, import/validate it with:

```bash
python scripts/import_generated_asset.py \
  --src retargeted.fbx --engine blender --kind motion \
  --blender $A3GF_RETARGET_BPY_PYTHON
```

## The gameplay kit (`game/`)

What a generated mechanic imports. A game subclasses `kernel.Game` and fills in
three methods — `build()`, `tick()`, `summary()` — and the kernel does the rest:

| Module | What it gives a game |
|---|---|
| `kernel` | fixed-timestep loop, `Actor`, the event log, world and sun setup, `main()` |
| `prims` | shared unit meshes — box, cylinder, sphere, plane, swept ribbon — and spawning |
| `materials` | cached Principled and emissive materials, and a shared palette |
| `camera_rigs` | first-person, chase and side-on cameras with one yaw convention |
| `hud` | bars, pip rows, labels, crosshair and vignettes as camera-parented geometry |
| `recorder` | keyframe baking, Cycles setup, MP4 and thumbnail export |
| `controls` | the input surface a player drives, and how keys and mouse map onto it |
| `interactive` | that surface wired to a live Blender window — the `--play` mode |

Three properties of the design carry most of the weight:

**The clock is not the wall clock.** `tick()` advances by a fixed `dt` and one
tick is one rendered frame, so a run is reproducible, an event logged at tick N
is at N/fps in the video, and a slow render cannot change the outcome of a match.

**The HUD is geometry, not an overlay.** There is no viewport to draw into
headless. Widgets are emissive planes parented to the camera, which makes them
screen-space for free and — more importantly — *keyframeable*: a health bar is
`scale.x`, so it survives into the `.blend` a reviewer opens. Bars are emissive
at strength 1.0 because the render uses the Standard view transform, which clips
instead of rolling off; anything brighter loses its dimmest channels and every
coloured bar on screen converges on white.

**`hide_render` does not stop a ray.** Hiding a HUD element or an idle VFX object
from the render leaves it in the ray-cast depsgraph, where it silently blocks
every shot the player fires. `prims.spawn(..., collide=False)` sets
`hide_viewport` as well, which is what actually removes it. Every HUD widget,
tracer, spark and viewmodel part is spawned that way.

```bash
# run one of the shipped examples directly
GAMEFACTORY3A_ROOT=$PWD blender --background --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- \
    --out-dir /tmp/fps --duration 8 --no-render      # rules only, seconds
```

A run writes `gameplay.mp4`, `thumbnail.png`, `session.blend`,
`demo_outputs/events.json` and `demo_outputs/report.json`. The report carries the
metrics and a pass/fail verdict the game computes about itself, and **the report
is the result** — `blender --background --python x.py` exits 0 whatever the
script did, so a missing report is a failure, not a silent success.

## Playtest

Discovered keys through `Controls`, not the unattended policy:

```python
from engine_adapters.blender import BlenderClient

BlenderClient(
    project_path="engine_adapters/blender/examples/FPSExample",
).playtest.record(
    output_dir="/tmp/blender_playtest",
    duration=8,
    no_render=True,
)
```

`no_render=True` skips the Cycles clip. See `blender_api.md` § Playtest.

## Playing one (`--play`)

The same game, stepped live from a keyboard instead of baked. It needs a real
Blender window, so no `--background`:

```bash
GAMEFACTORY3A_ROOT=$PWD blender --factory-startup \
    --python engine_adapters/blender/examples/RacingExample/game.py -- --play
```

Generated mechanics get a `play.sh` next to their `launch.sh` that does this with
the right spec and environment already filled in.

| | FPS | Racing | Fighting |
|---|---|---|---|
| move | `WASD` | `W`/`S` pedals, `A`/`D` steer | `A`/`D` step |
| act | mouse aim, `LMB` fire, `R` reload | `SPACE` handbrake | `J` light, `K` heavy, `L` guard |

`P` pauses and `ESC` quits everywhere. Arrow keys mirror `WASD`, and in the FPS
they also turn the view — mouse capture is the first thing to break over a remote
display, and a shooter you cannot aim in is not testable.

Four things make a batch-written mechanic safe to play:

**The timestep still does not change.** The wall clock decides *when* a tick
happens and never how big it is; a frame that arrives late runs the same 33 ms of
game, and a very late one runs up to four of them before the debt is dropped.
Scaling a fixed step by measured elapsed time is the classic way to make a
simulation explode the first time a window is dragged.

**Nothing bakes.** `Recorder.capture()` is not called, so a ten-minute session
does not accumulate eighteen thousand keyframes per object.

**EEVEE draws it, not Cycles.** Interactive Cycles is a slideshow. The generated
materials are flat diffuse-and-emissive, which EEVEE renders close enough to the
Cycles video that the played level and the rendered one read the same.

**The rules do not know who is playing.** A game reads `self.controls`; whether
that came from a keyboard, a recorded timeline or its own policy is not its
concern. Which is what makes the next section possible.

### Replaying a session

Every session writes `demo_outputs/input_timeline.json` — the keys and mouse
deltas, not the outcome. Feeding it back drives the offline renderer through the
identical loop:

```bash
./launch.sh --replay-input demo_outputs/input_timeline.json --duration 12
```

The replay reproduces the session exactly — same positions, same shots, same
events — which is the property that makes playing worth anything to a benchmark:
a session becomes evidence that can be re-rendered at full quality and diffed,
rather than an anecdote about how it felt.

Exactly is a strong word and it took two fixes to earn. A timeline stores
*seconds*, tick times are thirds of a hundredth, and `0.0333… < 0.033` decides a
key was released a frame early — so span boundaries are compared as tick indices,
not as floats. And aiming is a feedback loop: rounding a recorded mouse delta to a
hundredth of a pixel is a missed shot three hundred ticks later and a different
fight after that. Both were found by replaying a 354-tick session and diffing it
against the original, which is the only test that finds them; a short round trip
passes with either bug in place.

## Headless rendering

The pip `bpy` wheel drives EEVEE and Workbench through a GL/EGL context. A
machine without a display has none, and the failure is a `libEGL` abort rather
than an exception, so `render_preview.py` defaults to **Cycles on CPU** and falls
back to it when a GL engine is asked for and dies. Grease-pencil objects go
through GL even under Cycles and take the process down uncatchably; they are
hidden from the render and restored afterwards.

```bash
blender --background --factory-startup \
    --python engine_adapters/blender/render_preview.py -- \
    --src world.glb --out previews/ --mode orbit --format mp4
```

`--format mp4` needs an FFMPEG writer, which the Blender application bundles and
**the pip wheel does not** — under the wheel the `file_format` enum has no
`FFMPEG` entry at all. `auto` and `mp4` both fall back to a PNG sequence and
record why, so a turntable still comes out either way.

Output paths are made absolute before they reach `bpy`. Blender resolves a
relative render path against the blend file, and headless there is none: the
render then writes nothing and still reports `FINISHED`. For the same reason
every report field naming a file is filled in only after that file is confirmed
on disk.

## Dependencies

| Module | Needs |
|--------|-------|
| `import_generated/import_mesh.py`, `import_motion.py`, `render_preview.py` | `bpy` only |
| `game/` | `bpy` only — plus a bundled FFMPEG writer for MP4 |
| `runtime/` | `bpy` only — and `runtime/send_command.py` needs nothing at all |

Every `bpy` import is deferred in the two importer modules, so the host-side
launcher and `test/` can read their constants with no Blender installed.

## Verified

Run against **Blender 5.0.1** (pip `bpy` wheel, Python 3.11, no display, no GPU):

- the importer and the preview renderer — see `import_generated/README.md` for
  the measured numbers and how to reproduce them;
- the playable runtime — `runtime/selftest.py`, 17/17 steps and 5/5 effect
  backends, plus a live server driven over UDP from a Python with no Blender in
  it. `runtime/README.md` records two Blender 5.0.1 findings that cost real time
  to diagnose.

The host side — job files, argument shapes, tier defaults — is covered by
`tests/test_world_asset.py`, which needs no Blender.

The interactive mode was verified on **Blender 4.5.12** against all three shipped
templates: keys and mouse reaching each genre's rules, the session loop's fixed
step, catch-up cap, pause and quit, and a recorded session of several hundred
ticks replaying into a byte-identical run. Not executed: a live window, because
that needs a graphics driver — this host has the CUDA compute stack and no
OpenGL, so Cycles renders fine and no window can open. `--play` therefore refuses
with an explanation rather than starting a session nobody can see.
