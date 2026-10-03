"""Stable artifact reflection operations for ThreeClient v1."""

from pathlib import Path
from typing import Any

from ..assets import ThreeAssetsClient
from ..assets._internal.inspectors import inspect_source
from ..config import ThreeClientConfig
from ..contracts import ThreeOperationResult


class ThreeReflectionClient:
    """Inspect registered web artifacts through glTF document reflection."""

    def __init__(
        self,
        config: ThreeClientConfig,
        assets: ThreeAssetsClient,
    ) -> None:
        self._config = config
        self._assets = assets

    def inspect_artifact(
        self,
        artifact_id: str,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        record = self._assets._service.artifacts.get(artifact_id)
        if record is None:
            return ThreeOperationResult.failure(
                "reflection.inspect_artifact",
                f"Unknown artifact_id: {artifact_id}",
            ).to_dict()

        cached = dict(
            (record.metadata or {}).get("inspection") or {}
        )
        payload: dict[str, Any] = {
            "artifact_id": artifact_id,
            "asset_id": record.asset_id,
            "type": record.type,
            "backend": record.backend,
            "backend_class": record.backend_class,
            "backend_path": record.backend_path,
            "representation": record.representation,
            "runtime_capabilities": dict(
                record.runtime_capabilities or {}
            ),
            "source": "registry_cache",
            "reflection": cached,
        }

        if not refresh and cached:
            return ThreeOperationResult.success(
                "reflection.inspect_artifact",
                artifacts=[record.to_dict()],
                payload=payload,
            ).to_dict()

        public_root = self._config.public_root
        if public_root is None:
            return ThreeOperationResult.failure(
                "reflection.inspect_artifact",
                "project_path is not configured; cannot re-inspect "
                "the staged artifact",
                payload=payload,
            ).to_dict()
        staged = public_root / record.backend_path.lstrip("/")
        if not staged.exists():
            return ThreeOperationResult.failure(
                "reflection.inspect_artifact",
                f"Staged artifact was not found: {staged}",
                payload=payload,
            ).to_dict()
        try:
            reflection = inspect_source(
                Path(staged),
                asset_type=record.type,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "reflection.inspect_artifact",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        payload["source"] = "staged_file"
        payload["reflection"] = reflection
        payload["staged_path"] = str(staged)
        return ThreeOperationResult.success(
            "reflection.inspect_artifact",
            artifacts=[record.to_dict()],
            payload=payload,
        ).to_dict()

    def list_object_names(
        self,
        artifact_id: str,
    ) -> dict[str, Any]:
        """List animation clip and material names carried by an artifact."""

        inspected = self.inspect_artifact(artifact_id)
        if not inspected.get("ok"):
            inspected["operation"] = "reflection.list_object_names"
            return inspected
        reflection = dict(
            (inspected.get("payload") or {}).get("reflection") or {}
        )
        return ThreeOperationResult.success(
            "reflection.list_object_names",
            payload={
                "artifact_id": artifact_id,
                "animations": list(
                    reflection.get("animations") or []
                ),
                "materials": list(
                    reflection.get("materials") or []
                ),
                "mesh_count": int(
                    reflection.get("mesh_count") or 0
                ),
                "node_count": int(
                    reflection.get("node_count") or 0
                ),
                "triangle_count": int(
                    reflection.get("triangle_count") or 0
                ),
                "bounds": dict(reflection.get("bounds") or {}),
            },
        ).to_dict()
