"""JSON file registry for WorldSpec documents."""

import json
from pathlib import Path

from engine_adapters.ue5.config import UEClientConfig

from .specs import WorldSpec, safe_id


class WorldRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(
            root or UEClientConfig.resolve().world_registry_root
        )

    def list_worlds(self) -> list[dict]:
        if not self.root.exists():
            return []
        worlds = []
        for path in sorted(self.root.glob("*.json")):
            try:
                spec = self.load(path.stem)
                worlds.append({"world_id": spec.world_id, "path": str(path), "entity_count": len(spec.entities)})
            except Exception as exc:
                worlds.append({"world_id": path.stem, "path": str(path), "error": f"{type(exc).__name__}: {exc}"})
        return worlds

    def load(self, world_id: str) -> WorldSpec:
        world_id = safe_id(world_id, fallback="")
        if not world_id:
            raise ValueError("world_id is required")
        path = self.root / f"{world_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"找不到 WorldSpec: {path}")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"WorldSpec 必须是 JSON object: {path}")
        return WorldSpec.from_dict(data)
