"""
models/common/glb_utils.py

Dependency-free inspection of binary glTF (`.glb`) buffers.

Why this exists instead of `trimesh.load(...)`: the API wrappers must report the
triangle count of what they just paid for (`api_model_require.md` R9.8), and
that number has to be available on a CPU-only box with nothing but the stdlib
installed. Parsing the JSON chunk of a GLB is enough for counting.

`glb_summary` and `glb_triangle_count` read the JSON chunk only. `read_glb_mesh`
decodes vertex data as well, because a generated part has to be *composed* with
primitives rather than merely counted, and that needs its triangles in the same
coordinate frame as everything else.

Usage:
    from models.common.glb_utils import glb_summary, read_glb_mesh
    info = glb_summary(open("model.glb", "rb").read())
    print(info["triangles"], info["materials"])

    mesh = read_glb_mesh(open("part.glb", "rb").read())
    print(len(mesh["positions"]), mesh["low"], mesh["high"])
"""

import json
import math
import struct
from typing import Any, Optional, Sequence

GLB_MAGIC = b"glTF"

#: glTF primitive mode 4 == TRIANGLES. Only triangle primitives are counted.
_MODE_TRIANGLES = 4

#: glTF componentType -> (struct format, byte size). Indices are allowed to be
#: any of the unsigned types; positions are float in every file worth reading.
_COMPONENT_TYPES: dict[int, tuple[str, int]] = {
    5120: ("b", 1),   # BYTE
    5121: ("B", 1),   # UNSIGNED_BYTE
    5122: ("h", 2),   # SHORT
    5123: ("H", 2),   # UNSIGNED_SHORT
    5125: ("I", 4),   # UNSIGNED_INT
    5126: ("f", 4),   # FLOAT
}

#: glTF accessor type -> component count.
_TYPE_COUNTS: dict[str, int] = {
    "SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
    "MAT2": 4, "MAT3": 9, "MAT4": 16,
}


class GLBParseError(ValueError):
    """The buffer is not a GLB we can read."""


def is_glb(data: bytes) -> bool:
    """True when `data` starts with the 12-byte GLB header."""
    return len(data) >= 12 and data[:4] == GLB_MAGIC


