"""Validate mesh-backed PLY files and convert them to temporary OBJ files."""

import json
import math
import struct
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Sequence


_PLY_SCALAR_TYPES = {
    "char": ("b", int),
    "int8": ("b", int),
    "uchar": ("B", int),
    "uint8": ("B", int),
    "short": ("h", int),
    "int16": ("h", int),
    "ushort": ("H", int),
    "uint16": ("H", int),
    "int": ("i", int),
    "int32": ("i", int),
    "uint": ("I", int),
    "uint32": ("I", int),
    "long": ("q", int),
    "int64": ("q", int),
    "ulong": ("Q", int),
    "uint64": ("Q", int),
    "float": ("f", float),
    "float32": ("f", float),
    "double": ("d", float),
    "float64": ("d", float),
}
_FACE_INDEX_PROPERTY_NAMES = {
    "vertex_index",
    "vertex_indices",
    "vertex_indexes",
}
_INTEGER_SCALAR_TYPES = {
    name
    for name, (_, caster) in _PLY_SCALAR_TYPES.items()
    if caster is int
}
_MAX_LIST_LENGTH = 10_000_000


class PlyMeshError(ValueError):
    """Raised when a PLY file is not a valid polygon mesh."""


@dataclass(frozen=True)
class _PlyProperty:
    name: str
    value_type: str
    count_type: str = ""

    @property
    def is_list(self) -> bool:
        return bool(self.count_type)


@dataclass(frozen=True)
class _PlyElement:
    name: str
    count: int
    properties: tuple[_PlyProperty, ...]


@dataclass(frozen=True)
class _PlyHeader:
    encoding: str
    elements: tuple[_PlyElement, ...]


@dataclass(frozen=True)
class PlyMeshSummary:
    source_path: str
    output_path: str
    encoding: str
    vertex_count: int
    polygon_count: int
    triangle_count: int
    bounds_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: tuple[float, float, float] = (0.0, 0.0, 0.0)
    has_vertex_colors: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "output_path": self.output_path,
            "encoding": self.encoding,
            "vertex_count": self.vertex_count,
            "polygon_count": self.polygon_count,
            "triangle_count": self.triangle_count,
            "bounds_min": list(self.bounds_min),
            "bounds_max": list(self.bounds_max),
            "has_vertex_colors": self.has_vertex_colors,
        }


@dataclass(frozen=True)
class PlyGroundAlignment:
    source_path: str
    source_normal: tuple[float, float, float]
    rotation: dict[str, float]
    location_z_cm: float
    ground_z_before_offset_cm: float
    target_ground_z_cm: float
    ground_bounds_min_cm: tuple[float, float]
    ground_bounds_max_cm: tuple[float, float]
    sample_point_count: int
    grounded_sample_count: int
    sampled_triangle_count: int
    supporting_triangle_count: int
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "source_normal": list(self.source_normal),
            "rotation": dict(self.rotation),
            "location_z_cm": self.location_z_cm,
            "ground_z_before_offset_cm": self.ground_z_before_offset_cm,
            "target_ground_z_cm": self.target_ground_z_cm,
            "ground_bounds_min_cm": list(self.ground_bounds_min_cm),
            "ground_bounds_max_cm": list(self.ground_bounds_max_cm),
            "sample_point_count": self.sample_point_count,
            "grounded_sample_count": self.grounded_sample_count,
            "sampled_triangle_count": self.sampled_triangle_count,
            "supporting_triangle_count": self.supporting_triangle_count,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PreparedMeshSource:
    original_path: Path
    import_path: Path
    summary: PlyMeshSummary | None = None

    @property
    def converted(self) -> bool:
        return self.summary is not None


def _decode_header_line(raw_line: bytes, source: Path) -> str:
    try:
        return raw_line.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise PlyMeshError(f"PLY 头不是有效 ASCII: {source}") from exc


def _parse_header(handle: BinaryIO, source: Path) -> _PlyHeader:
    if _decode_header_line(handle.readline(), source) != "ply":
        raise PlyMeshError(f"不是有效的 PLY 文件: {source}")

    encoding = ""
    elements: list[_PlyElement] = []
    current_name = ""
    current_count = 0
    current_properties: list[_PlyProperty] = []

    def finish_element() -> None:
        nonlocal current_name, current_count, current_properties
        if not current_name:
            return
        elements.append(
            _PlyElement(
                name=current_name,
                count=current_count,
                properties=tuple(current_properties),
            )
        )
        current_name = ""
        current_count = 0
        current_properties = []

    while True:
        raw_line = handle.readline()
        if not raw_line:
            raise PlyMeshError(f"PLY 头缺少 end_header: {source}")
        line = _decode_header_line(raw_line, source)
        if not line or line.startswith("comment ") or line.startswith("obj_info "):
            continue
        parts = line.split()
        directive = parts[0]
        if directive == "format":
            if len(parts) != 3 or parts[2] != "1.0":
                raise PlyMeshError(f"不支持的 PLY format 声明: {line}")
            encoding = parts[1]
            if encoding not in {
                "ascii",
                "binary_little_endian",
                "binary_big_endian",
            }:
                raise PlyMeshError(f"不支持的 PLY 编码: {encoding}")
        elif directive == "element":
            if len(parts) != 3:
                raise PlyMeshError(f"无效的 PLY element 声明: {line}")
            finish_element()
            current_name = parts[1]
            try:
                current_count = int(parts[2])
            except ValueError as exc:
                raise PlyMeshError(f"无效的 PLY element 数量: {line}") from exc
            if current_count < 0:
                raise PlyMeshError(f"PLY element 数量不能为负数: {line}")
        elif directive == "property":
            if not current_name:
                raise PlyMeshError(f"PLY property 出现在 element 之前: {line}")
            if len(parts) == 3:
                value_type, name = parts[1], parts[2]
                _require_scalar_type(value_type)
                current_properties.append(
                    _PlyProperty(name=name, value_type=value_type)
                )
            elif len(parts) == 5 and parts[1] == "list":
                count_type, value_type, name = parts[2], parts[3], parts[4]
                _require_scalar_type(count_type)
                _require_scalar_type(value_type)
                if count_type not in _INTEGER_SCALAR_TYPES:
                    raise PlyMeshError(
                        f"PLY list count 类型必须是整数: {count_type}"
                    )
                current_properties.append(
                    _PlyProperty(
                        name=name,
                        value_type=value_type,
                        count_type=count_type,
                    )
                )
            else:
                raise PlyMeshError(f"无效的 PLY property 声明: {line}")
        elif directive == "end_header":
            finish_element()
            break

    if not encoding:
        raise PlyMeshError(f"PLY 头缺少 format 声明: {source}")
    if not elements:
        raise PlyMeshError(f"PLY 头没有 element: {source}")
    return _PlyHeader(encoding=encoding, elements=tuple(elements))


