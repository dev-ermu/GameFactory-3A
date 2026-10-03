"""
engine_adapters/blender/runtime/session/world_session.py

Participants, controllers, and the bindings between a controller and the thing
it drives.

Three ideas kept apart on purpose:

- a **participant** is a person or agent connected to the world;
- a **controller** is one input source they own — a human at a keyboard and a
  headless policy are both controllers, and one participant may hold several;
- a **binding** says which entity a controller drives, under what `ControlMode`.

Collapsing them is what makes a multiplayer session hard to change later; keeping
them apart is what lets an agent and a human share one character (`ASSISTED`) or
a spectator join with no entity at all.

No `bpy` here — pure bookkeeping, exercisable without Blender installed.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class ControlMode(Enum):
    #: One controller, nobody else gets a say.
    EXCLUSIVE = "exclusive"
    #: Several controllers; the highest `priority` wins each frame.
    PRIORITY = "priority"
    #: Inputs are blended rather than arbitrated — human plus assist policy.
    ASSISTED = "assisted"
    #: Bound for the camera feed only; input is ignored.
    OBSERVING = "observing"


@dataclass
class Participant:
    participant_id: str
    user_id: str = ""
    world_id: str = ""
    entity_id: str = ""
    online: bool = True


@dataclass
class Controller:
    controller_id: str
    participant_id: str = ""
    world_id: str = ""
    #: `human` or `agent`. The runtime treats them alike; the distinction is
    #: for whoever is reading the session snapshot.
    kind: str = "human"
    online: bool = True


@dataclass
class ControlBinding:
    controller_id: str
    entity_id: str
    world_id: str = ""
    mode: ControlMode = ControlMode.EXCLUSIVE
    priority: int = 0
    active: bool = True


@dataclass
class InputState:
    """One controller's input for one tick."""

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
    #: Sender's counter. Lets a receiver drop packets that arrived out of order.
    sequence: int = 0
    timestamp_seconds: float = 0.0


class WorldSessionManager:
    def __init__(self, world_id: str = "world_001") -> None:
        self.world_id = world_id
        self.participants: Dict[str, Participant] = {}
        self.controllers: Dict[str, Controller] = {}
        self.bindings: Dict[str, ControlBinding] = {}
        #: Newest input per controller. Only the last one per tick matters, so
        #: this is a slot rather than a queue — late packets replace, not pile up.
        self.latest_inputs: Dict[str, InputState] = {}

    # ── Registry ──────────────────────────────────────────────────────────────

    def register_participant(self, participant_id: str,
                             user_id: str = "") -> Participant:
        participant = Participant(participant_id=participant_id, user_id=user_id,
                                  world_id=self.world_id)
        self.participants[participant_id] = participant
        return participant

    def mark_participant_offline(self, participant_id: str) -> None:
        participant = self.participants.get(participant_id)
        if participant is not None:
            participant.online = False

    def create_controller(self, participant_id: str, controller_id: str,
                          kind: str = "human") -> Controller:
        controller = Controller(controller_id=controller_id,
                                participant_id=participant_id,
                                world_id=self.world_id, kind=kind)
        self.controllers[controller_id] = controller
        return controller

    def bind_controller_to_entity(self, controller_id: str, entity_id: str,
                                  mode: ControlMode = ControlMode.EXCLUSIVE,
                                  priority: int = 0) -> bool:
        self.bindings[controller_id] = ControlBinding(
            controller_id=controller_id, entity_id=entity_id,
            world_id=self.world_id, mode=mode, priority=priority)
        return True

    def unbind_controller(self, controller_id: str) -> bool:
        return self.bindings.pop(controller_id, None) is not None

    # ── Lifecycle commands ────────────────────────────────────────────────────

    def join_world(self, payload: dict) -> bool:
        participant_id = payload.get("participant_id", "")
        if not participant_id:
            print("[session] join_world needs a participant_id")
            return False
        self.register_participant(participant_id, payload.get("user_id", ""))

        controller_id = payload.get("controller_id", f"ctrl_{participant_id}")
        self.create_controller(participant_id, controller_id,
                               payload.get("kind", "human"))

        entity_id = payload.get("entity_id", "")
        if entity_id:
            self.participants[participant_id].entity_id = entity_id
            self.bind_controller_to_entity(controller_id, entity_id)
        return True

    def leave_world(self, payload: dict) -> bool:
        participant_id = payload.get("participant_id", "")
        self.mark_participant_offline(participant_id)
        for controller_id in list(self.bindings):
            controller = self.controllers.get(controller_id)
            if controller is not None and controller.participant_id == participant_id:
                self.unbind_controller(controller_id)
        return True

    def destroy_session(self, payload: dict) -> bool:
        self.participants.clear()
        self.controllers.clear()
        self.bindings.clear()
        self.latest_inputs.clear()
        return True

    # ── Input routing ─────────────────────────────────────────────────────────

    def enqueue_input(self, state: InputState) -> bool:
        previous = self.latest_inputs.get(state.controller_id)
        if previous is not None and state.sequence < previous.sequence:
            return False  # arrived late; the newer input already won
        self.latest_inputs[state.controller_id] = state
        return True

    def consume_latest_inputs(self, players) -> int:
        """
        Push each controller's newest input onto the entity it is bound to.

        Returns how many players were driven. Call once per tick, before
        `PlayerManager.tick`, so movement integrates this frame's input.
        """
        applied = 0
        for controller_id, state in list(self.latest_inputs.items()):
            binding = self.bindings.get(controller_id)
            if binding is None or not binding.active:
                continue
            if binding.mode is ControlMode.OBSERVING:
                continue
            player = players.get(binding.entity_id)
            if player is None:
                continue
            player.apply_input(state.move_x, state.move_y, state.run,
                               state.jump, state.yaw, state.pitch)
            applied += 1
        self.latest_inputs.clear()
        return applied

    def snapshot(self) -> List[dict]:
        """The session as plain data, for logging or for a debug endpoint."""
        return [
            {
                "participant_id": p.participant_id,
                "user_id": p.user_id,
                "entity_id": p.entity_id,
                "online": p.online,
            }
            for p in self.participants.values()
        ]
