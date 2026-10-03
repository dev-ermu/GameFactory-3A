"""UE avatar importer."""

from engine_adapters.ue5._internal.transport import Transport

from ..config import DEFAULT_AVATAR_DEST
from ..builders import AvatarImportScriptBuilder
from .base import BaseImporter, suffixes_for


class AvatarImporter(BaseImporter):
    asset_type_name = "avatar"

    def __init__(self, transport: Transport | None = None) -> None:
        super().__init__(DEFAULT_AVATAR_DEST, suffixes_for("avatar"), AvatarImportScriptBuilder(), transport=transport)
