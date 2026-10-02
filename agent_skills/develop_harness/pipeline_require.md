# pipeline_require.md — contract for `pipeline/`

A pipeline directory exposes a small public generation API: `run.load_*()`
loads or reuses the required models, `run.make_operator()` injects them into the
Operator, and `run.generate(inp, operator)` generates one asset. `run.py`
batch-drives the same `generate()` entry point for Benchmark; `eval.py` only
scores existing artifacts.

> Scope: this contract applies to `<REPO_PATH>/pipeline/assets_gen/` only. The public API is
> `load_*()` → `make_operator()` → `generate(inp, operator)`; `run.py` batch
> execution and `eval.py` form the asset-generation Benchmark chain.
>
> For callers that already own loaded models, `operator.run(inp)` is the
> lower-level injected-model API.

```
pipeline/
├── common/paths.py                  # single source of truth for all I/O paths
└── assets_gen/<task>/
    ├── run.py                       # public `generate()` + Benchmark batch driver
    └── eval.py                      # Benchmark scoring only
```

Reference implementation: `<REPO_PATH>/pipeline/assets_gen/gen_3d_object/run.py`.

---

## R1 — Hard rules

| # | Rule | Why |
|---|------|-----|
| R1.1 | Runs correctly **from any CWD** — prepend the repo root to `sys.path` before importing anything local. | Users invoke it as `python pipeline/.../run.py`. |
| R1.2 | **Never build an output path.** Only `pipeline.common.paths`. | One source of truth. |
| R1.3 | `run.py` generates artifacts only; `eval.py` reads artifacts from an existing `run_id` and computes metrics only. | Clean split; evaluation never imports or triggers generation. |
| R1.4 | Every required module-level function must exist with the exact name. `<REPO_PATH>/test/` imports them. | They are an API, not style. |
| R1.5 | Model imports go **inside** `load_*()`, operator imports **inside** `make_operator()`. | So `--help` works without CUDA, and the smoke test can import the module. |
| R1.6 | Zero side effects at import time beyond `sys.path` and constants. | The module is imported by tests. |

## R2 — Required structure of `run.py`

```python
TASK_KIND = "3d_object"                       # registered in paths.py
DEFAULT_CKPT = "<hf/repo-id>"                 # one per model slot
DEFAULT_TASKS = paths.collect_jsonl(TASK_KIND)

def load_model(ckpt, device="cuda", **kw): ...        # one per model slot
def make_operator(model, output_dir=None,
                  run_id=paths.DEFAULT_RUN_ID,
                  default_game_id=None): ...          # the only wiring point
def generate(inp: dict, operator) -> dict: ...        # thin operator wrapper
def run_from_jsonl(tasks_path, operator,
                   game_filter=None) -> list[dict]: ...
def main(): ...
if __name__ == "__main__": main()
```

| # | Rule |
|---|------|
| R2.1 | One `load_<slot>_model()` per model the task needs (`load_gen_model`, `load_mask_model`, …). Each prints what it is loading. |
| R2.2 | `make_operator()` mirrors the operator's constructor 1:1 and passes arguments through unchanged. Do not invent defaults here. |
| R2.3 | `generate(inp, operator)` is a one-liner `return operator.run(inp)`. |
| R2.4 | `run_from_jsonl()` iterates via `paths.iter_tasks(tasks_path, game_filter=...)` — never open and `json.loads` the file by hand. |
| R2.5 | Log one line per task before running and one after, including `game_id`, `task_id` and `elapsed_sec`. |
| R2.6 | `main()` does argparse → load models → make operator → branch (single demo vs. batch) → write summaries. Nothing else. |

## R3 — Standard CLI flags

Identical across every task, so a user learns them once:

| Flag | Default | Meaning |
|------|---------|---------|
| `--ckpt` / `--gen-ckpt` / `--mask-ckpt` | env var, then `DEFAULT_*_CKPT` | weights; local path or HF repo id |
| `--game` | `None` | restrict to one game project; also the `default_game_id` fallback |
| `--tasks` | `None` | explicit jsonl, overrides the `--game` lookup |
| `--run-id` | `"default"` | run directory name; `"auto"` → `paths.new_run_id()` |
| `--out-dir` | `None` | legacy flat output; bypasses the per-game layout |
| `--device` | `"cuda"` | |
| `--image` / `--task-id` / task params | | single-demo mode, no jsonl |

