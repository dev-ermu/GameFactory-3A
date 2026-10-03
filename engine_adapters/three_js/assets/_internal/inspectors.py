"""Source inspectors for three.js-compatible artifacts.

These probes are pure Python so validation, reflection, and metadata
extraction stay available without a Node process or a browser.
"""

import json
import struct
from pathlib import Path
from typing import Any


GLB_MAGIC = 0x46546C67
GLB_CHUNK_JSON = 0x4E4F534A
GLB_CHUNK_BIN = 0x004E4942

MESH_SUFFIXES = {
    ".glb": "gltf_binary",
    ".gltf": "gltf",
    ".fbx": "fbx",
    ".obj": "obj",
    ".stl": "stl",
    ".ply": "ply",
    ".usdz": "usdz",
    ".splat": "gaussian_splat",
}
TEXTURE_SUFFIXES = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".ktx2": "ktx2",
    ".basis": "basis",
    ".hdr": "hdr",
    ".exr": "exr",
    ".tga": "tga",
}
AUDIO_SUFFIXES = {
    ".mp3": "mp3",
    ".ogg": "ogg",
    ".wav": "wav",
    ".m4a": "m4a",
}
DATA_SUFFIXES = {
    ".json": "json",
    ".bin": "binary",
}

STREAMABLE_REPRESENTATIONS = {
    "gltf",
    "gltf_binary",
    "ktx2",
    "basis",
}


class SourceInspectionError(ValueError):
    """Raised when a source artifact cannot be inspected."""


def classify_suffix(path: Path) -> tuple[str, str]:
    """Return ``(family, representation)`` for one source file."""

    suffix = path.suffix.lower()
    if suffix in MESH_SUFFIXES:
        return "mesh", MESH_SUFFIXES[suffix]
    if suffix in TEXTURE_SUFFIXES:
        return "texture", TEXTURE_SUFFIXES[suffix]
    if suffix in AUDIO_SUFFIXES:
        return "audio", AUDIO_SUFFIXES[suffix]
    if suffix in DATA_SUFFIXES:
        return "data", DATA_SUFFIXES[suffix]
    return "unknown", suffix.lstrip(".")


def read_gltf_document(path: Path) -> dict[str, Any]:
    """Read the JSON document of a ``.gltf`` or ``.glb`` file."""

    suffix = path.suffix.lower()
    if suffix == ".gltf":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SourceInspectionError(
                f"glTF document is not readable JSON: {path}"
            ) from exc
        if not isinstance(document, dict):
            raise SourceInspectionError(
                f"glTF document must be an object: {path}"
            )
        return document
    if suffix != ".glb":
        raise SourceInspectionError(
            f"Not a glTF container: {path}"
        )

    data = path.read_bytes()
    if len(data) < 20:
        raise SourceInspectionError(f"GLB file is truncated: {path}")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise SourceInspectionError(
            f"GLB magic header is invalid: {path}"
        )
    if version != 2:
        raise SourceInspectionError(
            f"Only GLB version 2 is supported; found {version}: {path}"
        )
    offset = 12
    document: dict[str, Any] | None = None
    while offset + 8 <= min(len(data), total):
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + length]
        offset += length + (-length % 4)
        if chunk_type == GLB_CHUNK_JSON:
            try:
                decoded = json.loads(
                    chunk.decode("utf-8").rstrip("\x00")
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise SourceInspectionError(
                    f"GLB JSON chunk is invalid: {path}"
                ) from exc
            if isinstance(decoded, dict):
                document = decoded
            break
        if chunk_type != GLB_CHUNK_BIN:
            continue
    if document is None:
        raise SourceInspectionError(
            f"GLB file does not contain a JSON chunk: {path}"
        )
    return document


def _accessor_bounds(document: dict[str, Any]) -> dict[str, Any]:
    accessors = document.get("accessors")
    meshes = document.get("meshes")
    if not isinstance(accessors, list) or not isinstance(meshes, list):
        return {}
    position_indices: set[int] = set()
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives") or []:
            if not isinstance(primitive, dict):
                continue
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict):
                continue
            index = attributes.get("POSITION")
            if isinstance(index, int):
                position_indices.add(index)
    minimum: list[float] | None = None
    maximum: list[float] | None = None
    for index in sorted(position_indices):
        if not 0 <= index < len(accessors):
            continue
        accessor = accessors[index]
        if not isinstance(accessor, dict):
            continue
        low = accessor.get("min")
        high = accessor.get("max")
        if (
            not isinstance(low, list)
            or not isinstance(high, list)
            or len(low)< 3
            or len(high) < 3
        ):
            continue
        low_values = [float(item) for item in low[:3]]
        high_values = [float(item) for item in high[:3]]
        if minimum is None or maximum is None:
            minimum, maximum = low_values, high_values
            continue
        minimum = [min(a, b) for a, b in zip(minimum, low_values)]
        maximum = [max(a, b) for a, b in zip(maximum, high_values)]
    if minimum is None or maximum is None:
        return {}
    return {
        "min": minimum,
        "max": maximum,
        "size": [
            round(high - low, 6)
            for low, high in zip(minimum, maximum)
        ],
        "center": [
            round((high + low) / 2.0, 6)
            for low, high in zip(minimum, maximum)
        ],
    }


