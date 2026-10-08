"""
pipeline/common/

Shared, task-agnostic helpers for every Pipeline entry point.

`paths` is the single source of truth for input / output locations — never
hand-build an output path in a `run.py`, an `eval.py` or an operator.

`artifacts` provides shared Prompt rendering, workspace path validation, JSON
persistence, and file-manifest helpers.
"""
from pipeline.common import paths  # noqa: F401

__all__ = ["paths"]
