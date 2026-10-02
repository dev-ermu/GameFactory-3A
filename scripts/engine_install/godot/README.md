# Automated Godot 4 installation

This directory is the non-interactive entry point an AI agent should use. Do
not begin with project creation or asset import: first discover/reuse or install
the engine, validate the exact binary, and consume the emitted configuration.

The default is pinned to Godot `4.5.1-stable`; no “latest” lookup can silently
change a run.

## One-command installation

Linux or macOS:

```bash
scripts/engine_install/godot/install.sh --json > godot-install-result.json
```

Windows Command Prompt:

```bat
scripts\engine_install\godot\install.cmd --json > godot-install-result.json
```

The installer uses only Python's standard library and requires Python 3.14 or
newer. The repository's Godot tests are executed on Python 3.14 as a
compatibility gate.

A successful JSON result contains `ok=true`, `action`, exact version/platform,
official URLs, SHA-512, validated executable, PATH shim, and configuration-file
paths. Treat any nonzero exit or `ok=false` as a hard failure.

## AI automation sequence

1. Run `install.sh --dry-run --json` (or `install.cmd`) and record the resolved
   release asset, target architecture, official URL, and paths.
2. Run the installer without `--dry-run`. It first validates an explicit
   `--executable`, configured `A3GAME_GODOT_*` executable, or `godot4`/`godot`
   on PATH. A matching build is reused; a different build does not satisfy the
   pinned request.
3. Parse JSON and require `ok=true` plus `verified_version` matching the exact
   requested version. Do not infer success from a downloaded archive.
4. Source the emitted `.env` on POSIX or call the emitted `.cmd` on Windows, or
   directly set `A3GAME_GODOT_EXECUTABLE` to the returned executable.
5. Set `A3GAME_GODOT_PROJECT`, then use the adapter CLI to create/validate the
   project, import assets, run tests, and launch.

Example with isolated, reviewable paths:

```bash
scripts/engine_install/godot/install.sh \
  --version 4.5.1 \
  --install-root "$PWD/.tools/godot" \
  --cache-dir "$PWD/.cache/godot" \
  --bin-dir "$PWD/.tools/bin" \
  --config-dir "$PWD/.tools/config" \
  --json
export A3GAME_GODOT_EXECUTABLE="$PWD/.tools/bin/godot4"
export A3GAME_GODOT_PROJECT=/projects/MyGame
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  create-project --name MyGame
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  validate-project
```

## Installer guarantees

| Requirement | Behavior |
| --- | --- |
| Non-interactive | No prompts, GUI, package manager, elevated permission, or shell-profile edit |
| Version selection | Exact stable `4.x[.y]`; default `4.5.1`; `latest`, prereleases, and non-4 versions fail |
| Architecture | Linux x86-64/x86-32/arm64/arm32; macOS universal on Intel/Apple Silicon; Windows x64/x86/arm64 |
| Source | `https://github.com/godotengine/godot/releases/download/<version>-stable/` official release assets |
| Integrity | Downloads official `SHA512-SUMS.txt`, requires exactly one matching entry, hashes the full archive, and fails closed on absence/mismatch |
| Extraction | Rejects absolute/traversing/duplicate paths, symbolic links, and special nodes before extracting |
| Atomicity | Extracts and probes a sibling staging tree, publishes by rename, and restores a preserved prior target if replacement fails |
| Reuse | A managed install is reused only when its schema/version/asset/executable manifest matches and `godot --headless --version` passes |
| Existing binary | `--executable`, environment, then PATH are probed in order; exact requested version only |
| PATH/config | Creates a user-writable `godot4` shim and JSON plus `.env`/`.cmd`; never edits a login profile |
| Post-install gate | Runs the installed executable and requires the exact requested Godot 4 version |

`--force` replaces only the fully resolved version/platform install target and
PATH shim. It never rewrites other versions. `--version 4.6.0` installs beside
`4.5.1`; this is the upgrade path. Rerunning the same command is idempotent and
reports `action=reused-managed`.

Use `--no-path-shim` when callers will consume only the absolute executable.
Use `--dry-run --json` to inspect resolution without network or filesystem
writes. Run `install.py --help` for all path/timeout options.

## Continue through the adapter

This directory deliberately contains only the cross-platform installer. Project
and gameplay operations belong to `engine_adapters.godot`; keeping them behind
one CLI avoids making an agent discover and read a separate shell/batch wrapper
for every operation.

After installation, use the adapter directly on Linux, macOS, or Windows:

```bash
export A3GAME_GODOT_EXECUTABLE=/absolute/path/to/godot4
export A3GAME_GODOT_PROJECT=/projects/MyGame

python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  create-project --name MyGame
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  install-framework
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  import-asset --source-json generated-asset.json --asset-type prop
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" launch-game
```

On Windows, replace `python3` with `python` or `%A3GAME_PYTHON%`. The JSON file
passed to `--source-json` is a repository task identity with `game_id`, `run_id`,
`task_kind`, `task_id`, and optional `artifact_key`; it is not an arbitrary host
path. For the legacy direct-file compatibility workflow, call
`scripts/import_generated_asset.py --engine godot` explicitly.

Builds require a project-owned preset in `export_presets.cfg`:

```bash
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" build \
  --preset "Linux/X11" --output builds/game.x86_64
```

Use a new output for the first adapter-managed export. Later replacement is
allowed only while the signed ownership manifest and existing output content
still match; altered/unmanaged outputs, linked paths, and protected project
inputs fail before commit.
