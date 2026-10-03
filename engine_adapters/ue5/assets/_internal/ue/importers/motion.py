"""UE motion importer."""

from engine_adapters.ue5._internal.transport import Transport

from ..config import DEFAULT_MOTION_DEST
from ..builders import MotionImportScriptBuilder
from .base import BaseImporter, suffixes_for


class MotionImporter(BaseImporter):
    asset_type_name = "motion"

    def __init__(self, transport: Transport | None = None) -> None:
        super().__init__(DEFAULT_MOTION_DEST, suffixes_for("motion"), MotionImportScriptBuilder(), transport=transport)
