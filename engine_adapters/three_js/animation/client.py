"""Stable animation operations for ThreeClient v1."""

from typing import Any, Mapping

from ..assets import ThreeAssetsClient
from ..contracts import ThreeOperationResult


class ThreeAnimationClient:
    """Animation-facing view over registered web artifacts."""

    def __init__(self, assets: ThreeAssetsClient) -> None:
        self._assets = assets

    def import_motion(
        self,
        source: Mapping[str, Any],
        *,
        skeleton: str = "",
        destination: str = "",
        avatar_name: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self._assets.import_motion(
            source,
            skeleton=skeleton,
            destination=destination,
            avatar_name=avatar_name,
            options=options,
        )
        result["operation"] = "animation.import_motion"
        return result

    def resolve_skeleton(
        self,
        artifact_id: str,
    ) -> dict[str, Any]:
        """Report the skinned hierarchy carried by one artifact."""

        record = self._assets._service.artifacts.get(artifact_id)
        if record is None:
            return ThreeOperationResult.failure(
                "animation.resolve_skeleton",
                f"Unknown artifact_id: {artifact_id}",
            ).to_dict()
        inspection = dict(
            (record.metadata or {}).get("inspection") or {}
        )
        skin_count = int(inspection.get("skin_count") or 0)
        if not skin_count:
            return ThreeOperationResult.failure(
                "animation.resolve_skeleton",
                f"Artifact {artifact_id} declares no glTF skin; "
                "three.js cannot bind motion to it",
                payload={
                    "artifact_id": artifact_id,
                    "backend_path": record.backend_path,
                },
            ).to_dict()
        return ThreeOperationResult.success(
            "animation.resolve_skeleton",
            payload={
                "artifact_id": artifact_id,
                "asset_id": record.asset_id,
                "backend_path": record.backend_path,
                "backend_class": record.backend_class,
                "skin_count": skin_count,
                "node_count": int(inspection.get("node_count") or 0),
                "skeleton_ref": (
                    f"{record.backend_path}#skin/0"
                ),
            },
        ).to_dict()

    def validate_compatibility(
        self,
        motion_artifact_id: str,
        skeleton_artifact_id: str,
    ) -> dict[str, Any]:
        """Check whether motion clips can drive an avatar skeleton."""

        registry = self._assets._service.artifacts
        motion = registry.get(motion_artifact_id)
        skeleton = registry.get(skeleton_artifact_id)
        missing = [
            name
            for name, record in {
                motion_artifact_id: motion,
                skeleton_artifact_id: skeleton,
            }.items()
            if record is None
        ]
        if missing:
            return ThreeOperationResult.failure(
                "animation.validate_compatibility",
                "Unknown artifact_id: " + ", ".join(missing),
            ).to_dict()
        assert motion is not None and skeleton is not None

        motion_inspection = dict(
            (motion.metadata or {}).get("inspection") or {}
        )
        skeleton_inspection = dict(
            (skeleton.metadata or {}).get("inspection") or {}
        )
        clips = [
            str(item)
            for item in motion_inspection.get("animations") or []
        ]
        errors: list[str] = []
        warnings: list[str] = []
        if not clips:
            errors.append(
                f"Motion artifact {motion_artifact_id} declares no "
                "animation clip"
            )
        if not skeleton_inspection.get("skin_count"):
            errors.append(
                f"Skeleton artifact {skeleton_artifact_id} declares "
                "no glTF skin"
            )
        motion_nodes = int(motion_inspection.get("node_count") or 0)
        skeleton_nodes = int(
            skeleton_inspection.get("node_count") or 0
        )
        if (
            motion_nodes
            and skeleton_nodes
            and motion_nodes > skeleton_nodes
        ):
            warnings.append(
                "Motion declares more nodes than the target "
                "hierarchy; three.js will need "
                "SkeletonUtils.retargetClip"
            )
        payload = {
            "motion_artifact_id": motion_artifact_id,
            "skeleton_artifact_id": skeleton_artifact_id,
            "clips": clips,
            "motion_node_count": motion_nodes,
            "skeleton_node_count": skeleton_nodes,
            "retarget_required": bool(warnings),
        }
        if errors:
            return ThreeOperationResult.failure(
                "animation.validate_compatibility",
                *errors,
                warnings=warnings,
                payload=payload,
            ).to_dict()
        return ThreeOperationResult.success(
            "animation.validate_compatibility",
            warnings=warnings,
            payload=payload,
        ).to_dict()
