"""Persistent World Draft, Revision, and Runtime Package records."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4

from engine_adapters.ue5.assets._internal.artifacts import (
    ArtifactRegistry,
)
from engine_adapters.ue5.config import UEClientConfig

from .specs import WorldSpec, safe_id


def _now() -> float:
    return time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        Path(temp_name).replace(path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


@dataclass
class WorldDraft:
    draft_id: str
    project_id: str
    world_id: str
    spec: WorldSpec
    status: str = "draft"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldDraft":
        spec_data = data.get("spec") if isinstance(data.get("spec"), dict) else data
        spec = WorldSpec.from_dict(spec_data)
        return cls(
            draft_id=safe_id(str(data.get("draft_id") or data.get("id") or ""), fallback=_new_id("draft")),
            project_id=safe_id(str(data.get("project_id") or spec.project_id or ""), fallback=""),
            world_id=spec.world_id,
            spec=spec,
            status=str(data.get("status") or "draft"),
            created_at=float(data.get("created_at") or _now()),
            updated_at=float(data.get("updated_at") or _now()),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "project_id": self.project_id,
            "world_id": self.world_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "spec": self.spec.to_dict(),
        }


@dataclass(frozen=True)
class WorldRevision:
    revision_id: str
    source_draft_id: str
    project_id: str
    world_id: str
    status: str
    asset_versions: dict[str, str]
    world_graph_hash: str
    runtime_package_id: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "source_draft_id": self.source_draft_id,
            "project_id": self.project_id,
            "world_id": self.world_id,
            "status": self.status,
            "asset_versions": dict(self.asset_versions),
            "world_graph_hash": self.world_graph_hash,
            "runtime_package_id": self.runtime_package_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class RuntimePackage:
    package_id: str
    project_id: str
    world_id: str
    revision_id: str
    status: str
    manifest: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "project_id": self.project_id,
            "world_id": self.world_id,
            "revision_id": self.revision_id,
            "status": self.status,
            "created_at": self.created_at,
            "manifest": dict(self.manifest),
        }


class WorldPackageRegistry:
    """JSON persistence for drafts, immutable revisions, and packages."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(
            root or UEClientConfig.resolve().world_registry_root
        )
        self.drafts_root = self.root / "drafts"
        self.revisions_root = self.root / "revisions"
        self.packages_root = self.root / "packages"

    def save_draft(self, draft: WorldDraft) -> WorldDraft:
        draft.updated_at = _now()
        _write_json(self.drafts_root / f"{draft.draft_id}.json", draft.to_dict())
        return draft

    def load_draft(self, draft_id: str) -> WorldDraft:
        path = self.drafts_root / f"{safe_id(draft_id, fallback='')}.json"
        if not path.exists():
            raise FileNotFoundError(f"找不到 WorldDraft: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return WorldDraft.from_dict(json.load(handle))

    def list_drafts(self) -> list[dict[str, Any]]:
        if not self.drafts_root.exists():
            return []
        result = []
        for path in sorted(self.drafts_root.glob("*.json")):
            try:
                result.append(self.load_draft(path.stem).to_dict())
            except Exception as exc:
                result.append({"draft_id": path.stem, "status": "invalid", "error": f"{type(exc).__name__}: {exc}"})
        return result

    def save_revision(self, revision: WorldRevision) -> None:
        _write_json(self.revisions_root / revision.world_id / f"{revision.revision_id}.json", revision.to_dict())

    def save_package(self, package: RuntimePackage) -> None:
        _write_json(self.packages_root / f"{package.package_id}.json", package.to_dict())

    def load_package(self, package_id: str) -> RuntimePackage:
        safe_package_id = safe_id(package_id, fallback="")
        path = self.packages_root / f"{safe_package_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"找不到 Runtime Package: {path}")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return RuntimePackage(
            package_id=str(data.get("package_id") or safe_package_id),
            project_id=str(data.get("project_id") or ""),
            world_id=str(data.get("world_id") or ""),
            revision_id=str(data.get("revision_id") or ""),
            status=str(data.get("status") or ""),
            manifest=dict(data.get("manifest") or {}),
            created_at=float(data.get("created_at") or 0.0),
        )

    def list_packages(self, project_id: str = "", world_id: str = "") -> list[dict[str, Any]]:
        if not self.packages_root.exists():
            return []
        packages = []
        for path in sorted(self.packages_root.glob("*.json")):
            try:
                package = self.load_package(path.stem)
            except Exception as exc:
                packages.append({"package_id": path.stem, "status": "invalid", "error": f"{type(exc).__name__}: {exc}"})
                continue
            if project_id and package.project_id != project_id:
                continue
            if world_id and package.world_id != world_id:
                continue
            packages.append(package.to_dict())
        return packages

    def latest_package(self, world_id: str, project_id: str = "") -> RuntimePackage | None:
        packages = self.list_packages(project_id=project_id, world_id=world_id)
        if not packages:
            return None
        packages.sort(key=lambda item: float(item.get("created_at") or 0.0), reverse=True)
        return self.load_package(packages[0]["package_id"])


