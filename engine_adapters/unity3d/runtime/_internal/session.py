"""In-memory A3Game runtime session core.

This service tracks participants,
controllers, control bindings, persistent entities, and input queues, but it
does not own authoritative world physics. Unity remains the source of truth for
actual GameObject transforms once the runtime bridge is connected.
"""

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from queue import Empty, Queue
from threading import RLock, Thread
from time import time
from typing import Any, Deque, Optional, Protocol
from uuid import uuid4


DEFAULT_WORLD_ID = "world_001"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class RuntimeParticipantInfo:
    participant_id: str
    world_id: str
    user_id: str = ""
    avatar_asset_path: str = ""
    idle_animation_path: str = ""
    move_animation_path: str = ""
    unity_input_host: str = ""
    unity_input_port: int = 0
    entity_id: str = ""
    online: bool = True
    created_at: float = field(default_factory=time)
    last_seen_at: float = field(default_factory=time)


@dataclass
class RuntimeControllerState:
    controller_id: str
    participant_id: str
    world_id: str
    kind: str = "human"
    unity_input_host: str = ""
    unity_input_port: int = 0
    online: bool = True
    created_at: float = field(default_factory=time)
    last_seen_at: float = field(default_factory=time)


@dataclass
class RuntimeControlBinding:
    controller_id: str
    entity_id: str
    world_id: str
    mode: str = "exclusive"
    priority: int = 0
    active: bool = True
    bound_at: float = field(default_factory=time)


@dataclass
class RuntimeEntityState:
    entity_id: str
    world_id: str
    avatar_asset_path: str = ""
    idle_animation_path: str = ""
    move_animation_path: str = ""
    actor_label: str = ""
    spawn_transform: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    persistent: bool = True
    locomotion_state: str = "idle"
    motion_state: str = "idle"
    position: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    rotation: dict[str, float] = field(default_factory=lambda: {"pitch": 0.0, "yaw": 0.0, "roll": 0.0})
    created_at: float = field(default_factory=time)
    last_input_at: float = 0.0


@dataclass
class RuntimeInputState:
    world_id: str
    participant_id: str
    controller_id: str
    entity_id: str
    move_x: float = 0.0
    move_y: float = 0.0
    run: bool = False
    jump: bool = False
    yaw: float = 0.0
    pitch: float = 0.0
    unity_input_host: str = ""
    unity_input_port: int = 0
    seq: int = 0
    ts: float = field(default_factory=time)


class RuntimeSessionError(RuntimeError):
    """Raised when runtime session state is inconsistent or unauthorized."""


