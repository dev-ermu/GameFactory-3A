"""Text-to-motion step: thin pass-through to an injected model."""

from typing import Any

# MoMask / HumanML3D default; prefer the model's own fps when present.
DEFAULT_FPS = 20


def generate_motion(
    prompt: str,
    model: Any,
    *,
    seed: int = 42,
    motion_length: int = 0,
    use_ik: bool = True,
    in_place: bool = False,
    in_place_lock_height: bool = False,
    repeat_times: int = 1,
    cond_scale: float = 4.0,
    time_steps: int = 18,
    temperature: float = 1.0,
) -> dict:
    """Generate one clip; returns in-memory artifacts including ``bvh_bytes``."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("generate_motion needs a non-empty text prompt.")
    if motion_length < 0:
        raise ValueError(f"motion_length must be >= 0, got {motion_length}")
    if repeat_times < 1:
        raise ValueError(f"repeat_times must be >= 1, got {repeat_times}")

    artifacts = model.infer(
        prompt.strip(),
        seed=seed,
        motion_length=motion_length,
        use_ik=use_ik,
        in_place=in_place,
        in_place_lock_height=in_place_lock_height,
        repeat_times=repeat_times,
        cond_scale=cond_scale,
        time_steps=time_steps,
        temperature=temperature,
    )
    if not isinstance(artifacts, dict):
        raise RuntimeError(
            f"Text-to-motion model returned {type(artifacts).__name__}, "
            "expected a dict."
        )
    if not artifacts.get("bvh_bytes"):
        raise RuntimeError(
            "Text-to-motion model returned no BVH; "
            f"keys present: {sorted(artifacts)}"
        )
    artifacts.setdefault("fps", DEFAULT_FPS)
    return artifacts


__all__ = ["DEFAULT_FPS", "generate_motion"]
