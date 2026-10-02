"""
models/common/

Plumbing shared by more than one model family. Nothing here knows about tasks,
games or output paths (`model_require.md` R1.1 / R1.4 apply unchanged).

Contents:
    cloud_api.py — HTTP session, retry/backoff, error classification, response
                   cache and the submit → poll → download loop used by every
                   closed-source API wrapper (`api_model_require.md` R9.11).
    glb_utils.py — dependency-free GLB inspection (triangle count, bounds).

Imports are kept lazy and stdlib-only at module level so `tests/harness/smoke.py`
can import the chain on a CPU box with no extra packages installed.
"""
