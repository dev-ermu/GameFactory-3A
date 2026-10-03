"""Write rendered views to disk as labelled PNGs and one contact sheet.

The labels are the point of this module. A directory of five unlabelled
crops of a robot is a puzzle; the same five images captioned "camera on
+Z · screen right is +X" is a measurement. Since the whole purpose is to
let a vision model name an axis, the axis has to be legible inside the
image the model is shown — a filename is not visible to a reader that
was handed only pixels.
"""

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .views import label_for

_LABEL_HEIGHT = 26
_TITLE_HEIGHT = 30


def _font():
    from PIL import ImageFont

    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, 14)
            except Exception:
                continue
    return ImageFont.load_default()


def _label_text(axis: str) -> str:
    return label_for(axis)


def label_image(image: np.ndarray, axis: str):
    """Return a PIL image with the view's axis burnt into the frame."""

    from PIL import Image, ImageDraw

    height, width = image.shape[:2]
    canvas = Image.new(
        "RGB", (width, height + _LABEL_HEIGHT), (18, 20, 24)
    )
    canvas.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (8, height + 5),
        _label_text(axis),
        fill=(232, 236, 244),
        font=_font(),
    )
    return canvas


def write_views(
    images: Mapping[str, np.ndarray],
    output_dir: str | Path,
    *,
    stem: str,
) -> dict[str, str]:
    """Write one PNG per view; return``{axis: path}``."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for axis, image in images.items():
        safe = axis.replace("+", "p").replace("-", "n")
        path = directory / f"{stem}_view_{safe}.png"
        label_image(image, axis).save(path)
        written[axis] = str(path)
    return written


def write_contact_sheet(
    images: Mapping[str, np.ndarray],
    output_dir: str | Path,
    *,
    stem: str,
    title: str = "",
    columns: int = 0,
) -> str:
    """Write every view into one image, which is what a reviewer reads."""

    from PIL import Image, ImageDraw

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    tiles = [label_image(image, axis) for axis, image in images.items()]
    if not tiles:
        raise ValueError("No views to lay out")
    count = len(tiles)
    grid_columns = int(columns) or min(count, 2 if count <= 4 else 3)
    grid_rows = math.ceil(count / grid_columns)
    tile_width, tile_height = tiles[0].size
    gap = 6
    sheet = Image.new(
        "RGB",
        (
            grid_columns * tile_width + (grid_columns + 1) * gap,
            grid_rows * tile_height + (grid_rows + 1) * gap + _TITLE_HEIGHT,
        ),
        (12, 13, 16),
    )
    for index, tile in enumerate(tiles):
        row, column = divmod(index, grid_columns)
        sheet.paste(
            tile,
            (
                gap + column * (tile_width + gap),
                _TITLE_HEIGHT + gap + row * (tile_height + gap),
            ),
        )
    if title:
        ImageDraw.Draw(sheet).text(
            (gap + 2, 8), title, fill=(238, 240, 246), font=_font()
        )
    path = directory / f"{stem}_orientation_sheet.png"
    sheet.save(path)
    return str(path)


def sheet_title(
    asset_id: str,
    info: Mapping[str, Any],
    extra: Sequence[str] = (),
) -> str:
    size = info.get("bounds_size") or []
    dimensions = (
        " x ".join(f"{float(value):.3g}" for value in size) if size else "?"
    )
    parts = [
        asset_id or "asset",
        f"bbox {dimensions} units",
        f"{int(info.get('triangle_count') or 0)} tris",
    ]
    if info.get("skinned"):
        parts.append("skinned")
    parts.extend(str(item) for item in extra if item)
    return "  ·  ".join(parts)
