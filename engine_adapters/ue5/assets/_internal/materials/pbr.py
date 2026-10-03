"""PBR texture-set discovery for generated assets."""

import re
from pathlib import Path
from typing import Any


PBR_TEXTURE_CHANNELS = (
    "base_color",
    "normal",
    "roughness",
    "metallic",
    "specular",
    "ambient_occlusion",
    "opacity",
    "emissive",
)
SUPPORTED_TEXTURE_SUFFIXES = {
    ".bmp",
    ".exr",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".png",
    ".tga",
    ".tif",
    ".tiff",
}
CHANNEL_ALIASES = {
    "albedo": "base_color",
    "basecolor": "base_color",
    "base_color": "base_color",
    "color": "base_color",
    "diff": "base_color",
    "diffuse": "base_color",
    "normal": "normal",
    "normal_gl": "normal",
    "normal_dx": "normal",
    "nor": "normal",
    "nor_gl": "normal",
    "nor_dx": "normal",
    "rough": "roughness",
    "roughness": "roughness",
    "metal": "metallic",
    "metallic": "metallic",
    "metalness": "metallic",
    "spec": "specular",
    "specular": "specular",
    "ao": "ambient_occlusion",
    "ambient_occlusion": "ambient_occlusion",
    "occlusion": "ambient_occlusion",
    "alpha": "opacity",
    "mask": "opacity",
    "opacity": "opacity",
    "emit": "emissive",
    "emissive": "emissive",
}
CHANNEL_PATTERNS = (
    ("ambient_occlusion", ("ambient_occlusion", "occlusion", "_ao")),
    ("base_color", ("base_color", "basecolor", "albedo", "diffuse", "_diff", "_color")),
    ("normal", ("normal_gl", "normal_dx", "normal", "nor_gl", "nor_dx", "_nor")),
    ("roughness", ("roughness", "_rough")),
    ("metallic", ("metallic", "metalness", "_metal")),
    ("specular", ("specular", "_spec")),
    ("opacity", ("opacity", "_alpha", "_mask")),
    ("emissive", ("emissive", "_emit")),
)


def normalize_texture_channel(value: Any) -> str:
    normalized = re.sub(
        r"[^0-9a-z]+",
        "_",
        str(value or "").strip().lower(),
    ).strip("_")
    return CHANNEL_ALIASES.get(normalized, normalized)


def discover_pbr_textures(
    source_path: str | Path,
    explicit: dict[str, str | Path] | None = None,
    *,
    auto_discover: bool = True,
) -> dict[str, str]:
    """Find a conventional PBR texture set beside a mesh source."""
    source = Path(source_path).expanduser().resolve()
    result: dict[str, str] = {}
    for raw_channel, raw_path in (explicit or {}).items():
        channel = normalize_texture_channel(raw_channel)
        if channel not in PBR_TEXTURE_CHANNELS:
            continue
        path = Path(raw_path).expanduser().resolve()
        if path.is_file() and path.suffix.lower() in SUPPORTED_TEXTURE_SUFFIXES:
            result[channel] = str(path)

    if not auto_discover or not source.parent.is_dir():
        return result
    candidates = sorted(
        _texture_candidates(source.parent),
        key=lambda path: _candidate_score(path, source),
    )
    for path in candidates:
        if not _texture_matches_source(path, source):
            continue
        channel = _channel_for_path(path)
        if channel and channel not in result:
            result[channel] = str(path.resolve())
    return result


def _texture_candidates(root: Path):
    """Yield nearby textures without traversing unrelated directory trees."""
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                if path.is_file():
                    if path.suffix.lower() in SUPPORTED_TEXTURE_SUFFIXES:
                        yield path
                elif depth == 0 and path.is_dir():
                    pending.append((path, depth + 1))
            except OSError:
                continue


def _channel_for_path(path: Path) -> str:
    normalized = re.sub(
        r"[^0-9a-z]+",
        "_",
        path.stem.lower(),
    )
    padded = f"_{normalized}_"
    for channel, patterns in CHANNEL_PATTERNS:
        if any(pattern in padded for pattern in patterns):
            return channel
    return ""


def _candidate_score(path: Path, source: Path) -> tuple[int, int, str]:
    source_key = re.sub(r"[^0-9a-z]+", "_", source.stem.lower())
    source_key = re.sub(r"_(1k|2k|4k|8k)$", "", source_key)
    texture_key = re.sub(r"[^0-9a-z]+", "_", path.stem.lower())
    matching_source = 0 if source_key and source_key in texture_key else 1
    depth = len(path.relative_to(source.parent).parts)
    return matching_source, depth, path.as_posix().lower()


def _texture_matches_source(path: Path, source: Path) -> bool:
    source_key = re.sub(r"[^0-9a-z]+", "_", source.stem.lower())
    source_key = re.sub(
        r"_(1k|2k|4k|8k)$",
        "",
        source_key,
    ).strip("_")
    if not source_key:
        return False
    texture_key = re.sub(r"[^0-9a-z]+", "_", path.stem.lower())
    parent_key = re.sub(r"[^0-9a-z]+", "_", path.parent.name.lower())
    return source_key in texture_key or source_key in parent_key
