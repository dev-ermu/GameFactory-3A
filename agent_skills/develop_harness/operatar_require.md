# operatar_require.md — contract for `operators/`

> Filename keeps the spelling used in the repo skeleton. Rename with
> `git mv operatar_require.md operator_require.md` if you want it fixed —
> nothing imports it by name.

An **operator** turns *one task dict* into *artifacts on disk*. It owns task
semantics (prompts, step order, artifact naming, metadata) and is deliberately
**model-agnostic**: any wrapper satisfying the expected method signature is
injected in.

Reference implementations: `<REPO_PATH>/operators/gen_3d_object/` (single-call),
`<REPO_PATH>/operators/gen_tpose_image/` (multi-step with `funcs/`).

---

## Directory layout

```
operators/<task>/
├── __init__.py
├── operator.py       # the class — Gen<Task>Operator
├── funcs/            # decoupled algorithm steps, one file per logical step
└── metrics/          # task-specific evaluation, exposed by `operator.eval()`
```

`metrics/` is co-located on purpose: scoring logic is tightly coupled to that
operator's artifact layout.

---

## R1 — Hard rules

| # | Rule | Why |
|---|------|-----|
| R1.1 | **No imports from `<REPO_PATH>/pipeline/`** except `pipeline.common.paths`, and that one **inside a method**, not at module top level. | Keeps the layer boundary; avoids import cycles. |
| R1.2 | **Never load a model.** Models arrive fully loaded via the constructor. | Lets `run.py` load once and reuse across a batch, and lets tests inject stubs. |
| R1.3 | **No `argparse`, no env-var reading, no `sys.exit`.** | CLI belongs to `run.py`. |
| R1.4 | **Never hardcode an output path.** Use `paths.task_output_dir(...)`. | One source of truth for the layout. |
| R1.5 | **No `try/except` swallowing inference errors.** Let it raise with the real traceback. | A silent partial result is worse than a crash. |
| R1.6 | Heavy imports (`torch`, `scipy`, the `funcs/` module) go **inside** `run()`. | The module must import on a CPU box with no weights. |

## R2 — Constructor

```python
def __init__(
    self,
    model: Any,                          # or gen_model / mask_model / ...
    output_dir: Optional[str] = None,    # legacy flat mode
    run_id: str = "default",
    default_game_id: Optional[str] = None,
):
```

| # | Rule |
|---|------|
| R2.1 | Loaded model objects are the **leading positional** arguments. |
| R2.2 | Auxiliary models are `Optional` and default to `None`; the operator degrades gracefully (see `mask_model` — without it the T-pose stays opaque). |
| R2.3 | Do **no** work beyond storing args and `mkdir`. No inference, no downloads. |
| R2.4 | Every arg after the models has a default, so `Op(model)` alone is valid. |
| R2.5 | Store `run_id` / `default_game_id`; they are needed per-task, not per-batch. |

### Output mode resolution

Two modes, selected by whether `output_dir` was supplied:

| `output_dir` | Mode | Path |
|---|---|---|
| `None` (default) | **per-game** | `paths.task_output_dir(game_id, kind, task_id, run_id)`, fixed artifact filenames (`model.glb`, `tpose_fg.png`), plus `meta.json` |
| a string | **legacy flat** | `<output_dir>/<task_id>.<ext>` — byte-for-byte the historical behaviour, no `meta.json` |

Isolate this in one private helper (`_resolve_out_path`) so `run()` stays linear.
Never branch on the mode more than once.

## R3 — `run(inp: dict) -> dict`

The single public entry point. Exactly one task in, one dict out.

| # | Rule |
|---|------|
| R3.1 | Signature is exactly `run(self, inp: dict) -> dict`. No extra positional args. |
| R3.2 | Read every field with `inp.get(key, default)`. Only the primary input (image / prompt / motion) may be mandatory. |
| R3.3 | `task_id` defaults to `f"task_{int(time.time())}"` — never crash on a missing one. |
| R3.4 | `game_id` comes from `paths.infer_game_id(inp, fallback=self.default_game_id)`. Never parse it out of a path yourself. |
| R3.5 | `seed` defaults to `42`. |
| R3.6 | Resolve relative input paths against the repo root — a jsonl path must work from any CWD. |
| R3.7 | Measure wall time around the model call only, not around I/O: `t0 = time.time()` … `elapsed = time.time() - t0`. |
| R3.8 | Write `meta.json` via `paths.write_task_meta()` — per-game mode only. |
| R3.9 | Also provide `run_batch(self, inputs: list[dict]) -> list[dict]`, which is just a list comprehension over `run`. |
| R3.10 | Provide `eval(self, result: dict, task: dict) -> dict`; it delegates to `metrics.evaluate(result, task)`, reads existing artifacts only, and is never called by `run()`. |