def _require_scalar_type(value_type: str) -> None:
    if value_type not in _PLY_SCALAR_TYPES:
        supported = ", ".join(sorted(_PLY_SCALAR_TYPES))
        raise PlyMeshError(
            f"不支持的 PLY 数据类型 {value_type}；支持: {supported}"
        )


def _cast_ascii(token: str, value_type: str) -> int | float:
    caster = _PLY_SCALAR_TYPES[value_type][1]
    try:
        return caster(token)
    except ValueError as exc:
        raise PlyMeshError(
            f"PLY 数据值 {token!r} 不符合类型 {value_type}"
        ) from exc


def _read_ascii_record(
    handle: BinaryIO,
    properties: tuple[_PlyProperty, ...],
) -> dict[str, int | float | list[int | float]]:
    while True:
        raw_line = handle.readline()
        if not raw_line:
            raise PlyMeshError("PLY 数据提前结束")
        try:
            line = raw_line.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise PlyMeshError("ASCII PLY 数据包含非 ASCII 字节") from exc
        if line:
            break

    tokens = line.split()
    cursor = 0
    result: dict[str, int | float | list[int | float]] = {}
    for prop in properties:
        if cursor >= len(tokens):
            raise PlyMeshError("PLY 数据列少于 header 中声明的 property")
        if not prop.is_list:
            result[prop.name] = _cast_ascii(tokens[cursor], prop.value_type)
            cursor += 1
            continue
        list_length = int(_cast_ascii(tokens[cursor], prop.count_type))
        cursor += 1
        if list_length < 0 or list_length > _MAX_LIST_LENGTH:
            raise PlyMeshError(f"PLY list 长度异常: {list_length}")
        end = cursor + list_length
        if end > len(tokens):
            raise PlyMeshError("PLY list 数据少于声明的长度")
        result[prop.name] = [
            _cast_ascii(token, prop.value_type)
            for token in tokens[cursor:end]
        ]
        cursor = end
    if cursor != len(tokens):
        raise PlyMeshError("PLY 数据列多于 header 中声明的 property")
    return result


def _read_binary_scalar(
    handle: BinaryIO,
    value_type: str,
    endian: str,
) -> int | float:
    format_code = _PLY_SCALAR_TYPES[value_type][0]
    scalar = struct.Struct(endian + format_code)
    raw_value = handle.read(scalar.size)
    if len(raw_value) != scalar.size:
        raise PlyMeshError("Binary PLY 数据提前结束")
    return scalar.unpack(raw_value)[0]


def _read_binary_record(
    handle: BinaryIO,
    properties: tuple[_PlyProperty, ...],
    endian: str,
) -> dict[str, int | float | list[int | float]]:
    result: dict[str, int | float | list[int | float]] = {}
    for prop in properties:
        if not prop.is_list:
            result[prop.name] = _read_binary_scalar(
                handle,
                prop.value_type,
                endian,
            )
            continue
        list_length = int(
            _read_binary_scalar(handle, prop.count_type, endian)
        )
        if list_length < 0 or list_length > _MAX_LIST_LENGTH:
            raise PlyMeshError(f"PLY list 长度异常: {list_length}")
        result[prop.name] = [
            _read_binary_scalar(handle, prop.value_type, endian)
            for _ in range(list_length)
        ]
    return result


def _record_reader(
    encoding: str,
):
    if encoding == "ascii":
        return lambda handle, properties: _read_ascii_record(
            handle,
            properties,
        )
    endian = "<" if encoding == "binary_little_endian" else ">"
    return lambda handle, properties: _read_binary_record(
        handle,
        properties,
        endian,
    )


def _required_mesh_elements(
    header: _PlyHeader,
) -> tuple[_PlyElement, _PlyElement, str]:
    vertex = next(
        (element for element in header.elements if element.name == "vertex"),
        None,
    )
    face = next(
        (element for element in header.elements if element.name == "face"),
        None,
    )
    if vertex is None or vertex.count <= 0:
        raise PlyMeshError("Collider PLY 必须包含至少一个 vertex")
    vertex_properties = {
        prop.name: prop
        for prop in vertex.properties
    }
    for coordinate in ("x", "y", "z"):
        prop = vertex_properties.get(coordinate)
        if prop is None or prop.is_list:
            raise PlyMeshError(
                f"Collider PLY 的 vertex 缺少标量坐标 {coordinate}"
            )
    if face is None or face.count <= 0:
        raise PlyMeshError(
            "PLY 没有 face 数据，可能是 Gaussian Splat/点云 PLY，"
            "不能作为 Collider Mesh"
        )
    face_lists = [prop for prop in face.properties if prop.is_list]
    index_property = next(
        (
            prop
            for prop in face_lists
            if prop.name.lower() in _FACE_INDEX_PROPERTY_NAMES
        ),
        face_lists[0] if len(face_lists) == 1 else None,
    )
    if index_property is None:
        raise PlyMeshError(
            "Collider PLY 的 face 缺少 vertex_indices list property"
        )
    if index_property.value_type not in _INTEGER_SCALAR_TYPES:
        raise PlyMeshError(
            "Collider PLY 的 face vertex_indices 必须使用整数类型"
        )
    return vertex, face, index_property.name


def _vertex_color_properties(
    vertex_element: _PlyElement,
) -> tuple[_PlyProperty, ...]:
    properties = {
        prop.name.lower(): prop
        for prop in vertex_element.properties
        if not prop.is_list
    }
    colors = tuple(
        properties.get(name)
        for name in ("red", "green", "blue")
    )
    if not all(colors):
        return ()
    alpha = properties.get("alpha")
    return (*colors, alpha) if alpha is not None else colors


