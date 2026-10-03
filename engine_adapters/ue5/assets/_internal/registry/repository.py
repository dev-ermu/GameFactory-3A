"""Repository adapter over the current JSON-backed ArtifactRegistry."""

from typing import Any

from engine_adapters.ue5.assets._internal.artifacts.models import ArtifactRecord
from engine_adapters.ue5.assets._internal.artifacts.registry import ArtifactRegistry


class ArtifactRegistryRepository:
    def __init__(self, registry: ArtifactRegistry | None = None) -> None:
        self.registry = registry or ArtifactRegistry()

    def save(self, artifacts: list[ArtifactRecord]) -> None:
        if artifacts:
            self.registry.upsert_many(artifacts)

    def load(self, artifact_id: str) -> ArtifactRecord | None:
        return self.registry.get(artifact_id)

    def search(self, **filters: Any) -> list[ArtifactRecord]:
        return self.registry.list(
            type=filters.get("type"),
            category=filters.get("category"),
            spawnable=filters.get("spawnable"),
            backend=filters.get("backend"),
        )

    def delete(self, artifact_id: str) -> bool:
        # Archive/revision semantics are deferred beyond M1.
        return False
