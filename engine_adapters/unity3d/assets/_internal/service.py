"""Asset service wrapping backend and registry."""

from typing import Any, Optional

from engine_adapters.unity3d.assets._internal.artifacts import ArtifactRegistry, build_artifact_records
from engine_adapters.unity3d.assets._internal.artifacts.models import asset_id_from_source, normalize_artifact_type
from engine_adapters.unity3d.assets._internal.unity.dispatcher import UnityImportDispatcher
from engine_adapters.unity3d.config import UNITY_ASSET_TYPE_DEFAULT_DESTS


SUPPORTED_IMPORT_ASSET_TYPES = {
    "avatar",
    "motion",
    "prop",
    "environment",
    "effect",
    "material",
    "texture",
    "weapon",
    "static_mesh",
    "scene",
}


class AssetService:
    def __init__(
        self,
        dispatcher: UnityImportDispatcher,
        artifact_registry: ArtifactRegistry,
    ) -> None:
        self.dispatcher = dispatcher
        self.artifacts = artifact_registry

    def default_destination(self, asset_type: str) -> str:
        normalized = normalize_artifact_type(asset_type)
        return UNITY_ASSET_TYPE_DEFAULT_DESTS.get(
            normalized,
            "Assets/Imported/Props",
        )

    def import_asset(self, src_path: str, asset_type: str, dst_path: str = "", **options: Any) -> dict:
        raw_asset_type = (asset_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        if raw_asset_type not in SUPPORTED_IMPORT_ASSET_TYPES:
            supported = ", ".join(sorted(SUPPORTED_IMPORT_ASSET_TYPES))
            raise ValueError(f"Unsupported asset type: {asset_type} (supported: {supported})")
        if not dst_path:
            dst_path = self.default_destination(raw_asset_type)
        result = self.dispatcher.import_asset(
            src_path,
            raw_asset_type,
            dst_path=dst_path,
            **options,
        )
        if result.get("ok"):
            result.setdefault(
                "asset_id",
                str(options.get("name") or asset_id_from_source(src_path)),
            )
            artifacts = build_artifact_records(
                result,
                backend="unity",
                category=str(options.get("category") or ""),
            )
            if artifacts:
                self.artifacts.upsert_many(artifacts)
                result["artifacts"] = [artifact.to_dict() for artifact in artifacts]
                result["asset_id"] = artifacts[0].asset_id
                result["type"] = artifacts[0].type
                result["backend"] = artifacts[0].backend
            else:
                result["artifacts"] = []
        return result

    def validate_asset(self, src_path: str, asset_type: str, dst_path: str = "", **options: Any) -> dict:
        return self.dispatcher.validate_asset(src_path, asset_type, dst_path=dst_path, **options)

    def list_assets(self, asset_type: Optional[str] = None, root_path: str = "Assets/Imported") -> list[dict]:
        return self.dispatcher.list_assets(asset_type=asset_type or "", root_path=root_path)