def _color_byte(value: int | float, value_type: str) -> int:
    if not math.isfinite(float(value)):
        raise PlyMeshError("Collider PLY 包含非有限顶点颜色")
    if value_type in {"float", "float32", "double", "float64"}:
        numeric = float(value)
        if 0.0 <= numeric <= 1.0:
            numeric *= 255.0
        return max(0, min(255, round(numeric)))
    ranges = {
        "char": 127,
        "int8": 127,
        "uchar": 255,
        "uint8": 255,
        "short": 32767,
        "int16": 32767,
        "ushort": 65535,
        "uint16": 65535,
        "int": 2147483647,
        "int32": 2147483647,
        "uint": 4294967295,
        "uint32": 4294967295,
        "long": 9223372036854775807,
        "int64": 9223372036854775807,
        "ulong": 18446744073709551615,
        "uint64": 18446744073709551615,
    }
    maximum = ranges[value_type]
    numeric = max(0, int(value))
    if maximum == 255:
        return min(255, numeric)
    return max(0, min(255, round(numeric * 255.0 / maximum)))


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _copy_binary_stream(
    destination: BinaryIO,
    source: BinaryIO,
    byte_length: int,
) -> None:
    source.seek(0)
    remaining = byte_length
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            raise PlyMeshError("PLY 临时二进制缓冲区提前结束")
        destination.write(chunk)
        remaining -= len(chunk)


def _numpy_scalar_dtype(value_type: str, endian: str):
    import numpy as np

    codes = {
        "char": "i1",
        "int8": "i1",
        "uchar": "u1",
        "uint8": "u1",
        "short": "i2",
        "int16": "i2",
        "ushort": "u2",
        "uint16": "u2",
        "int": "i4",
        "int32": "i4",
        "uint": "u4",
        "uint32": "u4",
        "long": "i8",
        "int64": "i8",
        "ulong": "u8",
        "uint64": "u8",
        "float": "f4",
        "float32": "f4",
        "double": "f8",
        "float64": "f8",
    }
    code = codes[value_type]
    if code.endswith("1"):
        return np.dtype(code)
    return np.dtype(endian + code)


def _load_ply_triangle_geometry(source: Path):
    """Load PLY vertices and triangulated faces, with a fast binary path."""

    import numpy as np

    with source.open("rb") as handle:
        header = _parse_header(handle, source)
        data_offset = handle.tell()
        vertex_element, face_element, face_index_property = (
            _required_mesh_elements(header)
        )

    endian = (
        "<"
        if header.encoding == "binary_little_endian"
        else ">"
    )
    fixed_binary_layout = (
        header.encoding != "ascii"
        and len(header.elements) == 2
        and header.elements[0].name == vertex_element.name
        and header.elements[1].name == face_element.name
        and all(not prop.is_list for prop in vertex_element.properties)
        and len(face_element.properties) == 1
        and face_element.properties[0].is_list
        and face_element.properties[0].name == face_index_property
    )
    if fixed_binary_layout:
        vertex_dtype = np.dtype(
            [
                (
                    prop.name,
                    _numpy_scalar_dtype(prop.value_type, endian),
                )
                for prop in vertex_element.properties
            ],
            align=False,
        )
        vertex_records = np.memmap(
            source,
            mode="r",
            dtype=vertex_dtype,
            offset=data_offset,
            shape=(vertex_element.count,),
        )
        vertices = np.column_stack(
            [
                vertex_records["x"],
                vertex_records["y"],
                vertex_records["z"],
            ]
        ).astype(np.float64, copy=False)
        face_property = face_element.properties[0]
        count_dtype = _numpy_scalar_dtype(
            face_property.count_type,
            endian,
        )
        index_dtype = _numpy_scalar_dtype(
            face_property.value_type,
            endian,
        )
        face_offset = data_offset + vertex_element.count * vertex_dtype.itemsize
        remaining = source.stat().st_size - face_offset
        triangle_record_size = count_dtype.itemsize + 3 * index_dtype.itemsize
        if remaining == face_element.count * triangle_record_size:
            face_dtype = np.dtype(
                [
                    ("count", count_dtype),
                    ("i0", index_dtype),
                    ("i1", index_dtype),
                    ("i2", index_dtype),
                ],
                align=False,
            )
            face_records = np.memmap(
                source,
                mode="r",
                dtype=face_dtype,
                offset=face_offset,
                shape=(face_element.count,),
            )
            if bool(np.all(face_records["count"] == 3)):
                faces = np.column_stack(
                    [
                        face_records["i0"],
                        face_records["i1"],
                        face_records["i2"],
                    ]
                ).astype(np.int64, copy=False)
                return vertices, faces, header.encoding

    vertices_list: list[tuple[float, float, float]] = []
    faces_list: list[tuple[int, int, int]] = []
    with source.open("rb") as handle:
        header = _parse_header(handle, source)
        vertex_element, face_element, face_index_property = (
            _required_mesh_elements(header)
        )
        read_record = _record_reader(header.encoding)
        for element in header.elements:
            for _ in range(element.count):
                record = read_record(handle, element.properties)
                if element.name == vertex_element.name:
                    vertices_list.append(
                        tuple(
                            float(record[name])
                            for name in ("x", "y", "z")
                        )
                    )
                elif element.name == face_element.name:
                    raw_indices = record.get(face_index_property)
                    if not isinstance(raw_indices, list):
                        raise PlyMeshError(
                            "Collider PLY face 索引不是 list"
                        )
                    indices = [int(value) for value in raw_indices]
                    if len(indices) < 3:
                        raise PlyMeshError(
                            "Collider PLY 包含少于 3 个顶点的面"
                        )
                    for offset in range(1, len(indices) - 1):
                        faces_list.append(
                            (
                                indices[0],
                                indices[offset],
                                indices[offset + 1],
                            )
                        )
    vertices = np.asarray(vertices_list, dtype=np.float64)
    faces = np.asarray(faces_list, dtype=np.int64)
    return vertices, faces, header.encoding


