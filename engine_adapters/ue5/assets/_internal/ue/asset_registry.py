"""UE Asset Registry queries for the asset pipeline."""

import textwrap
from typing import Optional

from engine_adapters.ue5._internal.transport import (
    PythonRPCTransport,
    Transport,
)

from .asset_types import ASSET_TYPE_CLASSES, _normalize_asset_type
from .config import DEFAULT_IMPORT_ROOT
from .utils import normalize_dest_path


def _execute_json(
    script: str,
    transport: Transport | None,
):
    return (
        transport
        or PythonRPCTransport()
    ).execute_json(script)


def _asset_class_name_expr() -> str:
    return textwrap.dedent("""\
        def _asset_class_name(asset_data):
            try:
                return str(asset_data.asset_class_path.asset_name)
            except Exception:
                try:
                    return str(asset_data.asset_class)
                except Exception:
                    return ""
    """)


def list_ue_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    root_path = normalize_dest_path(root_path, DEFAULT_IMPORT_ROOT)
    script = _asset_class_name_expr() + textwrap.dedent(f"""\
        import unreal
        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = asset_registry.get_assets_by_path({root_path!r}, recursive=True)
        result = []
        for asset_data in assets:
            class_name = _asset_class_name(asset_data)
            package_name = str(asset_data.package_name)
            package_path = str(asset_data.package_path)
            asset_name = str(asset_data.asset_name)
            result.append({{
                "name": asset_name,
                "path": package_name,
                "class": class_name,
                "package_path": package_path,
            }})
    """)
    return _execute_json(script, transport)


def _filter_assets_by_class(assets: list[dict], class_names: tuple[str, ...]) -> list[dict]:
    allowed = set(class_names)
    return [asset for asset in assets if asset.get("class") in allowed]


def _technical_avatar_suffixes_expr() -> str:
    return textwrap.dedent("""\
        import re

        TECHNICAL_AVATAR_SUFFIXES = (
            "_skeleton",
            "_physicsasset",
            "_anim",
            "_anim_mixamo_com",
            "_diffuse",
            "_normal",
            "_specular",
            "_glossiness",
            "_roughness",
            "_metallic",
            "_basecolor",
            "_albedo",
            "_opacity",
            "_emissive",
            "_ao",
            "_mat",
            "_body",
            "mat",
        )

        def _looks_like_runtime_avatar(asset_name):
            normalized = str(asset_name or "").strip().lower()
            if not normalized:
                return False
            if re.search(r"(_body|_body\\d+)$", normalized):
                return False
            return not any(normalized.endswith(suffix) for suffix in TECHNICAL_AVATAR_SUFFIXES)
    """)


