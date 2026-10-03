"""Stable Unreal asset reflection operations for UEClient v1."""

from typing import Any

from .._internal.transport import PythonRPCTransport
from ..assets import UEAssetsClient
from ..contracts import UEOperationResult


def _inspect_asset_script(asset_path: str) -> str:
    return f"""
import unreal

asset_path = {asset_path!r}
asset = unreal.load_asset(asset_path)
if asset is None:
    result = {{
        "ok": False,
        "asset_path": asset_path,
        "error": "asset not found",
    }}
else:
    asset_class = asset.get_class()
    result = {{
        "ok": True,
        "asset_path": asset_path,
        "name": asset.get_name(),
        "class": asset_class.get_name(),
        "class_path": asset_class.get_path_name(),
        "package": asset.get_outermost().get_name(),
    }}
"""


class UEReflectionClient:
    def __init__(
        self,
        transport: PythonRPCTransport,
        assets: UEAssetsClient,
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
            return UEOperationResult.failure(
                "reflection.inspect_artifact",
                f"Unknown artifact_id: {artifact_id}",
            ).to_dict()
        payload = {
            "artifact": record.to_dict(),
            "live": live,
        }
        if not live:
            return UEOperationResult.success(
                "reflection.inspect_artifact",
                artifacts=[record.to_dict()],
                payload=payload,
            ).to_dict()
        try:
            inspection = self._transport.execute_json(
                _inspect_asset_script(record.backend_path),
                timeout=60,
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "reflection.inspect_artifact",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        if not isinstance(inspection, dict):
            return UEOperationResult.failure(
                "reflection.inspect_artifact",
                "Unreal reflection returned an invalid payload",
                payload=payload,
            ).to_dict()
        payload["inspection"] = inspection
        if not inspection.get("ok"):
            return UEOperationResult.failure(
                "reflection.inspect_artifact",
                str(
                    inspection.get("error")
                    or "Unreal asset inspection failed"
                ),
                payload=payload,
            ).to_dict()
        return UEOperationResult.success(
            "reflection.inspect_artifact",
            artifacts=[record.to_dict()],
            payload=payload,
        ).to_dict()
