"""Audio generation backends for dialogue and game sound effects.

Cloud APIs only: `SeedAudioModel` covers both dialogue and sound effects.
"""

from .seed_audio_model import SeedAudioModel

__all__ = ["SeedAudioModel"]