| # | Rule |
|---|------|
| R3.1 | Checkpoint precedence is `CLI flag > env var > DEFAULT_CKPT`, expressed as `default=os.environ.get("<VAR>", DEFAULT_CKPT)`. |
| R3.2 | `--game`'s help string lists the known games via `paths.list_games()`. |
| R3.3 | Task-list resolution is `paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)` — explicit jsonl → the game's own `*_tasks.jsonl` → cross-game `*_collect.jsonl`. |
| R3.4 | Single-demo mode passes `game_id=args.game` so ad-hoc runs still land in a sane directory (`_scratch` when unset). |
| R3.5 | An empty result set prints a message and returns 0 — it is not an error. |

## R4 — Summaries

```python
if args.out_dir:                       # legacy flat mode
    Path(args.out_dir, "results_summary.json").write_text(...)
else:                                  # per-game mode
    paths.write_results_summary(results, TASK_KIND, run_id)
```

`write_results_summary()` groups results by `game_id` and, per game, writes
`<task_kind>_results_summary.json`, refreshes `run_meta.json` (ckpts, seeds, git
sha, argv) and repoints the `latest` symlink. Never write a global summary that
mixes games — it defeats the per-project layout.

## R5 — `eval.py`

```python
# Locate existing artifacts for (game_id, run_id, TASK_KIND, task_id).
# Score them through operator.eval(result, task).
```

| # | Rule |
|---|------|
| R5.1 | Read existing artifacts for the requested `--game` / `--run-id`; never import `run.py`, load generation models, or trigger generation. |
| R5.2 | Build the minimal result dict required by `operator.eval(result, task)` from the resolved artifact directory. |
| R5.3 | Per-task scores → `paths.eval_output_dir(game, kind, task_id, run_id)/metrics.json`. |
| R5.4 | Aggregate → `paths.eval_summary_path(game, run_id)`, including per-metric mean and the task count. |
| R5.5 | One task failing must not abort the sweep: record the error in that task's `metrics.json` and continue. |
| R5.6 | Accept the same `--game` / `--run-id` / `--tasks` flags as `run.py`. |

## R6 — Registering a task kind

`<REPO_PATH>/pipeline/common/paths.py` is the **only** registration point. Add one entry to
each of the four tables:

```python
TASK_LAYER["motion"]         = "assets"            # assets | mechanic | ui | pipeline
TASK_INPUT_DIR["motion"]     = "motion"            # dir under test_samples/<game>/
TASK_JSONL["motion"]         = "motion_tasks.jsonl"
TASK_COLLECT_JSONL["motion"] = "motion_gen_collect.jsonl"
```

Then `python tests/harness/smoke.py --kind motion` verifies that the tables, the
operator and the on-disk layout all agree.

## R7 — `tests/test_<task>.py`

| # | Rule |
|---|------|
| R7.1 | `unittest`; load models once in `setUpClass`. |
| R7.2 | Checkpoints from env vars, defaulting to HF repo ids. |
| R7.3 | Use `run_id="_test"` so the integration test never clobbers a real run. |
| R7.4 | Import `load_*` / `make_operator` / `run_from_jsonl` from `run.py` — never reconstruct the chain. |
| R7.5 | Assert: artifact exists, size is plausible, `elapsed_sec > 0`, the parent dir equals `paths.task_output_dir(...)`, and `meta.json` exists. |

## R8 — Checklist

- [ ] `TASK_KIND` set and registered in all four `paths.py` tables
- [ ] `sys.path` bootstrap present; runs from any CWD
- [ ] `load_*`, `make_operator`, `generate`, `run_from_jsonl`, `main` all present with exact names
- [ ] Model / operator imports are inside functions
- [ ] `--game`, `--tasks`, `--run-id`, `--out-dir`, `--device` all accepted
- [ ] Task iteration via `paths.iter_tasks`
- [ ] Summaries via `paths.write_results_summary` (per-game mode)
- [ ] `eval.py` reads existing artifacts only; it does not import `run.py` or trigger generation
- [ ] `python pipeline/assets_gen/<task>/run.py --help` works without CUDA
- [ ] `python tests/harness/smoke.py --kind <kind>` passes
