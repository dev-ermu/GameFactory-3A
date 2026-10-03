"""Avatar import script builder."""

from pathlib import Path

from engine_adapters.ue5.assets._internal.types import ImportRequest

from ..scripts.import_scripts import _build_fbx_import_script, _build_generic_import_script

from .base import ScriptBuilder


class AvatarImportScriptBuilder(ScriptBuilder):
    def build_import_script(self, request: ImportRequest, dest_path: str) -> str:
        suffix = Path(request.src_path).suffix.lower()
        if suffix == ".fbx":
            return _build_fbx_import_script(
                request.src_path,
                dest_path,
                bool(request.options.get("as_skeletal", True)),
                "Avatar FBX",
                import_animations=False,
            )
        return _build_generic_import_script(request.src_path, dest_path, "Avatar")
