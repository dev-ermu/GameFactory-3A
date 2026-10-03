"""UE generic mesh/material/texture/effect importer."""

from engine_adapters.ue5._internal.transport import Transport

from ..asset_types import ASSET_TYPE_SUFFIXES, default_dest_for_asset_type
from ..builders import GenericImportScriptBuilder
from .base import BaseImporter


class GenericImporter(BaseImporter):
    def __init__(self, asset_type_name: str, transport: Transport | None = None) -> None:
        key = "prop" if asset_type_name == "static_mesh" else asset_type_name
        super().__init__(default_dest_for_asset_type(key), ASSET_TYPE_SUFFIXES[key], GenericImportScriptBuilder(), transport=transport)
        self.asset_type_name = key