def _triangle_count(document: dict[str, Any]) -> int:
    accessors = document.get("accessors")
    meshes = document.get("meshes")
    if not isinstance(accessors, list) or not isinstance(meshes, list):
        return 0
    total = 0
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives") or []:
            if not isinstance(primitive, dict):
                continue
            mode = primitive.get("mode", 4)
            if mode not in {4, None}:
                continue
            index = primitive.get("indices")
            if not isinstance(index, int):
                attributes = primitive.get("attributes") or {}
                index = attributes.get("POSITION")
            if not isinstance(index, int):
                continue
            if not 0 <= index < len(accessors):
                continue
            accessor = accessors[index]
            if not isinstance(accessor, dict):
                continue
            count = accessor.get("count")
            if isinstance(count, int):
                total += count // 3
    return total


def inspect_gltf(path: Path) -> dict[str, Any]:
    """Inspect a glTF or GLB artifact without loading it into three.js."""

    document = read_gltf_document(path)
    animations = [
        str(item.get("name") or f"clip_{index}")
        for index, item in enumerate(document.get("animations") or [])
        if isinstance(item, dict)
    ]
    scenes = document.get("scenes") or []
    nodes = document.get("nodes") or []
    skins = document.get("skins") or []
    materials = [
        str(item.get("name") or f"material_{index}")
        for index, item in enumerate(document.get("materials") or [])
        if isinstance(item, dict)
    ]
    asset = document.get("asset")
    asset_info = asset if isinstance(asset, dict) else {}
    extensions = sorted(
        {
            str(item)
            for item in (document.get("extensionsUsed") or [])
            if isinstance(item, str)
        }
    )
    required = sorted(
        {
            str(item)
            for item in (document.get("extensionsRequired") or [])
            if isinstance(item, str)
        }
    )
    return {
        "generator": str(asset_info.get("generator") or ""),
        "gltf_version": str(asset_info.get("version") or ""),
        "scene_count": len(scenes) if isinstance(scenes, list) else 0,
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "mesh_count": len(document.get("meshes") or []),
        "material_count": len(materials),
        "materials": materials,
        "texture_count": len(document.get("textures") or []),
        "image_count": len(document.get("images") or []),
        "skin_count": len(skins) if isinstance(skins, list) else 0,
        "skinned": bool(skins),
        "animation_count": len(animations),
        "animations": animations,
        "triangle_count": _triangle_count(document),
        "bounds": _accessor_bounds(document),
        "extensions_used": extensions,
        "extensions_required": required,
        "draco_compressed": (
            "KHR_draco_mesh_compression" in extensions
        ),
        "meshopt_compressed": (
            "EXT_meshopt_compression" in extensions
        ),
    }


def _inspect_directory(path: Path) -> dict[str, Any]:
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file()
    )
    entries = [
        {
            "path": str(item.relative_to(path)).replace("\\", "/"),
            "bytes": item.stat().st_size,
            "family": classify_suffix(item)[0],
            "representation": classify_suffix(item)[1],
        }
        for item in files
    ]
    entry_points = [
        item["path"]
        for item in entries
        if item["representation"] in {"gltf", "gltf_binary"}
    ]
    return {
        "family": "package",
        "representation": "asset_package",
        "file_count": len(entries),
        "bytes": sum(int(item["bytes"]) for item in entries),
        "files": entries[:256],
        "entry_points": entry_points,
    }


def inspect_source(
    path: Path,
    *,
    asset_type: str = "",
) -> dict[str, Any]:
    """Inspect one resolved source artifact for the web backend."""

    resolved = Path(path)
    if resolved.is_dir():
        payload = _inspect_directory(resolved)
        payload["asset_type"] = str(asset_type or "")
        payload["source_path"] = str(resolved)
        return payload
    if not resolved.is_file():
        raise SourceInspectionError(
            f"Source artifact was not found: {resolved}"
        )

    family, representation = classify_suffix(resolved)
    payload: dict[str, Any] = {
        "asset_type": str(asset_type or ""),
        "source_path": str(resolved),
        "family": family,
        "representation": representation,
        "bytes": resolved.stat().st_size,
        "streamable": representation in STREAMABLE_REPRESENTATIONS,
        "web_ready": representation
        in {
            "gltf",
            "gltf_binary",
            "png",
            "jpeg",
            "webp",
            "ktx2",
            "basis",
            "hdr",
            "mp3",
            "ogg",
            "wav",
            "json",
        },
    }
    if representation in {"gltf", "gltf_binary"}:
        payload.update(inspect_gltf(resolved))
    return payload
