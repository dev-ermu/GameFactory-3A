"""Base UE asset importer."""

from abc import ABC
from dataclasses import replace
from pathlib import Path

from engine_adapters.ue5.assets._internal.preprocessors import (
    prepare_mesh_source,
)
from engine_adapters.ue5.assets._internal.types import ImportRequest, ValidationResult

from ..asset_types import ASSET_TYPE_SUFFIXES
from ..config import DEFAULT_IMPORT_ROOT
from ..utils import normalize_dest_path, validate_local_file
from ..builders.base import ScriptBuilder
from engine_adapters.ue5._internal.transport import PythonRPCTransport, Transport


class BaseImporter(ABC):
    asset_type_name = ""

    def __init__(
        self,
        default_dest: str,
        allowed_suffixes: tuple[str, ...],
        builder: ScriptBuilder,
        transport: Transport | None = None,
    ) -> None:
        self.default_dest = default_dest
        self.allowed_suffixes = allowed_suffixes
        self.builder = builder
        self.transport = transport or PythonRPCTransport()

    def validate(self, request: ImportRequest) -> ValidationResult:
        errors: list[str] = []
        suffix = Path(request.src_path).suffix.lower()
        if suffix not in self.allowed_suffixes:
            allowed = ", ".join(self.allowed_suffixes)
            errors.append(f"不支持的 {request.type_key} 文件类型: {suffix}（支持: {allowed}）")
        try:
            validate_local_file(request.src_path, self.allowed_suffixes)
        except Exception as exc:
            errors.append(str(exc))
        return ValidationResult(ok=not errors, errors=errors)

    def prepare_destination(self, request: ImportRequest) -> str:
        return normalize_dest_path(request.dst_path, self.default_dest or DEFAULT_IMPORT_ROOT)

    def import_asset(self, request: ImportRequest) -> dict:
        suffix = Path(request.src_path).suffix.lower()
        if suffix not in self.allowed_suffixes:
            allowed = ", ".join(self.allowed_suffixes)
            raise ValueError(f"不支持的 {request.type_key} 文件类型: {suffix}（支持: {allowed}）")
        local_path = validate_local_file(request.src_path, self.allowed_suffixes)
        with prepare_mesh_source(local_path) as prepared:
            normalized_request = replace(
                request,
                src_path=prepared.import_path.as_posix(),
            )
            result = self.execute(
                normalized_request,
                self.prepare_destination(normalized_request),
            )
            result["src_path"] = prepared.original_path.as_posix()
            if prepared.summary is not None:
                summary = prepared.summary.to_dict()
                summary.pop("output_path", None)
                result["source_preprocessing"] = {
                    "kind": "ply_mesh_to_glb",
                    **summary,
                }
            return result

    def execute(self, request: ImportRequest, dest_path: str) -> dict:
        script = self.builder.build_import_script(request, dest_path)
        imported_paths = self.transport.execute_json(script + "\n\nresult = imported_paths\n")
        return {
            "asset_type": request.type_key,
            "src_path": str(Path(request.src_path).expanduser().resolve()),
            "dest_path": dest_path,
            "imported_paths": imported_paths,
        }


def suffixes_for(asset_type_name: str) -> tuple[str, ...]:
    key = "prop" if asset_type_name == "static_mesh" else asset_type_name
    return ASSET_TYPE_SUFFIXES[key]
