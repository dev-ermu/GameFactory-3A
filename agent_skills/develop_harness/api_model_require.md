# api_model_require.md — supplement to `model_require.md` for closed-source cloud APIs

`model_require.md` was written for **local-weight** models: you own the weights,
the device and the process. A wrapper around a **closed-source cloud API**
(Tripo, Meshy, Rodin, ElevenLabs, Kling, …) breaks several of its assumptions —
there is no weight path, no device, no `torch`, inference is a remote *task*
rather than a call, every call costs money, and the network fails routinely.

This file adds **R9** on top of `model_require.md`. Everything in R1–R8 that is
not explicitly overridden here still applies, in particular R1.1 (no imports from
`<REPO_PATH>/operators/` or `<REPO_PATH>/pipeline/`), R1.2 (never construct an output path), R1.4 (no task
semantics) and R6 (swappability).

> Read `<REPO_PATH>/models/gen_3d_object/tripo_model.py` as the reference implementation, and
> `<REPO_PATH>/models/common/cloud_api.py` for the shared HTTP / retry / cache plumbing.

---

## R9 — Cloud-API wrappers

| # | Rule | Rationale |
|---|------|-----------|
| **R9.1** | `model_path` carries a **model version identifier** (`"v3.1-20260211"`, `"meshy-6"`), not a weight location. Keep the argument name and position — the operator must not need a branch. | Overrides R2.1 / R2.2. |
| **R9.2** | `device` is accepted **for interface parity and ignored**. `device="cpu"` must not raise. State this in the docstring. | Overrides R2.3. |
| **R9.3** | No `@torch.no_grad()` / `torch.inference_mode()`. `torch` must not be imported. | Overrides R3.6 / R5.5. |
| **R9.4** | `unload()` exists, is idempotent and closes the HTTP session. It never invalidates cached credentials. | Overrides R4.1–R4.3. |
| **R9.5** | `seed` is forwarded when the provider supports it, otherwise accepted and ignored. The docstring must say **server-side reproducibility is not guaranteed**. Never fake determinism by seeding locally. | Overrides R3.3 / R3.4. |
| **R9.6** | Task-based APIs (submit → poll → download) are hidden behind the synchronous `infer()`. `timeout` and `poll_interval` are constructor arguments; the timeout default errs **long** (generation runs into the tens of minutes). On timeout raise an error that **contains the `task_id`**, so the run can be recovered manually. | R3.1 stays synchronous for the caller. A tripped budget refunds nothing — the task finishes server-side and only the download is lost — so a short default costs credits while a long one costs nothing. |
| **R9.7** | Both the **API key** and the **API base URL** are read at **first call**, never at construction. When either is missing, fail fast naming the variable and pointing at `<REPO_PATH>/.env`. A base URL is **required, never defaulted**: the public endpoint is not reachable from every network, so a silent fallback looks like working configuration until the first billed call fails. Use `cloud_api.require_api_key()` / `cloud_api.require_api_base()`. | Constructing a model must not require credentials — `<REPO_PATH>/test/harness` imports it. A wrong or unreachable endpoint must be a configuration error, not a mystery failure at request time. |
| **R9.8** | Support `cache_dir`. A request identified by `(model_path, prompt / image hash, all inference params, output_format)` that is already in the cache returns **without any network traffic**. Every real call logs `task_id`, elapsed seconds, credits consumed (when reported) and the output size. | Every call is billed. Re-running a pipeline must not re-bill. |
| **R9.9** | Support `max_retries` with exponential backoff, and **classify** failures: retryable (5xx, 429, connection reset, read timeout) vs. terminal (400 bad params, 401/403 auth, 402 insufficient credits, task rejected). Never retry a terminal failure. **Classify on the response body, not only the status code**: providers return "out of credit" under an auth status, which by status alone is indistinguishable from a bad key, and a caller must be able to tell them apart. | Network failure is the normal case, not the exception. |

### R9.10 — output format

`output_format` is a constructor argument (`"glb"` default). A format the provider
cannot produce natively must raise a **terminal, actionable** error naming an
alternative — never silently return a different format.

### R9.11 — where shared plumbing lives

HTTP session, retry/backoff, error classification, response cache and the polling
loop are **not** duplicated per provider. They live in `<REPO_PATH>/models/common/cloud_api.py`
and are shared across families (`gen_3d_object`, `gen_audio`, `gen_cg_video`, …).
Provider-specific request bodies stay in the wrapper.

### R9.12 — one configuration source

