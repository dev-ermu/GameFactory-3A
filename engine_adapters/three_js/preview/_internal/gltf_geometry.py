"""Read a glTF/GLB document into plain numpy triangle surfaces.

The preview renderer must work where the rest of the adapter works: on
a headless build machine with no GPU, no display, no Node process, and
no OpenGL context. That rules out every mesh library in the usual
toolbox —``trimesh`` needs a rasteriser, ``pyrender`` needs EGL — so
the geometry is decoded here with nothing but ``numpy`` and ``Pillow``,
both of which the repository already depends on for image work.

What is decoded is deliberately the *bind pose*: node transforms are
composed down the scene graph, and a skinned mesh's own node transform
is ignored exactly as the glTF specification requires. A skinned vertex
in bind pose evaluates to the vertex as authored, because each joint's
world matrix is then the inverse of its inverse-bind matrix, so no skin
evaluation is needed to draw a character standing still. That is the
pose an orientation check wants anyway: an animated frame would confuse
"which way does this model face" with "where is it in its walk cycle".
"""

import base64
import json
import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np

GLB_MAGIC = 0x46546C67
GLB_CHUNK_JSON = 0x4E4F534A
GLB_CHUNK_BIN = 0x004E4942

_COMPONENT_DTYPES = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
_COMPONENT_NORMALIZERS = {
    5120: 127.0,
    5121: 255.0,
    5122: 32767.0,
    5123: 65535.0,
}
_TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}

#: Extensions that change how vertex data is stored. Without a decoder
#: the bytes are meaningless, so the reader says so instead of drawing
#: nonsense.
_BLOCKING_EXTENSIONS = {
    "KHR_draco_mesh_compression": "Draco geometry compression",
    "EXT_meshopt_compression": "meshopt geometry compression",
}


class GeometryUnavailable(RuntimeError):
    """Raised when a document cannot be decoded without a GPU decoder."""


@dataclass
class Surface:
    """One glTF primitive, flattened into scene space."""

    positions: np.ndarray  # (V, 3) float32
    normals: np.ndarray  # (V, 3) float32
    uvs: np.ndarray | None  # (V, 2) float32
    indices: np.ndarray  # (F, 3) int64
    base_color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    texture: Any | None = None  # PIL.Image.Image
    name: str = ""
    node_name: str = ""
    skinned: bool = False

    @property
    def triangle_count(self) -> int:
        return int(self.indices.shape[0])


@dataclass
class Geometry:
    """Every drawable surface of one document, plus its bounding box."""

    surfaces: list[Surface] = field(default_factory=list)
    source_path: str = ""

    @property
    def triangle_count(self) -> int:
        return sum(surface.triangle_count for surface in self.surfaces)

    @property
    def vertex_count(self) -> int:
        return sum(
            int(surface.positions.shape[0]) for surface in self.surfaces
        )

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.surfaces:
            zero = np.zeros(3, dtype=np.float64)
            return zero, zero
        low = np.full(3, np.inf)
        high = np.full(3, -np.inf)
        for surface in self.surfaces:
            if surface.positions.size == 0:
                continue
            low = np.minimum(low, surface.positions.min(axis=0))
            high = np.maximum(high, surface.positions.max(axis=0))
        if not np.all(np.isfinite(low)):
            zero = np.zeros(3, dtype=np.float64)
            return zero, zero
        return low.astype(np.float64), high.astype(np.float64)


# ── Container────────────────────────────────────────────────────────────────

def _read_container(path: Path) -> tuple[dict[str, Any], bytes | None]:
    suffix = path.suffix.lower()
    if suffix == ".gltf":
        return json.loads(path.read_text(encoding="utf-8")), None
    if suffix != ".glb":
        raise GeometryUnavailable(
            f"Not a glTF container: {path}"
        )
    data = path.read_bytes()
    if len(data) < 20:
        raise GeometryUnavailable(f"GLB file is truncated: {path}")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise GeometryUnavailable(f"GLB magic header is invalid: {path}")
    if version != 2:
        raise GeometryUnavailable(
            f"Only GLB version 2 is supported; found {version}"
        )
    offset = 12
    document: dict[str, Any] | None = None
    binary: bytes | None = None
    while offset + 8 <= min(len(data), total):
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + length]
        offset += length + (-length % 4)
        if chunk_type == GLB_CHUNK_JSON:
            document = json.loads(chunk.decode("utf-8").rstrip("\x00"))
        elif chunk_type == GLB_CHUNK_BIN:
            binary = chunk
    if document is None:
        raise GeometryUnavailable(
            f"GLB file carries no JSON chunk: {path}"
        )
    return document, binary


