"""Versioned generated-effect package validation."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


EFFECT_PACKAGE_FORMAT = "a3game_effect"
EFFECT_PACKAGE_VERSION = "1.0"
EFFECT_PACKAGE_FILENAME = "a3game.effect.json"
LEGACY_EFFECT_PACKAGE_FORMAT = "openwl_effect"
LEGACY_EFFECT_PACKAGE_FILENAME = "openwl.effect.json"
EFFECT_PACKAGE_FORMATS = {
    EFFECT_PACKAGE_FORMAT,
    LEGACY_EFFECT_PACKAGE_FORMAT,
}
EFFECT_PACKAGE_FILENAMES = {
    EFFECT_PACKAGE_FILENAME,
    LEGACY_EFFECT_PACKAGE_FILENAME,
}
EFFECT_PACKAGE_ID_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_.-]*$")

EFFECT_TEXTURE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tga",
    ".exr",
    ".hdr",
    ".bmp",
    ".tif",
    ".tiff",
}
EFFECT_MESH_SUFFIXES = {
    ".fbx",
    ".glb",
    ".gltf",
    ".obj",
    ".abc",
    ".usd",
    ".usda",
    ".usdc",
}
EFFECT_AUXILIARY_SUFFIXES = {
    ".json",
    ".hlsl",
    ".usf",
    ".vdb",
    ".bgeo",
    ".wav",
    ".ogg",
}
EFFECT_PACKAGE_SOURCE_SUFFIXES = (
    EFFECT_TEXTURE_SUFFIXES
    | EFFECT_MESH_SUFFIXES
    | EFFECT_AUXILIARY_SUFFIXES
)
EFFECT_PACKAGE_ROLES = {
    "texture",
    "mesh",
    "cache",
    "shader",
    "audio",
    "data",
    "source",
}
EFFECT_BUILD_MODES = {
    "none",
    "existing_asset",
    "duplicate_template",
}


@dataclass(frozen=True)
class EffectPackageInspection:
    manifest_path: str
    canonical: bool
    format: str = ""
    version: str = ""
    effect_id: str = ""
    representation: str = ""
    asset_count: int = 0
    referenced_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    assets: dict[str, dict[str, Any]] = field(
        default_factory=dict,
        repr=False,
    )
    build: dict[str, Any] = field(default_factory=dict, repr=False)
    binding: Any = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path,
            "canonical": self.canonical,
            "format": self.format,
            "version": self.version,
            "effect_id": self.effect_id,
            "representation": self.representation,
            "asset_count": self.asset_count,
            "referenced_files": list(self.referenced_files),
            "warnings": list(self.warnings),
            "build_mode": str(self.build.get("mode") or "none"),
            "has_binding": self.binding is not None,
        }


def load_effect_descriptor(path: str | Path) -> dict[str, Any]:
    descriptor_path = Path(path).expanduser().resolve()
    try:
        with descriptor_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"特效 JSON 解析失败: {descriptor_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("特效 JSON 根节点必须是 object")
    if isinstance(data.get("effect"), dict):
        merged = dict(data["effect"])
        for key, value in data.items():
            if key != "effect" and key not in merged:
                merged[key] = value
        data = merged
    return data


def inspect_effect_descriptor(
    descriptor_path: str | Path,
    descriptor: dict[str, Any] | None = None,
) -> EffectPackageInspection:
    path = Path(descriptor_path).expanduser().resolve()
    data = (
        descriptor
        if descriptor is not None
        else load_effect_descriptor(path)
    )
    canonical = (
        path.name.lower() in EFFECT_PACKAGE_FILENAMES
        or bool(str(data.get("format") or "").strip())
    )
    if not canonical:
        return EffectPackageInspection(
            manifest_path=str(path),
            canonical=False,
            effect_id=str(
                data.get("effect_id")
                or data.get("id")
                or path.stem
            ).strip(),
            representation=str(
                data.get("representation")
                or "effect_descriptor"
            ).strip(),
        )
    if path.name.lower() not in EFFECT_PACKAGE_FILENAMES:
        raise ValueError(
            "Effect Package manifest 必须命名为 "
            f"{EFFECT_PACKAGE_FILENAME}"
        )

    package_format = str(data.get("format") or "").strip()
    if package_format not in EFFECT_PACKAGE_FORMATS:
        raise ValueError(
            f"{EFFECT_PACKAGE_FILENAME} 的 format 必须是 "
            f"{EFFECT_PACKAGE_FORMAT}"
        )
    version = str(data.get("version") or "").strip()
    if version != EFFECT_PACKAGE_VERSION:
        raise ValueError(
            f"不支持的 Effect Package version: "
            f"{version or '<missing>'}"
            f"（当前支持: {EFFECT_PACKAGE_VERSION}）"
        )

    effect_id = str(
        data.get("effect_id")
        or data.get("id")
        or ""
    ).strip()
    _validate_local_id(effect_id, "effect_id")
    representation = str(
        data.get("representation")
        or "niagara_recipe"
    ).strip().lower()
    if representation not in {
        "native_ue_content",
        "niagara_recipe",
        "source_bundle",
        "generated",
    }:
        raise ValueError(
            "effect representation 不支持: "
            f"{representation}（支持: native_ue_content, "
            "niagara_recipe, source_bundle, generated）"
        )

    raw_assets = data.get("assets") or []
    if not isinstance(raw_assets, list):
        raise ValueError(
            f"{EFFECT_PACKAGE_FILENAME} 的 assets 必须是数组"
        )

    assets: dict[str, dict[str, Any]] = {}
    referenced_files: list[str] = []
    warnings: list[str] = []
    for index, raw_asset in enumerate(raw_assets):
        if not isinstance(raw_asset, dict):
            raise ValueError(f"特效包 assets[{index}] 必须是 object")
        asset_id = str(raw_asset.get("id") or "").strip()
        _validate_local_id(asset_id, f"assets[{index}].id")
        if asset_id in assets:
            raise ValueError(f"特效包 asset id 重复: {asset_id}")
        source = str(
            raw_asset.get("source")
            or raw_asset.get("source_path")
            or ""
        ).strip()
        source_path = _resolve_package_source(
            path.parent,
            source,
            f"asset {asset_id}",
        )
        suffix = source_path.suffix.lower()
        if suffix not in EFFECT_PACKAGE_SOURCE_SUFFIXES:
            supported = ", ".join(
                sorted(EFFECT_PACKAGE_SOURCE_SUFFIXES)
            )
            raise ValueError(
                f"特效包 asset {asset_id} 文件类型不支持: "
                f"{suffix}（支持: {supported}）"
            )
        role = _normalize_role(
            raw_asset.get("role")
            or _role_for_suffix(suffix),
            f"asset {asset_id}",
        )
        import_as = str(
            raw_asset.get("import_as")
            or _import_type_for_role(role, suffix)
            or ""
        ).strip().lower()
        if import_as and import_as not in {
            "texture",
            "prop",
            "effect",
            "material",
        }:
            raise ValueError(
                f"特效包 asset {asset_id} import_as 不支持: {import_as}"
            )
        normalized = dict(raw_asset)
        normalized.update(
            {
                "id": asset_id,
                "source": source.replace("\\", "/"),
                "source_path": str(source_path),
                "role": role,
                "import_as": import_as,
            }
        )
        assets[asset_id] = normalized
        referenced_files.append(normalized["source"])
        if not import_as:
            warnings.append(
                f"asset {asset_id} ({suffix}) 作为辅助源文件保留，"
                "当前不会直接导入 UE Asset"
            )

    build = _normalize_build(data)
    if not assets and build.get("mode") == "none":
        raise ValueError(
            f"{EFFECT_PACKAGE_FILENAME} 必须声明 assets，"
            "或提供可解析的 build 配置"
        )

    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("effect metadata 必须是 object")
    binding = data.get("binding")
    if binding is None:
        binding = data.get("bindings")

    return EffectPackageInspection(
        manifest_path=str(path),
        canonical=True,
        format=package_format,
        version=version,
        effect_id=effect_id,
        representation=representation,
        asset_count=len(assets),
        referenced_files=tuple(dict.fromkeys(referenced_files)),
        warnings=tuple(warnings),
        assets=assets,
        build=build,
        binding=binding,
        metadata=dict(metadata),
    )


def _normalize_build(data: dict[str, Any]) -> dict[str, Any]:
    raw_build = data.get("build")
    if raw_build is None:
        entry_asset = str(data.get("entry_asset") or "").strip()
        raw_build = (
            {
                "mode": "existing_asset",
                "entry_asset": entry_asset,
            }
            if entry_asset
            else {"mode": "none"}
        )
    if not isinstance(raw_build, dict):
        raise ValueError("effect build 必须是 object")
    build = dict(raw_build)
    mode = str(build.get("mode") or "none").strip().lower()
    if mode not in EFFECT_BUILD_MODES:
        allowed = ", ".join(sorted(EFFECT_BUILD_MODES))
        raise ValueError(
            f"effect build.mode 不支持: {mode}（支持: {allowed}）"
        )
    build["mode"] = mode
    if mode == "existing_asset":
        entry_asset = str(
            build.get("entry_asset")
            or build.get("asset")
            or ""
        ).strip()
        if not entry_asset.startswith("/Game/") and not entry_asset.startswith(
            "/Niagara/"
        ):
            raise ValueError(
                "existing_asset build 需要有效的 entry_asset UE 路径"
            )
        build["entry_asset"] = entry_asset
    elif mode == "duplicate_template":
        template = str(build.get("template") or "").strip()
        if not template.startswith("/"):
            raise ValueError(
                "duplicate_template build 需要 template UE 资产路径"
            )
        build["template"] = template
        output_name = str(build.get("output_name") or "").strip()
        if output_name and not EFFECT_PACKAGE_ID_PATTERN.fullmatch(
            output_name
        ):
            raise ValueError(
                "effect build.output_name 只能包含字母、数字、点、"
                "下划线或短横线"
            )
    return build


def _validate_local_id(value: str, field_name: str) -> None:
    if not value or not EFFECT_PACKAGE_ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"{field_name} 必须匹配 "
            f"{EFFECT_PACKAGE_ID_PATTERN.pattern}: {value!r}"
        )


def _resolve_package_source(
    root: Path,
    source: str,
    label: str,
) -> Path:
    if not source:
        raise ValueError(f"特效包 {label} 缺少 source")
    relative = Path(source)
    if relative.is_absolute():
        raise ValueError(
            f"特效包 {label} 的 source 必须是包内相对路径: {source}"
        )
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"特效包 {label} 的 source 越出特效包目录: {source}"
        ) from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"特效包 {label} 文件不存在: {source}")
    return resolved


def _normalize_role(value: Any, label: str) -> str:
    role = (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    aliases = {
        "static_mesh": "mesh",
        "geometry": "mesh",
        "flipbook": "texture",
        "image": "texture",
        "volume": "cache",
        "recipe": "data",
        "config": "data",
    }
    role = aliases.get(role, role)
    if role not in EFFECT_PACKAGE_ROLES:
        allowed = ", ".join(sorted(EFFECT_PACKAGE_ROLES))
        raise ValueError(
            f"特效包 {label} role 不支持: {role}（支持: {allowed}）"
        )
    return role


def _role_for_suffix(suffix: str) -> str:
    if suffix in EFFECT_TEXTURE_SUFFIXES:
        return "texture"
    if suffix in EFFECT_MESH_SUFFIXES:
        return "mesh"
    if suffix in {".hlsl", ".usf"}:
        return "shader"
    if suffix in {".vdb", ".bgeo"}:
        return "cache"
    if suffix in {".wav", ".ogg"}:
        return "audio"
    return "data"


def _import_type_for_role(role: str, suffix: str) -> str:
    if role == "texture" and suffix in EFFECT_TEXTURE_SUFFIXES:
        return "texture"
    if role == "mesh" and suffix in EFFECT_MESH_SUFFIXES:
        return "prop"
    return ""


__all__ = [
    "EFFECT_PACKAGE_FILENAME",
    "EFFECT_PACKAGE_FILENAMES",
    "EFFECT_PACKAGE_FORMAT",
    "EFFECT_PACKAGE_FORMATS",
    "EFFECT_PACKAGE_SOURCE_SUFFIXES",
    "EFFECT_PACKAGE_VERSION",
    "EffectPackageInspection",
    "inspect_effect_descriptor",
    "load_effect_descriptor",
]
