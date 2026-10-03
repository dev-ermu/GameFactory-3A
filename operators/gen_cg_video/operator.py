"""
operators/gen_cg_video/operator.py

GenCGVideoOperator — turns one task dict into an MP4 video artifact.

The operator is model-agnostic: inject any model implementing
``infer_and_save(VideoGenerationInput, output_path) -> str``.  It owns task
semantics and local path loading; the model owns provider transport encoding.

Output layout — two modes, chosen by whether ``output_dir`` is supplied:

* per-game (default):
  ``test_data/outputs/<game>/<run>/assets/cg_video/<task>/video.mp4``
* legacy flat mode: ``<output_dir>/<task_id>.mp4``
"""

import time
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from models.gen_cg_video.utils import VideoGenerationInput, VideoGenerationMode

TASK_KIND = "cg_video"
VIDEO_FILENAME = "video.mp4"


class GenCGVideoOperator:
    """Generate one CG video with an injected video-generation model."""

    def __init__(
        self,
        model: Any,
        output_dir: Optional[str] = None,
        run_id: str = "default",
        default_game_id: Optional[str] = None,
    ):
        self.model = model
        self.run_id = run_id
        self.default_game_id = default_game_id
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_image_value(inp: dict, object_key: str, path_key: str) -> Image.Image | None:
        """Load one optional PIL image from an object field or repo-relative path."""
        image = inp.get(object_key)
        path_value = inp.get(path_key)
        if image is not None and path_value is not None:
            raise ValueError(f"provide only one of {object_key!r} and {path_key!r}")
        if image is not None:
            if not isinstance(image, Image.Image):
                raise TypeError(
                    f"{object_key} must be a PIL.Image.Image, not "
                    f"{type(image).__name__}"
                )
            return image
        if path_value is None:
            return None
        if not isinstance(path_value, (str, Path)):
            raise TypeError(f"{path_key} must be a local path string")

        from pipeline.common import paths

        path = paths.resolve_input_path(path_value)
        if not path.is_file():
            raise FileNotFoundError(f"{path_key} does not exist: {path}")
        with Image.open(path) as opened:
            return opened.convert("RGB").copy()

    @staticmethod
    def _load_reference_images(inp: dict) -> tuple[Image.Image, ...]:
        """Load ordered reference images without changing their caller order."""
        images = inp.get("reference_images")
        path_values = inp.get("reference_image_paths")
        if images is not None and path_values is not None:
            raise ValueError(
                "provide only one of 'reference_images' and 'reference_image_paths'"
            )
        if images is not None:
            if isinstance(images, Image.Image) or not isinstance(images, (list, tuple)):
                raise TypeError("reference_images must be a list or tuple of PIL images")
            for index, image in enumerate(images):
                if not isinstance(image, Image.Image):
                    raise TypeError(
                        f"reference_images[{index}] must be a PIL.Image.Image, "
                        f"not {type(image).__name__}"
                    )
            return tuple(images)
        if path_values is None:
            return ()
        if isinstance(path_values, (str, Path)) or not isinstance(path_values, (list, tuple)):
            raise TypeError("reference_image_paths must be a list or tuple of paths")

        from pipeline.common import paths

        loaded = []
        for index, value in enumerate(path_values):
            if not isinstance(value, (str, Path)):
                raise TypeError(f"reference_image_paths[{index}] must be a local path")
            path = paths.resolve_input_path(value)
            if not path.is_file():
                raise FileNotFoundError(
                    f"reference_image_paths[{index}] does not exist: {path}"
                )
            with Image.open(path) as opened:
                loaded.append(opened.convert("RGB").copy())
        return tuple(loaded)

    def _build_request(self, inp: dict) -> VideoGenerationInput:
        """Normalize one task dict into the existing shared model input type."""
        return VideoGenerationInput(
            mode=inp.get("mode", VideoGenerationMode.TEXT_TO_VIDEO),
            prompt=inp.get("prompt", ""),
            duration_sec=inp.get("duration_sec", 5),
            seed=inp.get("seed", 42),
            first_frame=self._load_image_value(
                inp, "first_frame", "first_frame_path"
            ),
            last_frame=self._load_image_value(inp, "last_frame", "last_frame_path"),
            reference_images=self._load_reference_images(inp),
        )

    def _resolve_out_path(self, inp: dict, task_id: str) -> tuple[str, Path, Path]:
        if self.output_dir is not None:
            game_id = str(inp.get("game_id") or inp.get("game") or "")
            return game_id, self.output_dir, self.output_dir / f"{task_id}.mp4"

        from pipeline.common import paths

        game_id = paths.infer_game_id(inp, fallback=self.default_game_id)
        task_dir = paths.task_output_dir(
            game_id, TASK_KIND, task_id, run_id=self.run_id
        )
        return game_id, task_dir, task_dir / VIDEO_FILENAME

    def run(self, inp: dict) -> dict:
        """Generate one video from a task dictionary and return artifact metadata."""
        if not isinstance(inp, dict):
            raise TypeError(f"inp must be a dict, not {type(inp).__name__}")

        task_id = str(inp.get("task_id", f"task_{int(time.time())}"))
        game_id, task_dir, output_path = self._resolve_out_path(inp, task_id)
        request = self._build_request(inp)

        t0 = time.time()
        video_path = self.model.infer_and_save(
            request,
            output_path=str(output_path),
        )
        elapsed = time.time() - t0

        result = {
            "task_id": task_id,
            "video_path": str(video_path),
            "elapsed_sec": round(elapsed, 2),
            "game_id": game_id,
            "task_kind": TASK_KIND,
            "output_dir": str(task_dir),
        }

        if self.output_dir is None:
            from pipeline.common import paths

            meta = {
                **result,
                "run_id": self.run_id,
                "mode": request.mode.value,
                "prompt": request.prompt,
                "duration_sec": request.duration_sec,
                "seed": request.seed,
                "first_frame_path": inp.get("first_frame_path"),
                "last_frame_path": inp.get("last_frame_path"),
                "reference_image_paths": inp.get("reference_image_paths", []),
                "model": type(self.model).__name__,
            }
            call_info = getattr(self.model, "last_call_info", None)
            if call_info:
                meta["model_call"] = dict(call_info)
            paths.write_task_meta(task_dir, meta)

        return result

    def run_batch(self, inputs: list[dict]) -> list[dict]:
        """Run tasks sequentially through the same loaded model."""
        return [self.run(inp) for inp in inputs]