def _load_buffers(
    document: dict[str, Any],
    binary: bytes | None,
    base_dir: Path,
) -> list[bytes]:
    buffers: list[bytes] = []
    for index, buffer in enumerate(document.get("buffers") or []):
        uri = buffer.get("uri") if isinstance(buffer, dict) else None
        if not uri:
            buffers.append(binary or b"")
            continue
        if uri.startswith("data:"):
            _, _, payload = uri.partition(",")
            buffers.append(base64.b64decode(payload))
            continue
        candidate = (base_dir / uri).resolve()
        try:
            candidate.relative_to(base_dir.resolve())
        except ValueError as exc:
            raise GeometryUnavailable(
                f"buffer {index} escapes the asset directory: {uri}"
            ) from exc
        if not candidate.is_file():
            raise GeometryUnavailable(
                f"buffer {index} is missing: {candidate}"
            )
        buffers.append(candidate.read_bytes())
    return buffers


# ── Accessors ────────────────────────────────────────────────────────────────

def _read_accessor(
    document: dict[str, Any],
    buffers: list[bytes],
    index: int,
) -> np.ndarray:
    accessors = document.get("accessors") or []
    if not 0 <= index < len(accessors):
        raise GeometryUnavailable(f"accessor {index} is out of range")
    accessor = accessors[index]
    count = int(accessor.get("count") or 0)
    components = _TYPE_COMPONENTS[str(accessor.get("type") or "SCALAR")]
    component_type = int(accessor.get("componentType") or 5126)
    dtype = _COMPONENT_DTYPES.get(component_type)
    if dtype is None:
        raise GeometryUnavailable(
            f"accessor {index} uses componentType {component_type}"
        )
    item_bytes = np.dtype(dtype).itemsize * components

    view_index = accessor.get("bufferView")
    if view_index is None:
        values = np.zeros((count, components), dtype=np.float64)
    else:
        views = document.get("bufferViews") or []
        view = views[int(view_index)]
        buffer = buffers[int(view.get("buffer") or 0)]
        view_offset = int(view.get("byteOffset") or 0)
        stride = int(view.get("byteStride") or 0) or item_bytes
        start = view_offset + int(accessor.get("byteOffset") or 0)
        if stride == item_bytes:
            raw = np.frombuffer(
                buffer,
                dtype=dtype,
                count=count * components,
                offset=start,
            )
            values = raw.reshape(count, components).astype(np.float64)
        else:
            # Interleaved vertex buffer: take one strided slice per row.
            raw = np.frombuffer(
                buffer,
                dtype=np.uint8,
                count=stride * (count - 1) + item_bytes,
                offset=start,
            )
            rows = np.lib.stride_tricks.as_strided(
                raw,
                shape=(count, item_bytes),
                strides=(stride, 1),
            )
            values = (
                np.ascontiguousarray(rows)
                .view(dtype)
                .reshape(count, components)
                .astype(np.float64)
            )

    if accessor.get("sparse"):
        values = _apply_sparse(document, buffers, accessor, values)
    if accessor.get("normalized") and component_type in _COMPONENT_NORMALIZERS:
        values = values / _COMPONENT_NORMALIZERS[component_type]
        if component_type in {5120, 5122}:
            values = np.maximum(values, -1.0)
    return values


def _apply_sparse(
    document: dict[str, Any],
    buffers: list[bytes],
    accessor: dict[str, Any],
    values: np.ndarray,
) -> np.ndarray:
    sparse = accessor.get("sparse") or {}
    count = int(sparse.get("count") or 0)
    if count <= 0:
        return values
    indices_spec = sparse.get("indices") or {}
    values_spec = sparse.get("values") or {}
    views = document.get("bufferViews") or []

    def _slice(spec: dict[str, Any], dtype, components: int) -> np.ndarray:
        view = views[int(spec.get("bufferView") or 0)]
        buffer = buffers[int(view.get("buffer") or 0)]
        offset = int(view.get("byteOffset") or 0) + int(
            spec.get("byteOffset") or 0
        )
        raw = np.frombuffer(
            buffer, dtype=dtype, count=count * components, offset=offset
        )
        return raw.reshape(count, components)

    index_dtype = _COMPONENT_DTYPES[
        int(indices_spec.get("componentType") or 5125)
    ]
    target = _slice(indices_spec, index_dtype, 1).reshape(-1).astype(np.int64)
    replacement = _slice(
        values_spec,
        _COMPONENT_DTYPES[int(accessor.get("componentType") or 5126)],
        values.shape[1],
    ).astype(np.float64)
    values = values.copy()
    values[target] = replacement
    return values


# ── Node hierarchy ───────────────────────────────────────────────────────────

