"""Shared request types for cinematic / CG video generation models."""

from dataclasses import dataclass
from enum import Enum

from PIL import Image


class VideoGenerationMode(str, Enum):
    """Video-generation capabilities implemented in the Seedance phase."""

    TEXT_TO_VIDEO = "text_to_video"
    FIRST_FRAME_TO_VIDEO = "first_frame_to_video"
    FIRST_LAST_FRAME_TO_VIDEO = "first_last_frame_to_video"
    REFERENCE_TO_VIDEO = "reference_to_video"


@dataclass(frozen=True)
class VideoGenerationInput:
    """Provider-neutral input for one video-generation request.

    Images are normalized objects, never paths. Operators own path loading;
    provider wrappers own transport encoding.
    """

    mode: VideoGenerationMode
    prompt: str
    duration_sec: float
    seed: int = 42
    first_frame: Image.Image | None = None
    last_frame: Image.Image | None = None
    reference_images: tuple[Image.Image, ...] = ()

    def __post_init__(self) -> None:
        try:
            mode = (
                self.mode
                if isinstance(self.mode, VideoGenerationMode)
                else VideoGenerationMode(self.mode)
            )
        except (TypeError, ValueError) as exc:
            supported = ", ".join(mode.value for mode in VideoGenerationMode)
            raise ValueError(
                f"unsupported video generation mode {self.mode!r}; "
                f"expected one of: {supported}"
            ) from exc
        object.__setattr__(self, "mode", mode)

        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if isinstance(self.duration_sec, bool) or not isinstance(self.duration_sec, (int, float)):
            raise TypeError("duration_sec must be a positive number")
        if self.duration_sec <= 0:
            raise ValueError("duration_sec must be greater than zero")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an int")

        references = tuple(self.reference_images)
        object.__setattr__(self, "reference_images", references)

        for name, image in (
            ("first_frame", self.first_frame),
            ("last_frame", self.last_frame),
        ):
            if image is not None and not isinstance(image, Image.Image):
                raise TypeError(f"{name} must be a PIL.Image.Image, not {type(image).__name__}")
        for index, image in enumerate(references):
            if not isinstance(image, Image.Image):
                raise TypeError(
                    f"reference_images[{index}] must be a PIL.Image.Image, "
                    f"not {type(image).__name__}"
                )

        has_first = self.first_frame is not None
        has_last = self.last_frame is not None
        has_references = bool(references)

        expected = {
            VideoGenerationMode.TEXT_TO_VIDEO: (False, False, False),
            VideoGenerationMode.FIRST_FRAME_TO_VIDEO: (True, False, False),
            VideoGenerationMode.FIRST_LAST_FRAME_TO_VIDEO: (True, True, False),
            VideoGenerationMode.REFERENCE_TO_VIDEO: (False, False, True),
        }[mode]
        actual = (has_first, has_last, has_references)
        if actual != expected:
            raise ValueError(
                f"mode={mode.value!r} requires "
                f"first_frame={expected[0]}, last_frame={expected[1]}, "
                f"reference_images={expected[2]}; got "
                f"first_frame={actual[0]}, last_frame={actual[1]}, "
                f"reference_images={actual[2]}"
            )
