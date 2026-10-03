"""A dependency-free orthographic renderer for orientation review.

The question this renderer exists to answer is narrow: *which way is
this model facing?* That makes the requirements unusual. Photographic
quality is worthless; unambiguous framing is everything. So each view is

* **orthographic**, because perspective foreshortening is exactly the
  cue that makes a viewer mistake a shoulder for a chest;
* **named after the axis the camera sits on**, not "front" or "back" —
  naming a view "front" would presuppose the answer being sought;
* **shot from a fixed distance with a shared world-to-pixel scale**, so
  the five images can be compared to each other.

Rendering happens by area-weighted point sampling rather than triangle
scan conversion. A per-triangle Python loop is unusable on a generated
mesh — TRELLIS.2 emits a million faces — while sampling is a handful of
fully vectorised numpy operations whose cost depends on the requested
sample budget instead of the model's complexity. Sampling a surface
densely and resolving visibility with a depth buffer gives a solid,
shaded, textured image; supersampling then downsampling removes the
speckle that point splatting would otherwise leave behind.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from .gltf_geometry import Geometry, Surface
from .views import (
    HORIZONTAL_VIEW_AXES,
    VIEW_AXES,
    VIEW_SCREEN_RIGHT,
)

_AXIS_VECTORS = {
    "+x": np.array([1.0, 0.0, 0.0]),
    "-x": np.array([-1.0, 0.0, 0.0]),
    "+y": np.array([0.0, 1.0, 0.0]),
    "-y": np.array([0.0, -1.0, 0.0]),
    "+z": np.array([0.0, 0.0, 1.0]),
    "-z": np.array([0.0, 0.0, -1.0]),
}

DEFAULT_BACKGROUND = (0.10, 0.11, 0.13)
DEFAULT_TARGET_SAMPLES = 3_000_000


@dataclass
class SurfaceSamples:
    """Points scattered over the surface, with shading inputs attached."""

    positions: np.ndarray  # (N, 3) float32
    normals: np.ndarray  # (N, 3) float32
    colors: np.ndarray  # (N, 3) float32 in linear-ish sRGB
    count: int


def _triangle_arrays(
    surface: Surface,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    corners = surface.positions[surface.indices]  # (F, 3, 3)
    edge_a = corners[:, 1] - corners[:, 0]
    edge_b = corners[:, 2] - corners[:, 0]
    face_normals = np.cross(edge_a, edge_b)
    areas = 0.5 * np.linalg.norm(face_normals, axis=1)
    return corners, face_normals, areas


def _sample_surface(
    surface: Surface,
    budget: int,
    rng: np.random.Generator,
) -> SurfaceSamples | None:
    """Scatter ``budget`` points over one primitive, area-weighted."""

    corners, face_normals, areas = _triangle_arrays(surface)
    if corners.shape[0] == 0:
        return None
    total_area = float(areas.sum())
    face_count = corners.shape[0]

    # Every triangle contributes its three corners regardless of size, so
    # a thin sliver — a blade, a wire, an antenna — never disappears.
    corner_positions = corners.reshape(-1, 3)
    extra = max(0, int(budget) - corner_positions.shape[0])

    if extra > 0 and total_area > 0:
        weights = areas / total_area
        picks = rng.choice(face_count, size=extra, p=weights)
        u = rng.random(extra)
        v = rng.random(extra)
        outside = (u + v) > 1.0
        u[outside] = 1.0 - u[outside]
        v[outside] = 1.0 - v[outside]
        bary = np.stack([1.0 - u - v, u, v], axis=1).astype(np.float32)
        picked = corners[picks]  # (extra, 3, 3)
        positions = np.einsum("nij,ni->nj", picked, bary)
        positions = np.vstack([corner_positions, positions])
        face_ids = np.concatenate(
            [np.repeat(np.arange(face_count), 3), picks]
        )
        corner_bary = np.tile(np.eye(3, dtype=np.float32), (face_count, 1))
        bary_all = np.vstack([corner_bary, bary])
    else:
        positions = corner_positions
        face_ids = np.repeat(np.arange(face_count), 3)
        bary_all = np.tile(np.eye(3, dtype=np.float32), (face_count, 1))

    if surface.normals.size and np.any(surface.normals):
        vertex_normals = surface.normals[surface.indices][face_ids]
        normals = np.einsum("nij,ni->nj", vertex_normals, bary_all)
    else:
        normals = face_normals[face_ids]
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, np.where(lengths > 1e-12, lengths, 1.0))

    colors = _sample_colors(surface, face_ids, bary_all)
    return SurfaceSamples(
        positions=positions.astype(np.float32),
        normals=normals.astype(np.float32),
        colors=colors.astype(np.float32),
        count=int(positions.shape[0]),
    )


def _sample_colors(
    surface: Surface,
    face_ids: np.ndarray,
    bary: np.ndarray,
) -> np.ndarray:
    base = np.array(surface.base_color[:3], dtype=np.float32)
    count = face_ids.shape[0]
    if surface.texture is None or surface.uvs is None:
        return np.tile(base, (count, 1))

    uv_corners = surface.uvs[surface.indices][face_ids]  # (N, 3, 2)
    uv = np.einsum("nij,ni->nj", uv_corners, bary)
    image = np.asarray(surface.texture, dtype=np.float32) / 255.0
    if image.ndim == 2:
        image = np.stack([image] * 3, axis=-1)
    height, width = image.shape[:2]
    # glTF UV origin is the top-left corner of the image.
    x = np.clip((uv[:, 0] % 1.0) * width, 0, width - 1).astype(np.int32)
    y = np.clip((uv[:, 1] % 1.0) * height, 0, height - 1).astype(np.int32)
    sampled = image[y, x, :3]
    return sampled * base


def sample_geometry(
    geometry: Geometry,
    *,
    target_samples: int = DEFAULT_TARGET_SAMPLES,
    seed: int = 7,
) -> SurfaceSamples:
    """Scatter one shared point cloud over every surface of a document."""

    rng = np.random.default_rng(seed)
    areas: list[float] = []
    for surface in geometry.surfaces:
        _, _, surface_areas = _triangle_arrays(surface)
        areas.append(float(surface_areas.sum()))
    total_area = sum(areas)

    chunks: list[SurfaceSamples] = []
    for surface, area in zip(geometry.surfaces, areas):
        share = (
            area / total_area
            if total_area > 0
            else 1.0 / max(1, len(geometry.surfaces))
        )
        budget = max(3 * surface.triangle_count, int(target_samples * share))
        sampled = _sample_surface(surface, budget, rng)
        if sampled is not None:
            chunks.append(sampled)
    if not chunks:
        raise ValueError("No surface produced samples")
    return SurfaceSamples(
        positions=np.vstack([chunk.positions for chunk in chunks]),
        normals=np.vstack([chunk.normals for chunk in chunks]),
        colors=np.vstack([chunk.colors for chunk in chunks]),
        count=sum(chunk.count for chunk in chunks),
    )


def _view_basis(axis: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(eye_direction, screen_right, screen_up)`` for one view."""

    eye = _AXIS_VECTORS[axis]
    up = (
        np.array([0.0, 0.0, -1.0])
        if abs(float(eye[1])) > 0.9
        else np.array([0.0, 1.0, 0.0])
    )
    right = np.cross(up, eye)
    right /= np.linalg.norm(right)
    screen_up = np.cross(eye, right)
    screen_up /= np.linalg.norm(screen_up)
    return eye, right, screen_up


