"""World draft, validation, and package services for three.js."""

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...assets._internal.artifacts import ArtifactRegistry
from .specs import WorldSpec


def _now() -> float:
    return time.time()


def _short_id(*parts: str, length: int = 8) -> str:
    joined = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length]


@dataclass
class WorldDraft:
    draft_id: str
    world_id: str
    spec: WorldSpec
    project_id: str = ""
    status: str = "draft"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldDraft":
        return cls(
            draft_id=str(data.get("draft_id") or ""),
            world_id=str(data.get("world_id") or ""),
            spec=WorldSpec.from_dict(dict(data.get("spec") or {})),
            project_id=str(data.get("project_id") or ""),
            status=str(data.get("status") or "draft"),
            created_at=float(data.get("created_at") or _now()),
            updated_at=float(data.get("updated_at") or _now()),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "world_id": self.world_id,
            "project_id": self.project_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "spec": self.spec.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WorldPackage:
    package_id: str
    world_id: str
    project_id: str
    revision_id: str
    status: str
    scene_url: str
    scene_path: str
    manifest: dict[str, Any]
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "world_id": self.world_id,
            "project_id": self.project_id,
            "revision_id": self.revision_id,
            "status": self.status,
            "scene_url": self.scene_url,
            "scene_path": self.scene_path,
            "manifest": dict(self.manifest),
            "created_at": self.created_at,
        }


