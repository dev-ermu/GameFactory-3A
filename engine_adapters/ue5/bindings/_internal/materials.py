"""Shared PBR texture import and material binding workflow."""

from pathlib import Path
from typing import Any

from engine_adapters.ue5._internal.transport import (
    PythonRPCTransport,
    Transport,
)
from engine_adapters.ue5.assets._internal.materials import (
    discover_pbr_textures,
)
from engine_adapters.ue5.assets._internal.ue.scripts.material_scripts import (
    build_pbr_material_binding_script,
)


class PBRMaterialBindingService:
    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or PythonRPCTransport()

    def bind(
        self,
        *,
        asset_id: str,
        source_path: str | Path,
        mesh_asset_paths: list[str],
        destination_root: str,
        material_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = dict(material_config or {})
        if config.get("enabled") is False:
            return {
                "ok": True,
                "skipped": True,
                "reason": "material binding disabled",
                "asset_id": asset_id,
            }
        source = Path(source_path).expanduser().resolve()
        explicit = self._resolve_explicit_textures(
            source,
            config.get("textures"),
        )
        texture_sources = discover_pbr_textures(
            source,
            explicit=explicit,
            auto_discover=bool(config.get("auto", True)),
        )
        if not texture_sources:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no PBR textures discovered",
                "asset_id": asset_id,
            }
        result = self.transport.execute_json(
            build_pbr_material_binding_script(
                asset_id,
                texture_sources,
                mesh_asset_paths,
                destination_root,
                two_sided=bool(config.get("two_sided", False)),
                opacity_mode=str(config.get("opacity_mode") or "masked"),
            ),
            timeout=240,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(f"UE PBR 材质绑定失败: {result!r}")
        result["source_path"] = str(source)
        result["texture_sources"] = dict(texture_sources)
        return result

    @staticmethod
    def _resolve_explicit_textures(
        source: Path,
        value: Any,
    ) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result = {}
        for channel, raw_path in value.items():
            path = Path(str(raw_path or "")).expanduser()
            if not path.is_absolute():
                path = source.parent / path
            result[str(channel)] = str(path.resolve())
        return result


__all__ = ["PBRMaterialBindingService"]
