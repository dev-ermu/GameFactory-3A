"""Prepare Gaussian Splat PLY files for the XV3dGS Unreal importer."""

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


_SCALAR_SIZES = {
    "char": 1,
    "int8": 1,
    "uchar": 1,
    "uint8": 1,
    "short": 2,
    "int16": 2,
    "ushort": 2,
    "uint16": 2,
    "int": 4,
    "int32": 4,
    "uint": 4,
    "uint32": 4,
    "float": 4,
    "float32": 4,
    "double": 8,
    "float64": 8,
}
_GAUSSIAN_PROPERTIES = {
    "x",
    "y",
    "z",
    "f_dc_0",
    "f_dc_1",
    "f_dc_2",
    "opacity",
    "scale_0",
    "scale_1",
    "scale_2",
    "rot_0",
    "rot_1",
    "rot_2",
    "rot_3",
}
_NORMAL_PROPERTIES = ("nx", "ny", "nz")


class GaussianSplatPlyError(ValueError):
    """Raised when a PLY is not a supported Gaussian Splat source."""


@dataclass(frozen=True)
class GaussianSplatPlySummary:
    source_path: str
    output_path: str
    encoding: str
    vertex_count: int
    injected_normals: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "output_path": self.output_path,
            "encoding": self.encoding,
            "vertex_count": self.vertex_count,
            "injected_normals": self.injected_normals,
        }


@dataclass(frozen=True)
class PreparedGaussianSplatSource:
    original_path: Path
    import_path: Path
    summary: GaussianSplatPlySummary


@dataclass(frozen=True)
class _GaussianPlyLayout:
    encoding: str
    vertex_count: int
    properties: tuple[tuple[str, str], ...]
    header_lines: tuple[bytes, ...]


def _parse_layout(handle: BinaryIO, source: Path) -> _GaussianPlyLayout:
    first = handle.readline()
    if first.strip() != b"ply":
        raise GaussianSplatPlyError(f"Not a PLY file: {source}")

    header_lines = [first]
    encoding = ""
    vertex_count = 0
    current_element = ""
    extra_element_count = 0
    properties: list[tuple[str, str]] = []
    while True:
        raw = handle.readline()
        if not raw:
            raise GaussianSplatPlyError(
                f"PLY header is missing end_header: {source}"
            )
        header_lines.append(raw)
        try:
            line = raw.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise GaussianSplatPlyError(
                f"PLY header is not ASCII: {source}"
            ) from exc
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "format" and len(parts) >= 2:
            encoding = parts[1]
        elif parts[0] == "element" and len(parts) == 3:
            current_element = parts[1]
            count = int(parts[2])
            if current_element == "vertex":
                vertex_count = count
            elif count > 0:
                extra_element_count += count
        elif parts[0] == "property" and current_element == "vertex":
            if len(parts) != 3 or parts[1] == "list":
                raise GaussianSplatPlyError(
                    "Gaussian Splat vertex properties must be scalar"
                )
            value_type, name = parts[1], parts[2]
            if value_type not in _SCALAR_SIZES:
                raise GaussianSplatPlyError(
                    f"Unsupported PLY scalar type: {value_type}"
                )
            properties.append((value_type, name))
        elif parts[0] == "end_header":
            break

    if encoding != "binary_little_endian":
        raise GaussianSplatPlyError(
            "XV3dGS Gaussian PLY import requires binary_little_endian"
        )
    if vertex_count <= 0:
        raise GaussianSplatPlyError(
            "Gaussian Splat PLY must contain vertices"
        )
    if extra_element_count:
        raise GaussianSplatPlyError(
            "Gaussian Splat PLY must not contain mesh faces or other records"
        )
    names = {name for _, name in properties}
    missing = sorted(_GAUSSIAN_PROPERTIES.difference(names))
    if missing:
        raise GaussianSplatPlyError(
            "PLY is missing Gaussian Splat properties: "
            + ", ".join(missing)
        )
    present_normals = [name in names for name in _NORMAL_PROPERTIES]
    if any(present_normals) and not all(present_normals):
        raise GaussianSplatPlyError(
            "Gaussian Splat PLY must contain all of nx, ny, nz or none"
        )
    return _GaussianPlyLayout(
        encoding=encoding,
        vertex_count=vertex_count,
        properties=tuple(properties),
        header_lines=tuple(header_lines),
    )


