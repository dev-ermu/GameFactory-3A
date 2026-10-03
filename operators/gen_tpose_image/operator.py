"""
operators/gen_tpose_image/operator.py

GenTPoseImageOperator — accepts a loaded image-edit model (and an optional
foreground / matting model) and processes an input dict into a T-pose RGBA
image saved as PNG.

The operator is intentionally model-agnostic: you inject any object that
implements the same interface as `QwenEditModel` (`.infer(image, prompt, seed,
steps) -> PIL.Image`), and any tool model that behaves like `RMBGModel` or
`DepthAnythingModel` (`.infer(image) -> np.ndarray`). New model wrappers
can be swapped in without touching this file.

Output layout — two modes, chosen by whether `output_dir` is given:

  * **per-game (default, `output_dir=None`)** — resolved by
    `pipeline.common.paths`, so artifacts are grouped by generated game project::

        test_data/outputs/<game_id>/<run_id>/assets/tpose/<task_id>/
            ├── tpose_fg.png     # transparent background (the deliverable)
            ├── tpose.png        # white background (intermediate)
            └── meta.json

  * **flat (legacy, `output_dir="..."`)** — writes
    `<output_dir>/<task_id>_tpose_fg.png` and `<output_dir>/<task_id>_tpose.png`,
    byte-for-byte the historical behaviour. Existing callers are unaffected.

Usage:
    from models.gen_image.qwen_edit_model import QwenEditModel
    from models.tools.image_matting.rmbg_model import RMBGModel
    from operators.gen_tpose_image.operator import GenTPoseImageOperator

    gen_model  = QwenEditModel(model_path="Qwen/Qwen-Image-Edit-2511")
    mask_model = RMBGModel(model_path="briaai/RMBG-1.4")

    # per-game layout
    op = GenTPoseImageOperator(gen_model=gen_model, mask_model=mask_model)

    # legacy flat layout (unchanged)
    op = GenTPoseImageOperator(gen_model=gen_model, mask_model=mask_model,
                               output_dir="outputs/tpose")

    result = op.run({
        "game_id": "gameA_cyberpunk_shooter",   # optional, inferred when omitted
        "task_id": "luffy_001",
        "image_path": "path/to/character.png",  # or "image": PIL.Image
        "description": "Monkey D. Luffy in a red vest and straw hat.",
        "seed": 42,
    })
    print(result["tpose_rgba_path"])
"""

import time
from pathlib import Path
from typing import Any, Optional

from PIL import Image

#: Registered task kind for this operator (see pipeline/common/paths.py).
TASK_KIND = "tpose"

#: Artifact filenames used by the per-game layout.
RGBA_FILENAME = "tpose_fg.png"
RGB_FILENAME = "tpose.png"


