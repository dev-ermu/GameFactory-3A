"""Scene import script builder."""

from pathlib import Path

from engine_adapters.ue5.assets._internal.types import ImportRequest

from ..scripts.import_scripts import (
    _build_scene_generic_import_script,
    _build_scene_import_script,
)

from .base import ScriptBuilder


class SceneImportScriptBuilder(ScriptBuilder):
    def build_import_script(self, request: ImportRequest, dest_path: str) -> str:
        suffix = Path(request.src_path).suffix.lower()
        if suffix == ".json":
            raise ValueError(
                "Scene JSON 是 World 场景描述文件，不能直接作为 UE 资产导入；"
                "请使用 /api/worlds/build 创建 Runtime Package"
            )
        if suffix == ".fbx":
            return _build_scene_import_script(
                request.src_path,
                dest_path,
                "Scene FBX",
                generate_collision=bool(request.options.get("generate_collision", True)),
                combine_meshes=bool(request.options.get("combine_meshes", True)),
                force_complex_collision=bool(
                    request.options.get("force_complex_collision", False)
                ),
            )
        return _build_scene_generic_import_script(
            request.src_path,
            dest_path,
            "Scene",
            generate_collision=bool(request.options.get("generate_collision", True)),
            force_complex_collision=bool(
                request.options.get("force_complex_collision", False)
            ),
        )
