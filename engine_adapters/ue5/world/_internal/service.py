"""WorldSpec orchestration service."""

from dataclasses import dataclass
from typing import Any, Protocol

from engine_adapters.ue5.assets._internal.artifacts import (
    ArtifactRecord,
    ArtifactRegistry,
)

from .specs import EntitySpawnPlan, WorldBehaviorSpec, WorldEntitySpec, WorldSpec
from .registry import WorldRegistry
from .packages import RuntimePackage, WorldBuilderService, WorldDraft, WorldPackageRegistry


ROLE_LABEL_PART = {
    "environment": "Environment",
    "prop": "Prop",
    "avatar": "Avatar",
}


class WorldSceneExecutor(Protocol):
    def spawn_asset(
        self,
        asset_path: str,
        transform: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def clear_actor_tag(self, tag: str) -> dict[str, Any]:
        ...

    def set_actor_animation(
        self,
        *,
        actor_label: str,
        motion_asset_path: str,
        avatar_asset_path: str = "",
        looping: bool = True,
    ) -> dict[str, Any]:
        ...


@dataclass
class WorldSpawnResult:
    ok: bool
    world_id: str
    spawn_plan: list[dict]
    entities: list[dict]
    behaviors: list[dict]
    camera: dict

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "world_id": self.world_id,
            "spawn_plan": self.spawn_plan,
            "entities": self.entities,
            "behaviors": self.behaviors,
            "camera": self.camera,
        }


