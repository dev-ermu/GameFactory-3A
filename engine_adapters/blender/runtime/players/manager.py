"""
engine_adapters/blender/runtime/players/manager.py

Spawn, look up, and remove the characters in the world.

`ensure_player` is idempotent by entity id. Commands arrive over UDP, which
gives no delivery guarantee in either direction — a sender that retries a spawn
because it saw no effect must not end up with two characters.
"""

from math import radians
from typing import Dict, Optional, Tuple

from ..assets.loaders import import_as_root
from .player import Player

#: Prefix on every object this runtime spawns, so `clear_runtime_objects` can
#: tell a character apart from the scene it is standing in.
PLAYER_PREFIX = "player_"


class PlayerManager:
    def __init__(self, spawn_spacing: float = 2.2) -> None:
        self._players: Dict[str, Player] = {}
        #: Metres between characters spawned without an explicit location, so a
        #: multi-character session does not stack everyone at the origin.
        self.spawn_spacing = spawn_spacing
        self._spawn_index = 0

    def __len__(self) -> int:
        return len(self._players)

    def resolve_spawn_location(self, index: int) -> Tuple[float, float, float]:
        return (index * self.spawn_spacing, 0.0, 0.0)

    def ensure_player(self, entity_id: str, asset_path: str,
                      spawn_location: Optional[Tuple[float, float, float]] = None,
                      spawn_rotation: Optional[Tuple[float, float, float]] = None,
                      ) -> Player:
        """
        Spawn a character, or return the one already carrying this entity id.

        `asset_path` is real or `/Library/...`, in any format the shared importer
        table handles. `spawn_location` defaults to the next free slot, and
        `spawn_rotation` is Euler **degrees** — commands are written by hand,
        and radians in JSON are unreadable.
        """
        existing = self._players.get(entity_id)
        if existing is not None:
            return existing

        import bpy  # noqa: PLC0415

        root_name = import_as_root(asset_path, rename_to=f"{PLAYER_PREFIX}{entity_id}")
        obj = bpy.data.objects[root_name]
        location = (spawn_location if spawn_location is not None
                    else self.resolve_spawn_location(self._spawn_index))
        obj.location = location
        obj.rotation_euler = tuple(radians(a) for a in (spawn_rotation or (0.0, 0.0, 0.0)))

        player = Player(entity_id=entity_id, obj_name=root_name)
        self._players[entity_id] = player
        self._spawn_index += 1
        print(f"[players] {entity_id} -> {root_name} at {location}")
        return player

    def destroy_player(self, entity_id: str) -> bool:
        import bpy  # noqa: PLC0415

        player = self._players.pop(entity_id, None)
        if player is None:
            return False
        obj = bpy.data.objects.get(player.obj_name)
        if obj is not None:
            for victim in [obj] + list(obj.children_recursive):
                bpy.data.objects.remove(victim, do_unlink=True)
        return True

    def get(self, entity_id: str) -> Optional[Player]:
        return self._players.get(entity_id)

    def all(self) -> Dict[str, Player]:
        return dict(self._players)

    def tick(self, delta_seconds: float) -> int:
        """
        Advance every character that has fresh input. Returns how many moved.

        Characters with stale input are skipped rather than advanced with zeroed
        input, so a jump already in flight is not cut short by a dropped packet.
        """
        from .movement import advance  # noqa: PLC0415

        moved = 0
        for player in self._players.values():
            if not player.has_recent_input():
                continue
            if not player.exists():
                continue  # object removed out from under us; leave it to destroy_player
            advance(player, delta_seconds)
            moved += 1
        return moved