def _list_skeleton_assets_with_inferred(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    root_path = normalize_dest_path(root_path, DEFAULT_IMPORT_ROOT)
    script = _asset_class_name_expr() + textwrap.dedent(f"""\
        import unreal

        def _package_path_from_object(obj):
            path = str(obj.get_path_name())
            return path.split(".", 1)[0]

        def _asset_name_from_path(path):
            return path.rsplit("/", 1)[-1]

        def _add_skeleton(path, inferred_from=""):
            if not path or path in seen:
                return
            seen.add(path)
            result.append({{
                "name": _asset_name_from_path(path),
                "path": path,
                "class": "Skeleton",
                "package_path": path.rsplit("/", 1)[0],
                "inferred_from": inferred_from,
            }})

        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = asset_registry.get_assets_by_path({root_path!r}, recursive=True)
        result = []
        seen = set()
        skeletal_meshes = []
        for asset_data in assets:
            class_name = _asset_class_name(asset_data)
            package_name = str(asset_data.package_name)
            if class_name == "Skeleton":
                _add_skeleton(package_name)
            elif class_name == "SkeletalMesh":
                skeletal_meshes.append(package_name)

        for mesh_path in skeletal_meshes:
            try:
                mesh = unreal.load_asset(mesh_path)
                skeleton = mesh.get_editor_property("skeleton") if mesh is not None else None
                if skeleton is not None:
                    _add_skeleton(_package_path_from_object(skeleton), mesh_path)
            except Exception as exc:
                unreal.log_warning(f"[A3Game] 无法从 SkeletalMesh 推断 Skeleton {{mesh_path}}: {{exc}}")
    """)
    return _execute_json(script, transport)


def _skeleton_info_expr() -> str:
    return textwrap.dedent("""\
        def _package_path_from_object(obj):
            path = str(obj.get_path_name())
            return path.split(".", 1)[0]

        def _asset_name_from_path(path):
            return path.rsplit("/", 1)[-1]

        def _skeleton_path(asset):
            if asset is None:
                return ""
            skeleton = None
            for property_name in ("skeleton", "target_skeleton", "preview_skeletal_mesh"):
                try:
                    value = asset.get_editor_property(property_name)
                except Exception:
                    value = getattr(asset, property_name, None)
                if value is None:
                    continue
                if property_name == "preview_skeletal_mesh":
                    try:
                        value = value.get_editor_property("skeleton")
                    except Exception:
                        value = getattr(value, "skeleton", None)
                if value is not None:
                    skeleton = value
                    break
            if skeleton is None:
                method = getattr(asset, "get_skeleton", None)
                if method is not None:
                    try:
                        skeleton = method()
                    except Exception:
                        skeleton = None
            if skeleton is None:
                return ""
            return _package_path_from_object(skeleton)
    """)


def _list_motion_assets_with_skeleton(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    root_path = normalize_dest_path(root_path, DEFAULT_IMPORT_ROOT)
    script = _asset_class_name_expr() + _skeleton_info_expr() + textwrap.dedent(f"""\
        import unreal
        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = asset_registry.get_assets_by_path({root_path!r}, recursive=True)
        result = []
        for asset_data in assets:
            class_name = _asset_class_name(asset_data)
            if class_name != "AnimSequence":
                continue
            package_name = str(asset_data.package_name)
            package_path = str(asset_data.package_path)
            asset_name = str(asset_data.asset_name)
            animation = unreal.load_asset(package_name)
            skeleton_path = _skeleton_path(animation)
            result.append({{
                "name": asset_name,
                "path": package_name,
                "class": class_name,
                "package_path": package_path,
                "skeleton_path": skeleton_path,
                "skeleton_name": _asset_name_from_path(skeleton_path) if skeleton_path else "",
            }})
    """)
    return _execute_json(script, transport)


def _list_avatar_assets_with_skeleton(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    root_path = normalize_dest_path(root_path, DEFAULT_IMPORT_ROOT)
    script = _asset_class_name_expr() + _skeleton_info_expr() + _technical_avatar_suffixes_expr() + textwrap.dedent(f"""\
        import unreal
        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = asset_registry.get_assets_by_path({root_path!r}, recursive=True)
        result = []
        for asset_data in assets:
            class_name = _asset_class_name(asset_data)
            if class_name != "SkeletalMesh":
                continue
            package_name = str(asset_data.package_name)
            package_path = str(asset_data.package_path)
            asset_name = str(asset_data.asset_name)
            if not _looks_like_runtime_avatar(asset_name):
                continue
            avatar_asset = unreal.load_asset(package_name)
            skeleton_path = _skeleton_path(avatar_asset)
            result.append({{
                "name": asset_name,
                "path": package_name,
                "class": class_name,
                "package_path": package_path,
                "skeleton_path": skeleton_path,
                "skeleton_name": _asset_name_from_path(skeleton_path) if skeleton_path else "",
            }})
    """)
    return _execute_json(script, transport)


def list_assets_by_type(
    asset_type: str,
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    normalized = _normalize_asset_type(asset_type)
    if normalized == "avatar":
        return _list_avatar_assets_with_skeleton(
            root_path,
            transport=transport,
        )
    if normalized == "skeleton":
        return _list_skeleton_assets_with_inferred(
            root_path,
            transport=transport,
        )
    if normalized == "motion":
        return _list_motion_assets_with_skeleton(
            root_path,
            transport=transport,
        )
    return _filter_assets_by_class(
        list_ue_assets(
            root_path,
            transport=transport,
        ),
        ASSET_TYPE_CLASSES[normalized],
    )


def list_avatar_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "avatar",
        root_path,
        transport=transport,
    )


def list_skeleton_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "skeleton",
        root_path,
        transport=transport,
    )


def list_motion_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "motion",
        root_path,
        transport=transport,
    )


def list_effect_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "effect",
        root_path,
        transport=transport,
    )


def list_material_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "material",
        root_path,
        transport=transport,
    )


def list_texture_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "texture",
        root_path,
        transport=transport,
    )


def list_prop_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "prop",
        root_path,
        transport=transport,
    )


def list_weapon_assets(
    root_path: str = DEFAULT_IMPORT_ROOT,
    *,
    transport: Transport | None = None,
) -> list[dict]:
    return list_assets_by_type(
        "weapon",
        root_path,
        transport=transport,
    )


class AssetRegistry:
    def __init__(
        self,
        transport: Transport | None = None,
    ) -> None:
        self.transport = transport

    def list_assets(self, root_path: str = DEFAULT_IMPORT_ROOT, asset_type: Optional[str] = None) -> list[dict]:
        if asset_type:
            return list_assets_by_type(
                asset_type,
                root_path=root_path,
                transport=self.transport,
            )
        return list_ue_assets(
            root_path,
            transport=self.transport,
        )

    def list_avatar_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_avatar_assets(
            root_path,
            transport=self.transport,
        )

    def list_skeleton_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_skeleton_assets(
            root_path,
            transport=self.transport,
        )

    def list_motion_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_motion_assets(
            root_path,
            transport=self.transport,
        )

    def list_effect_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_effect_assets(
            root_path,
            transport=self.transport,
        )

    def list_material_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_material_assets(
            root_path,
            transport=self.transport,
        )

    def list_texture_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_texture_assets(
            root_path,
            transport=self.transport,
        )

    def list_prop_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_prop_assets(
            root_path,
            transport=self.transport,
        )

    def list_weapon_assets(self, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return list_weapon_assets(
            root_path,
            transport=self.transport,
        )
