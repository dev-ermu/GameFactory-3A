"""Stable world composition operations for UnityClient v1."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .._internal.transport.unity_editor import UnityEditorTransport
from ..assets import UnityAssetsClient
from ..assets._internal.artifacts.models import build_artifact_records
from ..assets._internal.unity.dispatcher import discover_unitypackage_root
from ..config import UnityClientConfig
from ..contracts import UnityOperationResult


def _is_native_unity_scene(path: Path) -> bool:
    """Check if the source is a native .unity scene file or a directory containing .unity files."""
    if path.is_file():
        return path.suffix.lower() == ".unity"
    if path.is_dir():
        try:
            return any(path.rglob("*.unity"))
        except (OSError, PermissionError):
            return False
    return False


@dataclass
class WorldSpec:
    world_id: str = ""
    project_id: str = ""
    spawn_points: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldSpec":
        return cls(
            world_id=str(data.get("world_id") or ""),
            project_id=str(data.get("project_id") or ""),
            spawn_points=list(data.get("spawn_points") or []),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorldDraft:
    draft_id: str
    spec: WorldSpec
    project_id: str = ""
    state: str = "draft"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "spec": self.spec.to_dict(),
            "project_id": self.project_id,
            "state": self.state,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


@dataclass
class WorldPackage:
    package_id: str
    world_id: str
    project_id: str
    status: str = "published"
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "world_id": self.world_id,
            "project_id": self.project_id,
            "status": self.status,
            "manifest": dict(self.manifest),
        }


class WorldRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _draft_path(self, draft_id: str) -> Path:
        return self.root / f"draft_{draft_id}.json"

    def _package_path(self, package_id: str) -> Path:
        return self.root / f"package_{package_id}.json"

    def save_draft(self, draft: WorldDraft) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._draft_path(draft.draft_id).write_text(
            json.dumps(draft.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def load_draft(self, draft_id: str) -> WorldDraft | None:
        path = self._draft_path(draft_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorldDraft(
            draft_id=data.get("draft_id", draft_id),
            spec=WorldSpec.from_dict(data.get("spec") or {}),
            project_id=data.get("project_id", ""),
            state=data.get("state", "draft"),
            metadata=data.get("metadata") or {},
            created_at=data.get("created_at", 0.0),
        )

    def save_package(self, package: WorldPackage) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._package_path(package.package_id).write_text(
            json.dumps(package.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def list_packages(self, *, project_id: str = "", world_id: str = "") -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.root.glob("package_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if project_id and str(data.get("project_id") or "") != project_id:
                continue
            if world_id and str(data.get("world_id") or "") != world_id:
                continue
            result.append(data)
        return result


class WorldService:
    def __init__(
        self,
        world_registry: WorldRegistry,
    ) -> None:
        self.registry = world_registry

    def create_draft(
        self,
        spec: WorldSpec,
        *,
        draft_id: str = "",
        project_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorldDraft:
        from time import time
        draft = WorldDraft(
            draft_id=draft_id or f"draft_{uuid4().hex[:8]}",
            spec=spec,
            project_id=project_id,
            state="draft",
            metadata=dict(metadata or {}),
            created_at=time(),
        )
        self.registry.save_draft(draft)
        return draft

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.registry.load_draft(draft_id)
        if draft is None:
            return {
                "ok": False,
                "errors": [f"Unknown draft: {draft_id}"],
                "warnings": [],
            }
        warnings: list[str] = []
        errors: list[str] = []
        if not draft.spec.world_id:
            errors.append("world_id is required")
        if not draft.spec.spawn_points:
            warnings.append("No spawn points defined")
        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "draft": draft.to_dict(),
        }

    def publish_draft(self, draft_id: str) -> WorldPackage:
        validation = self.validate_draft(draft_id)
        if not validation["ok"]:
            raise ValueError("; ".join(validation["errors"]))
        draft = self.registry.load_draft(draft_id)
        package = WorldPackage(
            package_id=f"world_{uuid4().hex[:8]}",
            world_id=draft.spec.world_id,
            project_id=draft.project_id,
            status="published",
            manifest={
                "spec": draft.spec.to_dict(),
                "draft_id": draft.draft_id,
            },
        )
        self.registry.save_package(package)
        return package

    def list_packages(
        self,
        *,
        project_id: str = "",
        world_id: str = "",
    ) -> list[dict[str, Any]]:
        return self.registry.list_packages(
            project_id=project_id,
            world_id=world_id,
        )


class UnityWorldClient:
    def __init__(
        self,
        config: UnityClientConfig,
        transport: UnityEditorTransport,
        assets: UnityAssetsClient,
    ) -> None:
        self._config = config
        self._assets = assets
        self._transport = transport
        self._service = WorldService(
            world_registry=WorldRegistry(
                config.world_registry_root
            ),
        )

    def compose_scene(
        self,
        spec: Mapping[str, Any],
        *,
        dry_run: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Compose and save a scene from imported prefab/component references."""
        if not isinstance(spec, Mapping):
            return UnityOperationResult.failure(
                "world.compose_scene",
                "spec must be an object",
            ).to_dict()
        payload = dict(spec)
        output_scene = str(
            payload.get("output_scene")
            or "Assets/Scenes/GeneratedGame.unity"
        ).strip()
        if not output_scene.startswith("Assets/") or not output_scene.endswith(".unity"):
            return UnityOperationResult.failure(
                "world.compose_scene",
                "output_scene must be an Assets-relative .unity path",
                payload={"spec": payload},
            ).to_dict()
        report = self._transport.execute_method(
            "ComposeScene.RunFromCLI",
            args=payload,
            timeout=timeout or self._config.editor_batchmode_timeout,
            dry_run=dry_run,
        )
        result_payload = {
            key: value
            for key, value in report.items()
            if key not in {"ok", "warnings", "errors", "error"}
        }
        result_payload["spec"] = payload
        if dry_run:
            return UnityOperationResult.success(
                "world.compose_scene",
                artifacts=[
                    {
                        "type": "unity_scene",
                        "path": output_scene,
                        "state": "planned",
                    }
                ],
                payload=result_payload,
            ).to_dict()
        errors = [str(item) for item in report.get("errors") or []]
        if report.get("error"):
            errors.insert(0, str(report["error"]))
        project_path = self._config.project_path
        scene_file = project_path / output_scene if project_path else None
        if not report.get("ok") or scene_file is None or not scene_file.is_file():
            if report.get("ok") and scene_file is not None:
                errors.append(
                    f"Unity reported success but the scene artifact is missing: {scene_file}"
                )
            return UnityOperationResult.failure(
                "world.compose_scene",
                *(errors or ["Unity scene composition failed"]),
                warnings=[str(item) for item in report.get("warnings") or []],
                payload=result_payload,
            ).to_dict()
        return UnityOperationResult.success(
            "world.compose_scene",
            artifacts=[
                {
                    "type": "unity_scene",
                    "path": str(scene_file),
                    "state": "ready",
                }
            ],
            warnings=[str(item) for item in report.get("warnings") or []],
            payload=result_payload,
        ).to_dict()
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
            return UnityOperationResult.failure(
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
            "native_scene",
            "replace_existing",
            "preview_in_editor",
            "repair_missing_collision",
        }
        ignored = sorted(set(resolved_options) - known)

        # Unity packages are imported by AssetDatabase.ImportPackage (or the
        # deterministic pre-extraction path), not by the generated-scene JSON
        # importer.  A native .unity scene uses the native copier.
        is_unitypackage = resolved.path.suffix.lower() == ".unitypackage"
        is_native_scene = _is_native_unity_scene(resolved.path)
        native_scene_name = str(
            resolved_options.get("native_scene")
            or resolved_options.get("native_map")
            or ""
        ).strip()

        if is_unitypackage:
            transport_source = str(resolved.path)
            package_warnings: list[str] = []
            package_pre_extracted = False
            try:
                (
                    prepared_source,
                    package_warnings,
                    package_pre_extracted,
                ) = self._assets._service.dispatcher._prepare_unitypackage(
                    resolved.path
                )
                transport_source = str(prepared_source)
            except Exception as exc:
                return UnityOperationResult.failure(
                    "world.build",
                    f"{type(exc).__name__}: {exc}",
                    payload={"source": resolved.descriptor()},
                ).to_dict()
            method = "ImportUnityPackage.RunFromCLI"
            args = {
                "src": transport_source,
                "package_root": discover_unitypackage_root(resolved.path),
                "pre_extracted": package_pre_extracted,
                "world_id": str(resolved_options.get("world_id") or ""),
                "project_id": str(resolved_options.get("project_id") or ""),
                "publish": bool(resolved_options.get("publish", True)),
            }
        elif is_native_scene:
            method = "ImportNativeScene.RunFromCLI"
            args = {
                "src": str(resolved.path),
                "dest": "Assets/Imported/Scenes",
                "native_scene": native_scene_name,
                "world_id": str(resolved_options.get("world_id") or ""),
                "project_id": str(resolved_options.get("project_id") or ""),
                "publish": bool(resolved_options.get("publish", True)),
                "replace_existing": bool(resolved_options.get("replace_existing", False)),
            }
        else:
            method = "ImportGeneratedScene.RunFromCLI"
            args = {
                "src": str(resolved.path),
                "dest": "Assets/Imported/Scenes",
                "world_id": str(resolved_options.get("world_id") or ""),
                "project_id": str(resolved_options.get("project_id") or ""),
                "publish": bool(resolved_options.get("publish", True)),
                "replace_existing": bool(resolved_options.get("replace_existing", False)),
            }

        try:
            report = self._transport.execute_method(
                method,
                args=args,
            )
        except Exception as exc:
            return UnityOperationResult.failure(
                "world.build",
                f"{type(exc).__name__}: {exc}",
                payload={"source": resolved.descriptor()},
            ).to_dict()
        if not isinstance(report, dict):
            report = {"ok": False, "error": "Invalid report from Unity"}
        warnings = [
            str(item)
            for item in report.get("warnings") or []
        ]
        if is_unitypackage:
            warnings.extend(str(item) for item in package_warnings)
        if ignored:
            warnings.append(
                "Ignored world options: "
                + ", ".join(ignored)
            )
        source_path = Path(str(resolved.path)).resolve(strict=False)
        world_id = str(
            resolved_options.get("world_id") or source_path.stem or "world"
        ).strip()
        project_id = str(resolved_options.get("project_id") or "").strip()
        scene_path = str(
            report.get("scenePath") or report.get("assetPath") or ""
        ).strip()
        imported_paths = [scene_path] if scene_path else []
        world_artifacts: list[dict[str, Any]] = []
        draft_payload: dict[str, Any] = {}
        validation_payload: dict[str, Any] = {}
        package_payload: dict[str, Any] = {}
        lifecycle_errors: list[str] = []
        if report.get("ok"):
            # World import is an asset-producing operation too.  Register the
            # selected native scene under the same artifact registry used by
            # assets.import_* so later composition/session calls can refer to
            # one stable artifact identity.
            records = build_artifact_records(
                {
                    "ok": True,
                    "src_path": str(source_path),
                    "asset_type": "environment",
                    "asset_id": world_id,
                    "dest_path": str(Path(scene_path).parent) if scene_path else "Assets/Imported/Scenes",
                    "imported_paths": imported_paths,
                    "metadata": {
                        "world_id": world_id,
                        "project_id": project_id,
                        "source_representation": (
                            "unitypackage"
                            if is_unitypackage
                            else "native_unity_scene"
                            if is_native_scene
                            else "generated_unity_scene"
                        ),
                    },
                },
                backend="unity",
                category="environment",
            )
            if records:
                self._assets._service.artifacts.upsert_many(records)
                world_artifacts = [record.to_dict() for record in records]

            # Mirror UE's world lifecycle: create and validate a draft for
            # every successful world import, then publish only when requested.
            world_spec = WorldSpec(
                world_id=world_id,
                project_id=project_id,
                spawn_points=self._spawn_points_from_report(report),
                metadata={
                    "source_path": str(source_path),
                    "scene_path": scene_path,
                    "artifact_ids": [
                        item.get("artifact_id") for item in world_artifacts
                    ],
                    "import_report": {
                        key: value
                        for key, value in report.items()
                        if key not in {"error"}
                    },
                },
            )
            try:
                draft = self._service.create_draft(
                    world_spec,
                    project_id=project_id,
                    metadata={"source_path": str(source_path), "import_mode": "scene"},
                )
                validation = self._service.validate_draft(draft.draft_id)
                draft_payload = draft.to_dict()
                validation_payload = dict(validation)
                if validation.get("ok") and bool(resolved_options.get("publish", True)):
                    package = self._service.publish_draft(draft.draft_id)
                    package_payload = package.to_dict()
            except Exception as exc:
                lifecycle_errors.append(
                    "Unity world package lifecycle failed: "
                    f"{type(exc).__name__}: {exc}"
                )
        return UnityOperationResult(
            operation="world.build",
            ok=bool(report.get("ok", False)) and not lifecycle_errors,
            artifacts=world_artifacts + [
                dict(item)
                for item in report.get("artifacts") or []
                if isinstance(item, dict)
            ] or (
                [
                    {
                        "type": "unity_scene",
                        "path": str(report.get("scenePath") or report.get("assetPath") or ""),
                        "state": "ready",
                    }
                ]
                if report.get("ok") else []
            ),
            warnings=tuple(warnings),
            errors=tuple(
                str(item)
                for item in (
                    [report.get("error", "")]
                    + list(report.get("errors") or [])
                    + lifecycle_errors
                )
                if str(item)
            ),
            payload={
                **{
                    key: value
                    for key, value in report.items()
                    if key not in {"ok", "artifacts", "warnings", "errors", "error"}
                },
                "source": resolved.descriptor(),
                "world_id": world_id,
                "project_id": project_id,
                "draft": draft_payload,
                "validation": validation_payload,
                "package": package_payload,
            },
        ).to_dict()

    @staticmethod
    def _spawn_points_from_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw = str(report.get("spawnPoint") or "").strip()
        if not raw:
            return []
        return [{"source": "unity_scene_report", "value": raw}]

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
            return UnityOperationResult.failure(
                "world.create_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UnityOperationResult.success(
            "world.create_draft",
            payload={"draft": draft.to_dict()},
        ).to_dict()

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        try:
            payload = self._service.validate_draft(draft_id)
        except Exception as exc:
            return UnityOperationResult.failure(
                "world.validate_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UnityOperationResult(
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
            return UnityOperationResult.failure(
                "world.publish_draft",
                f"{type(exc).__name__}: {exc}",
            ).to_dict()
        return UnityOperationResult.success(
            "world.publish_draft",
            artifacts=[
                {
                    "artifact_id": package.package_id,
                    "type": "world_package",
                    "backend": "unity",
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
        return UnityOperationResult.success(
            "world.list_packages",
            artifacts=[
                {
                    "artifact_id": str(
                        item.get("package_id") or ""
                    ),
                    "type": "world_package",
                    "backend": "unity",
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
