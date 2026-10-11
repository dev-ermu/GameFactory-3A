# Blender for the mechanic pipeline

What `engine_adapters/blender/` needs before it runs, why each piece is needed,
and the failure signature it produces when it is missing. The companion script
`install.sh` does all of this non-interactively; this file is the
reference for deciding *what* to install and for reading an error.

Everything here is **sudo-free**: a portable Blender tarball plus a conda prefix
holding the shared libraries the host does not have. Nothing is installed
system-wide, so a wrong guess costs a `rm -rf` rather than a broken machine.

Verified against **Blender 4.5.12 LTS** on Ubuntu 22.04.4 (kernel 5.15, glibc
2.35), no root. glibc is the one host requirement a conda prefix cannot paper
over: the portable build needs a recent enough one, and on an older distro the
symptom is a `GLIBC_2.xx not found` at startup rather than a missing `.so`.

## Which route

Two interpreters can run this code and most of it does not care which — but the
game pipeline does, in one place.

| | Blender application | `pip install bpy` wheel |
|---|---|---|
| `import_generated/`, `render_preview.py` | yes | yes |
| `game/` headless: simulate, bake, render | yes | untested |
| `game/ --play` (live window) | **yes, required** | no |

`--play` opens a real window and runs a modal operator against it.
`interactive.py` checks `bpy.app.background` and refuses rather than degrading:
there is deliberately no offscreen path, because an interactive mode that cannot
be interacted with is a slower headless run wearing a costume. So install the
application if you intend to play; the wheel is only enough for the importers.

## Install

Sizes are the reason for step 0: this needs about **2.5 GB** (361 MB tarball,
1.2 GB extracted, 0.9 GB conda prefix), and the usual failure is a home
directory or a container root with a few hundred megabytes free.

```bash
# 0. Pick a filesystem with room. Everything below goes here.
export AAAGF_TOOLS_DIR=/path/with/space/.aaagf
df -h "$(dirname "$AAAGF_TOOLS_DIR")"

# 1. The application, as a portable tarball. No installer, no root.
mkdir -p "$AAAGF_TOOLS_DIR"
cd "$AAAGF_TOOLS_DIR"
curl -fL -O https://download.blender.org/release/Blender4.5/blender-4.5.12-linux-x64.tar.xz
tar -xf blender-4.5.12-linux-x64.tar.xz

# 2. The shared libraries it links against, into a conda prefix.
conda create -y -p "$AAAGF_TOOLS_DIR/envs/bl" -c conda-forge \
    xorg-libxi xorg-libxxf86vm xorg-libxfixes xorg-libxrender xorg-libxext \
    xorg-libx11 xorg-libsm xorg-libice libxkbcommon mesalib libglu ffmpeg

# 3. Only if you want --play without a physical display.
conda create -y -p "$AAAGF_TOOLS_DIR/envs/xvfb" -c conda-forge xorg-xvfb-server
```

Install the twelve packages in step 2 **in one command**, not one at a time as
the errors ask for. See the first row of the table below for why.

Then an env script to source, because three of these are environment variables
that are easy to forget and silent when absent:

```bash
export BLENDER_HOME="$AAAGF_TOOLS_DIR/blender-4.5.12-linux-x64"
export BLENDER="$BLENDER_HOME/blender"
export AAAGF_BLENDER="$BLENDER"                      # what the launchers read
export LD_LIBRARY_PATH="$AAAGF_TOOLS_DIR/envs/bl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XDG_CACHE_HOME="$AAAGF_TOOLS_DIR/cache"       # Cycles kernel cache
export TMPDIR="$AAAGF_TOOLS_DIR/tmp"
mkdir -p "$XDG_CACHE_HOME" "$TMPDIR"
```

## Failure signatures

| Symptom | Cause | Fix |
|---|---|---|
| `error while loading shared libraries: libXrender.so.1` | The tarball links against X11/GL libraries the host lacks. The loader names **only the first** missing one, so fixing it reveals the next — seven, one run at a time | `LD_LIBRARY_PATH` at the conda prefix. `ldd "$BLENDER" \| grep 'not found'` lists all seven at once |
| Runs, but every render recompiles Cycles kernels | `$XDG_CACHE_HOME` is on a full filesystem; the cache write fails **silently** | Point `XDG_CACHE_HOME` somewhere with room |
| `--play` exits immediately, or "requires a window" | Started with `--background`, or no `$DISPLAY` | Drop `--background`; under Xvfb see below |
| Renders on the CPU while reporting GPU | `scene.cycles.device = "GPU"` with no device *enabled* in the add-on preferences is a lie, not an error | Go through `Recorder._select_device`, which enables devices and reports what it actually got |
| A run's numbers differ from someone else's | User preferences and enabled add-ons leak into the result | Always `--factory-startup` |

## Headless play

`--play` needs a window; a container usually has no display. Xvfb supplies one:

```bash
"$AAAGF_TOOLS_DIR/envs/xvfb/bin/Xvfb" :99 -screen 0 1280x720x24 &
DISPLAY=:99 "$BLENDER" --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- --play
```

This is for smoke-testing that the input path works, not for playing: software
GL through a virtual framebuffer is not a frame rate anyone wants. A real
session wants a real display.

## GPU

Cycles device support is per build and per card, and being *listed* is not the
same as being usable. Ask Blender rather than `nvidia-smi`:

```bash
"$BLENDER" -b --factory-startup --python-expr "
import bpy
p = bpy.context.preferences.addons['cycles'].preferences
for backend in ('CUDA','OPTIX','HIP','ONEAPI'):
    try: p.compute_device_type = backend
    except TypeError: print(backend, 'not compiled in'); continue
    d = p.get_devices_for_type(backend)
    print(backend, [x.name for x in d] or 'compiled in, no devices')"
```

On the reference host (2x H100 PCIe, driver 550.144.03) this prints both cards
under **CUDA** and *"compiled in, no devices"* under OPTIX. That is not a driver
problem: OptiX needs the ray-tracing cores a Hopper compute card does not have.

Pass the backend through `--device CUDA`. Whether it is worth it depends on how
much work a frame is — at 960x540/16 spp a GPU is barely ahead of the CPU, at
1920x1080/128 spp it is about 3x. `Recorder.configure_render` sets
`use_persistent_data`, without which the per-frame scene upload dominates and a
GPU is *slower* than the CPU on small frames.

## Verify

A ladder, so a failure says which layer broke:

```bash
"$BLENDER" --version                                    # 1. loader + libs
"$BLENDER" -b --factory-startup --python-expr "import bpy; print(bpy.app.version_string)"
python -c "import sys; sys.path.insert(0,'.'); import engine_adapters.blender.game"  # 3. import only

# 4. end to end, no render: writes demo_outputs/events.json in a few seconds
"$BLENDER" -b --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- \
    --out-dir /tmp/aaagf_check --no-render
```

Step 3 is expected to work with no Blender at all — the package is import-safe so
that the launcher and `test/` can read its constants on a bare Python.

Step 4 needs `engine_adapters/blender/examples/`. Without it, the runtime is
installed correctly but has no mechanic to run.

## Assets are optional

The 3D assets the specs name are **purely additive**. With
`$BLENDER_ASSET_ROOT` empty or absent, a run logs one
`[assets] no model at /Library/...` per missing reference, falls back to
primitives, and produces a byte-identical `events.json`. Measured, not assumed:
that invariant is what lets the visual layer change without invalidating a
generated mechanic. So a setup that renders grey boxes is not broken — it is a
setup without assets, and the gameplay it reports is the same gameplay.
