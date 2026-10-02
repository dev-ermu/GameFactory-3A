"""Resolve project-specific Unreal assets for the VFX integration tests."""
from __future__ import annotations

import os


CONTENT_ROOT_ENV = "AAAGF_VFX_TEST_CONTENT_ROOT"


def content_root() -> str:
    """Return the configured Unreal test-content root (for example /Game/MyVFX)."""
    root = os.environ.get(CONTENT_ROOT_ENV, "").replace("\\", "/").rstrip("/")
    if not root:
        raise RuntimeError(f"{CONTENT_ROOT_ENV} is required")
    if not root.startswith("/Game/"):
        raise RuntimeError(f"{CONTENT_ROOT_ENV} must be an Unreal /Game/ asset path")
    return root


def content_path(relative_path: str) -> str:
    """Resolve a path relative to the configured Unreal test-content root."""
    relative_path = relative_path.replace("\\", "/").strip("/")
    if not relative_path:
        raise ValueError("relative_path cannot be empty")
    return f"{content_root()}/{relative_path}"
