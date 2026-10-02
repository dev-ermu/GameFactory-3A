# model_require.md — contract for `models/`

A file under `<REPO_PATH>/models/` is a **thin wrapper around exactly one model**. It knows
weights, dtype, device and that model's native API. It knows nothing about
tasks, jsonl files, game projects or output directories.

> Required interface: every model implements `__init__()` and `infer()`.
> One file per model: `<REPO_PATH>/models/<family>/<model_name>_model.py`, class `<Name>Model`.
> Model-specific helpers belong in `<REPO_PATH>/models/<family>/<model_name>_utils/`.

> **Wrapping a closed-source cloud API** (Tripo, Meshy, Rodin, Kling, …)? This
> contract assumes local weights. Read `api_model_require.md` — it adds **R9**,
> which overrides R2.1–R2.3, R3.3/R3.4, R3.6 and R4 for remote models, and
> pins down how a deviation must be marked.

Examples:
- generation: `<REPO_PATH>/models/gen_3d_object/trellis_2_model.py`, `<REPO_PATH>/models/gen_image/qwen_edit_model.py`
- tool model: `<REPO_PATH>/models/tools/image_matting/rmbg_model.py` (inherits `BaseToolModel`)

---

## R1 — Hard rules

| # | Rule | Why |
|---|------|-----|
| R1.1 | **No imports from `<REPO_PATH>/operators/` or `<REPO_PATH>/pipeline/`.** | Dependencies point downward only. |
| R1.2 | **Never construct an output path.** Return in-memory data (PIL / numpy / tensor / trimesh). | The operator owns artifact placement. |
| R1.3 | **No `argparse`, no `if __name__ == "__main__"` business logic.** | CLI belongs to `run.py`. |
| R1.4 | **No task semantics.** No `task_id`, no `game_id`, no prompt templates for a specific task. | Prompts belong to `<REPO_PATH>/operators/<task>/funcs/`. |
| R1.5 | Heavy imports (`torch`, `diffusers`, vendored repos) go **inside** `__init__` / `_load()` when they are optional, so the module can be imported on a CPU box. | `<REPO_PATH>/tests/harness/smoke.py` must import the chain without weights. |
| R1.6 | Fail fast with an **actionable** message when an environment prerequisite is missing. | Refer to the `o_voxel` check in `trellis_2_model.py`. |

### R1.2 — the one exception

A `infer_and_save(..., output_path)` convenience method is allowed **only** when
the underlying library can serialize more efficiently than a round-trip through
memory (e.g. TRELLIS.2 → GLB with a texture atlas). Requirements:

- the path is passed **in** by the caller — never derived inside the model;
- `mkdir(parents=True, exist_ok=True)` on the parent;
- returns the path as `str`;
- a memory-returning `infer()` exists alongside it.

### R1.2.1 — optional intermediate observation

Optional only; disabled by default. A model may expose
`observe_intermediates=False` and/or `on_intermediate=None` to return in-memory
stage metadata or previews for debugging/supervision. It must not compute, print,
or save intermediates unless explicitly enabled; Operators/Pipelines own display,
persistence, and approval.

---

## R2 — Constructor

```python
def __init__(self, model_path: str | list[str], device: str = "cuda", **model_specific):
```

| # | Rule |
|---|------|
| R2.1 | First positional arg is the weight location — a local path or HuggingFace repo id; use `list[str]` when one wrapper loads multiple models. |
| R2.2 | Name it `model_path`. |
| R2.3 | `device: str = "cuda"`, and `"cpu"` must be honoured. |
| R2.4 | Store every constructor arg on `self` before loading, so `unload()`/`load()` can round-trip. |
| R2.5 | Any extra arg has a working default. `Model(path)` alone must be valid. |

## R3 — Inference

| # | Rule |
|---|------|
| R3.1 | One public inference entry point: **`infer()`**. |
| R3.2 | Takes the input **object**, not a path. `Image.Image`, `np.ndarray`, `str` prompt — never `"path/to/x.png"`. |
| R3.3 | Accept `seed: int = 42` whenever the model is stochastic, and actually seed the generator. |
| R3.4 | Deterministic for a fixed `(input, seed)` on a fixed device. |
| R3.5 | Return type is documented in the docstring and stable. Don't return a bare tuple. |
| R3.6 | Wrap inference in `torch.no_grad()` / `torch.inference_mode()`. |
| R3.7 | Do not print progress except behind an explicit `verbose` flag. |