def render_view(
    samples: SurfaceSamples,
    axis: str,
    *,
    centre: np.ndarray,
    radius: float,
    size: int = 384,
    supersample: int = 2,
    background: Sequence[float] = DEFAULT_BACKGROUND,
    shade: bool = True,
    denoise: bool = True,
) -> np.ndarray:
    """Render one orthographic view as an ``(size, size, 3)`` uint8 array."""

    if axis not in _AXIS_VECTORS:
        raise ValueError(f"Unknown view axis: {axis}")
    resolution = max(32, int(size)) * max(1, int(supersample))
    eye, right, screen_up = _view_basis(axis)

    relative = samples.positions.astype(np.float64) - centre
    screen_x = relative @ right
    screen_y = relative @ screen_up
    depth = relative @ eye  # larger is nearer the camera

    scale = (resolution * 0.5) / max(radius, 1e-9)
    px = np.rint(screen_x * scale + resolution * 0.5).astype(np.int64)
    py = np.rint(resolution * 0.5 - screen_y * scale).astype(np.int64)
    inside = (px >= 0) & (px < resolution) & (py >= 0) & (py < resolution)
    px, py, depth = px[inside], py[inside], depth[inside]
    flat = py * resolution + px

    depth_buffer = np.full(resolution * resolution, -np.inf)
    np.maximum.at(depth_buffer, flat, depth)

    # Keep only the samples that survived the depth test, then let later
    # writes win ties: any of them describes the same visible surface.
    visible = depth >= depth_buffer[flat] - 1e-9
    colors = samples.colors[inside][visible]
    normals = samples.normals[inside][visible]

    if shade:
        # A three-quarter key light plus a fill from the camera. Fixed in
        # *view* space, so every view of the model is lit identically and
        # a shading difference always means a geometry difference.
        key = eye * 0.55 + screen_up * 0.62 + right * 0.55
        key /= np.linalg.norm(key)
        lambert = np.clip(normals.astype(np.float64) @ key, 0.0, 1.0)
        rim = np.clip(np.abs(normals.astype(np.float64) @ eye), 0.0, 1.0)
        intensity = 0.28 + 0.66 * lambert + 0.12 * rim
        shaded = colors.astype(np.float64) * intensity[:, None]
    else:
        shaded = colors.astype(np.float64)
    shaded = np.clip(shaded, 0.0, 1.0)

    canvas = np.tile(
        np.array(background, dtype=np.float64), (resolution * resolution, 1)
    )
    canvas[flat[visible]] = shaded
    image = canvas.reshape(resolution, resolution, 3)

    factor = max(1, int(supersample))
    if denoise:
        image = _median_3x3(image)
    if factor > 1:
        final = max(32, int(size))
        image = image.reshape(final, factor, final, factor, 3).mean(
            axis=(1, 3)
        )
    return (np.clip(image, 0.0, 1.0) * 255.0).astype(np.uint8)


