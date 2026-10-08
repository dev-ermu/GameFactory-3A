"""Cinematic / CG video generation model wrappers (cloud APIs only)."""

from .seedance_model import SeedanceModel
from .utils import VideoGenerationInput, VideoGenerationMode

__all__ = [
    "SeedanceModel",
    "VideoGenerationInput",
    "VideoGenerationMode",
]
