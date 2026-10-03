"""
engine_adapters/blender/runtime/vfx/grease_pencil.py

Drawn 2D effects — impact spokes, shock rings — as grease-pencil strokes.

**The API changed generation in Blender 4.3.** Strokes used to live on the frame
(`frame.strokes.new()`, points with `.co`) and now live on a drawing the frame
owns (`frame.drawing.add_strokes([...])`, points with `.position`); 5.0 removed
the old one. `_draw` writes both, because the retargeting side of this adapter
still supports 4.2.

**These objects cannot be rendered headless** — see `GL_ONLY_TYPES` in
`../../render_preview.py`. `../snapshot.py` hides them before rendering; they
draw normally in the `.blend` that `save_blend` writes.
"""

import math
from typing import Tuple

TEMPLATES = ("impact_lines", "ring")

#: Spokes in an `impact_lines` burst, or segments approximating a `ring`.
DEFAULT_SEGMENTS = 8


def spawn(name: str, location: Tuple[float, float, float],
          template: str = "impact_lines",
          color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
          radius: float = 0.6, segments: int = DEFAULT_SEGMENTS,
          line_width: float = 0.01, **_ignored) -> str:
    """
    Draw one `TEMPLATES` entry's worth of strokes. Returns the object's name.

    `radius` is metres from the centre to the end of a spoke or to the ring;
    `line_width` is the stroke's own radius, also in metres.
    """
    import bpy  # noqa: PLC0415

    if template not in TEMPLATES:
        raise ValueError(f"unknown grease-pencil template {template!r}; "
                         f"expected one of {', '.join(TEMPLATES)}")

    datablocks = getattr(bpy.data, "grease_pencils_v3", None) or bpy.data.grease_pencils
    data = datablocks.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location

    material = bpy.data.materials.new(f"{name}_material")
    bpy.data.materials.create_gpencil_data(material)
    material.grease_pencil.color = color
    data.materials.append(material)

    layer = data.layers.new("fx")
    frame = layer.frames.new(bpy.context.scene.frame_current)
    polylines = (_ring(radius, segments) if template == "ring"
                 else _impact_lines(radius, segments))
    _draw(frame, polylines, line_width, cyclic=(template == "ring"))
    return obj.name


def _impact_lines(radius: float, segments: int) -> list:
    """Spokes radiating from the centre."""
    lines = []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        lines.append([(0.0, 0.0, 0.0),
                      (math.cos(angle) * radius, math.sin(angle) * radius, 0.0)])
    return lines


def _ring(radius: float, segments: int) -> list:
    """One closed loop, as a single polyline."""
    return [[(math.cos(i * 2.0 * math.pi / segments) * radius,
              math.sin(i * 2.0 * math.pi / segments) * radius,
              0.0) for i in range(segments)]]


def _draw(frame, polylines: list, line_width: float, cyclic: bool) -> None:
    """Write polylines onto a frame, on whichever grease-pencil API is present."""
    drawing = getattr(frame, "drawing", None)
    if drawing is not None:
        drawing.add_strokes([len(points) for points in polylines])
        for stroke, points in zip(drawing.strokes, polylines):
            stroke.cyclic = cyclic
            for point, position in zip(stroke.points, points):
                point.position = position
                point.radius = line_width
                point.opacity = 1.0
        return

    for points in polylines:
        stroke = frame.strokes.new()
        stroke.display_mode = "3DSPACE"
        stroke.use_cyclic = cyclic
        stroke.points.add(len(points))
        for point, position in zip(stroke.points, points):
            point.co = position
            point.pressure = 1.0