def _alignment_sample_point(value: Any) -> tuple[float, float, float] | None:
    raw = value
    if isinstance(raw, dict) and isinstance(raw.get("location"), dict):
        raw = raw["location"]
    if isinstance(raw, dict):
        try:
            return (
                float(raw.get("x", 0.0)),
                float(raw.get("y", 0.0)),
                float(raw.get("z", 0.0)),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return (
                float(raw[0]),
                float(raw[1]),
                float(raw[2]) if len(raw) > 2 else 0.0,
            )
        except (TypeError, ValueError):
            return None
    return None


def _alignment_rotation(source_normal) -> tuple[float, float]:
    """Return UE pitch/roll that maps GLTF-local normal to world +Z."""

    nx, ny, nz = (float(value) for value in source_normal)
    local_y = -nz
    local_z = ny
    roll = math.atan2(-local_y, local_z)
    pitch = math.atan2(nx, math.hypot(local_y, local_z))
    return math.degrees(pitch), math.degrees(roll)


def _transform_source_points_to_ue(
    points,
    *,
    pitch_degrees: float,
    roll_degrees: float,
    unit_scale_cm: float,
):
    import numpy as np

    local = np.column_stack(
        [
            points[:, 0],
            -points[:, 2],
            points[:, 1],
        ]
    ) * float(unit_scale_cm)
    pitch = math.radians(pitch_degrees)
    roll = math.radians(roll_degrees)
    cos_roll = math.cos(roll)
    sin_roll = math.sin(roll)
    cos_pitch = math.cos(pitch)
    sin_pitch = math.sin(pitch)
    rolled_y = cos_roll * local[:, 1] + sin_roll * local[:, 2]
    rolled_z = -sin_roll * local[:, 1] + cos_roll * local[:, 2]
    return np.column_stack(
        [
            cos_pitch * local[:, 0] - sin_pitch * rolled_z,
            rolled_y,
            sin_pitch * local[:, 0] + cos_pitch * rolled_z,
        ]
    )


def _ground_hits_at_points(
    transformed_vertices,
    faces,
    sample_points: Sequence[tuple[float, float, float]],
    *,
    actor_location_xy_cm: tuple[float, float],
    walkable_normal_z: float,
) -> list[tuple[float, int]]:
    import numpy as np

    hits: list[tuple[float, int]] = []
    chunk_size = 200_000
    actor_x, actor_y = actor_location_xy_cm
    for sample_x, sample_y, sample_z in sample_points:
        query_x = sample_x - actor_x
        query_y = sample_y - actor_y
        best_height = -math.inf
        best_face = -1
        for start in range(0, len(faces), chunk_size):
            face_chunk = faces[start : start + chunk_size]
            point_a = transformed_vertices[face_chunk[:, 0]]
            point_b = transformed_vertices[face_chunk[:, 1]]
            point_c = transformed_vertices[face_chunk[:, 2]]
            candidate = (
                (np.minimum.reduce(
                    [point_a[:, 0], point_b[:, 0], point_c[:, 0]]
                ) <= query_x)
                & (np.maximum.reduce(
                    [point_a[:, 0], point_b[:, 0], point_c[:, 0]]
                ) >= query_x)
                & (np.minimum.reduce(
                    [point_a[:, 1], point_b[:, 1], point_c[:, 1]]
                ) <= query_y)
                & (np.maximum.reduce(
                    [point_a[:, 1], point_b[:, 1], point_c[:, 1]]
                ) >= query_y)
            )
            if not bool(np.any(candidate)):
                continue
            local_indices = np.flatnonzero(candidate)
            a = point_a[local_indices]
            b = point_b[local_indices]
            c = point_c[local_indices]
            denominator = (
                (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0])
                + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
            )
            usable = np.abs(denominator) > 1e-9
            if not bool(np.any(usable)):
                continue
            local_indices = local_indices[usable]
            a = a[usable]
            b = b[usable]
            c = c[usable]
            denominator = denominator[usable]
            weight_a = (
                (b[:, 1] - c[:, 1]) * (query_x - c[:, 0])
                + (c[:, 0] - b[:, 0]) * (query_y - c[:, 1])
            ) / denominator
            weight_b = (
                (c[:, 1] - a[:, 1]) * (query_x - c[:, 0])
                + (a[:, 0] - c[:, 0]) * (query_y - c[:, 1])
            ) / denominator
            weight_c = 1.0 - weight_a - weight_b
            inside = (
                (weight_a >= -1e-7)
                & (weight_b >= -1e-7)
                & (weight_c >= -1e-7)
            )
            if not bool(np.any(inside)):
                continue
            local_indices = local_indices[inside]
            a = a[inside]
            b = b[inside]
            c = c[inside]
            weight_a = weight_a[inside]
            weight_b = weight_b[inside]
            weight_c = weight_c[inside]
            cross = np.cross(b - a, c - a)
            cross_length = np.linalg.norm(cross, axis=1)
            normal_z = np.abs(
                cross[:, 2] / np.maximum(cross_length, 1e-12)
            )
            heights = (
                weight_a * a[:, 2]
                + weight_b * b[:, 2]
                + weight_c * c[:, 2]
            )
            valid = (
                (normal_z >= walkable_normal_z)
                & (heights <= sample_z + 25.0)
            )
            if not bool(np.any(valid)):
                continue
            valid_heights = heights[valid]
            highest_index = int(np.argmax(valid_heights))
            highest = float(valid_heights[highest_index])
            if highest > best_height:
                best_height = highest
                best_face = (
                    start
                    + int(local_indices[valid][highest_index])
                )
        if best_face >= 0:
            hits.append((best_height, best_face))
    return hits