class WorldRegistry:
    """Filesystem registry of world drafts."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def drafts_root(self) -> Path:
        return self._root / "drafts"

    def save(self, draft: WorldDraft) -> WorldDraft:
        self.drafts_root.mkdir(parents=True, exist_ok=True)
        draft.updated_at = _now()
        (self.drafts_root / f"{draft.draft_id}.json").write_text(
            json.dumps(draft.to_dict(), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return draft

    def load(self, draft_id: str) -> WorldDraft:
        path = self.drafts_root / f"{draft_id}.json"
        if not path.is_file():
            raise ValueError(f"Unknown world draft: {draft_id}")
        return WorldDraft.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def list(self) -> list[dict[str, Any]]:
        if not self.drafts_root.is_dir():
            return []
        results = []
        for path in sorted(self.drafts_root.glob("*.json")):
            try:
                payload = json.loads(
                    path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                results.append(payload)
        return results


class WorldPackageRegistry:
    """Filesystem registry of published world packages."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def packages_root(self) -> Path:
        return self._root / "packages"

    def save(self, package: WorldPackage) -> WorldPackage:
        self.packages_root.mkdir(parents=True, exist_ok=True)
        (
            self.packages_root / f"{package.package_id}.json"
        ).write_text(
            json.dumps(package.to_dict(), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return package

    def load(self, package_id: str) -> WorldPackage:
        path = self.packages_root / f"{package_id}.json"
        if not path.is_file():
            raise ValueError(f"Unknown world package: {package_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return WorldPackage(
            package_id=str(payload.get("package_id") or ""),
            world_id=str(payload.get("world_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            revision_id=str(payload.get("revision_id") or ""),
            status=str(payload.get("status") or ""),
            scene_url=str(payload.get("scene_url") or ""),
            scene_path=str(payload.get("scene_path") or ""),
            manifest=dict(payload.get("manifest") or {}),
            created_at=float(payload.get("created_at") or _now()),
        )

    def list(
        self,
        *,
        project_id: str = "",
        world_id: str = "",
    ) -> list[dict[str, Any]]:
        if not self.packages_root.is_dir():
            return []
        results = []
        for path in sorted(self.packages_root.glob("*.json")):
            try:
                payload = json.loads(
                    path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if project_id and str(
                payload.get("project_id") or ""
            ) != project_id:
                continue
            if world_id and str(
                payload.get("world_id") or ""
            ) != world_id:
                continue
            results.append(payload)
        return results


class WorldService:
    """Create, validate, and publish three.js world scene graphs."""

    def __init__(
        self,
        *,
        artifact_registry: ArtifactRegistry,
        world_registry: WorldRegistry,
        package_registry: WorldPackageRegistry,
        scene_output_root: Path | None,
        scene_url_root: str = "assets/worlds",
    ) -> None:
        self._artifacts = artifact_registry
        self._drafts = world_registry
        self._packages = package_registry
        self._scene_output_root = scene_output_root
        self._scene_url_root = scene_url_root.strip("/")

    def create_draft(
        self,
        spec: WorldSpec,
        *,
        draft_id: str = "",
        project_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorldDraft:
        resolved_id = str(draft_id or "").strip() or (
            f"draft_{spec.world_id}_"
            f"{_short_id(spec.world_id, str(_now()))}"
        )
        draft = WorldDraft(
            draft_id=resolved_id,
            world_id=spec.world_id,
            spec=spec,
            project_id=project_id or spec.project_id,
            metadata=dict(metadata or {}),
        )
        return self._drafts.save(draft)

    def get_draft(self, draft_id: str) -> WorldDraft:
        return self._drafts.load(draft_id)

    def list_drafts(self) -> list[dict[str, Any]]:
        return self._drafts.list()

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self._drafts.load(draft_id)
        spec = draft.spec
        errors: list[str] = []
        warnings: list[str] = []
        resolved: list[dict[str, Any]] = []

        for artifact_id in spec.artifact_ids():
            record = self._artifacts.get(artifact_id)
            if record is None:
                errors.append(
                    f"Unknown artifact_id referenced by world: "
                    f"{artifact_id}"
                )
                continue
            if record.state != "ready":
                errors.append(
                    f"Artifact {artifact_id} is not ready "
                    f"(state={record.state})"
                )
            if not record.backend_path:
                errors.append(
                    f"Artifact {artifact_id} has no runtime URL"
                )
            resolved.append(
                {
                    "artifact_id": artifact_id,
                    "url": record.backend_path,
                    "class": record.backend_class,
                    "type": record.type,
                }
            )

        entity_ids = [entity.entity_id for entity in spec.entities]
        duplicates = sorted(
            {
                entity_id
                for entity_id in entity_ids
                if entity_ids.count(entity_id) > 1
            }
        )
        if duplicates:
            errors.append(
                "Duplicate entity_id values: " + ", ".join(duplicates)
            )
        if not spec.lights:
            warnings.append(
                "World declares no light; imported PBR materials will "
                "render black unless an environment map is set"
            )
        if not spec.spawn_points and not any(
            entity.role == "player_start" for entity in spec.entities
        ):
            warnings.append(
                "World declares no spawn point and no player_start "
                "entity; generated gameplay must supply its own"
            )
        for entity in spec.entities:
            for behavior in entity.behaviors:
                if behavior.type == "animation" and not (
                    behavior.artifact_id or behavior.clip
                ):
                    errors.append(
                        f"Entity {entity.entity_id} declares an "
                        "animation behavior without artifact_id or clip"
                    )

        return {
            "ok": not errors,
            "draft_id": draft_id,
            "world_id": spec.world_id,
            "warnings": warnings,
            "errors": errors,
            "entity_count": len(spec.entities),
            "light_count": len(spec.lights),
            "resolved_artifacts": resolved,
        }

    def publish_draft(self, draft_id: str) -> WorldPackage:
        validation = self.validate_draft(draft_id)
        if not validation.get("ok"):
            raise ValueError(
                "World draft is invalid: "
                + "; ".join(validation.get("errors") or [])
            )
        draft = self._drafts.load(draft_id)
        scene_graph = self.build_scene_graph(draft)
        graph_hash = _short_id(
            json.dumps(scene_graph, sort_keys=True),
            length=12,
        )
        revision_id = f"rev_{draft.world_id}_{graph_hash}"
        package_id = f"pkg_{draft.world_id}_{graph_hash}"
        scene_url = f"/{self._scene_url_root}/{draft.world_id}.json"
        scene_path = ""
        if self._scene_output_root is not None:
            target = (
                self._scene_output_root
                / self._scene_url_root
                / f"{draft.world_id}.json"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(scene_graph, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            scene_path = str(target)

        package = WorldPackage(
            package_id=package_id,
            world_id=draft.world_id,
            project_id=draft.project_id,
            revision_id=revision_id,
            status="published",
            scene_url=scene_url,
            scene_path=scene_path,
            manifest={
                "scene_graph_hash": graph_hash,
                "entity_count": len(draft.spec.entities),
                "light_count": len(draft.spec.lights),
                "artifact_ids": draft.spec.artifact_ids(),
                "resolved_artifacts": validation.get(
                    "resolved_artifacts"
                )
                or [],
                "warnings": validation.get("warnings") or [],
            },
        )
        draft.status = "published"
        self._drafts.save(draft)
        return self._packages.save(package)

    def build_scene_graph(self, draft: WorldDraft) -> dict[str, Any]:
        """Build the runtime scene graph document for one draft."""

        spec = draft.spec
        urls: dict[str, dict[str, Any]] = {}
        for artifact_id in spec.artifact_ids():
            record = self._artifacts.get(artifact_id)
            if record is None:
                continue
            urls[artifact_id] = {
                "url": record.backend_path,
                "class": record.backend_class,
                "type": record.type,
                "representation": record.representation,
                "capabilities": dict(
                    record.runtime_capabilities or {}
                ),
            }
        payload = spec.to_dict()
        payload.update(
            {
                "scene_graph_version": 1,
                "engine": "three_js",
                "coordinate_system": "y_up_right_handed_metres",
                "draft_id": draft.draft_id,
                "assets": urls,
            }
        )
        return payload

    def list_packages(
        self,
        *,
        project_id: str = "",
        world_id: str = "",
    ) -> list[dict[str, Any]]:
        return self._packages.list(
            project_id=project_id,
            world_id=world_id,
        )

    def get_package(self, package_id: str) -> WorldPackage:
        return self._packages.load(package_id)