## R4 — Lifecycle

| # | Rule |
|---|------|
| R4.1 | Provide `unload()` when the model holds >1 GB of VRAM: move to CPU, `del`, `gc.collect()`, `torch.cuda.empty_cache()`. |
| R4.2 | `unload()` is idempotent — safe to call twice, and after a failed load. |
| R4.3 | If `unload()` exists, calling `infer()` afterwards must transparently reload. |
| R4.4 | Support `lazy=True` (defer weight loading) for tool models — `BaseToolModel` already does this. |

## R5 — Tool models specifically

Anything auxiliary (depth, segmentation, matting, pose, keypoints) goes in
`<REPO_PATH>/models/tools/<group>/` and **must** subclass `BaseToolModel`
(`<REPO_PATH>/models/tools/base.py`), overriding only:

```python
def _load(self) -> None:        # weights + processors onto self.device
def infer(self, image: Image.Image, **kwargs) -> Any:
```

You get `__init__(model_path, device, lazy)`, `_ensure_loaded()`, `__call__`
and `unload()` for free.

| # | Rule |
|---|------|
| R5.1 | `infer()` starts with `self._ensure_loaded()`. |
| R5.2 | `infer()` accepts an RGB `PIL.Image` and normalizes internally (`image.convert("RGB")`). |
| R5.3 | Return a plain `np.ndarray` (`float32`), **at the original image resolution** — resize back after inference. |
| R5.4 | Document the value range in the docstring. Masks → `[0, 1]`. Depth → state whether normalized. |
| R5.5 | Decorate with `@torch.no_grad()`. |
| R5.6 | Export the class from the group's `__init__.py` **and** `<REPO_PATH>/models/tools/__init__.py`. |
| R5.7 | Convenience helpers that return a PIL image (e.g. `remove_background()`) are welcome, but `infer()` stays the raw-array contract. |

## R6 — Swappability

Two wrappers used for the same operator slot must be interchangeable without the
operator changing. Concretely, `RMBGModel` and `DepthAnythingModel` both satisfy
`infer(PIL.Image) -> np.ndarray[H, W] float32`, which is why
`<REPO_PATH>/operators/gen_tpose_image/funcs/gen_tpose_image.py` can dispatch on class name
alone.

When adding a second backend for an existing slot:

1. match the existing signature and return type exactly;
2. if semantics genuinely differ (mask vs. depth), the **operator's `funcs/`**
   absorbs the difference — never the model;
3. add it to the candidate table in `<REPO_PATH>/models/README.md`.

## R7 — Docstring template

```python
"""
<Name>Model — <one line: what it wraps and what it produces>.

Reference: <paper / HF model card / repo URL>

<Any environment prerequisite: compiled extension, minimum VRAM, extra pip deps.>

Usage:
    from models.<family>.<model_name>_model import <Name>Model
    model = <Name>Model(model_path="<hf/repo-id>")
    out = model.infer(image, seed=42)
"""
```

Every public method documents `Args`, `Returns` and — for arrays — **shape and
value range**.

## R8 — Checklist

- [ ] One file, one model, named `<model_name>_model.py`; class named `<Name>Model`
- [ ] `<REPO_PATH>/models/<family>/__init__.py` exports it (tool models: both `__init__.py`s)
- [ ] `model_path` accepts a local path *and* a HF repo id
- [ ] `device="cpu"` works
- [ ] No import from `<REPO_PATH>/operators/` or `<REPO_PATH>/pipeline/`
- [ ] No output path constructed inside (or: `output_path` is an argument)
- [ ] `seed` accepted and honoured; same seed → same output
- [ ] `torch.no_grad()` / `inference_mode()` around inference
- [ ] `unload()` present and idempotent for large models
- [ ] Return shape / dtype / range documented
- [ ] Added to the table in `<REPO_PATH>/models/README.md`
- [ ] A matching stub exists in `<REPO_PATH>/tests/harness/stubs.py`, and
      `python tests/harness/smoke.py --kind <kind>` passes
