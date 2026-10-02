# develop_harness

Development harness for the **asset-generation chain** — `<REPO_PATH>/models/` → `<REPO_PATH>/operators/`
→ `<REPO_PATH>/pipeline/`. Read this before adding or modifying any asset task.

It exists because the three layers are only useful if they agree on their
contracts. This directory pins those contracts down; the runnable counterpart
lives in `<REPO_PATH>/tests/harness/` and lets you check a chain **without a GPU and without
downloading weights**.

Paths are written from the repository root as `<REPO_PATH>/...`; see the Path
convention section of `<REPO_PATH>/agent_skills/setting_overview.md`. Shell
commands in fenced code blocks are repo-root-relative — run them with
`<REPO_PATH>` as the working directory.

## Contents

| File | Purpose |
|------|---------|
| `README.md` | This file — the workflow (SOP) and layering rules |
| `model_require.md` | Contract a `<REPO_PATH>/models/` wrapper must satisfy |
| `api_model_require.md` | **R9** — what changes when the model is a closed-source cloud API |
| `operatar_require.md` | Contract an `<REPO_PATH>/operators/` operator must satisfy |
| `pipeline_require.md` | Contract a `<REPO_PATH>/pipeline/*/run.py` + `eval.py` must satisfy |

Executable part (under `<REPO_PATH>/test/`, where code belongs):

| File | Purpose |
|------|---------|
| `<REPO_PATH>/tests/harness/stubs.py` | Fake models + fixtures — run any chain on CPU in milliseconds |
| `<REPO_PATH>/tests/harness/smoke.py` | End-to-end chain run with stub models, asserts the output layout |

## The three layers

```
models/<family>/<model_name>_model.py        Layer 1 — "how to talk to one model"
        │                          knows: weights, dtype, device, its own API
        │                          knows NOT: tasks, jsonl, output paths, games
        ▼
operators/<task>/operator.py      Layer 2 — "how to turn one task dict into artifacts"
        │   └── funcs/             knows: task semantics, artifact names, meta
        │   └── metrics/           knows NOT: which concrete model, argparse, jsonl
        ▼
pipeline/assets_gen/<task>/       Layer 3 — "how to run a batch and score it"
    run.py / eval.py               knows: argparse, ckpt resolution, jsonl, summaries
                                   knows NOT: model internals, artifact byte layout
```

**The one rule that keeps this honest:** dependencies point *downward only*.
A model never imports an operator; an operator never imports a `run.py`.
Cross-layer wiring happens exactly once — in `run.py`'s `make_operator()`.

## Workflow — adding a new asset task

Work top-down through the contracts, bottom-up through the code.

### 1. Register the task kind

Add the new kind to the four tables in `<REPO_PATH>/pipeline/common/paths.py`:
`TASK_LAYER`, `TASK_INPUT_DIR`, `TASK_JSONL`, `TASK_COLLECT_JSONL`.
Nothing else in the repo hardcodes a path, so this is the only registration point.

### 2. Model wrapper — `models/<family>/<model_name>_model.py`

Follow `model_require.md`. Reference implementations:
`<REPO_PATH>/models/gen_3d_object/trellis_2_model.py` (generation),
`<REPO_PATH>/models/tools/image_matting/rmbg_model.py` (tool model, inherits `BaseToolModel`).

### 3. Operator — `operators/<task>/operator.py` (+ `funcs/`)

Follow `operatar_require.md`. Reference: `<REPO_PATH>/operators/gen_tpose_image/`
(operator + a multi-step `funcs/gen_tpose_image.py`).

Put real algorithm steps in `funcs/` — one file per logical step, pure functions
taking and returning PIL / numpy / paths. The operator itself should read as a
short script: resolve inputs → call funcs → save artifacts → return a dict.

### 4. Runner — `pipeline/assets_gen/<task>/run.py`

Follow `pipeline_require.md`. Reference:
`<REPO_PATH>/pipeline/assets_gen/gen_3d_object/run.py`. Copy its structure verbatim; the
five module-level functions (`load_*`, `make_operator`, `generate`,
`run_from_jsonl`, `main`) are the generation-runner API; callers and `<REPO_PATH>/test/`
import them by name. `eval.py` stays independent and reads existing artifacts.

### 5. Test data

Add the task lines to both the per-game
`<REPO_PATH>/test_data/test_samples/<game>/<TaskDir>/<kind>_tasks.jsonl` and the cross-game
`<kind>_collect.jsonl`. Every line needs `game_id` and `task_id`.

### 6. Register a stub, then verify — no GPU needed

Add an entry to `STUB_OPERATOR_KWARGS` (and `OPERATOR_LOCATION`) in
`<REPO_PATH>/tests/harness/stubs.py`, then:

```bash
pip install pillow numpy scipy          # the harness needs nothing else
python tests/harness/smoke.py --kind <new_kind>
```

`smoke.py` asserts the artifacts land exactly where `paths.py` promises, that
`meta.json` is written, that legacy flat mode is unchanged, and that summaries are
grouped per game project.

Then, on a GPU box, the real integration test:

```bash
python tests/test_<task>.py
```

## Output layout — never hand-build a path

Every artifact is addressed by `(game_id, run_id, task_kind, task_id)` and lives
under one root that mirrors the test set:

```
test_data/outputs/<game_id>/<run_id>/assets/<task_kind>/<task_id>/
```

Always go through `<REPO_PATH>/pipeline/common/paths.py`:

```python
from pipeline.common import paths

paths.resolve_tasks_path(kind, args.tasks, args.game)   # inputs
paths.task_output_dir(game_id, kind, task_id, run_id)   # artifacts
paths.eval_output_dir(game_id, kind, task_id, run_id)   # scores
paths.write_results_summary(results, kind, run_id)      # per-game summaries
```

`grep -rn "outputs/" operators/ models/` must stay empty — a literal output path
anywhere outside `paths.py` is a bug.

## Backward compatibility

Operators are consumed by `run.py`, `eval.py` and `<REPO_PATH>/test/`. When changing one:

- **Never remove or rename a returned dict key.** Add keys; don't repurpose them.
- **Never change the meaning of an existing constructor argument.** New behaviour
  goes behind a new argument with a default that reproduces the old behaviour.
  Example: `Gen3DObjectOperator(output_dir=...)` still writes the flat
  `<output_dir>/<task_id>.glb`; the per-game layout only activates when
  `output_dir` is omitted.
- `<REPO_PATH>/tests/harness/smoke.py` exercises **both** modes, so a regression in the legacy
  path fails the smoke run.

## Anti-patterns

| Don't | Do |
|-------|-----|
| `argparse` inside an operator | keep CLI in `run.py` |
| operator constructs a model | inject the loaded model |
| model writes to `<REPO_PATH>/test_data/outputs/` | model returns data; operator saves it |
| `os.path.join("outputs", ...)` | `paths.task_output_dir(...)` |
| `torch` imported at module top-level of an operator | import inside the function |
| evaluation imports `run.generate()` or loads generation models | resolve and score existing artifacts only |
| `except Exception: pass` around inference | let it fail with the real traceback |

