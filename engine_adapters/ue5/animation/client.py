"""Stable animation asset operations for UEClient v1."""

from typing import Any, Mapping

from ..assets import UEAssetsClient
from ..contracts import UEOperationResult


def _normalized_ue_path(value: str) -> str:
    return str(value or "").strip().split(".", 1)[0]


def _skeleton_from_artifact(
    artifact: dict[str, Any],
) -> str:
    metadata = artifact.get("metadata")
    metadata = (
        metadata
        if isinstance(metadata, dict)
        else {}
    )
    direct = _normalized_ue_path(
        str(
            artifact.get("skeleton_path")
            or metadata.get("skeleton_path")
            or ""
        )
    )
    if direct:
        return direct
    for dependency in metadata.get("dependencies") or []:
        if not isinstance(dependency, dict):
            continue
        if str(dependency.get("type") or "") != "skeleton":
            continue
        paths = dependency.get("assets") or []
        if paths:
            return _normalized_ue_path(str(paths[0]))
    return ""


class UEAnimationClient:
    def __init__(self, assets: UEAssetsClient) -> None:
        self._assets = assets

    def import_motion(
        self,
        source: Mapping[str, Any],
        *,
        skeleton: str,
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
        avatar: str,
    ) -> dict[str, Any]:
        registered = self._assets.list_registered("avatar")
        for artifact in registered["artifacts"]:
            if avatar not in {
                str(artifact.get("artifact_id") or ""),
                str(artifact.get("asset_id") or ""),
                str(artifact.get("backend_path") or ""),
            }:
                continue
            skeleton = _skeleton_from_artifact(artifact)
            if skeleton:
                return UEOperationResult.success(
                    "animation.resolve_skeleton",
                    payload={
                        "avatar": avatar,
                        "skeleton": skeleton,
                        "source": "artifact_registry",
                    },
                ).to_dict()

        live = self._assets.list("avatar")
        if live["ok"]:
            normalized_avatar = _normalized_ue_path(avatar)
            for artifact in live["artifacts"]:
                backend_path = _normalized_ue_path(
                    str(
                        artifact.get("backend_path")
                        or ""
                    )
                )
                if normalized_avatar not in {
                    backend_path,
                    str(artifact.get("asset_id") or ""),
                }:
                    continue
                skeleton = _skeleton_from_artifact(artifact)
                if skeleton:
                    return UEOperationResult.success(
                        "animation.resolve_skeleton",
                        payload={
                            "avatar": avatar,
                            "skeleton": skeleton,
                            "source": "ue_asset_registry",
                        },
                    ).to_dict()

        return UEOperationResult.failure(
            "animation.resolve_skeleton",
            f"No Skeleton was found for avatar: {avatar}",
        ).to_dict()

    def validate_compatibility(
        self,
        motion: str,
        skeleton: str,
    ) -> dict[str, Any]:
        expected = _normalized_ue_path(skeleton)
        if not expected:
            return UEOperationResult.failure(
                "animation.validate_compatibility",
                "skeleton is required",
            ).to_dict()
        registered = self._assets.list_registered("motion")
        for artifact in registered["artifacts"]:
            if motion not in {
                str(artifact.get("artifact_id") or ""),
                str(artifact.get("asset_id") or ""),
                str(artifact.get("backend_path") or ""),
            }:
                continue
            actual = _skeleton_from_artifact(artifact)
            return UEOperationResult(
                operation="animation.validate_compatibility",
                ok=actual == expected,
                errors=(
                    ()
                    if actual == expected
                    else (
                        "Motion Skeleton does not match: "
                        f"expected={expected} actual={actual or '<missing>'}",
                    )
                ),
                payload={
                    "motion": motion,
                    "expected_skeleton": expected,
                    "actual_skeleton": actual,
                },
            ).to_dict()
        return UEOperationResult.failure(
            "animation.validate_compatibility",
            f"Unknown registered Motion: {motion}",
        ).to_dict()
