"""Dialogue-generation step for the AudioGen operator."""

from typing import Any, Optional


def generate_dialogue(
    model: Any,
    text: str,
    *,
    seed: int = 42,
    language: str = "Auto",
    speaker_id: str = "Vivian",
    emotion: str = "",
    delivery: str = "",
    reference_audio: Optional[tuple[Any, int]] = None,
    reference_text: Optional[str] = None,
) -> dict[str, Any]:
    """Generate one spoken line through an injected TTS model."""
    if model is None:
        raise RuntimeError("No dialogue model was loaded for this AudioGen operator.")
    if not text or not text.strip():
        raise ValueError("A dialogue task requires a non-empty `text` field.")

    instructions = []
    if emotion:
        instructions.append(f"Speak with a {emotion} emotion.")
    if delivery:
        instructions.append(delivery)
    return model.infer(
        text=text,
        seed=seed,
        language=language,
        speaker_id=speaker_id,
        instruct=" ".join(instructions),
        reference_audio=reference_audio,
        reference_text=reference_text,
    )
