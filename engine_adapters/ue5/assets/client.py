"""Stable asset operations for UEClient v1."""

from typing import Any, Mapping

from .._internal.transport import PythonRPCTransport
from ..config import DEFAULT_IMPORT_ROOT, UEClientConfig
from ..contracts import UEOperationResult
from ._internal.artifacts import ArtifactRegistry
from ._internal.effects import EffectImportService
from ._internal.service import AssetService
from ._internal.source_resolver import (
    GeneratedAssetSourceResolver,
    ResolvedAssetSource,
)
from ._internal.ue.backend import UEAssetBackend
from ._internal.ue.dispatcher import UEImportDispatcher
from ._internal.ue.registry import UEAssetRegistry


class UEAssetsClient:
    def __init__(
        self,
        config: UEClientConfig,
        transport: PythonRPCTransport,
    ) -> None:
        self._config = config
        self._sources = GeneratedAssetSourceResolver()
        registry = UEAssetRegistry(transport=transport)
        backend = UEAssetBackend(
            dispatcher=UEImportDispatcher(
                transport=transport
            ),
            registry=registry,
        )
        self._service = AssetService(
            backend=backend,
            artifact_registry=ArtifactRegistry(
                config.artifact_registry_path
            ),
        )
        self._effects = EffectImportService(
            asset_service=self._service,
            transport=transport,
            config=config,
        )

    def import_asset(
        self,
        source: Mapping[str, Any],
        asset_type: str,
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resolved = self._resolve_source(source, asset_type)
        except Exception as exc:
            return self._source_failure(
                "assets.import_asset",
                source,
                exc,
            )
        if str(asset_type or "").strip().lower() in {
            "effect",
            "effects",
            "niagara",
        }:
            return self._import_effect_source(
                resolved,
                destination=destination,
                options=options,
            )
        try:
            payload = self._service.import_asset(
                str(resolved.path),
                asset_type,
                dst_path=destination,
                **dict(options or {}),
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "assets.import_asset",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "source": resolved.descriptor(),
                },
            ).to_dict()
        result = self._import_result(
            "assets.import_asset",
            payload,
        )
        result["payload"]["source"] = resolved.descriptor()
        return result

    def import_effect(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resolved = self._resolve_source(
                source,
                "effect",
                allow_directory=True,
            )
        except Exception as exc:
            return self._source_failure(
                "assets.import_effect",
                source,
                exc,
            )
        return self._import_effect_source(
            resolved,
            destination=destination,
            options=options,
        )

    def _import_effect_source(
        self,
        source: ResolvedAssetSource,
        *,
        destination: str,
        options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        resolved_options = dict(options or {})
        try:
            payload = self._effects.import_effect(
                str(source.path),
                destination_root=destination,
                effect_id=str(
                    resolved_options.pop("effect_id", "")
                ),
                entry_id=str(
                    resolved_options.pop("entry_id", "")
                ),
                entry_asset=str(
                    resolved_options.pop("entry_asset", "")
                ),
                replace_existing=bool(
                    resolved_options.pop(
                        "replace_existing",
                        False,
                    )
                ),
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "assets.import_effect",
                f"{type(exc).__name__}: {exc}",
                payload={"source": source.descriptor()},
            ).to_dict()
        result = self._import_result(
            "assets.import_effect",
            payload,
        )
        if resolved_options:
            result["warnings"].append(
                "Ignored effect options: "
                + ", ".join(sorted(resolved_options))
            )
        result["payload"]["source"] = source.descriptor()
        return result

    def import_avatar(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.import_asset(
            source,
            "avatar",
            destination=destination,
            options=options,
        )

    def import_motion(
        self,
        source: Mapping[str, Any],
        *,
        skeleton: str,
        destination: str = "",
        avatar_name: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not str(skeleton or "").strip():
            descriptor = (
                dict(source)
                if isinstance(source, Mapping)
                else {"value": str(source)}
            )
            return UEOperationResult.failure(
                "assets.import_motion",
                "skeleton is required for Motion import",
                payload={"source": descriptor},
            ).to_dict()
        resolved_options = dict(options or {})
        resolved_options["skeleton_asset_path"] = skeleton
        if avatar_name:
            resolved_options["avatar_name"] = avatar_name
        result = self.import_asset(
            source,
            "motion",
            destination=destination,
            options=resolved_options,
        )
        result["operation"] = "assets.import_motion"
        return result

    def import_scene(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "scene",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_scene"
        return result

    def import_prop(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "prop",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_prop"
        return result

    def import_weapon(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "weapon",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_weapon"
        return result

    def import_material(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "material",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_material"
        return result

    def import_texture(
        self,
        source: Mapping[str, Any],
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.import_asset(
            source,
            "texture",
            destination=destination,
            options=options,
        )
        result["operation"] = "assets.import_texture"
        return result

    def validate(
        self,
        source: Mapping[str, Any],
        asset_type: str,
        *,
        destination: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resolved = self._resolve_source(source, asset_type)
        except Exception as exc:
            return self._source_failure(
                "assets.validate",
                source,
                exc,
            )
        try:
            validation = self._service.validate_asset(
                str(resolved.path),
                asset_type,
                dst_path=destination,
                **dict(options or {}),
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "assets.validate",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "source": resolved.descriptor(),
                },
            ).to_dict()
        result = UEOperationResult(
            operation="assets.validate",
            ok=validation.ok,
            warnings=tuple(validation.warnings),
            errors=tuple(validation.errors),
            payload={
                "asset_type": asset_type,
                "source": resolved.descriptor(),
            },
        )
        return result.to_dict()

    def resolve_source(
        self,
        source: Mapping[str, Any],
        *,
        asset_type: str = "",
    ) -> dict[str, Any]:
        try:
            resolved = self._resolve_source(
                source,
                asset_type,
                allow_directory=(
                    str(asset_type or "").strip().lower() == "scene"
                    or str(source.get("task_kind") or "").strip()
                    == "3d_scene"
                ),
            )
        except Exception as exc:
            return self._source_failure(
                "assets.resolve_source",
                source,
                exc,
            )
        return UEOperationResult.success(
            "assets.resolve_source",
            payload={
                "source": resolved.descriptor(),
                "path": str(resolved.path),
                "meta_path": str(resolved.meta_path),
                "metadata": dict(resolved.metadata),
            },
        ).to_dict()

    def list(
        self,
        asset_type: str = "",
        *,
        root: str = DEFAULT_IMPORT_ROOT,
    ) -> dict[str, Any]:
        try:
            assets = self._service.list_assets(
                asset_type=asset_type or None,
                root_path=root,
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "assets.list",
                f"{type(exc).__name__}: {exc}",
                payload={
                    "asset_type": asset_type,
                    "root": root,
                },
            ).to_dict()
        return UEOperationResult.success(
            "assets.list",
            artifacts=[
                self._query_artifact(asset)
                for asset in assets
            ],
            payload={
                "asset_type": asset_type,
                "root": root,
                "count": len(assets),
            },
        ).to_dict()

    def list_registered(
        self,
        asset_type: str = "",
    ) -> dict[str, Any]:
        records = self._service.artifacts.list(
            type=asset_type or None,
            backend="ue",
        )
        return UEOperationResult.success(
            "assets.list_registered",
            artifacts=[
                record.to_dict()
                for record in records
            ],
            payload={
                "asset_type": asset_type,
                "count": len(records),
                "registry_path": str(
                    self._config.artifact_registry_path
                ),
            },
        ).to_dict()

    def get_metadata(
        self,
        artifact_id: str,
    ) -> dict[str, Any]:
        record = self._service.artifacts.get(artifact_id)
        if record is None:
            return UEOperationResult.failure(
                "assets.get_metadata",
                f"Unknown artifact_id: {artifact_id}",
            ).to_dict()
        return UEOperationResult.success(
            "assets.get_metadata",
            artifacts=[record.to_dict()],
        ).to_dict()

    def _resolve_source(
        self,
        source: Mapping[str, Any],
        asset_type: str,
        *,
        allow_directory: bool = False,
    ) -> ResolvedAssetSource:
        return self._sources.resolve(
            source,
            asset_type=asset_type,
            allow_directory=allow_directory,
        )

    @staticmethod
    def _source_failure(
        operation: str,
        source: Any,
        exc: Exception,
    ) -> dict[str, Any]:
        descriptor = (
            dict(source)
            if isinstance(source, Mapping)
            else {"value": str(source)}
        )
        return UEOperationResult.failure(
            operation,
            f"{type(exc).__name__}: {exc}",
            payload={"source": descriptor},
        ).to_dict()

    @staticmethod
    def _import_result(
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        artifacts = [
            dict(item)
            for item in payload.get("artifacts") or []
            if isinstance(item, dict)
        ]
        warnings = [
            str(item)
            for item in payload.get("warnings") or []
        ]
        errors = [
            str(item)
            for item in payload.get("errors") or []
        ]
        extra = {
            key: value
            for key, value in payload.items()
            if key not in {
                "ok",
                "artifacts",
                "warnings",
                "errors",
            }
        }
        return UEOperationResult(
            operation=operation,
            ok=bool(payload.get("ok", not errors)),
            artifacts=tuple(artifacts),
            warnings=tuple(warnings),
            errors=tuple(errors),
            payload=extra,
        ).to_dict()

    @staticmethod
    def _query_artifact(asset: dict[str, Any]) -> dict[str, Any]:
        path = str(asset.get("path") or "")
        return {
            "artifact_id": path,
            "asset_id": str(
                asset.get("name")
                or path.rsplit("/", 1)[-1]
            ),
            "type": str(asset.get("type") or ""),
            "backend": "ue",
            "backend_class": str(asset.get("class") or ""),
            "backend_path": path,
            "metadata": {
                key: value
                for key, value in asset.items()
                if key
                not in {
                    "name",
                    "path",
                    "type",
                    "class",
                }
            },
        }
