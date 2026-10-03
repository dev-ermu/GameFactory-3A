"""
models/gen_image/sdxl_turbo.py

Thin wrapper around SDXL-Turbo for **concept art**, not for game output.

Image-to-3D needs an image, and a game's art plan is a list of sentences,
so something has to bridge the two. `qwen_edit.py` can do it by painting
over a blank canvas, but an editor asked to invent a whole subject is
being used against its grain. A distilled text-to-image model is the
right shape for the job: one to four steps, a few seconds per concept,
and a plain result that reconstructs cleanly.

The defaults here are chosen for reconstruction rather than for looking
good on their own, which is a real distinction:

* **`guidance_scale=0.0`** — SDXL-Turbo is trained without classifier-free
  guidance. Any other value degrades it, which is the most common way this
  model is misused.
* **square,512** — TRELLIS.2 crops to a square anyway, and a wide frame
  just means the subject arrives smaller.
* **a negative prompt naming shadows, ground planes and crops** — each of
  those becomes permanent geometry or permanent paint in the mesh. A cast
  shadow is baked into the albedo; a ground plane fuses to the subject; a
  crop simply ends the model where the image ended.

Usage:
    from models.gen_image.sdxl_turbo import SDXLTurboModel
    model = SDXLTurboModel(model_path="path/to/sdxl-turbo")
    image = model.generate(prompt="a wooden treasure chest ...", seed=42)
"""

import gc

import torch
from PIL import Image

#: Things that cost geometry or paint in the reconstruction, not taste.
#: The first line is the one that matters most: asked for a game asset,
#: this model happily produces a two-view turnaround sheet, and two
#: figures in one image reconstruct as two fused figures.
DEFAULT_NEGATIVE_PROMPT = (
    "character sheet, turnaround, multiple views, side by side, two "
    "figures, duplicate, collage, group, "
    "close-up, macro, zoomed in, cropped, cut off, out of frame, "
    "cast shadow, drop shadow, ground plane, floor, pedestal, base, "
    "busy background, scenery, text, watermark, signature, blurry, "
    "motion blur, depth of field"
)


class SDXLTurboModel:
    """
    Wraps `AutoPipelineForText2Image` for single-object concept art.

    Args:
        model_path (str): Local path or HuggingFace repo id.
        device (str): "cuda" or "cpu".
        steps (int): Denoising steps. SDXL-Turbo is distilled for 1-4.
        size (int): Square output resolution.
    """

    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
        steps: int = 4,
        size: int = 512,
    ):
        self.model_path = model_path
        self.device = device
        self.steps = int(steps)
        self.size = int(size)
        self.dtype = (
            torch.float16
            if device == "cuda"
            else torch.float32
        )
        self.pipe = None
        self.load()

    def load(self):
        """Load (or reload) the pipeline onto self.device."""
        if self.pipe is not None:
            return
        from diffusers import AutoPipelineForText2Image

        self.pipe = AutoPipelineForText2Image.from_pretrained(
            self.model_path,
            torch_dtype=self.dtype,
            variant=None,
            safety_checker=None,
        ).to(self.device)
        self.pipe.set_progress_bar_config(disable=True)

    def unload(self):
        """Free VRAM. Safe to call multiple times.

        Worth calling before TRELLIS.2 runs: 16GB of image-to-3D weights
        and an SDXL pipeline do not have to be resident at the same time.
        """
        if self.pipe is not None:
            try:
                self.pipe.to("cpu")
            except Exception:
                pass
            del self.pipe
            self.pipe = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

    def generate(
        self,
        prompt: str,
        seed: int = 42,
        steps: int | None = None,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    ) -> Image.Image:
        """Render one concept image."""
        if self.pipe is None:
            self.load()
        generator = torch.Generator(device=self.device).manual_seed(int(seed))
        with torch.inference_mode():
            return self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=int(steps or self.steps),
                # SDXL-Turbo is trained without CFG; anything above zero
                # makes it worse, not more faithful.
                guidance_scale=0.0,
                height=self.size,
                width=self.size,
                generator=generator,
            ).images[0]