class WorldBuilderService:
    def __init__(
        self,
        artifact_registry: ArtifactRegistry,
        package_registry: WorldPackageRegistry | None = None,
    ) -> None:
        self.artifacts = artifact_registry
        self.packages = package_registry or WorldPackageRegistry()

    def create_draft(
        self,
        spec: WorldSpec,
        *,
        draft_id: str = "",
        project_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorldDraft:
        resolved_project_id = safe_id(project_id or spec.project_id, fallback="")
        if resolved_project_id != spec.project_id:
            spec = WorldSpec(
                world_id=spec.world_id,
                project_id=resolved_project_id,
                version=spec.version,
                entities=spec.entities,
                camera=spec.camera,
                metadata=spec.metadata,
            )
        draft = WorldDraft(
            draft_id=safe_id(draft_id, fallback=_new_id("draft")),
            project_id=resolved_project_id,
            world_id=spec.world_id,
            spec=spec,
            metadata=dict(metadata or {}),
        )
        return self.packages.save_draft(draft)

    def validate(self, draft: WorldDraft) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        entity_ids: set[str] = set()
        resolved_artifacts: list[dict[str, Any]] = []
        native_level_path = str(draft.spec.metadata.get("level_path") or "").strip()
        if native_level_path and not native_level_path.startswith("/Game/"):
            errors.append(f"Native UE level_path 必须位于 /Game: {native_level_path}")

        for entity in draft.spec.entities:
            if entity.entity_id in entity_ids:
                errors.append(f"World entity_id 重复: {entity.entity_id}")
            entity_ids.add(entity.entity_id)
            artifact = self.artifacts.get(entity.artifact_id)
            if artifact is None:
                errors.append(f"找不到 Artifact: {entity.artifact_id}")
                continue
            if artifact.state != "ready":
                errors.append(f"Artifact 未 ready: {artifact.artifact_id} ({artifact.state})")
            if not artifact.spawnable:
                errors.append(f"Artifact 不可 Spawn: {artifact.artifact_id}")
            if artifact.backend != "ue":
                errors.append(f"当前 Runtime 只支持 UE Artifact: {artifact.artifact_id}")
            if entity.role in {"environment", "prop"} and artifact.backend_class != "StaticMesh":
                errors.append(
                    f"Player Runtime 当前只支持 StaticMesh world entity: "
                    f"{entity.entity_id} ({artifact.backend_class})"
                )
            if (
                entity.collision_enabled()
                and artifact.backend_class == "StaticMesh"
                and not bool(
                    artifact.runtime_capabilities.get("collidable", False)
                )
            ):
                errors.append(
                    f"World entity 请求碰撞，但 Artifact 未确认碰撞可用: "
                    f"{entity.entity_id} ({artifact.artifact_id})"
                )
            resolved_artifacts.append({
                "artifact_id": artifact.artifact_id,
                "backend": artifact.backend,
                "backend_class": artifact.backend_class,
                "backend_path": artifact.backend_path,
                "asset_version": str(artifact.metadata.get("version") or "v1"),
                "collidable": bool(
                    artifact.runtime_capabilities.get("collidable", False)
                ),
            })

            for behavior in entity.behaviors:
                motion = self.artifacts.get(behavior.artifact_id)
                if motion is None:
                    errors.append(f"找不到 Motion Artifact: {behavior.artifact_id}")
                elif motion.type != "motion" or motion.backend_class != "AnimSequence":
                    errors.append(f"Behavior motion 需要 AnimSequence Artifact: {behavior.artifact_id}")
                elif entity.role != "avatar":
                    errors.append(f"Motion behavior 只能配置在 avatar entity 上: {entity.entity_id}")

        if not draft.spec.entities and not native_level_path:
            warnings.append("WorldSpec 没有 entities，发布包可以创建但不会 Spawn 世界 Actor")
        if not native_level_path and not any(entity.role == "environment" for entity in draft.spec.entities):
            warnings.append("WorldSpec 没有 environment entity")
        if not any(entity.role == "avatar" for entity in draft.spec.entities):
            warnings.append("WorldSpec 没有 avatar entity；Player Runtime 仍可单独选择 Avatar")

        return {
            "ok": not errors,
            "draft_id": draft.draft_id,
            "world_id": draft.world_id,
            "project_id": draft.project_id,
            "errors": errors,
            "warnings": warnings,
            "resolved_artifacts": resolved_artifacts,
        }

    def publish(self, draft_id: str) -> RuntimePackage:
        draft = self.packages.load_draft(draft_id)
        validation = self.validate(draft)
        if not validation["ok"]:
            raise ValueError("; ".join(validation["errors"]))

        resolved_by_id = {item["artifact_id"]: item for item in validation["resolved_artifacts"]}
        world_data = draft.spec.to_dict()
        for entity in world_data["entities"]:
            resolved = resolved_by_id.get(entity["artifact_id"], {})
            entity["backend"] = resolved.get("backend", "")
            entity["backend_class"] = resolved.get("backend_class", "")
            entity["backend_path"] = resolved.get("backend_path", "")

        canonical = json.dumps(world_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        graph_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        revision_id = f"rev_{graph_hash[:10]}"
        package_id = f"pkg_{safe_id(draft.world_id)}_{graph_hash[:10]}"
        asset_versions = {
            item["artifact_id"]: item["asset_version"]
            for item in validation["resolved_artifacts"]
        }
        revision = WorldRevision(
            revision_id=revision_id,
            source_draft_id=draft.draft_id,
            project_id=draft.project_id,
            world_id=draft.world_id,
            status="published",
            asset_versions=asset_versions,
            world_graph_hash=graph_hash,
            runtime_package_id=package_id,
            created_at=_now(),
        )
        package = RuntimePackage(
            package_id=package_id,
            project_id=draft.project_id,
            world_id=draft.world_id,
            revision_id=revision_id,
            status="published",
            created_at=_now(),
            manifest={
                "schema_version": "0.1",
                "package_id": package_id,
                "project_id": draft.project_id,
                "world_id": draft.world_id,
                "revision_id": revision_id,
                "runtime_ready": True,
                "world": world_data,
                "artifacts": validation["resolved_artifacts"],
                "ue": {
                    "level_path": str(draft.spec.metadata.get("level_path") or ""),
                    "content_root": str(draft.spec.metadata.get("native_content_root") or ""),
                },
                "capabilities": {
                    "renderable": True,
                    "spawnable": True,
                    "collidable": bool(draft.spec.metadata.get("collidable", False))
                    or any(
                        entity.collision_enabled()
                        and bool(
                            resolved_by_id.get(
                                entity.artifact_id,
                                {},
                            ).get("collidable", False)
                        )
                        for entity in draft.spec.entities
                    ),
                    "navigable": bool(draft.spec.metadata.get("navigable", False)),
                    "interactive": bool(draft.spec.metadata.get("interactive", False)),
                    "benchmarkable": False,
                },
                "warnings": validation["warnings"],
            },
        )
        self.packages.save_revision(revision)
        self.packages.save_package(package)
        draft.status = "published"
        self.packages.save_draft(draft)
        return package