Every credential, base URL, backend switch and cache location is read from
**one place**: `<REPO_PATH>/global_config.py`, which loads `<REPO_PATH>/.env`
(template: `.env.example`). A wrapper must not invent its own env-var name, read
a `.env` of its own, or fall back to a literal endpoint.

`global_config` is a **top-level, stdlib-only** module on purpose: `models/` must
not import `pipeline/` (R1.1), and both layers need the same configuration, so it
belongs to neither. `models/common/cloud_api.py` imports it at module load, so a
wrapper used outside a Pipeline runner still sees the file.

Pipeline runners call `pipeline.common.config.require_cloud_or_exit(...)` in
`main()`, before loading anything, for every slot that resolves to a cloud
backend, so a misconfiguration is reported in the first second rather than during
the first task. A task whose cloud credentials are missing does not run at all;
the runner exits with code **2**.

---

## Contract-deviation marking — three places, all mandatory

A cloud wrapper deviates from `model_require.md` by design. Mark it so a reader
never has to guess whether the deviation was intentional.

**① A `CONTRACT DEVIATIONS` section in the file docstring**, one line per rule:

```python
"""
TripoModel — wrapper around Tripo3D's cloud 3D-generation API.

Reference: https://developers.tripo3d.ai/

CONTRACT DEVIATIONS (model_require.md targets local-weight models;
                     see agent_skills/develop_harness/api_model_require.md):
  C1  R2.1/R2.2 → R9.1  `model_path` carries a model version id, not a weight path.
  C2  R2.3      → R9.2  `device` accepted for interface parity and ignored.
  ...
"""
```

**② An inline `# [CONTRACT-DEVIATION Cx]` comment at the exact line** where the
deviation is visible:

```python
def __init__(self, model_path: str = "v3.1-20260211", device: str = "cuda", ...):
    # [CONTRACT-DEVIATION C1] model_path is a version id, not a weight location.
    # [CONTRACT-DEVIATION C2] device accepted for interface parity, ignored.
    self.model_path = model_path
    self.device = device
```

**③ This file** — the deviation must map onto one of R9.1–R9.12. If it does not,
add a rule here first.

### The canonical deviation ids

Use these ids so every cloud wrapper reads the same way.

| id | `model_require.md` | Deviation | Governed by |
|----|--------------------|-----------|-------------|
| C1 | R2.1 / R2.2 | `model_path` is a model version id | R9.1 |
| C2 | R2.3 | `device` ignored | R9.2 |
| C3 | R3.6 / R5.5 | no `torch.no_grad()` | R9.3 |
| C4 | R4.1–R4.3 | `unload()` is a session close | R9.4 |
| C5 | R3.3 / R3.4 | `seed` best-effort, not reproducible | R9.5 |
| C6 | R3.1 (implicit) | submit → poll → download behind a blocking `infer()` | R9.6 |
| C7 | R1.2 | `infer_and_save(..., output_path)` (documented R1.2 exception) | — |
| C8 | (new) | `cache_dir`, requests are billed | R9.8 |
| C9 | (new) | `max_retries`, network failure is expected | R9.9 |

---

## Checklist — in addition to R8

- [ ] `model_path` default is a **real provider version string**; aliases accepted
- [ ] `Model()` constructs with **no API key present** and no network access
- [ ] `device="cpu"` does not raise
- [ ] missing key → error naming the env var and pointing at `.env`
- [ ] missing base URL → error naming the env var and pointing at `.env`; the
      documented endpoint appears only as an example, never as a fallback (R9.7)
- [ ] `infer()` blocks until done; timeout error carries the `task_id`
- [ ] terminal errors (400 / 401 / 402) are **not** retried
- [ ] a cache hit performs **zero** HTTP requests
- [ ] real calls log `task_id`, elapsed, credits, output size
- [ ] `unload()` twice is a no-op
- [ ] `infer_and_save` signature is byte-identical to the other backends in the
      same operator slot (R6)
- [ ] a stub exists in `<REPO_PATH>/test/harness/stubs.py` that performs **no** network I/O,
      and `python test/harness/smoke.py --kind <kind>` passes with no key set

---

## Cost and licensing

- Free tiers are small. Bring a chain up on the **stub** first; spend real credits
  only on the final verification.
- API keys and base URLs live in `<REPO_PATH>/.env` (template: `.env.example`),
  read through `<REPO_PATH>/global_config.py` (R9.12). A key must never reach the
  repository, a log line, a `meta.json` or a cache filename.
- Commercial-use rights differ between free and paid tiers on every provider.
  Confirm the tier before any generated asset is published.
