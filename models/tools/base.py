"""
BaseToolModel — unified base class for all tool / utility models
(depth estimation, segmentation, background removal, matting, etc.).

Subclasses should override:
  - `_load()`      : load underlying model weights / processors
  - `infer(image)` : run inference and return the model's native output

The base class provides:
  - consistent `__init__(model_path, device)`
  - lazy-load via `_loaded` flag
  - convenient `__call__` alias for `infer`
  - `unload()` to release GPU memory
"""

from abc import ABC, abstractmethod
import gc
from typing import Any

from PIL import Image


class BaseToolModel(ABC):
    """Abstract base class for tool / utility models."""

    def __init__(self, model_path: str, device: str = "cpu", lazy: bool = False):
        """
        Args:
            model_path: Local path or HuggingFace hub id of the model.
            device:     Inference device. This project runs on CPU.
            lazy:       If True, defer weight loading until first `infer` call.
        """
        self.model_path = model_path
        self.device = device
        self.lazy = lazy
        self._loaded = False
        if not lazy:
            self._load()
            self._loaded = True

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def _load(self) -> None:
        """Load weights / processors. Called once on init (or first call if lazy)."""

    @abstractmethod
    def infer(self, image: Image.Image, **kwargs) -> Any:
        """Run inference on a single PIL image."""

    # ------------------------------------------------------------------
    # Common utilities
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def __call__(self, image: Image.Image, **kwargs) -> Any:
        return self.infer(image, **kwargs)

    def unload(self) -> None:
        """Release model references. Safe to call repeatedly."""
        model = getattr(self, "model", None)
        if model is not None:
            try:
                model.to("cpu")
            except (AttributeError, RuntimeError):
                pass

        for attr in ("model", "processor", "pipeline"):
            if hasattr(self, attr):
                delattr(self, attr)

        self._loaded = False
        gc.collect()
