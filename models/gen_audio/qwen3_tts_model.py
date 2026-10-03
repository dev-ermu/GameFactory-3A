"""
Qwen3TTSModel — thin wrapper for Qwen3-TTS dialogue generation.

Reference: https://github.com/QwenLM/Qwen3-TTS

Install the optional backend with ``pip install -U qwen-tts``.  The wrapper
supports CustomVoice, VoiceDesign, and Base/voice-clone checkpoints and returns
audio in memory; artifact paths are owned by the audio operator.
"""

import gc
from typing import Any, Optional

from models.gen_audio.qwen3_tts_utils import resolve_mode, resolve_torch_dtype


class Qwen3TTSModel:
    """Wrap a single Qwen3-TTS checkpoint behind the AudioGen model contract."""

    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
        dtype: Optional[str] = None,
        attn_implementation: Optional[str] = None,
        mode: str = "auto",
        lazy: bool = False,
    ):
        self.model_path = model_path
        self.device = device
        self.dtype = dtype
        self.attn_implementation = attn_implementation
        self.mode = mode
        self.lazy = lazy
        self.model: Any = None
        if not lazy:
            self.load()

    def _resolved_mode(self) -> str:
        return resolve_mode(self.model_path, self.mode)

    def load(self) -> None:
        """Load or reload the configured checkpoint."""
        if self.model is not None:
            return
        try:
            import torch
            from qwen_tts import Qwen3TTSModel as NativeQwen3TTSModel
        except ImportError as exc:
            raise RuntimeError(
                "Qwen3-TTS is not installed. Install it in an isolated environment with:\n"
                "  pip install -U qwen-tts\n"
                "See https://github.com/QwenLM/Qwen3-TTS for supported CUDA/Python versions."
            ) from exc

        resolved_dtype = resolve_torch_dtype(torch, self.device, self.dtype)

        kwargs: dict[str, Any] = {
            "device_map": "cuda:0" if self.device == "cuda" else self.device,
            "dtype": resolved_dtype,
        }
        if self.attn_implementation:
            kwargs["attn_implementation"] = self.attn_implementation
        self.model = NativeQwen3TTSModel.from_pretrained(self.model_path, **kwargs)

    def infer(
        self,
        text: str,
        seed: int = 42,
        language: str = "Auto",
        speaker_id: str = "Vivian",
        instruct: str = "",
        reference_audio: Optional[tuple[Any, int]] = None,
        reference_text: Optional[str] = None,
        **generation_kwargs: Any,
    ) -> dict[str, Any]:
        """Generate one dialogue clip.

        Args:
            text: Exact text to speak.
            seed: Sampling seed.
            language: Qwen language name, or ``Auto``.
            speaker_id: Built-in speaker for CustomVoice checkpoints.
            instruct: Optional delivery/emotion instruction.
            reference_audio: ``(numpy waveform, sample_rate)`` for Base checkpoints.
            reference_text: Transcript of the reference clip when available.

        Returns:
            ``{"waveform": float32 ndarray[C, T], "sample_rate": int}``, with
            waveform values normally in ``[-1, 1]``.
        """
        if not text or not text.strip():
            raise ValueError("Qwen3-TTS requires non-empty dialogue text.")
        if self.model is None:
            self.load()

        import numpy as np
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

        mode = self._resolved_mode()
        with torch.inference_mode():
            if mode == "voice_design":
                wavs, sample_rate = self.model.generate_voice_design(
                    text=text,
                    language=language,
                    instruct=instruct or "A clear, natural game character voice.",
                    **generation_kwargs,
                )
            elif mode == "voice_clone":
                if reference_audio is None:
                    raise ValueError(
                        "A Qwen3-TTS Base checkpoint requires reference_audio. "
                        "Use a CustomVoice checkpoint when no reference is available."
                    )
                clone_kwargs: dict[str, Any] = {
                    "text": text,
                    "language": language,
                    "ref_audio": reference_audio,
                    "x_vector_only_mode": not bool(reference_text),
                    **generation_kwargs,
                }
                if reference_text:
                    clone_kwargs["ref_text"] = reference_text
                wavs, sample_rate = self.model.generate_voice_clone(**clone_kwargs)
            elif mode == "custom_voice":
                wavs, sample_rate = self.model.generate_custom_voice(
                    text=text,
                    language=language,
                    speaker=speaker_id,
                    instruct=instruct,
                    **generation_kwargs,
                )
            else:
                raise ValueError(
                    f"Unsupported Qwen3-TTS mode {mode!r}; expected custom_voice, "
                    "voice_design, voice_clone, or auto."
                )

        waveform = np.asarray(wavs[0], dtype=np.float32)
        if waveform.ndim == 1:
            waveform = waveform[None, :]
        elif waveform.ndim != 2:
            raise ValueError(f"Unexpected Qwen3-TTS waveform shape: {waveform.shape}")
        return {"waveform": waveform, "sample_rate": int(sample_rate)}

    def unload(self) -> None:
        """Release model memory. Safe to call repeatedly; ``infer`` reloads it."""
        if self.model is not None:
            try:
                self.model.to("cpu")
            except (AttributeError, RuntimeError):
                pass
            del self.model
            self.model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
