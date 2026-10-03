"""Stable material and asset binding operations for UEClient v1."""

from typing import Any, Mapping

from .._internal.transport import PythonRPCTransport
from ..assets import UEAssetsClient
from ..contracts import UEOperationResult
from ._internal.materials import PBRMaterialBindingService


class UEBindingsClient:
    def __init__(
        self,
        transport: PythonRPCTransport,
        assets: UEAssetsClient,
    ) -> None:
        self._service = PBRMaterialBindingService(transport)
        self._assets = assets

    def bind_pbr_material(
        self,
        *,
        asset_id: str,
        source: Mapping[str, Any],
        mesh_assets: list[str],
        destination: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resolved = self._assets._resolve_source(
                source,
                "material",
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "bindings.bind_pbr_material",
                f"{type(exc).__name__}: {exc}",
                payload={"source": dict(source)},
            ).to_dict()
        try:
            payload = self._service.bind(
                asset_id=asset_id,
                source_path=resolved.path,
                mesh_asset_paths=list(mesh_assets),
                destination_root=destination,
                material_config=dict(options or {}),
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "bindings.bind_pbr_material",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_id": asset_id,
                    "source": resolved.descriptor(),
                },
            ).to_dict()
        payload["source"] = resolved.descriptor()
        return UEOperationResult.success(
            "bindings.bind_pbr_material",
            warnings=[
                str(item)
                for item in payload.get("warnings") or []
            ],
            payload=dict(payload),
        ).to_dict()
