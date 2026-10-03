"""UI/API-friendly asset operations."""

from dataclasses import replace
from typing import Any, Optional

from engine_adapters.ue5.assets._internal.backend import AssetBackend
from engine_adapters.ue5.assets._internal.backend_registry import AssetBackendRegistry, get_default_backend_registry
from engine_adapters.ue5.assets._internal.types import (
    ASSET_GROUP_TYPE_NAMES,
    SUPPORTED_IMPORT_ASSET_TYPE_NAMES,
    AssetQuery,
    ImportRequest,
    ValidationResult,
)
from engine_adapters.ue5.assets._internal.artifacts import ArtifactRegistry, build_artifact_records
from engine_adapters.ue5.assets._internal.artifacts.models import asset_id_from_source, normalize_artifact_type, normalize_backend_path
from engine_adapters.ue5.assets._internal.pipeline import ArtifactRegistryRepository, UEImportPipeline
from engine_adapters.ue5.assets._internal.ue.backend import UEAssetBackend
from engine_adapters.ue5.assets._internal.ue.config import DEFAULT_IMPORT_ROOT
from engine_adapters.ue5.assets._internal.ue.utils import normalize_dest_path

SUPPORTED_IMPORT_ASSET_TYPES = SUPPORTED_IMPORT_ASSET_TYPE_NAMES
ASSET_GROUP_TYPES = ASSET_GROUP_TYPE_NAMES

TECHNICAL_AVATAR_SUFFIXES = (
    "_skeleton",
    "_physicsasset",
    "_anim",
    "_anim_mixamo_com",
    "_diffuse",
    "_normal",
    "_specular",
    "_glossiness",
    "_roughness",
    "_metallic",
    "_basecolor",
    "_albedo",
    "_opacity",
    "_emissive",
    "_ao",
    "_mat",
    "_body",
    "mat",
)

PACKAGE_ISOLATED_TYPES = {"avatar", "motion", "prop", "environment"}
PROP_CATEGORY_TYPES = {"object", "weapon", "furniture", "decoration"}