def estimate_ply_ground_alignment(
    source_path: str | Path,
    *,
    sample_points: Sequence[Any] = (),
    target_ground_z_cm: float = 0.0,
    actor_location_xy_cm: tuple[float, float] = (0.0, 0.0),
    source_up_axis: str = "y",
    unit_scale_cm: float = 100.0,
    max_tilt_degrees: float = 70.0,
    max_sampled_triangles: int = 250_000,
    refinement_radius_cm: float = 1000.0,
) -> PlyGroundAlignment:
    """Estimate a level UE actor transform from a polygon-mesh PLY floor."""

    import numpy as np

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PLY 文件不存在: {source}")
    if source.suffix.lower() != ".ply":
        raise PlyMeshError(f"地面对齐只接受 .ply: {source}")
    if unit_scale_cm <= 0.0:
        raise ValueError("unit_scale_cm 必须大于 0")

    axis_key = str(source_up_axis or "y").strip().lower()
    axis_indices = {"x": 0, "y": 1, "z": 2}
    if axis_key not in axis_indices:
        raise ValueError("source_up_axis 必须是 x、y 或 z")

    vertices, faces, _ = _load_ply_triangle_geometry(source)
    if len(vertices) == 0 or len(faces) == 0:
        raise PlyMeshError("Collider PLY 没有可用于地面对齐的三角形")
    if not bool(np.all(np.isfinite(vertices))):
        raise PlyMeshError("Collider PLY 包含 NaN 或 Infinity 顶点坐标")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise PlyMeshError("Collider PLY face 引用了越界顶点索引")

    stride = max(
        1,
        math.ceil(len(faces) / max(1, int(max_sampled_triangles))),
    )
    sampled_faces = faces[::stride]
    point_a = vertices[sampled_faces[:, 0]]
    point_b = vertices[sampled_faces[:, 1]]
    point_c = vertices[sampled_faces[:, 2]]
    cross = np.cross(point_b - point_a, point_c - point_a)
    cross_length = np.linalg.norm(cross, axis=1)
    valid = np.isfinite(cross_length) & (cross_length > 1e-12)
    normals = cross[valid] / cross_length[valid, None]
    weights = cross_length[valid]
    if len(normals) == 0:
        raise PlyMeshError("Collider PLY 的三角形全部退化")

    up_axis_index = axis_indices[axis_key]
    normals[normals[:, up_axis_index] < 0.0] *= -1.0
    up_dot = normals[:, up_axis_index]
    tilted = up_dot >= math.cos(math.radians(max_tilt_degrees))
    normals = normals[tilted]
    weights = weights[tilted]
    if len(normals) == 0:
        raise PlyMeshError(
            "Collider PLY 没有找到接近 source_up_axis 的主平面"
        )

    bin_size = 0.05
    quantized = np.rint(normals / bin_size).astype(np.int16)
    bins, inverse = np.unique(
        quantized,
        axis=0,
        return_inverse=True,
    )
    bin_weights = np.bincount(inverse, weights=weights)
    bin_normals = bins.astype(np.float64) * bin_size
    bin_lengths = np.linalg.norm(bin_normals, axis=1)
    bin_normals = bin_normals / np.maximum(bin_lengths[:, None], 1e-12)
    scores = bin_weights * np.maximum(
        bin_normals[:, up_axis_index],
        0.0,
    ) ** 0.35
    candidate_normal = bin_normals[int(np.argmax(scores))]
    support = (
        normals @ candidate_normal
        >= math.cos(math.radians(12.0))
    )
    normal = np.sum(
        normals[support] * weights[support, None],
        axis=0,
    )
    normal /= np.linalg.norm(normal)

    normalized_samples = [
        point
        for point in (
            _alignment_sample_point(value)
            for value in sample_points
        )
        if point is not None
    ]
    pitch, roll = _alignment_rotation(normal)
    transformed_vertices = _transform_source_points_to_ue(
        vertices,
        pitch_degrees=pitch,
        roll_degrees=roll,
        unit_scale_cm=unit_scale_cm,
    )
    walkable_normal_z = math.cos(math.radians(40.0))
    hits = _ground_hits_at_points(
        transformed_vertices,
        faces,
        normalized_samples,
        actor_location_xy_cm=actor_location_xy_cm,
        walkable_normal_z=walkable_normal_z,
    )
    if hits:
        initial_ground_z = float(np.median([height for height, _ in hits]))
    else:
        sampled_centroids = (point_a[valid][tilted] + point_b[valid][tilted] + point_c[valid][tilted]) / 3.0
        projected = sampled_centroids @ normal * float(unit_scale_cm)
        bin_width_cm = 10.0
        minimum = math.floor(float(projected.min()) / bin_width_cm) * bin_width_cm
        plane_bins = np.floor((projected - minimum) / bin_width_cm).astype(np.int64)
        plane_weights = np.bincount(plane_bins, weights=weights)
        initial_ground_z = minimum + (
            int(np.argmax(plane_weights)) + 0.5
        ) * bin_width_cm

    support_weight = 0.0
    support_count = 0
    refined_normal_sum = np.zeros(3, dtype=np.float64)
    chunk_size = 200_000
    hint_xy = np.asarray(
        [
            (
                point[0] - actor_location_xy_cm[0],
                point[1] - actor_location_xy_cm[1],
            )
            for point in normalized_samples
        ],
        dtype=np.float64,
    )
    for start in range(0, len(faces), chunk_size):
        face_chunk = faces[start : start + chunk_size]
        a = vertices[face_chunk[:, 0]]
        b = vertices[face_chunk[:, 1]]
        c = vertices[face_chunk[:, 2]]
        chunk_cross = np.cross(b - a, c - a)
        chunk_weight = np.linalg.norm(chunk_cross, axis=1)
        usable = chunk_weight > 1e-12
        if not bool(np.any(usable)):
            continue
        chunk_normal = chunk_cross / np.maximum(
            chunk_weight[:, None],
            1e-12,
        )
        chunk_normal[
            chunk_normal[:, up_axis_index] < 0.0
        ] *= -1.0
        centroid = (a + b + c) / 3.0
        transformed_centroid = _transform_source_points_to_ue(
            centroid,
            pitch_degrees=pitch,
            roll_degrees=roll,
            unit_scale_cm=unit_scale_cm,
        )
        selected = (
            usable
            & (
                chunk_normal @ normal
                >= math.cos(math.radians(10.0))
            )
            & (
                np.abs(
                    transformed_centroid[:, 2] - initial_ground_z
                )
                <= 30.0
            )
        )
        if len(hint_xy):
            near_hint = np.zeros(len(face_chunk), dtype=bool)
            for hint_x, hint_y in hint_xy:
                near_hint |= (
                    (transformed_centroid[:, 0] - hint_x) ** 2
                    + (transformed_centroid[:, 1] - hint_y) ** 2
                    <= refinement_radius_cm ** 2
                )
            selected &= near_hint
        if not bool(np.any(selected)):
            continue
        selected_weights = chunk_weight[selected]
        refined_normal_sum += np.sum(
            chunk_normal[selected] * selected_weights[:, None],
            axis=0,
        )
        support_weight += float(np.sum(selected_weights))
        support_count += int(np.count_nonzero(selected))

    if support_weight > 0.0:
        refined_normal = refined_normal_sum / np.linalg.norm(
            refined_normal_sum
        )
        if float(refined_normal @ normal) >= math.cos(
            math.radians(8.0)
        ):
            normal = refined_normal
            pitch, roll = _alignment_rotation(normal)
            transformed_vertices = _transform_source_points_to_ue(
                vertices,
                pitch_degrees=pitch,
                roll_degrees=roll,
                unit_scale_cm=unit_scale_cm,
            )
            hits = _ground_hits_at_points(
                transformed_vertices,
                faces,
                normalized_samples,
                actor_location_xy_cm=actor_location_xy_cm,
                walkable_normal_z=walkable_normal_z,
            )

    ground_z = (
        float(np.median([height for height, _ in hits]))
        if hits
        else initial_ground_z
    )
    bounds_x: list[Any] = []
    bounds_y: list[Any] = []
    for start in range(0, len(faces), chunk_size):
        face_chunk = faces[start : start + chunk_size]
        a = vertices[face_chunk[:, 0]]
        b = vertices[face_chunk[:, 1]]
        c = vertices[face_chunk[:, 2]]
        chunk_cross = np.cross(b - a, c - a)
        chunk_weight = np.linalg.norm(chunk_cross, axis=1)
        chunk_normal = chunk_cross / np.maximum(
            chunk_weight[:, None],
            1e-12,
        )
        chunk_normal[
            chunk_normal[:, up_axis_index] < 0.0
        ] *= -1.0
        transformed_centroid = _transform_source_points_to_ue(
            (a + b + c) / 3.0,
            pitch_degrees=pitch,
            roll_degrees=roll,
            unit_scale_cm=unit_scale_cm,
        )
        selected = (
            (chunk_weight > 1e-12)
            & (
                chunk_normal @ normal
                >= math.cos(math.radians(8.0))
            )
            & (
                np.abs(transformed_centroid[:, 2] - ground_z)
                <= 20.0
            )
        )
        if bool(np.any(selected)):
            bounds_x.append(transformed_centroid[selected, 0])
            bounds_y.append(transformed_centroid[selected, 1])

    if bounds_x:
        all_x = np.concatenate(bounds_x)
        all_y = np.concatenate(bounds_y)
        min_x, max_x = np.quantile(all_x, [0.01, 0.99])
        min_y, max_y = np.quantile(all_y, [0.01, 0.99])
    else:
        min_x, max_x = np.quantile(
            transformed_vertices[:, 0],
            [0.05, 0.95],
        )
        min_y, max_y = np.quantile(
            transformed_vertices[:, 1],
            [0.05, 0.95],
        )
    actor_x, actor_y = actor_location_xy_cm
    ground_bounds_min = (
        float(min_x + actor_x),
        float(min_y + actor_y),
    )
    ground_bounds_max = (
        float(max_x + actor_x),
        float(max_y + actor_y),
    )
    grounded_samples = len(hits)
    sample_coverage = (
        grounded_samples / len(normalized_samples)
        if normalized_samples
        else 0.5
    )
    orientation_support = min(
        1.0,
        support_weight / max(float(np.sum(weights)), 1e-12),
    )
    confidence = min(
        1.0,
        0.65 * sample_coverage + 0.35 * orientation_support,
    )
    return PlyGroundAlignment(
        source_path=str(source),
        source_normal=tuple(float(value) for value in normal),
        rotation={
            "pitch": float(pitch),
            "yaw": 0.0,
            "roll": float(roll),
        },
        location_z_cm=float(target_ground_z_cm - ground_z),
        ground_z_before_offset_cm=float(ground_z),
        target_ground_z_cm=float(target_ground_z_cm),
        ground_bounds_min_cm=ground_bounds_min,
        ground_bounds_max_cm=ground_bounds_max,
        sample_point_count=len(normalized_samples),
        grounded_sample_count=grounded_samples,
        sampled_triangle_count=len(sampled_faces),
        supporting_triangle_count=support_count,
        confidence=float(confidence),
    )