class RuntimeUnityBridge(Protocol):
    def ensure_entity(self, **kwargs: Any) -> dict[str, Any]:
        ...

    def apply_input(self, **kwargs: Any) -> dict[str, Any]:
        ...

    def mark_participant_offline(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        ...

    def destroy_entity(self, **kwargs: Any) -> dict[str, Any]:
        ...


class RuntimeSessionService:
    """Engine-adapter session state for generic controllable entities."""

    def __init__(
        self,
        default_world_id: str = DEFAULT_WORLD_ID,
        input_queue_size: int = 64,
        unity_bridge: Optional[RuntimeUnityBridge] = None,
    ) -> None:
        self.default_world_id = default_world_id
        self.input_queue_size = input_queue_size
        self.unity_bridge = unity_bridge
        self._lock = RLock()
        self._bridge_queue: Queue[tuple[str, dict[str, Any]]] = Queue()
        self._bridge_worker_started = False
        self._coalesced_bridge_jobs: dict[
            str,
            tuple[str, dict[str, Any]],
        ] = {}
        self.participants: dict[str, RuntimeParticipantInfo] = {}
        self.controllers: dict[str, RuntimeControllerState] = {}
        self.entities: dict[str, RuntimeEntityState] = {}
        self.bindings: dict[str, RuntimeControlBinding] = {}
        self.input_queues: dict[str, Deque[RuntimeInputState]] = defaultdict(lambda: deque(maxlen=self.input_queue_size))
        self.latest_inputs: dict[str, RuntimeInputState] = {}
        self.bridge_errors: dict[str, str] = {}
        self.bridge_status: dict[str, dict[str, Any]] = {}
        self._bridge_retry_after: dict[str, float] = {}

    def join(
        self,
        *,
        world_id: Optional[str] = None,
        participant_id: str = "",
        user_id: str = "",
        avatar_asset_path: str = "",
        idle_animation_path: str = "",
        move_animation_path: str = "",
        controller_kind: str = "human",
        unity_input_host: str = "",
        unity_input_port: int = 0,
        transform: Optional[dict[str, Any]] = None,
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create or reconnect a participant and bind a fresh controller to its persistent entity."""

        now = time()
        resolved_world_id = world_id or self.default_world_id
        with self._lock:
            participant = self.participants.get(participant_id) if participant_id else None
            if participant is None:
                participant_id = participant_id or _new_id("p")
                entity_id = _new_id("ent")
                participant = RuntimeParticipantInfo(
                    participant_id=participant_id,
                    world_id=resolved_world_id,
                    user_id=user_id,
                    avatar_asset_path=avatar_asset_path,
                    idle_animation_path=idle_animation_path,
                    move_animation_path=move_animation_path,
                    unity_input_host=unity_input_host,
                    unity_input_port=unity_input_port,
                    entity_id=entity_id,
                    online=True,
                    created_at=now,
                    last_seen_at=now,
                )
                self.participants[participant_id] = participant
                self.entities[entity_id] = RuntimeEntityState(
                    entity_id=entity_id,
                    world_id=resolved_world_id,
                    avatar_asset_path=avatar_asset_path,
                    idle_animation_path=idle_animation_path,
                    move_animation_path=move_animation_path,
                    actor_label=f"A3Game_Entity_{entity_id}",
                    spawn_transform=dict(transform or {}),
                    parameters=dict(parameters or {}),
                    persistent=True,
                    created_at=now,
                )
            else:
                participant.online = True
                participant.last_seen_at = now
                if user_id:
                    participant.user_id = user_id
                if avatar_asset_path:
                    participant.avatar_asset_path = avatar_asset_path
                if idle_animation_path:
                    participant.idle_animation_path = idle_animation_path
                if move_animation_path:
                    participant.move_animation_path = move_animation_path
                if unity_input_host:
                    participant.unity_input_host = unity_input_host
                if unity_input_port:
                    participant.unity_input_port = int(unity_input_port)
                if not participant.entity_id or participant.entity_id not in self.entities:
                    participant.entity_id = _new_id("ent")
                    self.entities[participant.entity_id] = RuntimeEntityState(
                        entity_id=participant.entity_id,
                        world_id=participant.world_id,
                        avatar_asset_path=participant.avatar_asset_path,
                        idle_animation_path=participant.idle_animation_path,
                        move_animation_path=participant.move_animation_path,
                        actor_label=(
                            f"A3Game_Entity_"
                            f"{participant.entity_id}"
                        ),
                        spawn_transform=dict(transform or {}),
                        parameters=dict(parameters or {}),
                        persistent=True,
                        created_at=now,
                    )
                if avatar_asset_path:
                    self.entities[participant.entity_id].avatar_asset_path = avatar_asset_path
                if idle_animation_path:
                    self.entities[participant.entity_id].idle_animation_path = idle_animation_path
                if move_animation_path:
                    self.entities[participant.entity_id].move_animation_path = move_animation_path
                if transform is not None:
                    self.entities[
                        participant.entity_id
                    ].spawn_transform = dict(transform)
                if parameters is not None:
                    self.entities[
                        participant.entity_id
                    ].parameters = dict(parameters)

            controller_id = _new_id("ctrl")
            controller = RuntimeControllerState(
                controller_id=controller_id,
                participant_id=participant.participant_id,
                world_id=participant.world_id,
                kind=controller_kind or "human",
                unity_input_host=unity_input_host or participant.unity_input_host,
                unity_input_port=int(unity_input_port or participant.unity_input_port or 0),
                online=True,
                created_at=now,
                last_seen_at=now,
            )
            self.controllers[controller_id] = controller

            # Reconnect semantics: old controllers go offline; the persistent entity remains.
            for old_controller in self.controllers.values():
                if old_controller.participant_id == participant.participant_id and old_controller.controller_id != controller_id:
                    old_controller.online = False
                    old_binding = self.bindings.get(old_controller.controller_id)
                    if old_binding is not None:
                        old_binding.active = False

            binding = RuntimeControlBinding(
                controller_id=controller_id,
                entity_id=participant.entity_id,
                world_id=participant.world_id,
                mode="exclusive",
                active=True,
                bound_at=now,
            )
            self.bindings[controller_id] = binding

            entity = self.entities[participant.entity_id]
            runtime_parameters = dict(entity.parameters)
            for key, value in (
                ("avatar_asset_path", entity.avatar_asset_path),
                (
                    "idle_animation_path",
                    entity.idle_animation_path,
                ),
                (
                    "move_animation_path",
                    entity.move_animation_path,
                ),
                ("actor_label", entity.actor_label),
            ):
                if value and key not in runtime_parameters:
                    runtime_parameters[key] = value

            if self.unity_bridge:
                self._enqueue_bridge_job(
                    "ensure_entity",
                    {
                        "world_id": participant.world_id,
                        "participant_id": participant.participant_id,
                        "user_id": participant.user_id,
                        "controller_id": controller.controller_id,
                        "kind": controller.kind,
                        "entity_id": participant.entity_id,
                        "mode": binding.mode,
                        "priority": binding.priority,
                        "transform": entity.spawn_transform,
                        "avatar_asset_path": entity.avatar_asset_path,
                        "idle_animation_path": entity.idle_animation_path,
                        "move_animation_path": entity.move_animation_path,
                        "actor_label": entity.actor_label,
                        "parameters": runtime_parameters,
                        "unity_input_host": participant.unity_input_host,
                        "unity_input_port": participant.unity_input_port,
                    },
                )

            return {
                "ok": True,
                "world_id": participant.world_id,
                "participant_id": participant.participant_id,
                "controller_id": controller_id,
                "entity_id": participant.entity_id,
                "view_mode": "shared",
                "entity_persistent": True,
                "unity_input": {
                    "host": controller.unity_input_host,
                    "port": controller.unity_input_port,
                },
                "unity_bridge": {
                    "enabled": self.unity_bridge is not None,
                    "queued": self.unity_bridge is not None,
                    "status": self.bridge_status.get(participant.entity_id, {}),
                    "error": self.bridge_errors.get(participant.entity_id, ""),
                },
            }

    def leave(self, *, participant_id: str = "", controller_id: str = "") -> dict[str, Any]:
        """Mark a controller/participant offline without destroying the entity."""

        bridge_payload: Optional[dict[str, Any]] = None
        with self._lock:
            controller = self._resolve_controller(participant_id=participant_id, controller_id=controller_id, required=False)
            if controller is not None:
                controller.online = False
                controller.last_seen_at = time()
                binding = self.bindings.get(controller.controller_id)
                if binding is not None:
                    binding.active = False
                participant_id = controller.participant_id

            participant = self.participants.get(participant_id) if participant_id else None
            if participant is not None:
                participant.online = any(
                    item.online for item in self.controllers.values() if item.participant_id == participant.participant_id
                )
                participant.last_seen_at = time()
                entity_id = participant.entity_id
            else:
                entity_id = ""

            if self.unity_bridge and participant_id:
                bridge_payload = {
                    "participant_id": participant_id,
                    "unity_input_host": (
                        controller.unity_input_host
                        if controller is not None
                        else (
                            participant.unity_input_host
                            if participant is not None
                            else ""
                        )
                    ),
                    "unity_input_port": (
                        controller.unity_input_port
                        if controller is not None
                        else (
                            participant.unity_input_port
                            if participant is not None
                            else 0
                        )
                    ),
                }
            result = {
                "ok": True,
                "participant_id": participant_id,
                "controller_id": controller.controller_id if controller is not None else controller_id,
                "entity_id": entity_id,
                "entity_retained": bool(entity_id and entity_id in self.entities),
            }
        if bridge_payload is not None:
            self._enqueue_bridge_job(
                "mark_participant_offline",
                bridge_payload,
            )
        return result

    def reset_world(self, *, world_id: Optional[str] = None) -> dict[str, Any]:
        """Clear broker state for a world after Unity-side runtime GameObjects are removed."""

        resolved_world_id = world_id or self.default_world_id
        with self._lock:
            participant_ids = [key for key, item in self.participants.items() if item.world_id == resolved_world_id]
            controller_ids = [key for key, item in self.controllers.items() if item.world_id == resolved_world_id]
            entity_ids = [key for key, item in self.entities.items() if item.world_id == resolved_world_id]
            binding_ids = [key for key, item in self.bindings.items() if item.world_id == resolved_world_id]

            for key in participant_ids:
                self.participants.pop(key, None)
            for key in controller_ids:
                self.controllers.pop(key, None)
                self.input_queues.pop(key, None)
                self.latest_inputs.pop(key, None)
            for key in entity_ids:
                self.entities.pop(key, None)
                self.bridge_errors.pop(key, None)
                self.bridge_status.pop(key, None)
                self._bridge_retry_after.pop(key, None)
            for key in binding_ids:
                self.bindings.pop(key, None)

            return {
                "ok": True,
                "world_id": resolved_world_id,
                "removed_participants": len(participant_ids),
                "removed_controllers": len(controller_ids),
                "removed_entities": len(entity_ids),
                "removed_bindings": len(binding_ids),
            }

    def clear_entity(
        self,
        *,
        participant_id: str = "",
        controller_id: str = "",
        entity_id: str = "",
        destroy_actor: bool = True,
    ) -> dict[str, Any]:
        """Clear one participant/entity, preserving unrelated runtime users."""

        with self._lock:
            controller = self._resolve_controller(participant_id=participant_id, controller_id=controller_id, required=False)
            if controller is not None:
                participant_id = controller.participant_id
                binding = self.bindings.get(controller.controller_id)
                if binding is not None and not entity_id:
                    entity_id = binding.entity_id

            participant = self.participants.get(participant_id) if participant_id else None
            if participant is not None and not entity_id:
                entity_id = participant.entity_id

            entity = self.entities.get(entity_id) if entity_id else None
            actor_label = (
                entity.actor_label
                if entity is not None
                else (
                    f"A3Game_Entity_{entity_id}"
                    if entity_id
                    else ""
                )
            )
            unity_input_host = (
                controller.unity_input_host
                if controller is not None
                else (
                    participant.unity_input_host
                    if participant is not None
                    else ""
                )
            )
            unity_input_port = (
                controller.unity_input_port
                if controller is not None
                else (
                    participant.unity_input_port
                    if participant is not None
                    else 0
                )
            )

            controller_ids = [
                key
                for key, item in self.controllers.items()
                if (participant_id and item.participant_id == participant_id)
                or (key in self.bindings and self.bindings[key].entity_id == entity_id)
            ]
            binding_ids = [key for key, item in self.bindings.items() if item.entity_id == entity_id or key in controller_ids]

            for key in controller_ids:
                self.controllers.pop(key, None)
                self.input_queues.pop(key, None)
                self.latest_inputs.pop(key, None)
            for key in binding_ids:
                self.bindings.pop(key, None)
            if participant_id:
                self.participants.pop(participant_id, None)
            if entity_id:
                self.entities.pop(entity_id, None)
                self.bridge_errors.pop(entity_id, None)
                self.bridge_status.pop(entity_id, None)
                self._bridge_retry_after.pop(entity_id, None)

        bridge_queued = False
        if destroy_actor and self.unity_bridge and entity_id:
            self._enqueue_bridge_job(
                "destroy_entity",
                {
                    "entity_id": entity_id,
                    "actor_label": actor_label,
                    "destroy_actor": True,
                    "unity_input_host": unity_input_host,
                    "unity_input_port": unity_input_port,
                },
            )
            bridge_queued = True

        return {
            "ok": True,
            "participant_id": participant_id,
            "controller_id": controller.controller_id if controller is not None else controller_id,
            "entity_id": entity_id,
            "removed_controllers": len(controller_ids),
            "removed_bindings": len(binding_ids),
            "removed_participant": bool(participant_id),
            "removed_entity": bool(entity_id),
            "unity_bridge": {"enabled": self.unity_bridge is not None, "queued": bridge_queued},
        }

    def heartbeat(self, *, controller_id: str) -> dict[str, Any]:
        now = time()
        with self._lock:
            controller = self._resolve_controller(controller_id=controller_id)
            controller.online = True
            controller.last_seen_at = now
            participant = self.participants[controller.participant_id]
            participant.online = True
            participant.last_seen_at = now
            return {
                "ok": True,
                "world_id": controller.world_id,
                "participant_id": controller.participant_id,
                "controller_id": controller.controller_id,
                "entity_id": self.bindings.get(controller.controller_id).entity_id if controller.controller_id in self.bindings else "",
            }

    def apply_input(self, input_state: RuntimeInputState) -> dict[str, Any]:
        """Queue latest input state after verifying the controller binding."""

        with self._lock:
            controller = self._resolve_controller(controller_id=input_state.controller_id)
            binding = self.bindings.get(controller.controller_id)
            if binding is None or not binding.active:
                raise RuntimeSessionError(f"Controller is not bound to an active entity: {controller.controller_id}")
            if input_state.participant_id and input_state.participant_id != controller.participant_id:
                raise RuntimeSessionError("Input participant_id does not match controller owner")
            if input_state.entity_id and input_state.entity_id != binding.entity_id:
                raise RuntimeSessionError("Input entity_id does not match active control binding")

            input_state.world_id = input_state.world_id or controller.world_id
            input_state.participant_id = controller.participant_id
            input_state.entity_id = binding.entity_id
            input_state.move_x = max(-1.0, min(1.0, float(input_state.move_x)))
            input_state.move_y = max(-1.0, min(1.0, float(input_state.move_y)))
            input_state.ts = input_state.ts or time()

            self.input_queues[controller.controller_id].append(input_state)
            self.latest_inputs[controller.controller_id] = input_state

            entity = self.entities[binding.entity_id]
            entity.last_input_at = input_state.ts
            entity.rotation["yaw"] = float(input_state.yaw)
            entity.rotation["pitch"] = float(input_state.pitch)
            entity.locomotion_state = self._locomotion_from_input(input_state)
            entity.motion_state = entity.locomotion_state
            if self.unity_bridge:
                self._enqueue_bridge_job(
                    "apply_input",
                    {
                        "entity_id": input_state.entity_id,
                        "world_id": input_state.world_id,
                        "participant_id": input_state.participant_id,
                        "controller_id": input_state.controller_id,
                        "avatar_asset_path": entity.avatar_asset_path,
                        "idle_animation_path": entity.idle_animation_path,
                        "move_animation_path": entity.move_animation_path,
                        "move_x": input_state.move_x,
                        "move_y": input_state.move_y,
                        "run": input_state.run,
                        "jump": input_state.jump,
                        "yaw": input_state.yaw,
                        "pitch": input_state.pitch,
                        "seq": input_state.seq,
                        "ts": input_state.ts,
                        "actor_label": entity.actor_label,
                        "unity_input_host": input_state.unity_input_host or controller.unity_input_host,
                        "unity_input_port": input_state.unity_input_port or controller.unity_input_port,
                    },
                    coalesce=True,
                )

            return {
                "ok": True,
                "world_id": input_state.world_id,
                "participant_id": input_state.participant_id,
                "controller_id": input_state.controller_id,
                "entity_id": input_state.entity_id,
                "queued": len(self.input_queues[controller.controller_id]),
                "locomotion_state": entity.locomotion_state,
                "seq": input_state.seq,
                "unity_bridge": {
                    "enabled": self.unity_bridge is not None,
                    "queued": self.unity_bridge is not None,
                    "status": self.bridge_status.get(input_state.entity_id, {}),
                    "error": self.bridge_errors.get(input_state.entity_id, ""),
                },
            }

    def consume_latest_inputs(self, *, world_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Return and clear the latest input for each active controller."""

        resolved_world_id = world_id or self.default_world_id
        with self._lock:
            consumed: list[dict[str, Any]] = []
            for controller_id, latest in list(self.latest_inputs.items()):
                if latest.world_id != resolved_world_id:
                    continue
                binding = self.bindings.get(controller_id)
                if binding is None or not binding.active:
                    continue
                consumed.append(asdict(latest))
                self.input_queues[controller_id].clear()
                self.latest_inputs.pop(controller_id, None)
            return consumed

    def world_snapshot(self, *, world_id: Optional[str] = None) -> dict[str, Any]:
        resolved_world_id = world_id or self.default_world_id
        with self._lock:
            participants = [
                asdict(item)
                for item in self.participants.values()
                if item.world_id == resolved_world_id
            ]
            controllers = [
                asdict(item)
                for item in self.controllers.values()
                if item.world_id == resolved_world_id
            ]
            bindings = [
                asdict(item)
                for item in self.bindings.values()
                if item.world_id == resolved_world_id
            ]
            entities = [
                asdict(item)
                for item in self.entities.values()
                if item.world_id == resolved_world_id
            ]
            return {
                "ok": True,
                "world_id": resolved_world_id,
                "participants": participants,
                "controllers": controllers,
                "bindings": bindings,
                "entities": entities,
                "avatars": entities,
                "bridge_errors": dict(self.bridge_errors),
                "bridge_status": dict(self.bridge_status),
                "bridge_queue_size": self._bridge_queue.qsize() if self.unity_bridge is not None else 0,
                "server_time": time(),
            }

    def _start_bridge_worker(self) -> None:
        if self._bridge_worker_started:
            return
        self._bridge_worker_started = True
        worker = Thread(
            target=self._bridge_worker_loop,
            name="a3game-runtime-unity-bridge",
            daemon=True,
        )
        worker.start()

    def _enqueue_bridge_job(self, job_type: str, payload: dict[str, Any], coalesce: bool = False) -> None:
        if self.unity_bridge is None:
            return
        self._start_bridge_worker()
        entity_id = str(payload.get("entity_id", ""))
        with self._lock:
            if entity_id:
                current_status = self.bridge_status.get(entity_id, {})
                retry_after = self._bridge_retry_after.get(entity_id, 0.0)
                if coalesce and retry_after > time():
                    current_status["state"] = "cooldown"
                    current_status["cooldown_until"] = retry_after
                    current_status["coalesced_job"] = job_type
                    self.bridge_status[entity_id] = current_status
                    return
                if coalesce and current_status.get("state") in {"queued", "running"}:
                    if current_status.get("job") == job_type:
                        self._coalesced_bridge_jobs[entity_id] = (
                            job_type,
                            payload,
                        )
                        current_status["coalesced_at"] = time()
                        current_status["coalesced_job"] = job_type
                        self.bridge_status[entity_id] = current_status
                        return
                self.bridge_status[entity_id] = {
                    "state": "queued",
                    "job": job_type,
                    "queued_at": time(),
                    "queue_size": self._bridge_queue.qsize() + 1,
                }
        self._bridge_queue.put((job_type, payload))

    def _bridge_worker_loop(self) -> None:
        while True:
            try:
                job_type, payload = self._bridge_queue.get(timeout=0.5)
            except Empty:
                continue
            entity_id = str(payload.get("entity_id", ""))
            try:
                with self._lock:
                    if entity_id:
                        self.bridge_status[entity_id] = {"state": "running", "job": job_type, "started_at": time()}
                if self.unity_bridge is None:
                    continue
                if job_type == "ensure_entity":
                    result = self.unity_bridge.ensure_entity(**payload)
                    self._apply_bridge_result(entity_id, result, job_type)
                elif job_type == "apply_input":
                    result = self.unity_bridge.apply_input(**payload)
                    self._apply_bridge_result(entity_id, result, job_type)
                elif job_type == "mark_participant_offline":
                    result = (
                        self.unity_bridge.mark_participant_offline(
                            **payload
                        )
                    )
                    self._apply_bridge_result(
                        entity_id,
                        result,
                        job_type,
                    )
                elif job_type == "destroy_entity":
                    result = self.unity_bridge.destroy_entity(**payload)
                    self._apply_bridge_result(entity_id, result, job_type)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    if entity_id:
                        self.bridge_errors[entity_id] = message
                        self._bridge_retry_after[entity_id] = time() + 3.0
                        self.bridge_status[entity_id] = {"state": "error", "job": job_type, "error": message, "updated_at": time()}
            finally:
                replacement = None
                with self._lock:
                    if entity_id:
                        replacement = (
                            self._coalesced_bridge_jobs.pop(
                                entity_id,
                                None,
                            )
                        )
                if replacement is not None:
                    self._enqueue_bridge_job(
                        replacement[0],
                        replacement[1],
                    )
                self._bridge_queue.task_done()

    def _apply_bridge_result(self, entity_id: str, result: Optional[dict[str, Any]], job_type: str) -> None:
        with self._lock:
            if entity_id and result and result.get("actor_label") and entity_id in self.entities:
                self.entities[entity_id].actor_label = str(result["actor_label"])
            if entity_id and result and result.get("location") and entity_id in self.entities:
                location = result["location"]
                entity = self.entities[entity_id]
                entity.position = {
                    "x": float(location.get("x", entity.position["x"])),
                    "y": float(location.get("y", entity.position["y"])),
                    "z": float(location.get("z", entity.position["z"])),
                }
            if entity_id and result and result.get("rotation") and entity_id in self.entities:
                rotation = result["rotation"]
                entity = self.entities[entity_id]
                entity.rotation = {
                    "pitch": float(rotation.get("pitch", entity.rotation["pitch"])),
                    "yaw": float(rotation.get("yaw", entity.rotation["yaw"])),
                    "roll": float(rotation.get("roll", entity.rotation["roll"])),
                }
            if entity_id:
                if result and result.get("ok"):
                    self.bridge_errors.pop(entity_id, None)
                    self._bridge_retry_after.pop(entity_id, None)
                self.bridge_status[entity_id] = {
                    "state": "ok" if result and result.get("ok") else "done",
                    "job": job_type,
                    "result": result,
                    "updated_at": time(),
                }

    def _resolve_controller(
        self,
        *,
        participant_id: str = "",
        controller_id: str = "",
        required: bool = True,
    ) -> Optional[RuntimeControllerState]:
        if controller_id:
            controller = self.controllers.get(controller_id)
            if controller is not None:
                return controller
            if required:
                raise RuntimeSessionError(f"Unknown controller_id: {controller_id}")
            return None

        if participant_id:
            candidates = [
                controller
                for controller in self.controllers.values()
                if controller.participant_id == participant_id and controller.online
            ]
            if candidates:
                candidates.sort(key=lambda item: item.last_seen_at, reverse=True)
                return candidates[0]

        if required:
            raise RuntimeSessionError("Missing controller_id or online participant_id")
        return None

    @staticmethod
    def _locomotion_from_input(input_state: RuntimeInputState) -> str:
        moving = abs(input_state.move_x) > 0.001 or abs(input_state.move_y) > 0.001
        if input_state.jump:
            return "jump"
        if moving and input_state.run:
            return "run"
        if moving:
            return "walk"
        return "idle"
