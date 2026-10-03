"""UE scene importer."""

from dataclasses import replace
from pathlib import Path

from engine_adapters.ue5._internal.transport import Transport

from ..config import DEFAULT_SCENE_DEST
from ..builders import SceneImportScriptBuilder
from .base import BaseImporter, suffixes_for


class SceneImporter(BaseImporter):
    asset_type_name = "scene"

    def __init__(self, transport: Transport | None = None) -> None:
        super().__init__(DEFAULT_SCENE_DEST, suffixes_for("scene"), SceneImportScriptBuilder(), transport=transport)

    def validate(self, request):
        result = super().validate(request)
        if Path(request.src_path).suffix.lower() == ".json":
            result = replace(
                result,
                errors=[
                    error
                    for error in result.errors
                    if "文件类型" not in error
                ],
            )
        return result
