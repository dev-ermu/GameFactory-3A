"""Build backend-neutral ArtifactRecord values from UE import output."""

from dataclasses import replace

from engine_adapters.ue5.assets._internal.artifacts.models import (
    build_artifact_records,
)
from engine_adapters.ue5.assets._internal.pipeline.contracts import ImportResult


class UEArtifactBuilder:
    def build(self, result: ImportResult) -> None:
        raw_result = result.raw_result
        request = result.job.request
        metadata = request.options.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        category = str(request.options.get("category") or metadata.get("category") or "")
        artifacts = build_artifact_records(
            raw_result,
            backend="ue",
            category=category,
            classified_assets=result.imported_assets,
            include_all_static_meshes=bool(
                request.options.get("include_all_static_meshes", False)
            ),
        )
        if not artifacts:
            result.add_error("无法从 UE 导入结果构建主 ArtifactRecord")
            return
        collision_requested = bool(request.options.get("generate_collision", False))
        if collision_requested:
            artifacts = [
                replace(
                    artifact,
                    runtime_capabilities={
                        **dict(artifact.runtime_capabilities or {}),
                        "collidable": artifact.backend_class == "StaticMesh",
                    },
                    metadata={
                        **dict(artifact.metadata or {}),
                        "collision_requested": artifact.backend_class == "StaticMesh",
                    },
                )
                for artifact in artifacts
            ]
        if request.type_key == "motion":
            skeleton_path = str(request.options.get("skeleton_asset_path") or "").split(".", 1)[0].strip()
            if not skeleton_path:
                motion_asset = next(
                    (asset for asset in result.imported_assets if asset.get("class") == "AnimSequence"),
                    {},
                )
                skeleton_path = str(motion_asset.get("skeleton_path") or "").split(".", 1)[0].strip()
            if skeleton_path:
                artifacts = [
                    replace(
                        artifact,
                        metadata={
                            **dict(artifact.metadata or {}),
                            "skeleton_path": skeleton_path,
                        },
                    )
                    for artifact in artifacts
                ]
        result.artifacts = artifacts
