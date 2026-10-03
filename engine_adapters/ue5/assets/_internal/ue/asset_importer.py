"""UE asset import operations for the asset pipeline."""

import textwrap
from pathlib import Path
from typing import Any

from engine_adapters.ue5.assets._internal.types import ImportRequest

from .asset_types import ASSET_TYPE_SUFFIXES
from .backend import UEAssetBackend
from .config import DEFAULT_AVATAR_DEST, DEFAULT_IMPORT_ROOT, DEFAULT_MOTION_DEST, DEFAULT_SCENE_DEST
from .scripts.import_scripts import _build_fbx_import_script, _build_generic_import_script, _build_motion_import_script
from engine_adapters.ue5._internal.transport.python_rpc import _call_ue_python_json, call_ue_python
from .utils import normalize_dest_path, validate_local_file


def import_fbx_to_ue(
    local_path: str,
    dest_path: str = DEFAULT_AVATAR_DEST,
    as_skeletal: bool = True,
) -> bool:
    local_path = validate_local_file(local_path, (".fbx",))
    dest_path = normalize_dest_path(dest_path, DEFAULT_AVATAR_DEST)
    call_ue_python(_build_fbx_import_script(local_path, dest_path, as_skeletal, "FBX"))
    return True


def import_glb_to_ue(local_path: str, dest_path: str = DEFAULT_AVATAR_DEST) -> bool:
    local_path = validate_local_file(local_path, (".glb", ".gltf"))
    dest_path = normalize_dest_path(dest_path, DEFAULT_AVATAR_DEST)
    call_ue_python(_build_generic_import_script(local_path, dest_path, "GLB/GLTF"))
    return True


def _import_fbx_asset_paths(local_path: str, dest_path: str, as_skeletal: bool, label: str) -> list[str]:
    local_path = validate_local_file(local_path, (".fbx",))
    dest_path = normalize_dest_path(dest_path, DEFAULT_IMPORT_ROOT)
    script = _build_fbx_import_script(local_path, dest_path, as_skeletal, label) + textwrap.dedent("""\

        result = imported_paths
    """)
    return _call_ue_python_json(script)


def _import_generic_asset_paths(local_path: str, dest_path: str, label: str, allowed_suffixes: tuple[str, ...]) -> list[str]:
    local_path = validate_local_file(local_path, allowed_suffixes)
    dest_path = normalize_dest_path(dest_path, DEFAULT_IMPORT_ROOT)
    script = _build_generic_import_script(local_path, dest_path, label) + textwrap.dedent("""\

        result = imported_paths
    """)
    return _call_ue_python_json(script)


def _asset_import_result(asset_type: str, src_path: str, dest_path: str, imported_paths: list[str]) -> dict:
    return {
        "asset_type": asset_type,
        "src_path": str(Path(src_path).expanduser().resolve()),
        "dest_path": dest_path,
        "imported_paths": imported_paths,
    }


def import_avatar_to_ue(
    avatar_path: str,
    dest_path: str = DEFAULT_AVATAR_DEST,
    as_skeletal: bool = True,
) -> bool:
    suffix = Path(avatar_path).suffix.lower()
    if suffix == ".fbx":
        return import_fbx_to_ue(avatar_path, dest_path, as_skeletal=as_skeletal)
    if suffix in (".glb", ".gltf"):
        return import_glb_to_ue(avatar_path, dest_path)
    raise ValueError(f"不支持的 avatar 文件类型: {suffix}（支持 .fbx / .glb / .gltf）")


def import_scene_to_ue(scene_path: str, dest_path: str = DEFAULT_SCENE_DEST) -> bool:
    suffix = Path(scene_path).suffix.lower()
    if suffix == ".fbx":
        local_path = validate_local_file(scene_path, (".fbx",))
        dest_path = normalize_dest_path(dest_path, DEFAULT_SCENE_DEST)
        call_ue_python(_build_fbx_import_script(local_path, dest_path, False, "Scene FBX"))
        return True
    if suffix in (".glb", ".gltf", ".usd"):
        local_path = validate_local_file(scene_path, (".glb", ".gltf", ".usd"))
        dest_path = normalize_dest_path(dest_path, DEFAULT_SCENE_DEST)
        call_ue_python(_build_generic_import_script(local_path, dest_path, "Scene"))
        return True
    raise ValueError(f"不支持的 scene 文件类型: {suffix}（支持 .fbx / .glb / .gltf / .usd）")


def import_asset(src_path: str, dst_path: str = "", asset_type: str = "prop", **options: Any) -> dict:
    request = ImportRequest.from_values(src_path, asset_type, dst_path=dst_path, **options)
    return UEAssetBackend().import_asset(request)


def import_motion_to_ue(
    motion_path: str,
    avatar_name: str = "",
    dest_path: str = DEFAULT_MOTION_DEST,
    skeleton_asset_path: str = "",
) -> bool:
    local_path = validate_local_file(motion_path, (".fbx",))
    dest_path = normalize_dest_path(dest_path, DEFAULT_MOTION_DEST)
    skeleton_asset_path = (skeleton_asset_path or "").strip()
    avatar_name = (avatar_name or "").strip()
    call_ue_python(_build_motion_import_script(local_path, dest_path, skeleton_asset_path, avatar_name))
    return True


def import_motion_to_ue_paths(
    motion_path: str,
    avatar_name: str = "",
    dest_path: str = DEFAULT_MOTION_DEST,
    skeleton_asset_path: str = "",
) -> list[str]:
    local_path = validate_local_file(motion_path, (".fbx",))
    dest_path = normalize_dest_path(dest_path, DEFAULT_MOTION_DEST)
    skeleton_asset_path = (skeleton_asset_path or "").strip()
    avatar_name = (avatar_name or "").strip()
    script = _build_motion_import_script(local_path, dest_path, skeleton_asset_path, avatar_name) + textwrap.dedent("""\

        result = imported_paths
    """)
    return _call_ue_python_json(script)


def import_motion_fbx_to_ue(
    motion_path: str,
    dest_path: str = DEFAULT_MOTION_DEST,
    skeleton_asset_path: str = "",
) -> bool:
    return import_motion_to_ue(motion_path, dest_path=dest_path, skeleton_asset_path=skeleton_asset_path)


class AssetImporter:
    def import_asset(self, src_path: str, dst_path: str = "", asset_type: str = "prop", **options: Any) -> dict:
        return import_asset(src_path, dst_path=dst_path, asset_type=asset_type, **options)

    def import_avatar(self, avatar_path: str, dest_path: str = DEFAULT_AVATAR_DEST, as_skeletal: bool = True) -> bool:
        return import_avatar_to_ue(avatar_path, dest_path=dest_path, as_skeletal=as_skeletal)

    def import_motion(
        self,
        motion_path: str,
        dest_path: str = DEFAULT_MOTION_DEST,
        skeleton_asset_path: str = "",
        avatar_name: str = "",
    ) -> bool:
        return import_motion_to_ue(
            motion_path,
            avatar_name=avatar_name,
            dest_path=dest_path,
            skeleton_asset_path=skeleton_asset_path,
        )

    def import_scene(self, scene_path: str, dest_path: str = DEFAULT_SCENE_DEST) -> bool:
        return import_scene_to_ue(scene_path, dest_path=dest_path)