def _node_matrix(node: dict[str, Any]) -> np.ndarray:
    matrix = node.get("matrix")
    if isinstance(matrix, list) and len(matrix) == 16:
        # glTF stores matrices column-major.
        return np.array(matrix, dtype=np.float64).reshape(4, 4).T
    result = np.eye(4)
    scale = node.get("scale")
    if isinstance(scale, list) and len(scale) == 3:
        result[:3, :3] = np.diag([float(value) for value in scale])
    rotation = node.get("rotation")
    if isinstance(rotation, list) and len(rotation) == 4:
        x, y, z, w = (float(value) for value in rotation)
        rotation_matrix = np.array(
            [
                [
                    1 - 2 * (y * y + z * z),
                    2 * (x * y - z * w),
                    2 * (x * z + y * w),
                ],
                [
                    2 * (x * y + z * w),
                    1 - 2 * (x * x + z * z),
                    2 * (y * z - x * w),
                ],
                [
                    2 * (x * z - y * w),
                    2 * (y * z + x * w),
                    1 - 2 * (x * x + y * y),
                ],
            ],
            dtype=np.float64,
        )
        result[:3, :3] = rotation_matrix @ result[:3, :3]
    translation = node.get("translation")
    if isinstance(translation, list) and len(translation) == 3:
        result[:3, 3] = [float(value) for value in translation]
    return result


# ── Materials and textures ───────────────────────────────────────────────────

def _load_image(
    document: dict[str, Any],
    buffers: list[bytes],
    base_dir: Path,
    image_index: int,
):
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard dependency
        return None
    images = document.get("images") or []
    if not 0 <= image_index < len(images):
        return None
    image = images[image_index]
    payload: bytes | None = None
    uri = image.get("uri")
    if isinstance(uri, str) and uri:
        if uri.startswith("data:"):
            _, _, encoded = uri.partition(",")
            payload = base64.b64decode(encoded)
        else:
            candidate = (base_dir / uri).resolve()
            if candidate.is_file():
                payload = candidate.read_bytes()
    elif image.get("bufferView") is not None:
        views = document.get("bufferViews") or []
        view = views[int(image["bufferView"])]
        buffer = buffers[int(view.get("buffer") or 0)]
        offset = int(view.get("byteOffset") or 0)
        length = int(view.get("byteLength") or 0)
        payload = buffer[offset:offset + length]
    if not payload:
        return None
    try:
        decoded = Image.open(BytesIO(payload))
        decoded.load()
        return decoded.convert("RGB")
    except Exception:
        # A KTX2/Basis payload lands here. The base colour factor still
        # produces a readable silhouette, which is what a preview needs.
        return None


def _material_appearance(
    document: dict[str, Any],
    buffers: list[bytes],
    base_dir: Path,
    material_index: Any,
    texture_cache: dict[int, Any],
) -> tuple[tuple[float, float, float, float], Any | None]:
    default = (0.78, 0.78, 0.80, 1.0)
    materials = document.get("materials") or []
    if not isinstance(material_index, int):
        return default, None
    if not 0 <= material_index < len(materials):
        return default, None
    material = materials[material_index] or {}
    pbr = material.get("pbrMetallicRoughness") or {}
    factor = pbr.get("baseColorFactor")
    colour = default
    if isinstance(factor, list) and len(factor) >= 3:
        values = [float(item) for item in factor[:4]]
        while len(values) < 4:
            values.append(1.0)
        colour = (values[0], values[1], values[2], values[3])
    texture_ref = pbr.get("baseColorTexture") or {}
    texture = None
    index = texture_ref.get("index")
    if isinstance(index, int):
        textures = document.get("textures") or []
        if 0 <= index < len(textures):
            source = (textures[index] or {}).get("source")
            if isinstance(source, int):
                if source not in texture_cache:
                    texture_cache[source] = _load_image(
                        document, buffers, base_dir, source
                    )
                texture = texture_cache[source]
    return colour, texture


# ── Entry point ──────────────────────────────────────────────────────────────

