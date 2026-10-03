"""UE composition root for the generic Editor import pipeline."""

from typing import Any

from engine_adapters.ue5.assets._internal.builders import UEArtifactBuilder
from engine_adapters.ue5.assets._internal.inspectors import SourceFileInspector
from engine_adapters.ue5.assets._internal.postprocessors import UEImportedAssetPostProcessor
from engine_adapters.ue5.assets._internal.registry import ArtifactRegistryRepository
from engine_adapters.ue5.assets._internal.types import normalize_asset_type_name
from engine_adapters.ue5.assets._internal.ue.dispatcher import UEImportDispatcher
from engine_adapters.ue5.assets._internal.ue.registry import UEAssetRegistry
from engine_adapters.ue5.assets._internal.validators import ValidationRunner

from .contracts import ImportResult
from .import_pipeline import ImportPipeline


class UEImportStage:
    """Delegate raw source import to the existing UE importer dispatcher."""

    def __init__(self, dispatcher: UEImportDispatcher) -> None:
        self.dispatcher = dispatcher

    def import_asset(self, result: ImportResult) -> None:
        raw_result = self.dispatcher.import_asset(result.job.request)
        result.raw_result = dict(raw_result or {})
        imported_paths = list(dict.fromkeys(result.raw_result.get("imported_paths") or []))
        result.imported_assets = [{"path": path} for path in imported_paths if path]
        if not result.imported_assets:
            result.add_error("UE 导入完成但没有返回 imported_paths")


class UEImportPipeline(ImportPipeline):
    def __init__(
        self,
        *,
        dispatcher: UEImportDispatcher | None = None,
        content_registry: UEAssetRegistry | None = None,
        artifact_repository: ArtifactRegistryRepository | None = None,
        artifact_builder: UEArtifactBuilder | None = None,
        validation_runner: ValidationRunner | None = None,
    ) -> None:
        resolved_dispatcher = dispatcher or UEImportDispatcher()
        resolved_content_registry = content_registry or UEAssetRegistry()
        self.inspector = SourceFileInspector(resolved_dispatcher)
        self.importer = UEImportStage(resolved_dispatcher)
        self.post_processor = UEImportedAssetPostProcessor(resolved_content_registry)
        self.validator = validation_runner or ValidationRunner()
        self.artifact_builder = artifact_builder or UEArtifactBuilder()
        self.artifact_repository = artifact_repository or ArtifactRegistryRepository()

    def inspect(self, result: ImportResult) -> None:
        self.inspector.inspect(result)

    def import_asset(self, result: ImportResult) -> None:
        self.importer.import_asset(result)

    def post_process(self, result: ImportResult) -> None:
        self.post_processor.post_process(result)

    def validate(self, result: ImportResult) -> None:
        self.validator.validate(result)

    def build(self, result: ImportResult) -> None:
        self.artifact_builder.build(result)

    def register(self, result: ImportResult) -> None:
        self.artifact_repository.save(result.artifacts)


class ObjectPipeline(UEImportPipeline):
    """Named pipeline for props, objects, weapons, and static meshes."""


class AvatarPipeline(UEImportPipeline):
    """Named pipeline for skeletal avatar assets."""


class MotionPipeline(UEImportPipeline):
    """Named pipeline for animation assets."""


def pipeline_for_asset_type(asset_type: str, **kwargs: Any) -> UEImportPipeline:
    normalized = normalize_asset_type_name(asset_type)
    if normalized == "avatar":
        return AvatarPipeline(**kwargs)
    if normalized == "motion":
        return MotionPipeline(**kwargs)
    return ObjectPipeline(**kwargs)


__all__ = [
    "AvatarPipeline",
    "MotionPipeline",
    "ObjectPipeline",
    "UEImportPipeline",
    "pipeline_for_asset_type",
]
