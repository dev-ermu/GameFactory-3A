"""Stable Unity asset reflection operations for UnityClient v1."""

from typing import Any

from .._internal.transport.unity_editor import UnityEditorTransport
from ..assets import UnityAssetsClient
from ..contracts import UnityOperationResult


class UnityReflectionClient:
    def __init__(
        self,
        transport: UnityEditorTransport,
        assets: UnityAssetsClient,
    ) -> None:
        self._transport = transport
        self._assets = assets

    def inspect_artifact(
        self,
        artifact_id: str,
        *,
        live: bool = True,
    ) -> dict[str, Any]:
        record = self._assets._service.artifacts.get(
            artifact_id
        )
        if record is None:
            return UnityOperationResult.failure(
                "reflection.inspect_artifact",
                f"Unknown artifact_id: {artifact_id}",
            ).to_dict()
        payload: dict[str, Any] = {
            "artifact": record.to_dict(),
            "live": live,
        }
        if not live:
            return UnityOperationResult.success(
                "reflection.inspect_artifact",
                artifacts=[record.to_dict()],
                payload=payload,
            ).to_dict()
        try:
            inspection = self._transport.execute_method(
                "InspectArtifact.RunFromCLI",
                args={
                    "asset_path": record.backend_path,
                },
                timeout=60,
            )
        except Exception as exc:
            return UnityOperationResult.failure(
                "reflection.inspect_artifact",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        if not isinstance(inspection, dict):
            return UnityOperationResult.failure(
                "reflection.inspect_artifact",
                "Unity reflection returned an invalid payload",
                payload=payload,
            ).to_dict()
        payload["inspection"] = inspection
        if not inspection.get("ok"):
            return UnityOperationResult.failure(
                "reflection.inspect_artifact",
                str(
                    inspection.get("error")
                    or "Unity asset inspection failed"
                ),
                payload=payload,
            ).to_dict()
        return UnityOperationResult.success(
            "reflection.inspect_artifact",
            artifacts=[record.to_dict()],
            payload=payload,
        ).to_dict()