def load_geometry(
    path: str | Path,
    *,
    with_textures: bool = True,
) -> Geometry:
    """Decode one glTF/GLB file into scene-space triangle surfaces."""

    resolved = Path(path)
    if not resolved.is_file():
        raise GeometryUnavailable(f"File was not found: {resolved}")
    document, binary = _read_container(resolved)

    required = {
        str(item)
        for item in (document.get("extensionsRequired") or [])
        if isinstance(item, str)
    }
    blocking = sorted(required & set(_BLOCKING_EXTENSIONS))
    if blocking:
        names = ", ".join(_BLOCKING_EXTENSIONS[item] for item in blocking)
        raise GeometryUnavailable(
            f"{resolved.name} requires {names}, which this dependency-free "
            "reader cannot decode. Re-export the artifact uncompressed to "
            "preview it."
        )

    buffers = _load_buffers(document, binary, resolved.parent)
    texture_cache: dict[int, Any] = {}
    geometry = Geometry(source_path=str(resolved))

    nodes = document.get("nodes") or []
    meshes = document.get("meshes") or []
    scenes = document.get("scenes") or []
    scene_index = int(document.get("scene") or 0)
    if 0 <= scene_index < len(scenes):
        roots = list((scenes[scene_index] or {}).get("nodes") or [])
    else:
        roots = list(range(len(nodes)))

    stack: list[tuple[int, np.ndarray]] = [
        (int(index), np.eye(4)) for index in reversed(roots)
    ]
    visited: set[int] = set()
    while stack:
        node_index, parent = stack.pop()
        if not 0 <= node_index < len(nodes) or node_index in visited:
            continue
        visited.add(node_index)
        node = nodes[node_index] or {}
        world = parent @ _node_matrix(node)
        for child in node.get("children") or []:
            stack.append((int(child), world))

        mesh_index = node.get("mesh")
        if not isinstance(mesh_index, int):
            continue
        if not 0 <= mesh_index < len(meshes):
            continue
        skinned = node.get("skin") is not None
        # The specification requires a skinned mesh's node transform to
        # be ignored: its vertices are already in skin space.
        transform = np.eye(4) if skinned else world
        mesh = meshes[mesh_index] or {}
        for primitive in mesh.get("primitives") or []:
            surface = _build_surface(
                document,
                buffers,
                resolved.parent,
                primitive,
                transform,
                texture_cache if with_textures else None,
                name=str(mesh.get("name") or f"mesh_{mesh_index}"),
                node_name=str(node.get("name") or f"node_{node_index}"),
                skinned=skinned,
            )
            if surface is not None:
                geometry.surfaces.append(surface)

    if not geometry.surfaces:
        raise GeometryUnavailable(
            f"{resolved.name} carries no triangle geometry to preview"
        )
    return geometry


def _build_surface(
    document: dict[str, Any],
    buffers: list[bytes],
    base_dir: Path,
    primitive: dict[str, Any],
    transform: np.ndarray,
    texture_cache: dict[int, Any] | None,
    *,
    name: str,
    node_name: str,
    skinned: bool,
) -> Surface | None:
    if not isinstance(primitive, dict):
        return None
    if int(primitive.get("mode", 4)) != 4:
        return None  # lines and points are not previewable content
    if set(primitive.get("extensions") or {}) & set(_BLOCKING_EXTENSIONS):
        raise GeometryUnavailable(
            "A primitive is compressed with an extension this reader "
            "cannot decode; re-export the artifact uncompressed."
        )
    attributes = primitive.get("attributes") or {}
    position_index = attributes.get("POSITION")
    if not isinstance(position_index, int):
        return None

    positions = _read_accessor(document, buffers, position_index)[:, :3]
    homogeneous = np.hstack(
        [positions, np.ones((positions.shape[0], 1))]
    )
    positions = (homogeneous @ transform.T)[:, :3]

    normal_index = attributes.get("NORMAL")
    if isinstance(normal_index, int):
        normals = _read_accessor(document, buffers, normal_index)[:, :3]
        rotation = transform[:3, :3]
        normals = normals @ rotation.T
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        normals = np.divide(
            normals,
            np.where(lengths > 1e-12, lengths, 1.0),
        )
    else:
        normals = np.zeros_like(positions)

    uv_index = attributes.get("TEXCOORD_0")
    uvs = (
        _read_accessor(document, buffers, uv_index)[:, :2]
        if isinstance(uv_index, int)
        else None
    )

    index_accessor = primitive.get("indices")
    if isinstance(index_accessor, int):
        flat = (
            _read_accessor(document, buffers, index_accessor)
            .reshape(-1)
            .astype(np.int64)
        )
    else:
        flat = np.arange(positions.shape[0], dtype=np.int64)
    usable = (flat.shape[0] // 3) * 3
    indices = flat[:usable].reshape(-1, 3)
    if indices.shape[0] == 0:
        return None

    colour, texture = (
        _material_appearance(
            document,
            buffers,
            base_dir,
            primitive.get("material"),
            texture_cache,
        )
        if texture_cache is not None
        else ((0.78, 0.78, 0.80, 1.0), None)
    )

    return Surface(
        positions=positions.astype(np.float32),
        normals=normals.astype(np.float32),
        uvs=uvs.astype(np.float32) if uvs is not None else None,
        indices=indices,
        base_color=colour,
        texture=texture,
        name=name,
        node_name=node_name,
        skinned=skinned,
    )
