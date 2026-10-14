"""
operators/gen_tpose_image/funcs/gen_tpose_image.py

gen_tpose_image — Generate a game-CG T-pose RGBA image from a reference character image.

Pipeline:
  1. Use a GenImageModel (e.g. SeedreamModel) to turn the reference image into
     a game-CG T-pose render on a pure white background.
  2. Derive the alpha channel from that white background: the prompt pins it to
     RGB 255,255,255 with no gradient and no cast shadow, so a threshold is
     enough and no matting model is involved.
  3. Post-process: validate alpha, tight-crop the foreground bbox, pad to a
     square canvas and resize to a fixed target size (1024 by default) so the
     result is directly consumable by downstream 3D pipelines.
"""

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

TPOSE_PROMPT = (
    "Transform this character into a high-quality game CG T-pose reference sheet. "
    "The character should stand upright with arms extended horizontally at shoulder height (T-pose), "
    "facing directly forward, on a pure solid white background (RGB 255,255,255). "
    "Keep the character's original appearance, costume, colors, and style. "
    "Render in a clean game-art / anime-CG style with clear outlines. "
    "No background scenery, no shadows on the floor. "
    "The background must be a flat, uniform, solid white color only — no gradients, no shadows cast on background."
)


# ---------------------------------------------------------------------------
# Step 1: Generate T-pose CG image
# ---------------------------------------------------------------------------

def _generate_tpose_rgb(
    gen_model,
    ref_image: Image.Image,
    description: str,
    seed: int,
    steps: int,
) -> Image.Image:
    """Call the image-edit model to produce the T-pose CG image (white-bg RGB)."""
    prompt = TPOSE_PROMPT
    if description:
        prompt = f"Character description: {description}. " + prompt
    return gen_model.request(ref_image, prompt=prompt, seed=seed, steps=steps)


# ---------------------------------------------------------------------------
# Step 2: Foreground extraction from the white background
# ---------------------------------------------------------------------------

def _extract_foreground(
    image: Image.Image,
    white_thresh: int = 235,
) -> Image.Image:
    """Turn the pure-white backdrop into an alpha channel.

    阈值抠图而非模型抠图是刻意的：提示词已把背景钉死为 RGB 255,255,255，
    无渐变、无投影，因此前景恰好是低于阈值的像素集合。引入模型只会增加
    依赖与失败模式，却不会改变结果。
    """
    rgb = np.array(image.convert("RGB"))
    white = (
        (rgb[..., 0] >= white_thresh)
        & (rgb[..., 1] >= white_thresh)
        & (rgb[..., 2] >= white_thresh)
    )

    # 按与白色的距离生成软 alpha，避免抗锯齿轮廓像素被硬切成全透明而留下黑边。
    min_channel = rgb.min(axis=2)
    distance = np.clip(white_thresh - min_channel, 0, white_thresh)
    alpha = np.where(white, 0, distance.astype(np.uint8))

    rgba = np.dstack([rgb, alpha])
    return Image.fromarray(rgba, "RGBA")


# ---------------------------------------------------------------------------
# Step 3: Post-process for downstream 3D
# ---------------------------------------------------------------------------

def _postprocess_for_3d(
    rgba: Image.Image,
    size: int = 1024,
    white_thresh: int = 240,
    padding: float = 0.05,
) -> Image.Image:
    """Validate alpha, tight-crop, pad to square, resize."""
    arr = np.array(rgba).copy()

    fg_pixel_count = (arr[..., 3] > 0).sum()
    total_pixels = arr.shape[0] * arr.shape[1]
    if fg_pixel_count < total_pixels * 0.01:
        print("[warn] Mask alpha nearly empty; falling back to white-bg removal.")
        rgb = arr[..., :3]
        white = (
            (rgb[..., 0] >= white_thresh)
            & (rgb[..., 1] >= white_thresh)
            & (rgb[..., 2] >= white_thresh)
        )
        arr[white, 3] = 0
        arr[~white, 3] = 255

    alpha = arr[..., 3]
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if rows.any() and cols.any():
        y_min, y_max = np.where(rows)[0][[0, -1]]
        x_min, x_max = np.where(cols)[0][[0, -1]]

        h_box = y_max - y_min
        w_box = x_max - x_min
        pad_y = int(h_box * padding)
        pad_x = int(w_box * padding)

        img_h, img_w = alpha.shape
        y_min = max(0, y_min - pad_y)
        y_max = min(img_h, y_max + pad_y)
        x_min = max(0, x_min - pad_x)
        x_max = min(img_w, x_max + pad_x)

        arr = arr[y_min:y_max, x_min:x_max]
        print(f"[crop] Foreground bbox: ({x_min},{y_min})-({x_max},{y_max}), "
              f"cropped size: {arr.shape[1]}x{arr.shape[0]}")
    else:
        print("[warn] No foreground pixels found after alpha fix; skipping crop.")

    rgba = Image.fromarray(arr, "RGBA")

    w, h = rgba.size
    side = max(w, h)
    square = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    square.paste(rgba, ((side - w) // 2, (side - h) // 2))
    return square.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def gen_tpose_image(
    ref_image: Image.Image,
    description: str,
    gen_model,
    seed: int = 42,
    steps: int = 40,
    target_size: int = 1024,
    return_intermediate: bool = False,
):
    """
    Generate a T-pose RGBA image from a reference character image.

    Args:
        ref_image:           Reference PIL image of the character.
        description:         Short text description of the character (can be empty).
        gen_model:           Loaded GenImageModel (e.g. SeedreamModel).
        seed:                Random seed for the image-edit model.
        steps:               Diffusion steps for the image-edit model.
        target_size:         Output canvas size (square).
        return_intermediate: If True, also return the white-bg RGB T-pose.

    Returns:
        RGBA PIL image (target_size x target_size, transparent background).
        If `return_intermediate=True`, returns a dict with keys
        {"tpose_rgb", "tpose_rgba"}.
    """
    # Step 1: image edit → white-bg T-pose
    tpose_rgb = _generate_tpose_rgb(gen_model, ref_image, description, seed, steps)

    # Step 2: foreground extraction from the white backdrop
    fg_rgba = _extract_foreground(tpose_rgb)

    # Step 3: post-process for downstream 3D
    fg_rgba = _postprocess_for_3d(fg_rgba, size=target_size)

    if return_intermediate:
        return {"tpose_rgb": tpose_rgb, "tpose_rgba": fg_rgba}
    return fg_rgba