def convert_ply_mesh_to_glb(
    source_path: str | Path,
    output_path: str | Path,
) -> PlyMeshSummary:
    """Convert a polygon-mesh PLY to a vertex-color-preserving GLB."""

    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PLY 文件不存在: {source}")
    if source.suffix.lower() != ".ply":
        raise PlyMeshError(f"预处理器只接受 .ply: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as handle:
        header = _parse_header(handle, source)
        vertex_element, face_element, face_index_property = (
            _required_mesh_elements(header)
        )
        color_properties = _vertex_color_properties(vertex_element)
        read_record = _record_reader(header.encoding)
        vertex_count = 0
        polygon_count = 0
        triangle_count = 0
        bounds_min = [math.inf, math.inf, math.inf]
        bounds_max = [-math.inf, -math.inf, -math.inf]

        with (
            tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
            as position_data,
            tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
            as color_data,
            tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
            as index_data,
        ):
            for element in header.elements:
                for _ in range(element.count):
                    record = read_record(handle, element.properties)
                    if element.name == vertex_element.name:
                        coordinates = tuple(
                            float(record[name])
                            for name in ("x", "y", "z")
                        )
                        if not all(math.isfinite(value) for value in coordinates):
                            raise PlyMeshError(
                                "Collider PLY 包含 NaN 或 Infinity 顶点坐标"
                            )
                        try:
                            packed_coordinates = struct.pack(
                                "<fff",
                                *coordinates,
                            )
                        except (OverflowError, struct.error) as exc:
                            raise PlyMeshError(
                                "Collider PLY 顶点坐标超出 GLB float32 范围"
                            ) from exc
                        position_data.write(packed_coordinates)
                        glb_coordinates = struct.unpack(
                            "<fff",
                            packed_coordinates,
                        )
                        for axis, value in enumerate(glb_coordinates):
                            bounds_min[axis] = min(bounds_min[axis], value)
                            bounds_max[axis] = max(bounds_max[axis], value)
                        if color_properties:
                            color_data.write(
                                bytes(
                                    _color_byte(
                                        record[prop.name],
                                        prop.value_type,
                                    )
                                    for prop in color_properties
                                )
                            )
                        vertex_count += 1
                    elif element.name == face_element.name:
                        raw_indices = record.get(face_index_property)
                        if not isinstance(raw_indices, list):
                            raise PlyMeshError(
                                "Collider PLY face 索引不是 list"
                            )
                        indices = [int(value) for value in raw_indices]
                        if len(indices) < 3:
                            raise PlyMeshError(
                                "Collider PLY 包含少于 3 个顶点的面"
                            )
                        if any(
                            index < 0 or index >= vertex_element.count
                            for index in indices
                        ):
                            raise PlyMeshError(
                                "Collider PLY face 引用了越界顶点索引"
                            )
                        polygon_count += 1
                        for offset in range(1, len(indices) - 1):
                            index_data.write(
                                struct.pack(
                                    "<III",
                                    indices[0],
                                    indices[offset],
                                    indices[offset + 1],
                                )
                            )
                            triangle_count += 1

            if vertex_count != vertex_element.count:
                raise PlyMeshError(
                    "Collider PLY 实际 vertex 数量与 header 不一致"
                )
            if polygon_count != face_element.count or triangle_count <= 0:
                raise PlyMeshError(
                    "Collider PLY 没有生成有效三角面"
                )

            position_length = vertex_count * 12
            color_stride = len(color_properties)
            color_length = vertex_count * color_stride
            index_length = triangle_count * 12
            position_offset = 0
            color_offset = (
                _align4(position_length)
                if color_properties
                else 0
            )
            index_offset = _align4(
                color_offset + color_length
                if color_properties
                else position_length
            )
            binary_length = _align4(index_offset + index_length)

            buffer_views = [
                {
                    "buffer": 0,
                    "byteOffset": position_offset,
                    "byteLength": position_length,
                    "target": 34962,
                }
            ]
            accessors = [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": vertex_count,
                    "type": "VEC3",
                    "min": list(bounds_min),
                    "max": list(bounds_max),
                }
            ]
            attributes = {"POSITION": 0}
            if color_properties:
                color_view_index = len(buffer_views)
                color_accessor_index = len(accessors)
                buffer_views.append(
                    {
                        "buffer": 0,
                        "byteOffset": color_offset,
                        "byteLength": color_length,
                        "target": 34962,
                    }
                )
                accessors.append(
                    {
                        "bufferView": color_view_index,
                        "componentType": 5121,
                        "normalized": True,
                        "count": vertex_count,
                        "type": (
                            "VEC4"
                            if color_stride == 4
                            else "VEC3"
                        ),
                    }
                )
                attributes["COLOR_0"] = color_accessor_index
            index_view_index = len(buffer_views)
            index_accessor_index = len(accessors)
            buffer_views.append(
                {
                    "buffer": 0,
                    "byteOffset": index_offset,
                    "byteLength": index_length,
                    "target": 34963,
                }
            )
            accessors.append(
                {
                    "bufferView": index_view_index,
                    "componentType": 5125,
                    "count": triangle_count * 3,
                    "type": "SCALAR",
                }
            )
            document = {
                "asset": {
                    "version": "2.0",
                    "generator": "A3Game Collider PLY Preprocessor",
                },
                "scene": 0,
                "scenes": [{"nodes": [0]}],
                "nodes": [{"mesh": 0, "name": source.stem}],
                "meshes": [
                    {
                        "name": source.stem,
                        "primitives": [
                            {
                                "attributes": attributes,
                                "indices": index_accessor_index,
                                "material": 0,
                                "mode": 4,
                            }
                        ],
                    }
                ],
                "materials": [
                    {
                        "name": "ColliderVertexColor",
                        "doubleSided": True,
                        "pbrMetallicRoughness": {
                            "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                            "metallicFactor": 0.0,
                            "roughnessFactor": 1.0,
                        },
                    }
                ],
                "buffers": [{"byteLength": binary_length}],
                "bufferViews": buffer_views,
                "accessors": accessors,
            }
            json_bytes = json.dumps(
                document,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
            json_padded_length = _align4(len(json_bytes))
            total_length = (
                12
                + 8
                + json_padded_length
                + 8
                + binary_length
            )

            with output.open("wb") as glb:
                glb.write(struct.pack("<III", 0x46546C67, 2, total_length))
                glb.write(struct.pack("<II", json_padded_length, 0x4E4F534A))
                glb.write(json_bytes)
                glb.write(b" " * (json_padded_length - len(json_bytes)))
                glb.write(struct.pack("<II", binary_length, 0x004E4942))
                _copy_binary_stream(glb, position_data, position_length)
                next_offset = (
                    color_offset
                    if color_properties
                    else index_offset
                )
                glb.write(b"\0" * (next_offset - position_length))
                if color_properties:
                    _copy_binary_stream(glb, color_data, color_length)
                    glb.write(
                        b"\0"
                        * (
                            index_offset
                            - color_offset
                            - color_length
                        )
                    )
                _copy_binary_stream(glb, index_data, index_length)
                glb.write(
                    b"\0"
                    * (
                        binary_length
                        - index_offset
                        - index_length
                    )
                )

    return PlyMeshSummary(
        source_path=str(source),
        output_path=str(output),
        encoding=header.encoding,
        vertex_count=vertex_count,
        polygon_count=polygon_count,
        triangle_count=triangle_count,
        bounds_min=tuple(bounds_min),
        bounds_max=tuple(bounds_max),
        has_vertex_colors=bool(color_properties),
    )


def convert_ply_mesh_to_glb_with_world_xy_cutout(
    source_path: str | Path,
    output_path: str | Path,
    *,
    cutout_min_cm: tuple[float, float],
    cutout_max_cm: tuple[float, float],
    actor_pitch_degrees: float,
    actor_roll_degrees: float,
    actor_location_xy_cm: tuple[float, float] = (0.0, 0.0),
    unit_scale_cm: float = 100.0,
) -> PlyMeshSummary:
    """Convert PLY to GLB while removing triangles below a world XY box."""

    import numpy as np

    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PLY 文件不存在: {source}")
    if source.suffix.lower() != ".ply":
        raise PlyMeshError(f"预处理器只接受 .ply: {source}")
    min_x, min_y = (float(value) for value in cutout_min_cm)
    max_x, max_y = (float(value) for value in cutout_max_cm)
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("cutout world XY bounds 必须满足 min < max")

    vertices, faces, encoding = _load_ply_triangle_geometry(source)
    transformed = _transform_source_points_to_ue(
        vertices,
        pitch_degrees=actor_pitch_degrees,
        roll_degrees=actor_roll_degrees,
        unit_scale_cm=unit_scale_cm,
    )
    transformed[:, 0] += float(actor_location_xy_cm[0])
    transformed[:, 1] += float(actor_location_xy_cm[1])

    keep = np.ones(len(faces), dtype=bool)
    chunk_size = 200_000
    for start in range(0, len(faces), chunk_size):
        face_chunk = faces[start : start + chunk_size]
        triangle = transformed[face_chunk]
        triangle_min_x = np.min(triangle[:, :, 0], axis=1)
        triangle_max_x = np.max(triangle[:, :, 0], axis=1)
        triangle_min_y = np.min(triangle[:, :, 1], axis=1)
        triangle_max_y = np.max(triangle[:, :, 1], axis=1)
        overlaps = (
            (triangle_max_x >= min_x)
            & (triangle_min_x <= max_x)
            & (triangle_max_y >= min_y)
            & (triangle_min_y <= max_y)
        )
        keep[start : start + len(face_chunk)] = ~overlaps

    filtered_faces = faces[keep]
    if len(filtered_faces) == 0:
        raise PlyMeshError("竞技区挖空后 Collider 没有剩余三角面")

    positions = np.asarray(vertices, dtype="<f4")
    indices = np.asarray(filtered_faces, dtype="<u4").reshape(-1)
    position_bytes = positions.tobytes(order="C")
    index_bytes = indices.tobytes(order="C")
    position_length = len(position_bytes)
    index_offset = _align4(position_length)
    index_length = len(index_bytes)
    binary_length = _align4(index_offset + index_length)
    bounds_min = positions.min(axis=0).astype(float).tolist()
    bounds_max = positions.max(axis=0).astype(float).tolist()
    document = {
        "asset": {
            "version": "2.0",
            "generator": "A3Game Collider Arena Cutout",
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": output.stem}],
        "meshes": [
            {
                "name": output.stem,
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "HiddenCollider",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.2, 0.2, 0.2, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                },
            }
        ],
        "buffers": [{"byteLength": binary_length}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": position_length,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": index_offset,
                "byteLength": index_length,
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": bounds_min,
                "max": bounds_max,
            },
            {
                "bufferView": 1,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
    }
    json_bytes = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    json_padded_length = _align4(len(json_bytes))
    total_length = 12 + 8 + json_padded_length + 8 + binary_length
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as glb:
        glb.write(struct.pack("<III", 0x46546C67, 2, total_length))
        glb.write(struct.pack("<II", json_padded_length, 0x4E4F534A))
        glb.write(json_bytes)
        glb.write(b" " * (json_padded_length - len(json_bytes)))
        glb.write(struct.pack("<II", binary_length, 0x004E4942))
        glb.write(position_bytes)
        glb.write(b"\0" * (index_offset - position_length))
        glb.write(index_bytes)
        glb.write(
            b"\0" * (binary_length - index_offset - index_length)
        )

    return PlyMeshSummary(
        source_path=str(source),
        output_path=str(output),
        encoding=encoding,
        vertex_count=len(vertices),
        polygon_count=len(filtered_faces),
        triangle_count=len(filtered_faces),
        bounds_min=tuple(bounds_min),
        bounds_max=tuple(bounds_max),
        has_vertex_colors=False,
    )


def convert_ply_mesh_to_obj(
    source_path: str | Path,
    output_path: str | Path,
) -> PlyMeshSummary:
    """Convert a polygon-mesh PLY to OBJ while validating collision geometry."""

    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PLY 文件不存在: {source}")
    if source.suffix.lower() != ".ply":
        raise PlyMeshError(f"预处理器只接受 .ply: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as handle:
        header = _parse_header(handle, source)
        vertex_element, face_element, face_index_property = (
            _required_mesh_elements(header)
        )
        read_record = _record_reader(header.encoding)
        vertex_count = 0
        polygon_count = 0
        triangle_count = 0

        with (
            output.open("w", encoding="ascii", newline="\n") as obj,
            tempfile.SpooledTemporaryFile(
                mode="w+",
                encoding="ascii",
                newline="\n",
                max_size=16 * 1024 * 1024,
            ) as face_lines,
        ):
            obj.write("# Converted from collider PLY\n")
            for element in header.elements:
                for _ in range(element.count):
                    record = read_record(handle, element.properties)
                    if element.name == vertex_element.name:
                        coordinates = tuple(
                            float(record[name])
                            for name in ("x", "y", "z")
                        )
                        if not all(math.isfinite(value) for value in coordinates):
                            raise PlyMeshError(
                                "Collider PLY 包含 NaN 或 Infinity 顶点坐标"
                            )
                        obj.write(
                            "v "
                            + " ".join(f"{value:.9g}" for value in coordinates)
                            + "\n"
                        )
                        vertex_count += 1
                    elif element.name == face_element.name:
                        raw_indices = record.get(face_index_property)
                        if not isinstance(raw_indices, list):
                            raise PlyMeshError(
                                "Collider PLY face 索引不是 list"
                            )
                        indices = [int(value) for value in raw_indices]
                        if len(indices) < 3:
                            raise PlyMeshError(
                                "Collider PLY 包含少于 3 个顶点的面"
                            )
                        if any(
                            index < 0 or index >= vertex_element.count
                            for index in indices
                        ):
                            raise PlyMeshError(
                                "Collider PLY face 引用了越界顶点索引"
                            )
                        polygon_count += 1
                        for offset in range(1, len(indices) - 1):
                            triangle = (
                                indices[0] + 1,
                                indices[offset] + 1,
                                indices[offset + 1] + 1,
                            )
                            face_lines.write(
                                "f "
                                + " ".join(str(index) for index in triangle)
                                + "\n"
                            )
                            triangle_count += 1

            if vertex_count != vertex_element.count:
                raise PlyMeshError(
                    "Collider PLY 实际 vertex 数量与 header 不一致"
                )
            if polygon_count != face_element.count or triangle_count <= 0:
                raise PlyMeshError(
                    "Collider PLY 没有生成有效三角面"
                )
            face_lines.seek(0)
            while True:
                chunk = face_lines.read(1024 * 1024)
                if not chunk:
                    break
                obj.write(chunk)

    return PlyMeshSummary(
        source_path=str(source),
        output_path=str(output),
        encoding=header.encoding,
        vertex_count=vertex_count,
        polygon_count=polygon_count,
        triangle_count=triangle_count,
    )


@contextmanager
def prepare_mesh_source(
    source_path: str | Path,
) -> Iterator[PreparedMeshSource]:
    """Yield a UE-importable source, converting mesh PLY files when needed."""

    source = Path(source_path).expanduser().resolve()
    if source.suffix.lower() != ".ply":
        yield PreparedMeshSource(
            original_path=source,
            import_path=source,
        )
        return

    with tempfile.TemporaryDirectory(prefix="a3game-ply-") as temp_dir:
        output = Path(temp_dir) / f"{source.stem}.glb"
        summary = convert_ply_mesh_to_glb(source, output)
        yield PreparedMeshSource(
            original_path=source,
            import_path=output,
            summary=summary,
        )
