# test_data/outputs/

Single fixed output root — **organized per generated game project**, mirroring
`test_data/test_samples/`. Every evaluator (asset / code / full pipeline) reads
from here, right next to the test set it scored.

An artifact is uniquely addressed by `(game_id, run_id, task_kind, task_id)`.

## Layout

```
test_data/outputs/
└── <game_id>/                        ← one dir per game project, e.g. gameA_cyberpunk_shooter
    ├── latest -> <run_id>/           ← symlink to the most recent run
    └── <run_id>/                     ← "default", or a timestamp via `--run-id auto`
        ├── run_meta.json             ← ckpts · seeds · git sha · argv (reproducibility)
        ├── <task_kind>_results_summary.json
        │
        ├── assets/                   ← Layer A
        │   ├── tpose/<task_id>/      ← T-pose PNG · meta.json
        │   ├── 3d_object/<task_id>/  ← model.glb · meta.json
        │   ├── 3d_scene/<task_id>/
        │   ├── motion/<task_id>/
        │   ├── audio/<task_id>/      ← WAV · meta.json
        │   ├── cg_video/<task_id>/   ← video.mp4 · meta.json
        │   └── retarget/<task_id>/
        │
        ├── mechanic/<task_id>/       ← Layer B: engine project · demo_outputs/*.json · launch.sh
        ├── ui/<task_id>/             ← Layer C: UI code · screenshots/
        ├── pipeline/<task_id>/       ← end-to-end vertical slice
        │
        └── eval/
            ├── <task_kind>/<task_id>/    ← metrics.json · build.log · judge_log.json · reward.txt
            └── summary.json              ← aggregate over the whole run
```

## Why this shape

| Decision | Reason |
|---|---|
| **`<game_id>` first** | The benchmark is authored per game project. Same first axis on both sides means eval can join inputs↔outputs by path, and a finished game project ships as one directory. |
| **`<run_id>` second** | Keeps several attempts (different model, seed, prompt revision) side by side instead of overwriting. `latest` always points at the newest. |
| **`assets` / `mechanic` / `ui` layer dirs** | Matches the Layer A/B/C split used throughout the repo. Assets nest one level deeper by task type; mechanic and UI remain run-scoped game outputs, never root-level output directories. |
| **one directory per `task_id`** | An artifact rarely travels alone (GLB + preview + textures + `meta.json`). A directory avoids filename mangling like `<game>__<taskid>_tpose_fg.png`. |
| **`eval/` inside the run** | A score belongs to the exact run that produced it, never to "the game" in general. |
| **`meta.json` per task** | Records source input, seed and model, so an artifact stays self-describing after it leaves the repo. |

## Never hand-build these paths

Use `pipeline/common/paths.py` — the single source of truth:

```python
from pipeline.common import paths

out_dir = paths.task_output_dir("gameA_cyberpunk_shooter", "3d_object", "cyberpunk_sword_001")
ev_dir  = paths.eval_output_dir("gameA_cyberpunk_shooter", "3d_object", "cyberpunk_sword_001")
paths.write_results_summary(results, "3d_object", run_id)
```

`agent_skills/develop_harness/README.md` states the rule; `tests/harness/smoke.py`
asserts that artifacts really land where these helpers promise.

## Legacy flat mode

Passing `--out-dir` to a runner (or `output_dir=` to an operator) bypasses this
layout entirely and reproduces the historical flat naming
(`<out_dir>/<task_id>.glb`), without `meta.json`. It exists so older scripts keep
working; don't use it for benchmark runs.

## Relocating the root

Artifacts get large and are all git-ignored. To move the whole tree to a scratch
disk, no code change needed:

```bash
export AAAGF_OUTPUT_ROOT=/data/scratch/aaagf_outputs
```
