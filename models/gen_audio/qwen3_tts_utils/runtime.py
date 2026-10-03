"""Runtime configuration helpers used by the Qwen3-TTS model wrapper."""

from typing import Any, Optional


def resolve_mode(model_path: str, configured_mode: str = "auto") -> str:
    """Resolve an explicit or checkpoint-derived Qwen3-TTS inference mode."""
    if configured_mode != "auto":
        return configured_mode
    checkpoint_name = model_path.lower()
    if "voicedesign" in checkpoint_name or "voice-design" in checkpoint_name:
        return "voice_design"
    if "base" in checkpoint_name:
        return "voice_clone"
    return "custom_voice"


def resolve_torch_dtype(
    torch_module: Any,
    device: str,
    dtype: Optional[str] = None,
) -> Any:
    """Resolve a configured dtype without importing torch at module import time."""
    if dtype:
        try:
            return getattr(torch_module, dtype)
        except AttributeError as exc:
            raise ValueError(f"Unsupported torch dtype: {dtype!r}") from exc
    if device.startswith("cuda"):
        return (
            torch_module.bfloat16
            if torch_module.cuda.is_bf16_supported()
            else torch_module.float16
        )
    return torch_module.float32
