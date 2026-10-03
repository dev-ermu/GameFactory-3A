"""Private runtime session implementation for the three.js adapter."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..._internal.transport import DevServerClient


CONTROL_MODES = ("exclusive", "priority", "assisted", "observing")
LOCOMOTION_STATES = ("idle", "walk", "run", "jump")


def _now() -> float:
    return time.time()


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class RuntimeInputState:
    """Normalized control input frame shared with the web runtime."""

    world_id: str = ""
    participant_id: str = ""
    controller_id: str = ""
    entity_id: str = ""
    move_x: float = 0.0
    move_y: float = 0.0
    run: bool = False
    jump: bool = False
    yaw: float = 0.0
    pitch: float = 0.0
    seq: int = 0
    timestamp_seconds: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worldId": self.world_id,
            "participantId": self.participant_id,
            "controllerId": self.controller_id,
            "entityId": self.entity_id,
            "moveX": float(self.move_x),
            "moveY": float(self.move_y),
            "run": bool(self.run),
            "jump": bool(self.jump),
            "yaw": float(self.yaw),
            "pitch": float(self.pitch),
            "sequence": int(self.seq),
            "timestampSeconds": float(self.timestamp_seconds),
        }


class WebRuntimeBridge:
    """Forward generic session commands to a running web runtime."""

    def __init__(self, transport: DevServerClient) -> None:
        self._transport = transport

    def available(self, *, timeout: float = 2.0) -> bool:
        return self._transport.check_runtime_channel(timeout=timeout)

    def send(
        self,
        command: str,
        payload: dict[str, Any],
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        return self._transport.call_runtime(
            command,
            payload,
            timeout=timeout,
        )


class RuntimeSessionService:
    """Own generic participant, controller, entity, and binding state."""

    def __init__(
        self,
        *,
        bridge: WebRuntimeBridge | None = None,
        default_world_id: str = "world_001",
    ) -> None:
        self._bridge = bridge
        self._default_world_id = default_world_id
        self._participants: dict[str, dict[str, Any]] = {}
        self._controllers: dict[str, dict[str, Any]] = {}
        self._bindings: dict[str, dict[str, Any]] = {}
        self._entities: dict[str, dict[str, Any]] = {}
        self._latest_input: dict[str, dict[str, Any]] = {}

    def _dispatch(
        self,
        command: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._bridge is None:
            return {"delivered": False, "reason": "no_bridge"}
        try:
            response = self._bridge.send(command, payload)
        except Exception as exc:
            return {
                "delivered": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        return {"delivered": True, "response": response}

    def join(
        self,
        *,
        world_id: str | None = None,
        participant_id: str = "",
        user_id: str = "",
        avatar_url: str = "",
        idle_animation: str = "",
        move_animation: str = "",
        controller_kind: str = "human",
        control_mode: str = "exclusive",
        priority: int = 0,
        transform: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_mode = str(control_mode or "exclusive").lower()
        if normalized_mode not in CONTROL_MODES:
            supported = ", ".join(CONTROL_MODES)
            raise ValueError(
                f"control_mode must be one of: {supported}"
            )
        resolved_world = str(
            world_id or self._default_world_id
        ).strip() or self._default_world_id
        resolved_participant = (
            str(participant_id or "").strip()
            or _identifier("participant")
        )
        entity_id = _identifier("entity")
        controller_id = _identifier("controller")

        self._participants[resolved_participant] = {
            "participantId": resolved_participant,
            "worldId": resolved_world,
            "userId": str(user_id or ""),
            "entityId": entity_id,
            "online": True,
            "lastSeenSeconds": _now(),
        }
        self._controllers[controller_id] = {
            "controllerId": controller_id,
            "participantId": resolved_participant,
            "worldId": resolved_world,
            "kind": str(controller_kind or "human"),
            "online": True,
            "lastSeenSeconds": _now(),
        }
        self._bindings[controller_id] = {
            "controllerId": controller_id,
            "entityId": entity_id,
            "worldId": resolved_world,
            "mode": normalized_mode,
            "priority": int(priority),
            "active": True,
        }
        self._entities[entity_id] = {
            "entityId": entity_id,
            "worldId": resolved_world,
            "participantId": resolved_participant,
            "avatarUrl": str(avatar_url or ""),
            "idleAnimation": str(idle_animation or ""),
            "moveAnimation": str(move_animation or ""),
            "transform": dict(transform or {}),
            "parameters": dict(parameters or {}),
            "locomotionState": "idle",
            "motionState": "idle",
            "persistent": True,
            "lastInputTimeSeconds": 0.0,
        }

        spawn_request = {
            "worldId": resolved_world,
            "participantId": resolved_participant,
            "entityId": entity_id,
            "transform": dict(transform or {}),
            "parameters": {
                **dict(parameters or {}),
                "avatarUrl": str(avatar_url or ""),
                "idleAnimation": str(idle_animation or ""),
                "moveAnimation": str(move_animation or ""),
            },
        }
        delivery = self._dispatch(
            "sync_session",
            {
                "participant": self._participants[
                    resolved_participant
                ],
                "controller": self._controllers[controller_id],
                "binding": self._bindings[controller_id],
                "spawnRequest": spawn_request,
            },
        )
        return {
            "world_id": resolved_world,
            "participant_id": resolved_participant,
            "controller_id": controller_id,
            "entity_id": entity_id,
            "control_mode": normalized_mode,
            "spawn_request": spawn_request,
            "runtime_delivery": delivery,
        }

    def leave(
        self,
        *,
        participant_id: str = "",
        controller_id: str = "",
    ) -> dict[str, Any]:
        removed_controllers = []
        resolved_participant = str(participant_id or "").strip()
        resolved_controller = str(controller_id or "").strip()
        if resolved_controller:
            removed_controllers = [resolved_controller]
        elif resolved_participant:
            removed_controllers = [
                key
                for key, value in self._controllers.items()
                if value.get("participantId") == resolved_participant
            ]
        else:
            raise ValueError(
                "leave requires participant_id or controller_id"
            )
        for key in removed_controllers:
            self._controllers.pop(key, None)
            self._bindings.pop(key, None)
            self._latest_input.pop(key, None)
        if resolved_participant:
            participant = self._participants.get(
                resolved_participant
            )
            if participant is not None:
                participant["online"] = False
        delivery = self._dispatch(
            "leave_session",
            {
                "participantId": resolved_participant,
                "controllerIds": removed_controllers,
            },
        )
        return {
            "participant_id": resolved_participant,
            "removed_controllers": removed_controllers,
            "runtime_delivery": delivery,
        }

    def heartbeat(self, *, controller_id: str) -> dict[str, Any]:
        controller = self._controllers.get(str(controller_id))
        if controller is None:
            raise ValueError(
                f"Unknown controller_id: {controller_id}"
            )
        controller["lastSeenSeconds"] = _now()
        controller["online"] = True
        participant = self._participants.get(
            str(controller.get("participantId") or "")
        )
        if participant is not None:
            participant["lastSeenSeconds"] = _now()
            participant["online"] = True
        return {
            "controller_id": str(controller_id),
            "last_seen_seconds": controller["lastSeenSeconds"],
        }

    def apply_input(
        self,
        input_state: RuntimeInputState,
    ) -> dict[str, Any]:
        controller_id = str(input_state.controller_id or "").strip()
        binding = self._bindings.get(controller_id)
        if binding is None:
            raise ValueError(
                f"Controller is not bound to an entity: "
                f"{controller_id}"
            )
        entity_id = str(binding.get("entityId") or "")
        payload = {
            **input_state.to_dict(),
            "worldId": str(binding.get("worldId") or ""),
            "entityId": entity_id,
        }
        self._latest_input[controller_id] = payload
        entity = self._entities.get(entity_id)
        if entity is not None:
            moving = (
                abs(float(input_state.move_x)) > 1e-3
                or abs(float(input_state.move_y)) > 1e-3
            )
            if input_state.jump:
                state = "jump"
            elif moving and input_state.run:
                state = "run"
            elif moving:
                state = "walk"
            else:
                state = "idle"
            entity["locomotionState"] = state
            entity["motionState"] = state
            entity["lastInputTimeSeconds"] = float(
                input_state.timestamp_seconds
            )
        delivery = self._dispatch("apply_input", payload)
        return {
            "controller_id": controller_id,
            "entity_id": entity_id,
            "input": payload,
            "runtime_delivery": delivery,
        }

    def world_snapshot(
        self,
        *,
        world_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_world = str(
            world_id or self._default_world_id
        ).strip()
        live = self._dispatch(
            "world_snapshot",
            {"worldId": resolved_world},
        )
        entities = [
            dict(value)
            for value in self._entities.values()
            if not resolved_world
            or value.get("worldId") == resolved_world
        ]
        return {
            "world_id": resolved_world,
            "participants": [
                dict(value)
                for value in self._participants.values()
            ],
            "controllers": [
                dict(value)
                for value in self._controllers.values()
            ],
            "bindings": [
                dict(value) for value in self._bindings.values()
            ],
            "entities": entities,
            "runtime_delivery": live,
        }

    def reset_world(
        self,
        *,
        world_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_world = str(
            world_id or self._default_world_id
        ).strip()
        cleared_entities = [
            key
            for key, value in self._entities.items()
            if not resolved_world
            or value.get("worldId") == resolved_world
        ]
        for key in cleared_entities:
            self._entities.pop(key, None)
        cleared_controllers = [
            key
            for key, value in self._controllers.items()
            if not resolved_world
            or value.get("worldId") == resolved_world
        ]
        for key in cleared_controllers:
            self._controllers.pop(key, None)
            self._bindings.pop(key, None)
            self._latest_input.pop(key, None)
        self._participants = {
            key: value
            for key, value in self._participants.items()
            if resolved_world
            and value.get("worldId") != resolved_world
        }
        delivery = self._dispatch(
            "reset_world",
            {"worldId": resolved_world},
        )
        return {
            "world_id": resolved_world,
            "cleared_entities": cleared_entities,
            "cleared_controllers": cleared_controllers,
            "runtime_delivery": delivery,
        }

    def clear_entity(
        self,
        *,
        participant_id: str = "",
        controller_id: str = "",
        entity_id: str = "",
        destroy_object: bool = True,
    ) -> dict[str, Any]:
        resolved_entity = str(entity_id or "").strip()
        if not resolved_entity and controller_id:
            binding = self._bindings.get(str(controller_id))
            resolved_entity = str(
                (binding or {}).get("entityId") or ""
            )
        if not resolved_entity and participant_id:
            participant = self._participants.get(
                str(participant_id)
            )
            resolved_entity = str(
                (participant or {}).get("entityId") or ""
            )
        if not resolved_entity:
            raise ValueError(
                "clear_entity requires entity_id, controller_id, or "
                "participant_id"
            )
        self._entities.pop(resolved_entity, None)
        removed_bindings = [
            key
            for key, value in self._bindings.items()
            if value.get("entityId") == resolved_entity
        ]
        for key in removed_bindings:
            self._bindings.pop(key, None)
            self._latest_input.pop(key, None)
        delivery = self._dispatch(
            "clear_entity",
            {
                "entityId": resolved_entity,
                "destroyObject": bool(destroy_object),
            },
        )
        return {
            "entity_id": resolved_entity,
            "removed_bindings": removed_bindings,
            "destroy_object": bool(destroy_object),
            "runtime_delivery": delivery,
        }


__all__ = [
    "CONTROL_MODES",
    "LOCOMOTION_STATES",
    "RuntimeInputState",
    "RuntimeSessionService",
    "WebRuntimeBridge",
]