def is_gaussian_splat_ply(source_path: str | Path) -> bool:
    source = Path(source_path).expanduser().resolve()
    if source.suffix.lower() != ".ply" or not source.is_file():
        return False
    try:
        with source.open("rb") as handle:
            _parse_layout(handle, source)
    except (GaussianSplatPlyError, OSError, ValueError):
        return False
    return True


def _normal_insert_offsets(
    properties: tuple[tuple[str, str], ...],
) -> tuple[int, int]:
    record_size = sum(_SCALAR_SIZES[value_type] for value_type, _ in properties)
    offset = 0
    insert_offset = -1
    for value_type, name in properties:
        offset += _SCALAR_SIZES[value_type]
        if name == "z":
            insert_offset = offset
    if insert_offset < 0:
        raise GaussianSplatPlyError(
            "Gaussian Splat PLY vertex properties are missing z"
        )
    return insert_offset, record_size


def convert_gaussian_splat_ply_for_xv3dgs(
    source_path: str | Path,
    output_path: str | Path,
) -> GaussianSplatPlySummary:
    """Inject zero vertex normals required by XV3dGS when they are absent."""

    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Gaussian Splat PLY does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as src:
        layout = _parse_layout(src, source)
        property_names = {name for _, name in layout.properties}
        if all(name in property_names for name in _NORMAL_PROPERTIES):
            output.write_bytes(source.read_bytes())
            return GaussianSplatPlySummary(
                source_path=str(source),
                output_path=str(output),
                encoding=layout.encoding,
                vertex_count=layout.vertex_count,
                injected_normals=False,
            )

        insert_offset, record_size = _normal_insert_offsets(
            layout.properties
        )
        zero_normals = b"\0" * 12
        with output.open("wb") as dst:
            for raw_line in layout.header_lines:
                dst.write(raw_line)
                parts = raw_line.decode("ascii").strip().split()
                if (
                    len(parts) == 3
                    and parts[0] == "property"
                    and parts[2] == "z"
                ):
                    dst.write(b"property float nx\n")
                    dst.write(b"property float ny\n")
                    dst.write(b"property float nz\n")

            remaining = layout.vertex_count
            while remaining:
                record_count = min(4096, remaining)
                raw = src.read(record_size * record_count)
                if len(raw) != record_size * record_count:
                    raise GaussianSplatPlyError(
                        "Gaussian Splat PLY vertex data ended early"
                    )
                converted = bytearray((record_size + 12) * record_count)
                for index in range(record_count):
                    source_start = index * record_size
                    target_start = index * (record_size + 12)
                    converted[
                        target_start : target_start + insert_offset
                    ] = raw[
                        source_start : source_start + insert_offset
                    ]
                    normal_start = target_start + insert_offset
                    converted[normal_start : normal_start + 12] = zero_normals
                    converted[
                        normal_start + 12 : target_start + record_size + 12
                    ] = raw[
                        source_start + insert_offset : source_start + record_size
                    ]
                dst.write(converted)
                remaining -= record_count

            if src.read(1):
                raise GaussianSplatPlyError(
                    "Gaussian Splat PLY contains undeclared trailing data"
                )

    return GaussianSplatPlySummary(
        source_path=str(source),
        output_path=str(output),
        encoding=layout.encoding,
        vertex_count=layout.vertex_count,
        injected_normals=True,
    )


@contextmanager
def prepare_gaussian_splat_source(
    source_path: str | Path,
) -> Iterator[PreparedGaussianSplatSource]:
    source = Path(source_path).expanduser().resolve()
    with source.open("rb") as handle:
        layout = _parse_layout(handle, source)
    property_names = {name for _, name in layout.properties}
    if all(name in property_names for name in _NORMAL_PROPERTIES):
        yield PreparedGaussianSplatSource(
            original_path=source,
            import_path=source,
            summary=GaussianSplatPlySummary(
                source_path=str(source),
                output_path=str(source),
                encoding=layout.encoding,
                vertex_count=layout.vertex_count,
                injected_normals=False,
            ),
        )
        return

    with tempfile.TemporaryDirectory(
        prefix="a3game-gaussian-ply-"
    ) as temp_dir:
        output = Path(temp_dir) / source.name
        summary = convert_gaussian_splat_ply_for_xv3dgs(
            source,
            output,
        )
        yield PreparedGaussianSplatSource(
            original_path=source,
            import_path=output,
            summary=summary,
        )


__all__ = [
    "GaussianSplatPlyError",
    "GaussianSplatPlySummary",
    "PreparedGaussianSplatSource",
    "convert_gaussian_splat_ply_for_xv3dgs",
    "is_gaussian_splat_ply",
    "prepare_gaussian_splat_source",
]
