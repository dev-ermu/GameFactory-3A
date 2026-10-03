"""Unreal Engine asset backend."""

from engine_adapters.ue5.assets._internal.types import ASSET_GROUP_TYPE_NAMES, AssetQuery, ImportRequest, ValidationResult
from engine_adapters.ue5.assets._internal.project_content import (
    configured_project_content_dir,
    project_imported_assets,
)

from .asset_types import default_dest_for_asset_type
from .config import DEFAULT_IMPORT_ROOT
from .dispatcher import UEImportDispatcher
from .local_scan import dedupe_avatar_assets, list_local_imported_assets, merge_asset_lists
from .registry import UEAssetRegistry


class UEAssetBackend:
    engine = "ue"

    def __init__(self, dispatcher: UEImportDispatcher | None = None, registry: UEAssetRegistry | None = None) -> None:
        self.dispatcher = dispatcher or UEImportDispatcher()
        self.registry = registry or UEAssetRegistry()

    def default_destination(self, asset_type: str) -> str:
        if asset_type == "static_mesh":
            asset_type = "prop"
        return default_dest_for_asset_type(asset_type)

    def validate_asset(self, request: ImportRequest) -> ValidationResult:
        return self.dispatcher.validate_asset(request)

    def import_asset(self, request: ImportRequest) -> dict:
        if request.type_key == "skeleton":
            raise ValueError("Skeleton 资产通常由 SkeletalMesh Avatar 导入生成，请导入 avatar 或选择已有 Skeleton")
        return self.dispatcher.import_asset(request)

    def list_assets(self, query: AssetQuery) -> list[dict]:
        asset_type = query.type_key or None
        if asset_type == "static_mesh":
            asset_type = "prop"
        root_path = query.root_path or DEFAULT_IMPORT_ROOT
        if asset_type in ASSET_GROUP_TYPE_NAMES and (not query.root_path or query.root_path.rstrip("/").lower() == DEFAULT_IMPORT_ROOT.lower()):
            root_path = default_dest_for_asset_type(asset_type)
        if asset_type in {"avatar", "motion"}:
            local_assets = list_local_imported_assets(asset_type)
            if local_assets:
                return dedupe_avatar_assets(local_assets) if asset_type == "avatar" else local_assets
        if (
            asset_type in ASSET_GROUP_TYPE_NAMES
            and configured_project_content_dir() is not None
        ):
            local_assets = project_imported_assets(asset_type)
            return (
                dedupe_avatar_assets(local_assets)
                if asset_type == "avatar"
                else local_assets
            )
        try:
            assets = self.registry.list_assets(AssetQuery.from_values(asset_type=asset_type, root_path=root_path))
        except Exception:
            assets = []
        if asset_type not in {"avatar", "motion"}:
            return assets
        merged = merge_asset_lists(assets, list_local_imported_assets(asset_type))
        return dedupe_avatar_assets(merged) if asset_type == "avatar" else merged

    def list_all_groups(self, root_path: str = DEFAULT_IMPORT_ROOT) -> dict:
        groups: dict[str, list[dict] | dict[str, str]] = {}
        errors: dict[str, str] = {}
        for asset_type in ASSET_GROUP_TYPE_NAMES:
            try:
                groups[asset_type] = self.list_assets(AssetQuery.from_values(asset_type=asset_type, root_path=root_path))
            except Exception as exc:
                groups[asset_type] = []
                errors[asset_type] = f"{type(exc).__name__}: {exc}"
        if errors:
            groups["_errors"] = errors
        return groups
