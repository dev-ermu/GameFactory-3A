"""Stable world composition operations for UEClient v1."""

from typing import Any, Mapping

from .._internal.transport import PythonRPCTransport
from ..assets import UEAssetsClient
from ..assets._internal.scenes import SceneImportService
from ..config import UEClientConfig
from ..contracts import UEOperationResult
from ._internal import (
    WorldPackageRegistry,
    WorldRegistry,
    WorldService,
    WorldSpec,
)


class UEWorldClient:
    def __init__(
        self,
        config: UEClientConfig,
        transport: PythonRPCTransport,
        assets: UEAssetsClient,
    ) -> None:
        self._config = config
        self._assets = assets
        package_registry = WorldPackageRegistry(
            config.world_registry_root
        )
        self._service = WorldService(
            artifact_registry=assets._service.artifacts,
            world_registry=WorldRegistry(
                config.world_registry_root
            ),
            package_registry=package_registry,
        )
        self._scenes = SceneImportService(
            asset_service=assets._service,
            world_service=self._service,
            transport=transport,
            config=config,
        )

    def build(
        self,
        source: Mapping[str, Any],
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resolved = self._assets._resolve_source(
                source,
                "scene",
                allow_directory=True,
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "world.build",
                f"{type(exc).__name__}: {exc}",
                payload={"source": self._descriptor(source)},
            ).to_dict()

        resolved_options = dict(options or {})
        known = {
            "world_id",
            "project_id",
            "publish",
            "default_spawn_point",
            "native_map",
            "replace_existing",
            "preview_in_editor",
            "repair_missing_collision",
        }
        ignored = sorted(set(resolved_options) - known)
        try:
            payload = self._scenes.import_scene(
                str(resolved.path),
                world_id=str(
                    resolved_options.get("world_id") or ""
                ),
                project_id=str(
                    resolved_options.get("project_id") or ""
                ),
                publish=bool(
                    resolved_options.get("publish", True)
                ),
                default_spawn_point=resolved_options.get(
                    "default_spawn_point"
                ),
                native_map=str(
                    resolved_options.get("native_map") or ""
                ),
                replace_existing=bool(
                    resolved_options.get(
                        "replace_existing",
                        False,
                    )
                ),
                preview_in_editor=bool(
                    resolved_options.get(
                        "preview_in_editor",
                        True,
                    )
                ),
                repair_missing_collision=bool(
                    resolved_options.get(
                        "repair_missing_collision",
                        False,
                    )
                ),
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "world.build",
                f"{type(exc).__name__}: {exc}",
                payload={"source": resolved.descriptor()},
            ).to_dict()
        warnings = [
            str(item)
            for item in payload.get("warnings") or []
        ]
        if ignored:
            warnings.append(
                "Ignored world options: "
                + ", ".join(ignored)
            )
        return UEOperationResult.success(
            "world.build",
            artifacts=[
                dict(item)
                for item in payload.get("artifacts") or []
                if isinstance(item, dict)
            ],
            warnings=warnings,
            payload={
                **{
                    key: value
                    for key, value in payload.items()
                    if key not in {
                        "ok",
                        "artifacts",
                        "warnings",
                        "errors",
                    }
                },
                "source": resolved.descriptor(),
            },
        ).to_dict()

    def create_draft(
        self,
        spec: Mapping[str, Any],
        *,
        draft_id: str = "",
        project_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            draft = self._service.create_draft(
                WorldSpec.from_dict(dict(spec)),
                draft_id=draft_id,
                project_id=project_id,
                metadata=metadata,
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "world.create_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UEOperationResult.success(
            "world.create_draft",
            payload={"draft": draft.to_dict()},
        ).to_dict()

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        try:
            payload = self._service.validate_draft(draft_id)
        except Exception as exc:
            return UEOperationResult.failure(
                "world.validate_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UEOperationResult(
            operation="world.validate_draft",
            ok=bool(payload.get("ok")),
            warnings=tuple(
                str(item)
                for item in payload.get("warnings") or []
            ),
            errors=tuple(
                str(item)
                for item in payload.get("errors") or []
            ),
            payload={
                key: value
                for key, value in payload.items()
                if key not in {"ok", "warnings", "errors"}
            },
        ).to_dict()

    def publish_draft(self, draft_id: str) -> dict[str, Any]:
        try:
            package = self._service.publish_draft(draft_id)
        except Exception as exc:
            return UEOperationResult.failure(
                "world.publish_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UEOperationResult.success(
            "world.publish_draft",
            artifacts=[
                {
                    "artifact_id": package.package_id,
                    "type": "world_package",
                    "backend": "ue",
                    "state": package.status,
                }
            ],
            payload={"package": package.to_dict()},
        ).to_dict()

    def list_packages(
        self,
        *,
        project_id: str = "",
        world_id: str = "",
    ) -> dict[str, Any]:
        packages = self._service.list_packages(
            project_id=project_id,
            world_id=world_id,
        )
        return UEOperationResult.success(
            "world.list_packages",
            artifacts=[
                {
                    "artifact_id": str(
                        item.get("package_id") or ""
                    ),
                    "type": "world_package",
                    "backend": "ue",
                    "state": str(
                        item.get("status") or ""
                    ),
                    "metadata": dict(item),
                }
                for item in packages
            ],
            payload={"count": len(packages)},
        ).to_dict()

    @staticmethod
    def _descriptor(source: Any) -> dict[str, Any]:
        return (
            dict(source)
            if isinstance(source, Mapping)
            else {"value": str(source)}
        )
