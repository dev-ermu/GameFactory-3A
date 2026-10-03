"""UE asset registry adapter."""

from engine_adapters.ue5._internal.transport import Transport

from engine_adapters.ue5.assets._internal.types import AssetQuery

from .asset_registry import AssetRegistry
from .config import DEFAULT_IMPORT_ROOT


class UEAssetRegistry:
    def __init__(
        self,
        transport: Transport | None = None,
    ) -> None:
        self._registry = AssetRegistry(transport=transport)

    def list_assets(self, query: AssetQuery) -> list[dict]:
        root_path = query.root_path or DEFAULT_IMPORT_ROOT
        if query.type_key:
            asset_type = (
                "prop"
                if query.type_key == "static_mesh"
                else query.type_key
            )
            return self._registry.list_assets(
                root_path=root_path,
                asset_type=asset_type,
            )
        return self._registry.list_assets(
            root_path=root_path
        )
