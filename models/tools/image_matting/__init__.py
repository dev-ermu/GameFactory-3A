"""
`models.tools.image_matting` — foreground / background separation models.

Used by generation pipelines (e.g. `gen_tpose_image`) to isolate a character
from its background:

- `DepthAnythingModel`: depth estimation, combined with white-bg
                        suppression to derive a foreground mask.

Inherits from `BaseToolModel` (see `models/tools/base.py`).

The wrapper is re-exported lazily (PEP 562) because it imports `torch` at module
level: a caller that only wants `SkySegmentationModel` should not be made to
install a deep-learning runtime.
"""

from typing import Any

__all__ = ["DepthAnythingModel"]


def __getattr__(name: str) -> Any:
    """Lazy re-export of the matting wrappers (PEP 562)."""
    if name == "DepthAnythingModel":
        from models.tools.image_matting.depth_anything_model import DepthAnythingModel

        return DepthAnythingModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
