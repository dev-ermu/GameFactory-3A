# pipeline/

Full-chain runners, organized by function. Each task directory contains two
entry points:

- **`run.py`** — generation only (demo / production)
- **`eval.py`** — evaluation only (benchmark scoring)

Contracts and a GPU-free conformance checker live in
`agent_skills/develop_harness/pipeline_require.md`.

## Structure

```
pipeline/
├── common/                                  # Shared, task-agnostic helpers
│   └── paths.py                             #   single source of truth for all I/O paths
│
├── assets_gen/                              # Asset generation tasks
│   ├── gen_3d_object/{run.py, eval.py}      #   image / text → 3D object
│   ├── gen_tpose_image/{run.py, eval.py}    #   character image → T-pose RGBA
│   ├── gen_3d_scene/{run.py, eval.py, render.py}  # image / footage → scene mesh
│   ├── gen_motion/{run.py, eval.py}         #   text or downloaded clip + skeleton → animation
│   ├── gen_cg_video/{run.py, eval.py}       #   text / frame → CG video
│   └── gen_audio/{run.py, eval.py}          #   text / reference → dialogue or game SFX
│
```

An end-to-end game slice has no runner of its own: the agent orchestrates the
task runners above by following `agent_skills/setting_overview.md`. The
`pipeline` task kind stays registered in `common/paths.py` so slice artifacts and
`pipeline_task.jsonl` inputs keep a stable location.

## Public asset-generation API

Each implemented `pipeline/assets_gen/<task>/run.py` exposes the same lifecycle:

1. `load_*()` loads or reuses each required model slot.
2. `make_operator()` injects those loaded models into the task Operator.
3. `generate(inp, operator)` generates one asset and returns its result dict.
4. `run_from_jsonl(...)` batch-drives the same `generate()` function.

`generate()` does **not** load models or construct an Operator. Callers that
already manage loaded models may use the lower-level `operator.run(inp)` API.

### T-pose image example

```python
from pipeline.assets_gen.gen_tpose_image.run import (
    generate,
    load_gen_model,
    load_mask_model,
    make_operator,
)

gen_model = load_gen_model("Qwen/Qwen-Image-Edit-2511")
mask_model = load_mask_model("briaai/RMBG-1.4", model_type="rmbg")
operator = make_operator(gen_model, mask_model, run_id="default")

result = generate(
    {
        "game_id": "gameA_cyberpunk_shooter",
        "task_id": "hero_tpose",
        "image_path": "path/to/character.png",
        "description": "Full-body character in a neutral T-pose.",
        "seed": 42,
    },
    operator,
)
print(result["tpose_rgba_path"])
```

The concrete wrappers used by this runner live at
`models/gen_image/qwen_edit_model.py` and
`models/tools/image_matting/{rmbg_model.py,depth_anything_model.py}`. Call
`unload()` on loaded models when they are no longer needed.

## Responsibilities

### `run.py`
1. Load required models (from `models/`)
2. Instantiate operator (from `operators/`)
3. Take a single input → produce a single output artifact
4. No scoring, no metric computation

### `eval.py`
1. Iterate the test set from `test_data/test_samples/<game>/<task>/*_tasks.jsonl`
   (or the cross-game `*_collect.jsonl`)
2. Resolve artifacts from an existing `game_id` / `run_id`; never import
   `run.py`, load generation models, or trigger generation
3. Invoke `operators/<task>/metrics/` on each existing output
4. Write per-task scores to `paths.eval_output_dir(...)` and the aggregate to
   `paths.eval_summary_path(...)`

## Paths — always via `common/paths.py`

Outputs are grouped **per generated game project**, mirroring the test set.
Never concatenate an output path by hand:

```python
from pipeline.common import paths

paths.resolve_tasks_path(kind, args.tasks, args.game)   # inputs
paths.iter_tasks(tasks_path, game_filter=args.game)     # (task, game_id) pairs
paths.task_output_dir(game, kind, task_id, run_id)      # artifacts
paths.eval_output_dir(game, kind, task_id, run_id)      # scores
paths.write_results_summary(results, kind, run_id)      # per-game summaries
```

Adding a task kind means one entry in each of the four tables in `paths.py`
(`TASK_LAYER`, `TASK_INPUT_DIR`, `TASK_JSONL`, `TASK_COLLECT_JSONL`) — there is
no other registration point.

## Standard CLI flags

Every `run.py` exposes the same knobs:

| Flag | Default | Meaning |
|------|---------|---------|
| `--game <game_id>` | `None` | Restrict to one game project (and prefer its own `*_tasks.jsonl`) |
| `--tasks <jsonl>`  | `None` | Explicit task list, overrides the `--game` lookup |
| `--run-id <name>`  | `default` | Run directory name; `auto` for a timestamp |
| `--out-dir <dir>`  | `None` | Legacy flat output; bypasses the per-game layout |
| `--device`         | `cuda` | |

## Convention

```python
# pipeline/assets_gen/gen_3d_object/run.py
TASK_KIND = "3d_object"

def load_model(ckpt, device="cuda", **kw): ...
def make_operator(model, output_dir=None, run_id=..., default_game_id=None): ...
def generate(inp: dict, operator) -> dict: ...
def run_from_jsonl(tasks_path, operator, game_filter=None) -> list[dict]: ...

# pipeline/assets_gen/gen_3d_object/eval.py
# Resolve artifacts for an existing game_id/run_id and score them.
# Do not import run.py or invoke generate().
```

These five names are the generation-runner API — callers and `test/` import
them. `eval.py` remains independent and reads existing artifacts only.