class AssetService:
    def __init__(
        self,
        backend: Optional[AssetBackend] = None,
        backend_registry: Optional[AssetBackendRegistry] = None,
        backend_name: str = "",
        artifact_registry: Optional[ArtifactRegistry] = None,
    ) -> None:
        if backend is not None:
            self.backend = backend
        else:
            registry = backend_registry or get_default_backend_registry()
            self.backend = registry.get(backend_name)
        self.artifacts = artifact_registry or ArtifactRegistry()
        self.pipeline = None
        if isinstance(self.backend, UEAssetBackend):
            self.pipeline = UEImportPipeline(
                dispatcher=self.backend.dispatcher,
                content_registry=self.backend.registry,
                artifact_repository=ArtifactRegistryRepository(self.artifacts),
            )

    def default_destination(self, asset_type: str) -> str:
        return self.backend.default_destination(asset_type)

    def import_asset(self, src_path: str, asset_type: str, dst_path: str = "", **options: Any) -> dict:
        raw_asset_type = (asset_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        request = ImportRequest.from_values(src_path, asset_type, dst_path=dst_path, **options)
        if request.type_key not in SUPPORTED_IMPORT_ASSET_TYPES:
            supported = ", ".join(SUPPORTED_IMPORT_ASSET_TYPES)
            raise ValueError(f"不支持的资产类型: {asset_type}（支持: {supported}）")
        if raw_asset_type in PROP_CATEGORY_TYPES and not request.options.get("category"):
            request = replace(request, options={**request.options, "category": raw_asset_type})
        if not request.dst_path or self._is_type_root_destination(request.type_key, request.dst_path):
            request = replace(
                request,
                dst_path=self._default_package_destination(
                    request.type_key,
                    request.src_path,
                    request.options,
                ),
            )
        if self.pipeline is not None:
            pipeline_result = self.pipeline.run(request)
            if pipeline_result.errors:
                raise RuntimeError("; ".join(pipeline_result.errors))
            result = pipeline_result.to_dict()
            artifacts = pipeline_result.artifacts
            if artifacts:
                result["asset_id"] = artifacts[0].asset_id
                result["type"] = artifacts[0].type
                result["backend"] = artifacts[0].backend
            result["ok"] = True
            return result
        result = self.backend.import_asset(request)
        artifacts = self._register_import_artifacts(result, request)
        result["artifacts"] = [artifact.to_dict() for artifact in artifacts]
        result["ok"] = True
        return result

    def _default_package_destination(
        self,
        asset_type: str,
        src_path: str,
        options: Optional[dict[str, Any]] = None,
    ) -> str:
        canonical_type = normalize_artifact_type(asset_type)
        root = self.default_destination(canonical_type)
        if canonical_type not in PACKAGE_ISOLATED_TYPES:
            return root
        package_id = asset_id_from_source(src_path)
        if canonical_type == "motion":
            skeleton_path = str((options or {}).get("skeleton_asset_path") or "").split(".", 1)[0].strip()
            if skeleton_path:
                skeleton_id = asset_id_from_source(skeleton_path)
                package_id = f"{package_id}__{skeleton_id}"
        return f"{root.rstrip('/')}/{package_id}"

    def _is_type_root_destination(self, asset_type: str, dst_path: str) -> bool:
        canonical_type = normalize_artifact_type(asset_type)
        if canonical_type not in PACKAGE_ISOLATED_TYPES:
            return False
        try:
            requested = normalize_dest_path(dst_path, DEFAULT_IMPORT_ROOT).rstrip("/")
            default_root = normalize_dest_path(self.default_destination(canonical_type), DEFAULT_IMPORT_ROOT).rstrip("/")
        except Exception:
            return False
        return requested.lower() == default_root.lower()

    def _classify_imported_assets(self, result: dict) -> list[dict]:
        imported_paths = {normalize_backend_path(path) for path in result.get("imported_paths") or []}
        imported_paths.discard("")
        if not imported_paths:
            return []
        try:
            assets = self.backend.list_assets(AssetQuery.from_values(root_path=result.get("dest_path") or DEFAULT_IMPORT_ROOT))
        except Exception:
            return []
        dest_path = str(result.get("dest_path") or "").rstrip("/")
        asset_id = asset_id_from_source(str(result.get("src_path") or ""))
        is_package_root = bool(dest_path) and dest_path.rsplit("/", 1)[-1].lower() == asset_id.lower()
        if is_package_root:
            return assets
        return [asset for asset in assets if normalize_backend_path(asset.get("path") or "") in imported_paths]

    def _register_import_artifacts(self, result: dict, request: ImportRequest):
        backend_name = getattr(self.backend, "engine", "ue") or "ue"
        classified_assets = self._classify_imported_assets(result)
        metadata = request.options.get("metadata") if isinstance(request.options.get("metadata"), dict) else {}
        category = str(request.options.get("category") or metadata.get("category") or "")
        artifacts = build_artifact_records(
            result,
            backend=backend_name,
            category=category,
            classified_assets=classified_assets,
        )
        artifacts = self._attach_import_context_metadata(artifacts, request)
        if artifacts:
            self.artifacts.upsert_many(artifacts)
            result["asset_id"] = artifacts[0].asset_id
            result["type"] = artifacts[0].type
            result["backend"] = artifacts[0].backend
        result.setdefault("warnings", [])
        return artifacts

    def _attach_import_context_metadata(self, artifacts, request: ImportRequest):
        if not artifacts:
            return artifacts
        if request.type_key != "motion":
            return artifacts
        skeleton_path = str(request.options.get("skeleton_asset_path") or "").split(".", 1)[0].strip()
        if not skeleton_path:
            return artifacts
        updated = []
        for artifact in artifacts:
            metadata = dict(artifact.metadata or {})
            metadata["skeleton_path"] = skeleton_path
            updated.append(replace(artifact, metadata=metadata))
        return updated

    def validate_asset(self, src_path: str, asset_type: str, dst_path: str = "", **options: Any) -> ValidationResult:
        request = ImportRequest.from_values(src_path, asset_type, dst_path=dst_path or self.default_destination(asset_type), **options)
        return self.backend.validate_asset(request)

    def list_assets(self, asset_type: Optional[str] = None, root_path: str = DEFAULT_IMPORT_ROOT) -> list[dict]:
        return self.backend.list_assets(AssetQuery.from_values(asset_type=asset_type, root_path=root_path))

    def list_all_groups(self, root_path: str = DEFAULT_IMPORT_ROOT) -> dict:
        return self.backend.list_all_groups(root_path)

    def import_package(self, package_path: str, dst_root: str = DEFAULT_IMPORT_ROOT) -> dict:
        raise NotImplementedError("Zip asset package import is reserved for a later milestone")

    @staticmethod
    def _merge_asset_lists(primary: list[dict], fallback: list[dict]) -> list[dict]:
        from engine_adapters.ue5.assets._internal.ue.local_scan import merge_asset_lists

        return merge_asset_lists(primary, fallback)

    def _list_local_imported_assets(self, asset_type: str) -> list[dict]:
        from engine_adapters.ue5.assets._internal.ue.local_scan import list_local_imported_assets

        return list_local_imported_assets(asset_type)

    @staticmethod
    def _looks_like_local_avatar_mesh(asset_name: str) -> bool:
        from engine_adapters.ue5.assets._internal.ue.local_scan import looks_like_local_avatar_mesh

        return looks_like_local_avatar_mesh(asset_name)

    @classmethod
    def _dedupe_avatar_assets(cls, assets: list[dict]) -> list[dict]:
        from engine_adapters.ue5.assets._internal.ue.local_scan import dedupe_avatar_assets

        return dedupe_avatar_assets(assets)

    @staticmethod
    def _avatar_family_key(asset_name: str) -> str:
        from engine_adapters.ue5.assets._internal.ue.local_scan import avatar_family_key

        return avatar_family_key(asset_name)

    @staticmethod
    def _prettify_avatar_name(asset_name: str) -> str:
        from engine_adapters.ue5.assets._internal.ue.local_scan import prettify_avatar_name

        return prettify_avatar_name(asset_name)

    @staticmethod
    def _avatar_choice_score(asset: dict) -> tuple[int, str]:
        from engine_adapters.ue5.assets._internal.ue.local_scan import avatar_choice_score

        return avatar_choice_score(asset)

    @staticmethod
    def _content_package_path(asset_path, content_dir) -> str:
        from engine_adapters.ue5.assets._internal.ue.local_scan import content_package_path

        return content_package_path(asset_path, content_dir)

    def _infer_local_skeleton_path(self, asset_name: str, content_dir) -> str:
        from engine_adapters.ue5.assets._internal.ue.local_scan import infer_local_skeleton_path

        return infer_local_skeleton_path(asset_name, content_dir)

    def _infer_local_motion_skeleton_path(self, asset_name: str, content_dir) -> str:
        from engine_adapters.ue5.assets._internal.ue.local_scan import infer_local_motion_skeleton_path

        return infer_local_motion_skeleton_path(asset_name, content_dir)
