"""Generic import script builder."""

from pathlib import Path

from engine_adapters.ue5.assets._internal.types import ImportRequest

from ..scripts.import_scripts import (
    _build_fbx_import_script,
    _build_generic_import_script,
    _build_scene_generic_import_script,
    _build_scene_import_script,
)

from .base import ScriptBuilder


class GenericImportScriptBuilder(ScriptBuilder):
    def build_import_script(self, request: ImportRequest, dest_path: str) -> str:
        suffix = Path(request.src_path).suffix.lower()
        generate_collision = bool(request.options.get("generate_collision", False))
        if (
            request.type_key in {"prop", "weapon", "static_mesh"}
            and generate_collision
            and not bool(request.options.get("as_skeletal", False))
        ):
            if suffix == ".fbx":
                return _build_scene_import_script(
                    request.src_path,
                    dest_path,
                    f"{request.type_key.title()} FBX",
                    generate_collision=True,
                    combine_meshes=bool(
                        request.options.get("combine_meshes", True)
                    ),
                )
            return _build_scene_generic_import_script(
                request.src_path,
                dest_path,
                request.type_key.title(),
                generate_collision=True,
            )
        if request.type_key in {"prop", "weapon", "static_mesh"} and suffix == ".fbx":
            label = "Prop" if request.type_key == "static_mesh" else request.type_key.title()
            return _build_fbx_import_script(
                request.src_path,
                dest_path,
                bool(request.options.get("as_skeletal", False)),
                f"{label} FBX",
            )
        label = "Static Mesh" if request.type_key == "static_mesh" else request.type_key.title()
        return _build_generic_import_script(request.src_path, dest_path, label)
