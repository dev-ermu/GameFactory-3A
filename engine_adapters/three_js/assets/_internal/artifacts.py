"""Artifact records and registry for the three.js web backend."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BACKEND = "web"

SPAWNABLE_BACKEND_CLASSES = {
    "Group",
    "Mesh",
    "SkinnedMesh",
    "Points",
    "Sprite",
    "InstancedMesh",
}
RENDERABLE_BACKEND_CLASSES = SPAWNABLE_BACKEND_CLASSES | {
    "Texture",
    "DataTexture",
    "Material",
}
PLAYABLE_BACKEND_CLASSES = {
    "AnimationClip",
    "Audio",
    "PositionalAudio",
    "VideoTexture",
}
ARTIFACT_STATES = {"importing", "ready", "failed"}

BACKEND_CLASS_BY_REPRESENTATION = {
    "gltf": "Group",
    "gltf_binary": "Group",
    "fbx": "Group",
    "obj": "Group",
    "stl": "Mesh",
    "ply": "Points",
    "gaussian_splat": "Points",
    "usdz": "Group",
    "png": "Texture",
    "jpeg": "Texture",
    "webp": "Texture",
    "ktx2": "CompressedTexture",
    "basis": "CompressedTexture",
    "hdr": "DataTexture",
    "exr": "DataTexture",
    "tga": "Texture",
    "mp3": "Audio",
    "ogg": "Audio",
    "wav": "Audio",
    "m4a": "Audio",
    "json": "Object3D",
    "asset_package": "Group",
}
BACKEND_CLASS_BY_TYPE = {
    "avatar": "SkinnedMesh",
    "motion": "AnimationClip",
    "texture": "Texture",
    "material": "Material",
    "audio": "Audio",
}

TYPE_ALIASES = {
    "scene": "environment",
    "static_mesh": "prop",
    "object": "prop",
    "weapon": "prop",
    "furniture": "prop",
    "decoration": "prop",
}


def normalize_artifact_type(asset_type: str) -> str:
    normalized = (
        (asset_type or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    return TYPE_ALIASES.get(normalized, normalized)


def normalize_backend_path(backend_path: str) -> str:
    """Normalize a web-relative runtime URL path."""

    path = str(backend_path or "").strip().replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")
    return path.lstrip("./")


def asset_id_from_source(source_path: str) -> str:
    stem = Path(source_path or "asset").stem or "asset"
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", stem).strip("_").lower()
    return cleaned or "asset"


def short_hash(*parts: str, length: int = 6) -> str:
    joined = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length]


def artifact_id_for(
    backend: str,
    backend_class: str,
    asset_id: str,
    backend_path: str,
) -> str:
    def _part(value: str, fallback: str) -> str:
        cleaned = re.sub(
            r"[^0-9A-Za-z_]+",
            "_",
            (value or fallback).lower(),
        ).strip("_")
        return cleaned or fallback

    return (
        f"{_part(backend, 'backend')}_"
        f"{_part(backend_class, 'asset')}_"
        f"{_part(asset_id, 'asset')}_"
        f"{short_hash(backend, backend_path)}"
    )


def backend_class_for(
    asset_type: str,
    representation: str,
    *,
    skinned: bool = False,
) -> str:
    normalized = normalize_artifact_type(asset_type)
    if normalized in BACKEND_CLASS_BY_TYPE:
        return BACKEND_CLASS_BY_TYPE[normalized]
    if skinned:
        return "SkinnedMesh"
    return BACKEND_CLASS_BY_REPRESENTATION.get(
        str(representation or ""),
        "Object3D",
    )


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    asset_id: str
    type: str
    package_id: str = ""
    category: str = ""
    representation: str = ""
    primary_asset: dict[str, Any] = field(default_factory=dict)
    runtime_capabilities: dict[str, Any] = field(default_factory=dict)
    backend: str = BACKEND
    backend_class: str = ""
    backend_path: str = ""
    source_path: str = ""
    spawnable: bool = False
    state: str = "ready"
    editor_backend: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in ARTIFACT_STATES:
            object.__setattr__(self, "state", "ready")
        if not self.primary_asset:
            object.__setattr__(
                self,
                "primary_asset",
                {
                    "backend": self.backend,
                    "class": self.backend_class,
                    "path": self.backend_path,
                },
            )
        if not self.runtime_capabilities:
            object.__setattr__(
                self,
                "runtime_capabilities",
                {
                    "renderable": (
                        self.backend_class
                        in RENDERABLE_BACKEND_CLASSES
                    ),
                    "spawnable": self.spawnable,
                    "collidable": False,
                    "playable": (
                        self.backend_class in PLAYABLE_BACKEND_CLASSES
                    ),
                },
            )
        if not self.editor_backend:
            object.__setattr__(
                self,
                "editor_backend",
                {"backend": self.backend, "path": self.backend_path},
            )
        if not self.runtime:
            object.__setattr__(
                self,
                "runtime",
                {
                    "spawnable": self.spawnable,
                    "class": self.backend_class,
                    "url": self.backend_path,
                },
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRecord":
        backend = str(data.get("backend") or BACKEND)
        backend_class = str(
            data.get("backend_class") or data.get("class") or ""
        )
        backend_path = str(
            data.get("backend_path") or data.get("path") or ""
        )
        spawnable = bool(data.get("spawnable", False))
        state = str(data.get("state") or "ready")
        if state not in ARTIFACT_STATES:
            state = "ready"
        return cls(
            artifact_id=str(
                data.get("artifact_id") or data.get("id") or ""
            ),
            asset_id=str(data.get("asset_id") or ""),
            package_id=str(
                data.get("package_id") or data.get("asset_id") or ""
            ),
            type=str(data.get("type") or ""),
            category=str(data.get("category") or ""),
            representation=str(data.get("representation") or ""),
            primary_asset=dict(data.get("primary_asset") or {}),
            runtime_capabilities=dict(
                data.get("runtime_capabilities")
                or data.get("capabilities")
                or {}
            ),
            backend=backend,
            backend_class=backend_class,
            backend_path=backend_path,
            source_path=str(data.get("source_path") or ""),
            spawnable=spawnable,
            state=state,
            editor_backend=dict(data.get("editor_backend") or {}),
            runtime=dict(data.get("runtime") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "asset_id": self.asset_id,
            "package_id": self.package_id,
            "type": self.type,
            "category": self.category,
            "representation": self.representation,
            "primary_asset": dict(self.primary_asset or {}),
            "runtime_capabilities": dict(
                self.runtime_capabilities or {}
            ),
            "backend": self.backend,
            "backend_class": self.backend_class,
            "backend_path": self.backend_path,
            "source_path": self.source_path,
            "spawnable": self.spawnable,
            "state": self.state,
            "editor_backend": dict(self.editor_backend or {}),
            "runtime": dict(self.runtime or {}),
            "metadata": dict(self.metadata or {}),
        }


class ArtifactRegistry:
    """JSON-backed registry of imported web artifacts."""

    def __init__(self, registry_path: Path) -> None:
        self._path = Path(registry_path)

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        try:
            payload = json.loads(
                self._path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            return {}
        if isinstance(payload, dict):
            records = payload.get("artifacts")
            if isinstance(records, dict):
                return {
                    str(key): dict(value)
                    for key, value in records.items()
                    if isinstance(value, dict)
                }
            return {
                str(key): dict(value)
                for key, value in payload.items()
                if isinstance(value, dict)
            }
        if isinstance(payload, list):
            resolved: dict[str, dict[str, Any]] = {}
            for item in payload:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("artifact_id") or "")
                if key:
                    resolved[key] = dict(item)
            return resolved
        return {}

    def _save(self, records: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "backend": BACKEND,
                    "artifacts": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def upsert(self, record: ArtifactRecord) -> ArtifactRecord:
        records = self._load()
        records[record.artifact_id] = record.to_dict()
        self._save(records)
        return record

    def upsert_many(
        self,
        records: list[ArtifactRecord],
    ) -> list[ArtifactRecord]:
        stored = self._load()
        for record in records:
            stored[record.artifact_id] = record.to_dict()
        self._save(stored)
        return list(records)

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        record = self._load().get(str(artifact_id or ""))
        return ArtifactRecord.from_dict(record) if record else None

    def remove(self, artifact_id: str) -> bool:
        records = self._load()
        if str(artifact_id) not in records:
            return False
        records.pop(str(artifact_id))
        self._save(records)
        return True

    def list(
        self,
        *,
        type: str | None = None,
        backend: str | None = BACKEND,
    ) -> list[ArtifactRecord]:
        normalized_type = (
            normalize_artifact_type(type) if type else ""
        )
        results = []
        for payload in self._load().values():
            record = ArtifactRecord.from_dict(payload)
            if backend and record.backend != backend:
                continue
            if normalized_type and record.type != normalized_type:
                continue
            results.append(record)
        return sorted(results, key=lambda item: item.artifact_id)
