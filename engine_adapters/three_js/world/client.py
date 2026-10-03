"""Stable world composition operations for ThreeClient v1."""

import json
from pathlib import Path
from typing import Any, Mapping

from ..assets import ThreeAssetsClient
from ..config import ThreeClientConfig
from ..contracts import ThreeOperationResult
from ._internal import (
    WorldPackageRegistry,
    WorldRegistry,
    WorldService,
    WorldSpec,
)


class ThreeWorldClient:
    def __init__(
        self,
        config: ThreeClientConfig,
        assets: ThreeAssetsClient,
    ) -> None:
        self._config = config
        self._assets = assets
        self._service = WorldService(
            artifact_registry=assets._service.artifacts,
            world_registry=WorldRegistry(config.world_registry_root),
            package_registry=WorldPackageRegistry(
                config.world_registry_root
            ),
            scene_output_root=config.public_root,
        )

    def build(
        self,
        source: Mapping[str, Any],
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a World from a registered Scene artifact."""

        try:
            resolved = self._assets._resolve_source(
                source,
                "scene",
                allow_directory=True,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
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
            "native_scene",
            "replace_existing",
            "environment_artifact_id",
            "lights",
            "camera",
            "environment",
        }
        ignored = sorted(set(resolved_options) - known)
        world_id = str(
            resolved_options.get("world_id") or ""
        ).strip() or f"world_{resolved.task_id}"
        project_id = str(
            resolved_options.get("project_id") or ""
        ).strip()

        # A native three.js scene document is preserved as authored.
        native_scene = str(
            resolved_options.get("native_scene") or ""
        ).strip()
        warnings: list[str] = []
        if ignored:
            warnings.append(
                "Ignored world options: " + ", ".join(ignored)
            )

        imported = self._assets.import_scene(
            source,
            options={
                "replace_existing": bool(
                    resolved_options.get("replace_existing", False)
                ),
                "asset_id": world_id,
            },
        )
        if not imported.get("ok"):
            return ThreeOperationResult.failure(
                "world.build",
                *imported.get("errors") or["Scene import failed"],
                warnings=warnings,
                payload={
                    "source": resolved.descriptor(),
                    "import": imported,
                },
            ).to_dict()

        scene_artifacts = list(imported.get("artifacts") or [])
        environment_artifact_id = str(
            resolved_options.get("environment_artifact_id")
            or (
                scene_artifacts[0].get("artifact_id")
                if scene_artifacts
                else ""
            )
        )
        spec_payload: dict[str, Any] = {
            "world_id": world_id,
            "project_id": project_id,
            "name": world_id,
            "environment": {
                **dict(resolved_options.get("environment") or {}),
                "environment_artifact_id": "",
            },
            "camera": dict(resolved_options.get("camera") or {}),
            "lights": list(
                resolved_options.get("lights")
                or [
                    {
                        "light_id": "sky_light",
                        "type": "HemisphereLight",
                        "intensity": 0.6,
                    },
                    {
                        "light_id": "sun_light",
                        "type": "DirectionalLight",
                        "intensity": 2.0,
                        "position": {"x": 8.0, "y": 16.0, "z": 8.0},
                        "cast_shadow": True,
                    },
                ]
            ),
            "entities": [
                {
                    "entity_id": "environment_000",
                    "role": "environment",
                    "artifact_id": environment_artifact_id,
                    "collision": True,
                    "receive_shadow": True,
                }
            ],
            "metadata": {
                "native_scene": native_scene,
                "source": resolved.descriptor(),
            },
        }
        spawn_point = resolved_options.get("default_spawn_point")
        if isinstance(spawn_point, Mapping):
            spec_payload["spawn_points"] = [
                {
                    "name": "default",
                    "position": dict(spawn_point),
                }
            ]

        try:
            draft = self._service.create_draft(
                WorldSpec.from_dict(spec_payload),
                project_id=project_id,
                metadata={"source": resolved.descriptor()},
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "world.build",
                f"{type(exc).__name__}: {exc}",
                warnings=warnings,
                payload={"source": resolved.descriptor()},
            ).to_dict()

        payload: dict[str, Any] = {
            "source": resolved.descriptor(),
            "world_id": world_id,
            "project_id": project_id,
            "draft": draft.to_dict(),
            "import": imported,
        }
        artifacts = list(scene_artifacts)
        if bool(resolved_options.get("publish", True)):
            try:
                package = self._service.publish_draft(draft.draft_id)
            except Exception as exc:
                return ThreeOperationResult.failure(
                    "world.build",
                    f"{type(exc).__name__}: {exc}",
                    warnings=warnings,
                    payload=payload,
                ).to_dict()
            payload["package"] = package.to_dict()
            artifacts.append(
                {
                    "artifact_id": package.package_id,
                    "type": "world_package",
                    "backend": "web",
                    "backend_path": package.scene_url,
                    "state": package.status,
                }
            )
            warnings.extend(
                str(item)
                for item in package.manifest.get("warnings") or []
            )

        return ThreeOperationResult.success(
            "world.build",
            artifacts=artifacts,
            warnings=warnings,
            payload=payload,
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
            return ThreeOperationResult.failure(
                "world.create_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return ThreeOperationResult.success(
            "world.create_draft",
            payload={"draft": draft.to_dict()},
        ).to_dict()

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        try:
            payload = self._service.validate_draft(draft_id)
        except Exception as exc:
            return ThreeOperationResult.failure(
                "world.validate_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return ThreeOperationResult(
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
            return ThreeOperationResult.failure(
                "world.publish_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return ThreeOperationResult.success(
            "world.publish_draft",
            artifacts=[
                {
                    "artifact_id": package.package_id,
                    "type": "world_package",
                    "backend": "web",
                    "backend_path": package.scene_url,
                    "state": package.status,
                }
            ],
            warnings=[
                str(item)
                for item in package.manifest.get("warnings") or []
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
        return ThreeOperationResult.success(
            "world.list_packages",
            artifacts=[
                {
                    "artifact_id": str(
                        item.get("package_id") or ""
                    ),
                    "type": "world_package",
                    "backend": "web",
                    "backend_path": str(
                        item.get("scene_url") or ""
                    ),
                    "state": str(item.get("status") or ""),
                    "metadata": dict(item),
                }
                for item in packages
            ],
            payload={"count": len(packages)},
        ).to_dict()

    def get_scene_graph(self, draft_id: str) -> dict[str, Any]:
        """Return the runtime scene graph document for one draft."""

        try:
            draft = self._service.get_draft(draft_id)
            graph = self._service.build_scene_graph(draft)
        except Exception as exc:
            return ThreeOperationResult.failure(
                "world.get_scene_graph",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return ThreeOperationResult.success(
            "world.get_scene_graph",
            payload={
                "draft_id": draft_id,
                "world_id": draft.world_id,
                "scene_graph": graph,
                "byte_size": len(
                    json.dumps(graph).encode("utf-8")
                ),
            },
        ).to_dict()

    @staticmethod
    def _descriptor(source: Any) -> dict[str, Any]:
        return (
            dict(source)
            if isinstance(source, Mapping)
            else {"value": str(source)}
        )
