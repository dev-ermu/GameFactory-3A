"""Versioned A3Game generated-scene package validation."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine_adapters.ue5.assets._internal.materials import (
    SUPPORTED_TEXTURE_SUFFIXES,
    discover_pbr_textures,
    normalize_texture_channel,
)
from engine_adapters.ue5.world._internal.specs import (
    TransformSpec,
)


SCENE_PACKAGE_FORMAT = "a3game_scene"
SCENE_PACKAGE_VERSION = "1.0"
SCENE_PACKAGE_FILENAME = "a3game.scene.json"
LEGACY_SCENE_PACKAGE_FORMAT = "openwl_scene"
LEGACY_SCENE_PACKAGE_FILENAME = "openwl.scene.json"
SCENE_PACKAGE_FORMATS = {
    SCENE_PACKAGE_FORMAT,
    LEGACY_SCENE_PACKAGE_FORMAT,
}
SCENE_PACKAGE_FILENAMES = {
    SCENE_PACKAGE_FILENAME,
    LEGACY_SCENE_PACKAGE_FILENAME,
}
SCENE_PACKAGE_SOURCE_SUFFIXES = {
    ".fbx",
    ".glb",
    ".gltf",
    ".obj",
    ".ply",
    ".usd",
    ".usda",
    ".usdc",
}
SCENE_PACKAGE_ROLES = {"environment", "prop"}
SCENE_PACKAGE_ID_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_.-]*$")


@dataclass(frozen=True)
class ScenePackageInspection:
    manifest_path: str
    canonical: bool
    format: str = ""
    version: str = ""
    asset_count: int = 0
    entity_count: int = 0
    referenced_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    assets: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path,
            "canonical": self.canonical,
            "format": self.format,
            "version": self.version,
            "asset_count": self.asset_count,
            "entity_count": self.entity_count,
            "referenced_files": list(self.referenced_files),
            "warnings": list(self.warnings),
        }


def load_scene_descriptor(path: str | Path) -> dict[str, Any]:
    descriptor_path = Path(path).expanduser().resolve()
    try:
        with descriptor_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"场景 JSON 解析失败: {descriptor_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("场景 JSON 根节点必须是 object")
    if isinstance(data.get("world"), dict):
        merged = dict(data["world"])
        for key, value in data.items():
            if key != "world" and key not in merged:
                merged[key] = value
        data = merged
    return _normalize_legacy_asset_layout(descriptor_path, data)


def _normalize_legacy_asset_layout(
    descriptor_path: Path,
    data: dict[str, Any],
) -> dict[str, Any]:
    if (
        descriptor_path.name.lower() in SCENE_PACKAGE_FILENAMES
        or str(data.get("format") or "").strip()
        or data.get("entities")
        or data.get("objects")
        or data.get("nodes")
    ):
        return data
    raw_assets = data.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        return data
    if not any(
        isinstance(item, dict)
        and (item.get("file") or item.get("source_path"))
        for item in raw_assets
    ):
        return data

    entities = []
    has_environment = False
    for index, raw_asset in enumerate(raw_assets):
        if not isinstance(raw_asset, dict):
            continue
        source = str(
            raw_asset.get("file")
            or raw_asset.get("source_path")
            or ""
        ).strip()
        if not source:
            continue
        raw_role = str(
            raw_asset.get("role")
            or raw_asset.get("type")
            or "prop"
        ).strip().lower()
        role = "environment" if raw_role == "environment" else "prop"
        has_environment = has_environment or role == "environment"
        transform = _normalize_legacy_transform(raw_asset.get("transform"))
        entities.append(
            {
                "id": str(
                    raw_asset.get("id")
                    or raw_asset.get("name")
                    or f"asset_{index}"
                ),
                "role": role,
                "category": raw_role if raw_role != role else "",
                "source_path": source,
                "collision": bool(raw_asset.get("collision", True)),
                "transform": transform,
            }
        )
    if not entities:
        return data

    normalized = dict(data)
    normalized.setdefault(
        "world_id",
        str(
            data.get("scene_name")
            or data.get("name")
            or descriptor_path.stem
        ),
    )
    normalized.setdefault("representation", "mesh_layout")
    normalized["entities"] = entities
    spawn = data.get("spawn")
    if "spawn_point" not in normalized and isinstance(spawn, dict):
        normalized["spawn_point"] = _normalize_legacy_transform(spawn)
    if "add_default_ground" not in normalized:
        normalized["add_default_ground"] = not has_environment
    metadata = dict(normalized.get("metadata") or {})
    metadata.setdefault("source_schema", "legacy_assets_file_layout")
    normalized["metadata"] = metadata
    return normalized


def _normalize_legacy_transform(value: Any) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, dict) else {}
    location = raw.get("location", raw.get("position"))
    rotation = raw.get("rotation")
    if isinstance(rotation, (list, tuple)):
        values = list(rotation)
        rotation = {
            "roll": float(values[0]) if len(values) > 0 else 0.0,
            "pitch": float(values[1]) if len(values) > 1 else 0.0,
            "yaw": float(values[2]) if len(values) > 2 else 0.0,
        }
    return {
        key: item
        for key, item in {
            "location": location,
            "rotation": rotation,
            "scale": raw.get("scale"),
        }.items()
        if item is not None
    }


def inspect_scene_descriptor(
    descriptor_path: str | Path,
    descriptor: dict[str, Any] | None = None,
) -> ScenePackageInspection:
    path = Path(descriptor_path).expanduser().resolve()
    data = descriptor if descriptor is not None else load_scene_descriptor(path)
    canonical = (
        path.name.lower() in SCENE_PACKAGE_FILENAMES
        or bool(str(data.get("format") or "").strip())
    )
    if not canonical:
        return ScenePackageInspection(
            manifest_path=str(path),
            canonical=False,
            entity_count=len(data.get("entities") or []),
        )
    if path.name.lower() not in SCENE_PACKAGE_FILENAMES:
        raise ValueError(
            f"Scene Package manifest 必须命名为 {SCENE_PACKAGE_FILENAME}"
        )

    package_format = str(data.get("format") or "").strip()
    if package_format not in SCENE_PACKAGE_FORMATS:
        raise ValueError(
            f"{SCENE_PACKAGE_FILENAME} 的 format 必须是 {SCENE_PACKAGE_FORMAT}"
        )
    version = str(data.get("version") or "").strip()
    if version != SCENE_PACKAGE_VERSION:
        raise ValueError(
            f"不支持的 Scene Package version: {version or '<missing>'}"
            f"（当前支持: {SCENE_PACKAGE_VERSION}）"
        )

    raw_assets = data.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ValueError(f"{SCENE_PACKAGE_FILENAME} 的 assets 必须是非空数组")
    raw_entities = data.get("entities")
    if not isinstance(raw_entities, list) or not raw_entities:
        raise ValueError(f"{SCENE_PACKAGE_FILENAME} 的 entities 必须是非空数组")

    assets: dict[str, dict[str, Any]] = {}
    referenced_files: list[str] = []
    for index, raw_asset in enumerate(raw_assets):
        if not isinstance(raw_asset, dict):
            raise ValueError(f"场景包 assets[{index}] 必须是 object")
        asset_id = str(raw_asset.get("id") or "").strip()
        _validate_local_id(asset_id, f"assets[{index}].id")
        if asset_id in assets:
            raise ValueError(f"场景包 asset id 重复: {asset_id}")
        source = str(
            raw_asset.get("source")
            or raw_asset.get("source_path")
            or ""
        ).strip()
        source_path = _resolve_package_source(path.parent, source, f"asset {asset_id}")
        suffix = source_path.suffix.lower()
        if suffix not in SCENE_PACKAGE_SOURCE_SUFFIXES:
            supported = ", ".join(sorted(SCENE_PACKAGE_SOURCE_SUFFIXES))
            raise ValueError(
                f"场景包 asset {asset_id} 文件类型不支持: {suffix}（支持: {supported}）"
            )
        role = _normalize_role(raw_asset.get("role") or "prop", f"asset {asset_id}")
        normalized = dict(raw_asset)
        material = _normalize_material_config(
            path.parent,
            source_path,
            raw_asset.get("material"),
            asset_id,
        )
        normalized.update(
            {
                "id": asset_id,
                "source": source.replace("\\", "/"),
                "source_path": str(source_path),
                "role": role,
                "collision": bool(raw_asset.get("collision", True)),
                "material": material,
            }
        )
        assets[asset_id] = normalized
        referenced_files.append(normalized["source"])
        for texture_path in material.get("textures", {}).values():
            relative_texture = Path(texture_path).resolve().relative_to(
                path.parent.resolve()
            )
            referenced_files.append(relative_texture.as_posix())

    entity_ids: set[str] = set()
    environment_count = 0
    for index, raw_entity in enumerate(raw_entities):
        if not isinstance(raw_entity, dict):
            raise ValueError(f"场景包 entities[{index}] 必须是 object")
        entity_id = str(
            raw_entity.get("id")
            or raw_entity.get("entity_id")
            or ""
        ).strip()
        _validate_local_id(entity_id, f"entities[{index}].id")
        if entity_id in entity_ids:
            raise ValueError(f"场景包 entity id 重复: {entity_id}")
        entity_ids.add(entity_id)

        asset_ref = str(raw_entity.get("asset_ref") or "").strip()
        if not asset_ref:
            raise ValueError(f"场景包 entity {entity_id} 缺少 asset_ref")
        asset = assets.get(asset_ref)
        if asset is None:
            raise ValueError(
                f"场景包 entity {entity_id} 引用了未声明的 asset_ref: {asset_ref}"
            )
        role = _normalize_role(
            raw_entity.get("role") or asset["role"],
            f"entity {entity_id}",
        )
        if role == "environment":
            environment_count += 1
        transform = raw_entity.get("transform")
        if transform is not None and not isinstance(transform, dict):
            raise ValueError(f"场景包 entity {entity_id} 的 transform 必须是 object")
        try:
            TransformSpec.from_dict(transform if isinstance(transform, dict) else {})
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"场景包 entity {entity_id} 的 transform 无效: {exc}"
            ) from exc

    warnings = []
    if environment_count == 0 and not bool(data.get("add_default_ground", False)):
        warnings.append("场景包没有 role=environment 的实体；运行时仍可加载 prop")

    _validate_coordinate_system(data.get("coordinate_system"))
    return ScenePackageInspection(
        manifest_path=str(path),
        canonical=True,
        format=package_format,
        version=version,
        asset_count=len(assets),
        entity_count=len(raw_entities),
        referenced_files=tuple(dict.fromkeys(referenced_files)),
        warnings=tuple(warnings),
        assets=assets,
    )


def _validate_local_id(value: str, field_name: str) -> None:
    if not value or not SCENE_PACKAGE_ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"{field_name} 必须匹配 {SCENE_PACKAGE_ID_PATTERN.pattern}: {value!r}"
        )


def _resolve_package_source(root: Path, source: str, label: str) -> Path:
    if not source:
        raise ValueError(f"场景包 {label} 缺少 source")
    relative = Path(source)
    if relative.is_absolute():
        raise ValueError(f"场景包 {label} 的 source 必须是包内相对路径: {source}")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"场景包 {label} 的 source 越出场景包目录: {source}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"场景包 {label} 文件不存在: {source}")
    return resolved


def _normalize_role(value: Any, label: str) -> str:
    role = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "mesh": "prop",
        "object": "prop",
        "static_mesh": "prop",
        "decoration": "prop",
    }
    role = aliases.get(role, role)
    if role not in SCENE_PACKAGE_ROLES:
        allowed = ", ".join(sorted(SCENE_PACKAGE_ROLES))
        raise ValueError(f"场景包 {label} role 不支持: {role}（支持: {allowed}）")
    return role


def _normalize_material_config(
    package_root: Path,
    source_path: Path,
    value: Any,
    asset_id: str,
) -> dict[str, Any]:
    if value is False:
        return {"enabled": False, "auto": False, "textures": {}}
    if value is not None and not isinstance(value, dict):
        raise ValueError(f"场景包 asset {asset_id} material 必须是 object 或 false")
    raw = dict(value or {})
    explicit: dict[str, str] = {}
    raw_textures = raw.get("textures")
    if raw_textures is not None and not isinstance(raw_textures, dict):
        raise ValueError(f"场景包 asset {asset_id} material.textures 必须是 object")
    for raw_channel, raw_path in (raw_textures or {}).items():
        channel = normalize_texture_channel(raw_channel)
        texture_path = _resolve_package_source(
            package_root,
            str(raw_path or ""),
            f"asset {asset_id} texture {channel}",
        )
        if texture_path.suffix.lower() not in SUPPORTED_TEXTURE_SUFFIXES:
            raise ValueError(
                f"场景包 asset {asset_id} texture {channel} 类型不支持: "
                f"{texture_path.suffix}"
            )
        explicit[channel] = str(texture_path)

    auto = bool(raw.get("auto", True))
    textures = discover_pbr_textures(
        source_path,
        explicit=explicit,
        auto_discover=auto,
    )
    resolved_root = package_root.resolve()
    for channel, texture_path in textures.items():
        try:
            Path(texture_path).resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(
                f"场景包 asset {asset_id} texture {channel} 越出场景包目录"
            ) from exc
    opacity_mode = str(raw.get("opacity_mode") or "masked").strip().lower()
    if opacity_mode not in {"masked", "opaque"}:
        raise ValueError(
            f"场景包 asset {asset_id} opacity_mode 不支持: {opacity_mode}"
        )
    return {
        "enabled": bool(raw.get("enabled", True)),
        "auto": auto,
        "textures": textures,
        "two_sided": bool(raw.get("two_sided", False)),
        "opacity_mode": opacity_mode,
    }


def _validate_coordinate_system(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("场景包 coordinate_system 必须是 object")
    transform_space = str(value.get("transform_space") or "unreal").strip().lower()
    if transform_space != "unreal":
        raise ValueError(
            "场景包 JSON Transform 当前只支持 Unreal 坐标空间"
            "（coordinate_system.transform_space=unreal）"
        )
    unit = str(value.get("unit") or "centimeter").strip().lower()
    if unit not in {"centimeter", "centimeters", "cm"}:
        raise ValueError(
            "场景包 JSON Transform 当前只支持厘米"
            "（coordinate_system.unit=centimeter）"
        )


__all__ = [
    "SCENE_PACKAGE_FILENAME",
    "SCENE_PACKAGE_FORMAT",
    "SCENE_PACKAGE_SOURCE_SUFFIXES",
    "SCENE_PACKAGE_VERSION",
    "ScenePackageInspection",
    "inspect_scene_descriptor",
    "load_scene_descriptor",
]
