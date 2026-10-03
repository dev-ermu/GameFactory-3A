"""Sound-effect-generation step for the AudioGen operator."""

from typing import Any, Optional


def generate_sound_effect(
    model: Any,
    prompt: str,
    *,
    seed: int = 42,
    duration_sec: Optional[float] = None,
    num_steps: Optional[int] = None,
    cfg: Optional[float] = None,
) -> dict[str, Any]:
    """Generate one offline SFX/ambience asset through an injected model."""
    if model is None:
        raise RuntimeError("No sound-effect model was loaded for this AudioGen operator.")
    if not prompt or not prompt.strip():
        raise ValueError("A sound_effect task requires a non-empty `prompt` field.")
    return model.infer(
        prompt=prompt,
        seed=seed,
        duration_sec=duration_sec,
        num_steps=num_steps,
        cfg=cfg,
    )