class WorldService:
    def __init__(
        self,
        artifact_registry: ArtifactRegistry | None = None,
        scene_service: WorldSceneExecutor | None = None,
        world_registry: WorldRegistry | None = None,
        package_registry: WorldPackageRegistry | None = None,
    ) -> None:
        self.artifacts = artifact_registry or ArtifactRegistry()
        self.scene = scene_service
        self.worlds = world_registry or WorldRegistry()
        self.packages = package_registry or WorldPackageRegistry()
        self.builder = WorldBuilderService(self.artifacts, self.packages)

    def list_worlds(self) -> list[dict]:
        return self.worlds.list_worlds()

    def get_world(self, world_id: str) -> WorldSpec:
        try:
            return self.worlds.load(world_id)
        except FileNotFoundError:
            package = self.packages.latest_package(world_id)
            if package is None:
                raise
            return WorldSpec.from_dict(package.manifest.get("world") or {})

    def create_draft(
        self,
        spec: WorldSpec,
        *,
        draft_id: str = "",
        project_id: str = "",
        metadata: dict | None = None,
    ) -> WorldDraft:
        return self.builder.create_draft(spec, draft_id=draft_id, project_id=project_id, metadata=metadata)

    def list_drafts(self) -> list[dict]:
        return self.packages.list_drafts()

    def get_draft(self, draft_id: str) -> WorldDraft:
        return self.packages.load_draft(draft_id)

    def validate_draft(self, draft_id: str) -> dict:
        return self.builder.validate(self.get_draft(draft_id))

    def publish_draft(self, draft_id: str) -> RuntimePackage:
        return self.builder.publish(draft_id)

    def list_packages(self, project_id: str = "", world_id: str = "") -> list[dict]:
        return self.packages.list_packages(project_id=project_id, world_id=world_id)

    def get_package(self, package_id: str) -> RuntimePackage:
        return self.packages.load_package(package_id)

    def latest_package(self, world_id: str, project_id: str = "") -> RuntimePackage | None:
        return self.packages.latest_package(world_id, project_id=project_id)

    def load_world(self, world_id: str, clear_existing: bool = True) -> WorldSpawnResult:
        return self.spawn_world(self.worlds.load(world_id), clear_existing=clear_existing)

    def spawn_world(self, spec: WorldSpec, clear_existing: bool = True) -> WorldSpawnResult:
        scene = self._require_scene()
        if clear_existing:
            self.clear_world(spec.world_id)
        plans = self.build_spawn_plan(spec)
        spawned_entities = []
        behavior_results = []

        for index, plan in enumerate(plans):
            transform = plan.transform.to_dict()
            transform["actor_label"] = plan.actor_label
            transform["destroy_existing"] = False
            transform["create_camera"] = index == 0
            transform["tags"] = [self.world_tag(spec.world_id), self.entity_tag(plan.entity_id)]
            transform["collision"] = plan.collision
            result = scene.spawn_asset(
                plan.backend_path,
                transform=transform,
            )
            result["entity_id"] = plan.entity_id
            result["role"] = plan.role
            result["artifact_id"] = plan.artifact_id
            result["actor_label"] = result.get("actor_label") or plan.actor_label
            spawned_entities.append(result)

        for plan in plans:
            for behavior in plan.behaviors:
                behavior_results.append(self._apply_behavior(behavior, plan))

        return WorldSpawnResult(
            ok=True,
            world_id=spec.world_id,
            spawn_plan=[plan.to_dict() for plan in plans],
            entities=spawned_entities,
            behaviors=behavior_results,
            camera=spec.camera.to_dict(),
        )

    def clear_world(self, world_id: str) -> dict:
        return self._require_scene().clear_actor_tag(
            self.world_tag(world_id)
        )

    def build_spawn_plan(self, spec: WorldSpec) -> list[EntitySpawnPlan]:
        counters = {role: 0 for role in ROLE_LABEL_PART}
        plans = []
        for entity in spec.entities:
            artifact = self._resolve_artifact(entity)
            if artifact.type == "motion":
                raise ValueError(f"Motion Artifact 不能作为 entity spawn: {artifact.artifact_id}")
            index = counters.get(entity.role, 0)
            counters[entity.role] = index + 1
            plans.append(
                EntitySpawnPlan(
                    world_id=spec.world_id,
                    entity_id=entity.entity_id,
                    role=entity.role,
                    artifact_id=artifact.artifact_id,
                    backend_class=artifact.backend_class,
                    backend_path=artifact.backend_path,
                    actor_label=self.actor_label(spec.world_id, entity.role, index),
                    collision=entity.collision_enabled(),
                    transform=entity.transform,
                    behaviors=entity.behaviors,
                )
            )
        return plans

    def _resolve_artifact(self, entity: WorldEntitySpec) -> ArtifactRecord:
        artifact = self.artifacts.get(entity.artifact_id)
        if artifact is None:
            raise ValueError(f"World entity {entity.entity_id} 找不到 Artifact: {entity.artifact_id}")
        if entity.role in {"environment", "prop", "avatar"} and not artifact.spawnable:
            raise ValueError(f"World entity {entity.entity_id} 的 Artifact 不可 Spawn: {artifact.artifact_id}")
        if artifact.backend != "ue":
            raise ValueError(f"当前 WorldService 只支持 UE Artifact: {artifact.artifact_id}")
        return artifact

    def _apply_behavior(
        self,
        behavior: WorldBehaviorSpec,
        plan: EntitySpawnPlan,
    ) -> dict:
        if behavior.type != "motion":
            raise ValueError(f"不支持的 behavior type: {behavior.type}")
        motion = self.artifacts.get(behavior.artifact_id)
        if motion is None:
            raise ValueError(f"找不到 Motion Artifact: {behavior.artifact_id}")
        if motion.type != "motion" or motion.backend_class != "AnimSequence":
            raise ValueError(f"Behavior motion 需要 AnimSequence Artifact: {motion.artifact_id}")
        if plan.role != "avatar":
            raise ValueError(f"Motion behavior 只能配置在 avatar entity 上: {plan.entity_id}")
        result = self._require_scene().set_actor_animation(
            actor_label=plan.actor_label,
            motion_asset_path=motion.backend_path,
            avatar_asset_path=plan.backend_path,
            looping=behavior.loop,
        )
        result["behavior"] = behavior.to_dict()
        result["entity_id"] = plan.entity_id
        result["actor_label"] = plan.actor_label
        return result

    def _require_scene(self) -> WorldSceneExecutor:
        if self.scene is None:
            raise RuntimeError(
                "World scene execution is not configured"
            )
        return self.scene

    @staticmethod
    def world_actor_prefix(world_id: str) -> str:
        return f"A3Game_World_{world_id}_"

    @staticmethod
    def world_tag(world_id: str) -> str:
        return f"A3GameWorld:{world_id}"

    @staticmethod
    def entity_tag(entity_id: str) -> str:
        return f"A3GameEntity:{entity_id}"

    @classmethod
    def actor_label(cls, world_id: str, role: str, index: int) -> str:
        return f"{cls.world_actor_prefix(world_id)}{ROLE_LABEL_PART.get(role, role.title())}_{index}"
