"""File and format inspection before an asset reaches Unreal Engine."""

from pathlib import Path
from typing import Any

from engine_adapters.ue5.assets._internal.pipeline.contracts import ImportResult
from engine_adapters.ue5.assets._internal.ue.dispatcher import UEImportDispatcher


FORMAT_PROFILES: dict[str, dict[str, Any]] = {
    ".fbx": {
        "format": "fbx",
        "container": "mesh_animation",
        "may_contain": ["mesh", "skeleton", "animation", "material"],
    },
    ".glb": {
        "format": "glb",
        "container": "gltf_binary",
        "may_contain": ["mesh", "node", "material", "texture", "animation"],
    },
    ".gltf": {
        "format": "gltf",
        "container": "gltf_json",
        "may_contain": ["mesh", "node", "material", "texture", "animation"],
    },
    ".usd": {
        "format": "usd",
        "container": "scene",
        "may_contain": ["scene", "mesh", "material", "hierarchy"],
    },
    ".usda": {
        "format": "usda",
        "container": "scene",
        "may_contain": ["scene", "mesh", "material", "hierarchy"],
    },
    ".usdc": {
        "format": "usdc",
        "container": "scene",
        "may_contain": ["scene", "mesh", "material", "hierarchy"],
    },
    ".obj": {
        "format": "obj",
        "container": "mesh",
        "may_contain": ["mesh", "material_reference"],
    },
    ".ply": {
        "format": "ply",
        "container": "polygon_mesh_or_point_cloud",
        "may_contain": ["mesh", "point_cloud", "vertex_attributes"],
    },
    ".abc": {
        "format": "alembic",
        "container": "geometry_cache",
        "may_contain": ["geometry_cache"],
    },
}


class SourceFormatInspectorRegistry:
    """Select format metadata without changing pipeline orchestration."""

    def __init__(self, profiles: dict[str, dict[str, Any]] | None = None) -> None:
        self.profiles = profiles or FORMAT_PROFILES

    def inspect(self, source_path: Path) -> dict[str, Any]:
        suffix = source_path.suffix.lower()
        profile = self.profiles.get(suffix)
        if profile is None:
            return {
                "format": suffix.lstrip("."),
                "container": "unknown",
                "may_contain": [],
                "inspector": "generic",
            }
        return {**profile, "inspector": f"{profile['format']}_inspector"}


class SourceFileInspector:
    def __init__(
        self,
        dispatcher: UEImportDispatcher,
        format_registry: SourceFormatInspectorRegistry | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.format_registry = format_registry or SourceFormatInspectorRegistry()

    def inspect(self, result: ImportResult) -> None:
        request = result.job.request
        source_path = Path(request.src_path)
        result.source.update(
            {
                "path": str(source_path),
                "name": source_path.name,
                "suffix": source_path.suffix.lower(),
                "exists": source_path.exists(),
            }
        )
        if not source_path.exists() or not source_path.is_file():
            result.add_error(f"源文件不存在或不是文件: {source_path}")
            return

        try:
            result.source["size_bytes"] = source_path.stat().st_size
        except OSError as exc:
            result.add_warning(f"无法读取源文件大小: {exc}")

        result.inspect.update(self.format_registry.inspect(source_path))
        result.inspect.update(
            {
                "asset_type": request.type_key,
                "options": dict(request.options),
            }
        )

        validate_asset = getattr(self.dispatcher, "validate_asset", None)
        if callable(validate_asset):
            validation = validate_asset(request)
            for warning in validation.warnings:
                result.add_warning(warning)
            for error in validation.errors:
                result.add_error(error)