def _median_3x3(image: np.ndarray) -> np.ndarray:
    """Remove the speckle that point sampling leaves behind.

    Where a front surface happens to receive no sample, whatever lies
    behind it wins the depth test and a single dark pixel appears inside
    a lit region. A 3x3 median deletes exactly that — an isolated
    outlier — while leaving edges intact, which a blur would not. It runs
    at supersampled resolution, so the detail it costs is discarded by
    the downsample anyway.
    """

    try:
        from PIL import Image, ImageFilter
    except ImportError:  # pragma: no cover - Pillow is a dependency
        return image
    as_bytes = (np.clip(image, 0.0, 1.0) * 255.0).astype(np.uint8)
    filtered = Image.fromarray(as_bytes).filter(ImageFilter.MedianFilter(3))
    return np.asarray(filtered, dtype=np.float64) / 255.0


def framing(geometry: Geometry, *, margin: float = 1.06) -> tuple[
    np.ndarray, float
]:
    """Return the shared ``(centre, radius)`` every view is framed with."""

    low, high = geometry.bounds()
    centre = (low + high) * 0.5
    extent = float(np.max(high - low))
    radius = max(extent * 0.5 * float(margin), 1e-6)
    return centre, radius


def render_views(
    geometry: Geometry,
    axes: Iterable[str] = VIEW_AXES,
    *,
    size: int = 384,
    supersample: int = 2,
    target_samples: int = DEFAULT_TARGET_SAMPLES,
    background: Sequence[float] = DEFAULT_BACKGROUND,
    seed: int = 7,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Render every requested view and report how it was framed."""

    samples = sample_geometry(
        geometry, target_samples=target_samples, seed=seed
    )
    centre, radius = framing(geometry)
    images = {
        axis: render_view(
            samples,
            axis,
            centre=centre,
            radius=radius,
            size=size,
            supersample=supersample,
            background=background,
        )
        for axis in axes
    }
    low, high = geometry.bounds()
    info = {
        "sample_count": samples.count,
        "triangle_count": geometry.triangle_count,
        "vertex_count": geometry.vertex_count,
        "surface_count": len(geometry.surfaces),
        "textured_surface_count": sum(
            1 for surface in geometry.surfaces if surface.texture is not None
        ),
        "skinned": any(surface.skinned for surface in geometry.surfaces),
        "bounds_min": [round(float(value), 6) for value in low],
        "bounds_max": [round(float(value), 6) for value in high],
        "bounds_size": [round(float(value), 6) for value in (high - low)],
        "centre": [round(float(value), 6) for value in centre],
        "frame_radius": round(float(radius), 6),
        "metres_per_pixel": round(float(2.0 * radius / max(1, size)), 8),
        "screen_right_axis": {
            axis: VIEW_SCREEN_RIGHT.get(axis, "") for axis in images
        },
    }
    return images, info