### Return dict

Required keys:

| Key | Type | Note |
|-----|------|------|
| `task_id` | `str` | echoed back |
| `elapsed_sec` | `float` | `round(..., 2)` |
| `<artifact>_path` | `str` | one per artifact, e.g. `glb_path`, `tpose_rgba_path` |
| `game_id` | `str` | `""` in legacy flat mode |
| `task_kind` | `str` | the module-level `TASK_KIND` constant |
| `output_dir` | `str` | directory holding all artifacts of this task |

**Compatibility:** these keys are consumed by `run.py`, `eval.py` and `<REPO_PATH>/test/`.
Adding keys is safe. Removing, renaming or repurposing one is a breaking change —
`<REPO_PATH>/tests/harness/smoke.py` will fail.

Optional artifacts use `None`, not a missing key (see `tpose_rgb_path`).

## R4 — Module-level constants

```python
TASK_KIND = "3d_object"      # must be registered in pipeline/common/paths.py
GLB_FILENAME = "model.glb"   # per-game-mode artifact filenames
```

Artifact filenames are constants, never f-strings built at the call site: in
per-game mode `task_id` is already the directory, so files must be **generic**
(`model.glb`, not `sword_001.glb`). That keeps downstream globbing trivial.

## R5 — `funcs/`

| # | Rule |
|---|------|
| R5.1 | One file per logical step; the public function shares the file's name. |
| R5.2 | Pure-ish: takes PIL / numpy / primitives + injected models, returns PIL / numpy. **No disk writes.** |
| R5.3 | Private helpers prefixed `_`; only the pipeline function is public. |
| R5.4 | Prompt templates live here as module constants (see `TPOSE_PROMPT`), never in `operator.py`. |
| R5.5 | `return_intermediate: bool = False` when intermediates are useful — return a dict of named stages when `True`. |
| R5.6 | Model-flavour dispatch (mask vs. depth) is absorbed **here**, not in the model and not in the operator. |
| R5.7 | Keep backwards-compatible aliases when renaming a parameter (see `depth_model` → `mask_model`). |

## R6 — `metrics/`

| # | Rule |
|---|------|
| R6.1 | Expose `evaluate(result: dict, task: dict) -> dict[str, float]`. |
| R6.2 | Input is the operator's return dict + the original task dict — read artifacts from `result["output_dir"]`. |
| R6.3 | Return flat, JSON-serializable `{metric_name: float}`. No nesting, no numpy scalars. |
| R6.4 | Never regenerate anything. Metrics only read. |
| R6.5 | A metric needing a heavy model takes it as an injected argument, same as an operator. |
| R6.6 | Missing / corrupt artifact → return the failing metric as `0.0` plus an `"error"` string key, don't raise. |

## R7 — Docstring template

```python
"""
operators/<task>/operator.py

Gen<Task>Operator — accepts a loaded <model kind> and processes an input dict
into <artifact description>.

The operator is intentionally model-agnostic: inject any object implementing
<the expected signature>.

Output layout — two modes, chosen by whether `output_dir` is given:
  * per-game (default):  test_data/outputs/<game_id>/<run_id>/assets/<kind>/<task_id>/
  * flat (legacy):       <output_dir>/<task_id>.<ext>

Usage:
    ...
"""
```

## R8 — Checklist

- [ ] `TASK_KIND` set and registered in `<REPO_PATH>/pipeline/common/paths.py`
- [ ] Models injected, never loaded inside
- [ ] `output_dir=None` → per-game layout; `output_dir="..."` → unchanged legacy behaviour
- [ ] `run(inp: dict) -> dict` and `run_batch(...)` present
- [ ] Return dict has `task_id`, `elapsed_sec`, `<artifact>_path`, `game_id`, `task_kind`, `output_dir`
- [ ] No existing return key removed or renamed
- [ ] `meta.json` written in per-game mode
- [ ] Algorithm steps in `funcs/`, prompts as constants there
- [ ] `metrics/evaluate(result, task)` and `operator.eval(result, task)` present (or an explicit TODO)
- [ ] No `argparse`, no model loading, no literal output path
- [ ] Module imports cleanly on CPU with no weights installed
- [ ] Stub registered in `<REPO_PATH>/tests/harness/stubs.py` (`STUB_OPERATOR_KWARGS` + `OPERATOR_LOCATION`)
- [ ] `python tests/harness/smoke.py --kind <kind>` passes (covers **both** output modes)