def glb_json_chunk(data: bytes) -> dict[str, Any]:
    """
    Return the parsed JSON chunk of a GLB.

    Args:
        data: Whole `.glb` file content.

    Returns:
        The glTF document as a dict.

    Raises:
        GLBParseError: bad magic, truncated file, or a missing JSON chunk.
    """
    if not is_glb(data):
        raise GLBParseError(
            f"not a GLB: expected magic {GLB_MAGIC!r}, got {data[:4]!r}"
        )
    if len(data) < 20:
        raise GLBParseError(f"GLB truncated: {len(data)} bytes")

    _magic, version, total_len = struct.unpack_from("<4sII", data, 0)
    if total_len > len(data):
        raise GLBParseError(
            f"GLB header claims {total_len} bytes, buffer holds {len(data)}"
        )

    offset = 12
    while offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        chunk = data[offset:offset + chunk_len]
        offset += chunk_len
        if chunk_type == b"JSON":
            try:
                return json.loads(chunk.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise GLBParseError(f"GLB JSON chunk is not valid JSON: {e}") from e
    raise GLBParseError(f"GLB (version {version}) has no JSON chunk")


def glb_triangle_count(data: bytes) -> Optional[int]:
    """
    Triangle count of a GLB, or None when it cannot be determined.

    Counts every triangle-mode primitive of every mesh once, i.e. the *asset's*
    triangle budget, not the per-instance count after node duplication.

    Returns:
        int triangles, or None if the JSON chunk is unreadable.
    """
    try:
        doc = glb_json_chunk(data)
    except GLBParseError:
        return None

    accessors = doc.get("accessors", [])
    total = 0
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if prim.get("mode", _MODE_TRIANGLES) != _MODE_TRIANGLES:
                continue
            idx = prim.get("indices")
            if idx is not None and idx < len(accessors):
                count = accessors[idx].get("count", 0)
            else:
                pos = prim.get("attributes", {}).get("POSITION")
                count = accessors[pos].get("count", 0) if pos is not None and pos < len(accessors) else 0
            total += count // 3
    return total


def glb_summary(data: bytes) -> dict[str, Any]:
    """
    Cheap description of a GLB, for logs and `meta.json`.

    Returns:
        dict with keys:
            bytes (int)            — buffer size
            triangles (int | None) — see `glb_triangle_count`
            meshes, materials, textures, images, nodes (int)
            generator (str | None) — glTF `asset.generator`
            error (str)            — present only when the JSON chunk is unreadable
    """
    out: dict[str, Any] = {"bytes": len(data)}
    try:
        doc = glb_json_chunk(data)
    except GLBParseError as e:
        out.update({"triangles": None, "error": str(e)})
        return out

    out.update({
        "triangles": glb_triangle_count(data),
        "meshes": len(doc.get("meshes", [])),
        "materials": len(doc.get("materials", [])),
        "textures": len(doc.get("textures", [])),
        "images": len(doc.get("images", [])),
        "nodes": len(doc.get("nodes", [])),
        "generator": (doc.get("asset") or {}).get("generator"),
    })
    return out


# --------------------------------------------------------------------------
# Vertex decoding
#
# Needed to *compose* a generated part with primitives, as opposed to merely
# reporting on it: composition means putting its triangles into the same
# coordinate frame as the rest, and that requires reading them.
# --------------------------------------------------------------------------


def glb_binary_chunk(data: bytes) -> bytes:
    """Return the BIN chunk of a GLB, or b"" when there is none."""
    if not is_glb(data):
        raise GLBParseError(f"not a GLB: got magic {data[:4]!r}")
    offset = 12
    while offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        if chunk_type == b"BIN\x00":
            return data[offset:offset + chunk_len]
        offset += chunk_len
    return b""


def _read_accessor(doc: dict[str, Any], binary: bytes, index: int) -> list[tuple]:
    """Decode one accessor into a list of component tuples.

    Honours ``byteStride``. Interleaved buffers are normal out of an
    exporter, and reading one as tightly packed yields positions that are a
    silent mixture of coordinates and normals — it parses, it renders, it is
    garbage.
    """

    accessor = doc["accessors"][index]
    component_type = accessor["componentType"]
    if component_type not in _COMPONENT_TYPES:
        raise GLBParseError(f"unsupported componentType {component_type}")
    fmt, component_size = _COMPONENT_TYPES[component_type]
    per_element = _TYPE_COUNTS[accessor["type"]]
    count = accessor["count"]

    view_index = accessor.get("bufferView")
    if view_index is None:
        # A sparse or zero-filled accessor. Legal, and not something a mesh
        # we are about to weld into another asset should be relying on.
        return [tuple([0] * per_element)] * count

    view = doc["bufferViews"][view_index]
    if view.get("buffer", 0) != 0:
        raise GLBParseError("only single-buffer GLBs are supported")
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    packed = component_size * per_element
    stride = view.get("byteStride") or packed

    out: list[tuple] = []
    element_format = "<" + fmt * per_element
    for element in range(count):
        start = base + element * stride
        if start + packed > len(binary):
            raise GLBParseError(
                f"accessor {index} reads past the {len(binary)}-byte buffer"
            )
        out.append(struct.unpack_from(element_format, binary, start))
    return out


def _node_matrix(node: dict[str, Any]) -> list[float]:
    """A node's local transform as a 16-float column-major matrix.

    Handles both an explicit ``matrix`` and a TRS triple, since a file may use
    either. Ignoring the transform looks like a modelling error: a mesh
    authored Z-up whose node carries the -90 that stands it upright arrives on
    its side, and the natural reaction is to rotate it back in the spec —
    hard-coding a correction for something the file already stated.
    """

    if "matrix" in node:
        return [float(value) for value in node["matrix"]]

    tx, ty, tz = [float(value) for value in node.get("translation", (0, 0, 0))]
    qx, qy, qz, qw = [float(value) for value in node.get("rotation", (0, 0, 0, 1))]
    sx, sy, sz = [float(value) for value in node.get("scale", (1, 1, 1))]

    # Quaternion to rotation matrix.
    xx, yy, zz = qx * qx, qy * qy, qz * qz
    xy, xz, yz = qx * qy, qx * qz, qy * qz
    wx, wy, wz = qw * qx, qw * qy, qw * qz
    rotation = (
        (1 - 2 * (yy + zz), 2 * (xy + wz), 2 * (xz - wy)),
        (2 * (xy - wz), 1 - 2 * (xx + zz), 2 * (yz + wx)),
        (2 * (xz + wy), 2 * (yz - wx), 1 - 2 * (xx + yy)),
    )
    scale = (sx, sy, sz)
    return [
        rotation[0][0] * scale[0], rotation[0][1] * scale[0], rotation[0][2] * scale[0], 0.0,
        rotation[1][0] * scale[1], rotation[1][1] * scale[1], rotation[1][2] * scale[1], 0.0,
        rotation[2][0] * scale[2], rotation[2][1] * scale[2], rotation[2][2] * scale[2], 0.0,
        tx, ty, tz, 1.0,
    ]


def _multiply(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Column-major 4x4 product, applying `b` then `a`."""
    out = [0.0] * 16
    for column in range(4):
        for row in range(4):
            out[column * 4 + row] = sum(
                a[k * 4 + row] * b[column * 4 + k] for k in range(4)
            )
    return out


_IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def read_glb_mesh(data: bytes) -> dict[str, Any]:
    """Decode every triangle of a GLB into one flat, world-space mesh.

    Walks the scene graph and applies each node's accumulated transform, so
    the result is in the file's own world coordinates rather than in the
    local frame of whichever mesh happened to be first.

    The node hierarchy is deliberately *not* preserved. A part fetched from
    a generator is one object as far as the composition is concerned — the
    thing worth keeping addressable is the spec's part id, which the writer
    attaches, and a generator's internal node names ("mesh_0", "Object_2")
    are not names anything downstream can use.

    Returns:
        dict with ``positions`` and ``normals`` as lists of 3-tuples,
        ``uvs`` as 2-tuples, ``indices`` as a flat list, ``low``/``high`` as
        the axis-aligned bounds, and ``images`` / ``material_runs`` carrying
        whatever textures the file brought with it. Normals are generated
        per-face when the file omits them.

    Textures come across because a generated part's whole contribution is
    surface. Dropping them and letting the part inherit the spec's flat PBR
    factors is consistent but throws away the thing that was paid for: the
    stippling on a grip, the panel creases and decals on a car shell. That
    needs three things travelling together — UVs per vertex, the image
    bytes, and which triangles use which image — so ``material_runs``
    records index ranges rather than a single material for the part.
    """

    doc = glb_json_chunk(data)
    binary = glb_binary_chunk(data)
    if not binary:
        raise GLBParseError(
            "the GLB has no BIN chunk, so its vertex data is external; "
            "only self-contained GLBs can be composed"
        )

    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    indices: list[int] = []
    material_runs: list[dict[str, Any]] = []

    def add_mesh(mesh_index: int, matrix: Sequence[float]) -> None:
        # The inverse transpose of the upper 3x3, for the normals. A non-uniform
        # node scale makes the forward matrix wrong for them, and the symptom is
        # lighting that reads as a modelling error rather than as a bad import.
        normal_matrix = _inverse_transpose_3x3(matrix)

        for primitive in doc["meshes"][mesh_index].get("primitives", []):
            if primitive.get("mode", _MODE_TRIANGLES) != _MODE_TRIANGLES:
                continue
            attributes = primitive.get("attributes", {})
            if "POSITION" not in attributes:
                continue

            local = _read_accessor(doc, binary, attributes["POSITION"])
            base = len(positions)
            for x, y, z in local:
                positions.append((
                    matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
                    matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
                    matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
                ))

            if "NORMAL" in attributes:
                for nx, ny, nz in _read_accessor(doc, binary, attributes["NORMAL"]):
                    tx = normal_matrix[0] * nx + normal_matrix[3] * ny + normal_matrix[6] * nz
                    ty = normal_matrix[1] * nx + normal_matrix[4] * ny + normal_matrix[7] * nz
                    tz = normal_matrix[2] * nx + normal_matrix[5] * ny + normal_matrix[8] * nz
                    length = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
                    normals.append((tx / length, ty / length, tz / length))
            else:
                normals.extend([(0.0, 0.0, 0.0)] * len(local))

            # UVs are per-vertex and must stay aligned with positions, so a
            # primitive without them still contributes placeholders — a short
            # UV list would silently shift every following part's texturing.
            if "TEXCOORD_0" in attributes:
                uvs.extend(
                    (float(u), float(v))
                    for u, v in _read_accessor(doc, binary, attributes["TEXCOORD_0"])
                )
            else:
                uvs.extend([(0.0, 0.0)] * len(local))

            if "indices" in primitive and primitive["indices"] is not None:
                local_indices = [
                    value[0] for value in
                    _read_accessor(doc, binary, primitive["indices"])
                ]
            else:
                local_indices = list(range(len(local)))

            run_start = len(indices)
            indices.extend(base + value for value in local_indices)
            material_runs.append({
                "start": run_start,
                "count": len(local_indices),
                "material": primitive.get("material"),
            })

    def walk(node_index: int, parent: Sequence[float]) -> None:
        node = doc["nodes"][node_index]
        matrix = _multiply(parent, _node_matrix(node))
        if node.get("mesh") is not None:
            add_mesh(node["mesh"], matrix)
        for child in node.get("children", ()):
            walk(child, matrix)

    scenes = doc.get("scenes") or []
    scene = scenes[doc.get("scene", 0)] if scenes else None
    roots = scene.get("nodes", ()) if scene else range(len(doc.get("nodes", [])))
    for root in roots:
        walk(root, _IDENTITY)

    if not positions:
        raise GLBParseError("the GLB contains no triangle geometry")

    # Fill in any face normals the file left out, so a consumer never has to
    # ask whether normals are present.
    _fill_missing_normals(positions, normals, indices)

    low = tuple(min(point[axis] for point in positions) for axis in range(3))
    high = tuple(max(point[axis] for point in positions) for axis in range(3))
    return {
        "positions": positions,
        "normals": normals,
        "uvs": uvs,
        "indices": indices,
        "triangles": len(indices) // 3,
        "low": low,
        "high": high,
        "material_runs": material_runs,
        "materials": _read_materials(doc, binary),
        "has_uvs": any(u != 0.0 or v != 0.0 for u, v in uvs),
    }


def _read_materials(doc: dict[str, Any], binary: bytes) -> list[dict[str, Any]]:
    """Each material's PBR factors, its base-colour image and its MR image.

    Base colour and metallic-roughness. Not the normal or occlusion maps:
    those would give the composed asset a texture set the primitives beside it
    lack, and a car body with a normal map next to a flat-shaded spoiler reads
    as two assets. Metallic-roughness is different in kind — it is not detail
    on top of a surface, it is *which surface it is*.

    Taking the map is what makes the factors trustworthy. An exporter that puts
    those channels in a texture leaves the factors at glTF's default ``1.0`` to
    multiply it, so the two only mean anything together. This function used to
    take the colour alone and substitute dielectric defaults (``0.0``/``0.55``)
    on the grounds that inherited factors would render a polymer grip as
    sandblasted steel — true, but it threw away the answer to keep from
    guessing wrong. Plate armour came out as grey plastic: every generated
    piece of the knight had ``metallicFactor 1.0`` and an MR map in the file,
    and both were discarded.

    ``factors_from`` is still recorded, because a material with no map at all
    still has to fall back and a caller needs to know which happened.
    """

    out: list[dict[str, Any]] = []
    images = doc.get("images", [])
    textures = doc.get("textures", [])
    views = doc.get("bufferViews", [])

    def image_bytes(reference: dict[str, Any]) -> tuple[bytes | None, str | None]:
        index = reference.get("index")
        if index is None or index >= len(textures):
            return None, None
        image_index = textures[index].get("source")
        if image_index is None or image_index >= len(images):
            return None, None
        image = images[image_index]
        view_index = image.get("bufferView")
        if view_index is not None and view_index < len(views):
            view = views[view_index]
            start = view.get("byteOffset", 0)
            return (
                bytes(binary[start:start + view["byteLength"]]),
                image.get("mimeType") or "image/png",
            )
        if str(image.get("uri", "")).startswith("data:"):
            # A data URI is legal and some exporters emit one even in a GLB.
            # Decoded here so the caller never has to care which form was used.
            import base64

            header, _, payload = image["uri"].partition(",")
            return (
                base64.b64decode(payload),
                header.split(":")[1].split(";")[0] if ":" in header
                else "image/png",
            )
        return None, None

    for material in doc.get("materials", []):
        pbr = material.get("pbrMetallicRoughness") or {}
        colour_image, colour_mime = image_bytes(pbr.get("baseColorTexture") or {})
        mr_image, mr_mime = image_bytes(
            pbr.get("metallicRoughnessTexture") or {})

        if mr_image is not None:
            # The map is coming with us, so the factors mean what they say:
            # they scale it. glTF's default is 1.0 for exactly this case.
            metallic = float(pbr.get("metallicFactor", 1.0))
            roughness = float(pbr.get("roughnessFactor", 1.0))
            provenance = "file"
        elif (pbr.get("metallicRoughnessTexture") or {}).get("index") is not None:
            # A map is declared but its bytes could not be read. Falling back
            # to dielectric defaults, because inheriting factors written to
            # scale a map we do not have renders a polymer grip as steel.
            metallic, roughness, provenance = 0.0, 0.55, "assumed"
        else:
            metallic = float(pbr.get("metallicFactor", 1.0))
            roughness = float(pbr.get("roughnessFactor", 1.0))
            provenance = "file"

        out.append({
            "name": material.get("name") or "",
            "baseColor": [
                float(value)
                for value in pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
            ],
            "metallic": metallic,
            "roughness": roughness,
            "factors_from": provenance,
            "image": colour_image,
            "mimeType": colour_mime,
            "mrImage": mr_image,
            "mrMimeType": mr_mime,
        })
    return out


def _inverse_transpose_3x3(matrix: Sequence[float]) -> list[float]:
    """Inverse transpose of a column-major 4x4's rotation/scale block."""
    a = (matrix[0], matrix[1], matrix[2])
    b = (matrix[4], matrix[5], matrix[6])
    c = (matrix[8], matrix[9], matrix[10])
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant) < 1e-20:
        return [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
    # cofactor / determinant, already the inverse transpose.
    return [
        (b[1] * c[2] - b[2] * c[1]) / determinant,
        (b[2] * c[0] - b[0] * c[2]) / determinant,
        (b[0] * c[1] - b[1] * c[0]) / determinant,
        (a[2] * c[1] - a[1] * c[2]) / determinant,
        (a[0] * c[2] - a[2] * c[0]) / determinant,
        (a[1] * c[0] - a[0] * c[1]) / determinant,
        (a[1] * b[2] - a[2] * b[1]) / determinant,
        (a[2] * b[0] - a[0] * b[2]) / determinant,
        (a[0] * b[1] - a[1] * b[0]) / determinant,
    ]


def _fill_missing_normals(
    positions: list[tuple[float, float, float]],
    normals: list[tuple[float, float, float]],
    indices: list[int],
) -> None:
    """Replace zero-length normals with the area-weighted face average."""

    missing = [
        index for index, normal in enumerate(normals)
        if normal[0] == 0.0 and normal[1] == 0.0 and normal[2] == 0.0
    ]
    if not missing:
        return

    accumulated = {index: [0.0, 0.0, 0.0] for index in missing}
    needed = set(missing)
    for triangle in range(len(indices) // 3):
        ia, ib, ic = indices[triangle * 3:triangle * 3 + 3]
        if not (ia in needed or ib in needed or ic in needed):
            continue
        pa, pb, pc = positions[ia], positions[ib], positions[ic]
        e1 = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        e2 = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        cross = (
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0],
        )
        for index in (ia, ib, ic):
            if index in accumulated:
                for axis in range(3):
                    accumulated[index][axis] += cross[axis]

    for index, vector in accumulated.items():
        length = math.sqrt(sum(value * value for value in vector))
        normals[index] = (
            (vector[0] / length, vector[1] / length, vector[2] / length)
            if length > 1e-20 else (0.0, 1.0, 0.0)
        )