class GenTPoseImageOperator:
    """
    Operator for character T-pose image generation.

    Args:
        gen_model:  A loaded image-edit model with an
                    `.infer(image, prompt, seed, steps) -> PIL.Image` method
                    (currently supports QwenEditModel).
        mask_model: (optional) A loaded foreground / matting model — either
                    `RMBGModel` or `DepthAnythingModel` (or any object with a
                    `.infer(image) -> np.ndarray` method). The extraction
                    branch is selected automatically based on the class name.
        output_dir (str, optional): **Legacy flat mode.** When given, PNGs are
                    written as `<output_dir>/<task_id>_tpose_fg.png` (and
                    `_tpose.png`), exactly as before. When omitted (default),
                    the per-game layout under
                    `test_data/outputs/<game_id>/<run_id>/assets/tpose/<task_id>/`
                    is used instead.
        run_id (str): Groups all artifacts of one generation run. Per-game mode only.
        default_game_id (str, optional): Fallback game project for tasks that carry
                    no `game_id` and whose input paths reveal none. Per-game mode only.
    """

    def __init__(
        self,
        gen_model: Any,
        mask_model: Optional[Any] = None,
        output_dir: Optional[str] = None,
        run_id: str = "default",
        default_game_id: Optional[str] = None,
    ):
        self.gen_model = gen_model
        self.mask_model = mask_model
        self.run_id = run_id
        self.default_game_id = default_game_id
        # Legacy flat mode is active only when an explicit output_dir is supplied.
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------

    def _load_image(self, inp: dict) -> Image.Image:
        """Return a PIL image from an input dict that has 'image_path' or 'image'."""
        if "image" in inp and isinstance(inp["image"], Image.Image):
            return inp["image"]
        if "image_path" in inp:
            p = Path(inp["image_path"])
            if not p.is_absolute() and not p.exists():
                # resolve relative to repo root
                repo_root = Path(__file__).resolve().parents[2]
                p = repo_root / inp["image_path"]
            return Image.open(str(p)).convert("RGB")
        raise ValueError("Input must contain 'image_path' (str) or 'image' (PIL.Image).")

    # --------------------------------------------------------------------------

    def _resolve_out_paths(self, inp: dict, task_id: str) -> tuple[str, Path, Path, Path]:
        """
        Return ``(game_id, task_dir, rgba_path, rgb_path)`` for either output mode.

        Legacy flat mode keeps the historical `<task_id>_tpose_fg.png` naming.
        """
        if self.output_dir is not None:
            game_id = str(inp.get("game_id") or inp.get("game") or "")
            return (
                game_id,
                self.output_dir,
                self.output_dir / f"{task_id}_tpose_fg.png",
                self.output_dir / f"{task_id}_tpose.png",
            )

        from pipeline.common import paths
        game_id = paths.infer_game_id(inp, fallback=self.default_game_id)
        task_dir = paths.task_output_dir(game_id, TASK_KIND, task_id, run_id=self.run_id)
        return game_id, task_dir, task_dir / RGBA_FILENAME, task_dir / RGB_FILENAME

    # --------------------------------------------------------------------------

    def run(self, inp: dict) -> dict:
        """
        Generate a T-pose RGBA image from a reference character image.

        Args:
            inp (dict):
                - image_path (str): path to the reference character image
                  OR image (PIL.Image): pre-loaded image
                - game_id (str, optional): game project this task belongs to;
                  inferred from `image_path` when omitted
                - task_id (str, optional): used to name the output file / directory
                - description (str, optional): short text description of the character
                - seed (int, optional): random seed (default 42)
                - steps (int, optional): diffusion steps (default 40)
                - target_size (int, optional): output square canvas size (default 1024)
                - save_intermediate (bool, optional): also save the white-bg RGB
                                                     T-pose (default True)

        Returns:
            dict:
                - task_id (str)
                - tpose_rgb_path (str | None): path to the white-bg RGB T-pose PNG
                - tpose_rgba_path (str): path to the transparent-bg T-pose PNG
                - elapsed_sec (float)
                - game_id (str), task_kind (str), output_dir (str)  ← additive
        """
        from operators.gen_tpose_image.funcs.gen_tpose_image import gen_tpose_image

        task_id           = inp.get("task_id", f"task_{int(time.time())}")
        description       = inp.get("description", "")
        seed              = inp.get("seed", 42)
        steps             = inp.get("steps", 40)
        target_size       = inp.get("target_size", 1024)
        save_intermediate = inp.get("save_intermediate", True)

        game_id, task_dir, rgba_target, rgb_target = self._resolve_out_paths(inp, task_id)

        ref_image = self._load_image(inp)

        t0 = time.time()
        result = gen_tpose_image(
            ref_image,
            description=description,
            gen_model=self.gen_model,
            mask_model=self.mask_model,
            seed=seed,
            steps=steps,
            target_size=target_size,
            return_intermediate=True,
        )
        elapsed = time.time() - t0

        tpose_rgb  = result["tpose_rgb"]
        tpose_rgba = result["tpose_rgba"]

        rgba_path = rgba_target
        tpose_rgba.save(str(rgba_path))

        rgb_path: Optional[Path] = None
        if save_intermediate:
            rgb_path = rgb_target
            tpose_rgb.save(str(rgb_path))

        out = {
            "task_id": task_id,
            "tpose_rgb_path": str(rgb_path) if rgb_path is not None else None,
            "tpose_rgba_path": str(rgba_path),
            "elapsed_sec": round(elapsed, 2),
            "game_id": game_id,
            "task_kind": TASK_KIND,
            "output_dir": str(task_dir),
        }

        # meta.json only in per-game mode, so legacy output dirs stay untouched.
        if self.output_dir is None:
            from pipeline.common import paths
            paths.write_task_meta(task_dir, {
                **out,
                "run_id": self.run_id,
                "description": description,
                "source_image": inp.get("image_path"),
                "seed": seed,
                "steps": steps,
                "target_size": target_size,
                "gen_model": type(self.gen_model).__name__,
                "mask_model": type(self.mask_model).__name__ if self.mask_model else None,
            })

        return out

    # --------------------------------------------------------------------------

    def run_batch(self, inputs: list[dict]) -> list[dict]:
        """Run a list of input dicts sequentially and return results."""
        return [self.run(inp) for inp in inputs]
