"""WorldSpec schema definitions for A3Game world composition."""

import re
from dataclasses import dataclass, field
from typing import Any


WORLD_SPEC_VERSION = "1.0"
ENTITY_ROLES = {"environment", "prop", "avatar"}
BEHAVIOR_TYPES = {"motion"}


def normalize_role(role: str) -> str:
    normalized = (role or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in ENTITY_ROLES:
        allowed = ", ".join(sorted(ENTITY_ROLES))
        raise ValueError(f"不支持的 World entity role: {role}（支持: {allowed}）")
    return normalized


def safe_id(value: str, fallback: str = "world") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip()).strip("_").lower()
    return cleaned or fallback


def _vector_dict(value, keys: tuple[str, str, str], defaults: tuple[float, float, float]) -> dict[str, float]:
    if isinstance(value, dict):
        return {
            key: float(value.get(key, defaults[index]) if value.get(key, defaults[index]) not in ("", None) else defaults[index])
            for index, key in enumerate(keys)
        }
    if isinstance(value, (list, tuple)):
        cleaned = list(value)
        return {
            key: float(cleaned[index]) if index < len(cleaned) and cleaned[index] not in ("", None) else defaults[index]
            for index, key in enumerate(keys)
        }
    return {key: defaults[index] for index, key in enumerate(keys)}


@dataclass(frozen=True)
class TransformSpec:
    location: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    rotation: dict[str, float] = field(default_factory=lambda: {"pitch": 0.0, "yaw": 0.0, "roll": 0.0})
    scale: dict[str, float] = field(default_factory=lambda: {"x": 1.0, "y": 1.0, "z": 1.0})

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TransformSpec":
        data = data or {}
        return cls(
            location=_vector_dict(data.get("location"), ("x", "y", "z"), (0.0, 0.0, 0.0)),
            rotation=_vector_dict(data.get("rotation"), ("pitch", "yaw", "roll"), (0.0, 0.0, 0.0)),
            scale=_vector_dict(data.get("scale"), ("x", "y", "z"), (1.0, 1.0, 1.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"location": dict(self.location), "rotation": dict(self.rotation), "scale": dict(self.scale)}


@dataclass(frozen=True)
class WorldBehaviorSpec:
    type: str
    artifact_id: str
    loop: bool = True
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldBehaviorSpec":
        behavior_type = (data.get("type") or "").strip().lower()
        if behavior_type not in BEHAVIOR_TYPES:
            allowed = ", ".join(sorted(BEHAVIOR_TYPES))
            raise ValueError(f"不支持的 behavior type: {behavior_type}（支持: {allowed}）")
        return cls(
            type=behavior_type,
            artifact_id=str(data.get("artifact_id") or "").strip(),
            loop=bool(data.get("loop", True)),
            options=dict(data.get("options") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "artifact_id": self.artifact_id,
            "loop": self.loop,
            "options": dict(self.options),
        }


@dataclass(frozen=True)
class WorldEntitySpec:
    entity_id: str
    role: str
    artifact_id: str
    category: str = ""
    collision: bool | None = None
    transform: TransformSpec = field(default_factory=TransformSpec)
    behaviors: list[WorldBehaviorSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int = 0) -> "WorldEntitySpec":
        role = normalize_role(str(data.get("role") or ""))
        entity_id = str(data.get("entity_id") or f"{role}_{index}").strip()
        artifact_id = str(data.get("artifact_id") or "").strip()
        if not artifact_id:
            raise ValueError(f"World entity {entity_id} 缺少 artifact_id")
        return cls(
            entity_id=entity_id,
            role=role,
            artifact_id=artifact_id,
            category=str(data.get("category") or "").strip(),
            collision=(
                bool(data.get("collision"))
                if "collision" in data
                else None
            ),
            transform=TransformSpec.from_dict(data.get("transform") if isinstance(data.get("transform"), dict) else {}),
            behaviors=[WorldBehaviorSpec.from_dict(item) for item in data.get("behaviors") or [] if isinstance(item, dict)],
        )

    def collision_enabled(self) -> bool:
        if self.collision is not None:
            return self.collision
        return self.role in {"environment", "prop"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "role": self.role,
            "artifact_id": self.artifact_id,
            "category": self.category,
            "collision": self.collision_enabled(),
            "transform": self.transform.to_dict(),
            "behaviors": [item.to_dict() for item in self.behaviors],
        }


@dataclass(frozen=True)
class CameraSpec:
    mode: str = "orbit"
    target: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CameraSpec":
        data = data or {}
        return cls(
            mode=str(data.get("mode") or "orbit").strip().lower(),
            target=str(data.get("target") or "").strip(),
            options={key: value for key, value in data.items() if key not in {"mode", "target"}},
        )

    def to_dict(self) -> dict[str, Any]:
        result = {"mode": self.mode, "target": self.target}
        result.update(self.options)
        return result


@dataclass(frozen=True)
class WorldSpec:
    world_id: str
    project_id: str = ""
    version: str = WORLD_SPEC_VERSION
    entities: list[WorldEntitySpec] = field(default_factory=list)
    camera: CameraSpec = field(default_factory=CameraSpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldSpec":
        version = str(data.get("version") or WORLD_SPEC_VERSION).strip()
        if version != WORLD_SPEC_VERSION:
            raise ValueError(f"不支持的 WorldSpec version: {version}（当前支持: {WORLD_SPEC_VERSION}）")
        world_id = safe_id(str(data.get("world_id") or "world"), fallback="world")
        entities = [WorldEntitySpec.from_dict(item, index) for index, item in enumerate(data.get("entities") or []) if isinstance(item, dict)]
        return cls(
            world_id=world_id,
            project_id=safe_id(str(data.get("project_id") or ""), fallback=""),
            version=version,
            entities=entities,
            camera=CameraSpec.from_dict(data.get("camera") if isinstance(data.get("camera"), dict) else {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "world_id": self.world_id,
            "project_id": self.project_id,
            "entities": [item.to_dict() for item in self.entities],
            "camera": self.camera.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EntitySpawnPlan:
    world_id: str
    entity_id: str
    role: str
    artifact_id: str
    backend_class: str
    backend_path: str
    actor_label: str
    collision: bool
    transform: TransformSpec
    behaviors: list[WorldBehaviorSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "entity_id": self.entity_id,
            "role": self.role,
            "artifact_id": self.artifact_id,
            "backend_class": self.backend_class,
            "backend_path": self.backend_path,
            "actor_label": self.actor_label,
            "collision": self.collision,
            "transform": self.transform.to_dict(),
            "behaviors": [item.to_dict() for item in self.behaviors],
        }
