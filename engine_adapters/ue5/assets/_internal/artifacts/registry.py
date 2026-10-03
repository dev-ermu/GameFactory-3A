"""JSON-backed artifact registry."""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from engine_adapters.ue5.config import UEClientConfig

from .models import ArtifactRecord, normalize_backend_path


class ArtifactRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(
            path
            or UEClientConfig.resolve().artifact_registry_path
        )

    def _read(self) -> list[ArtifactRecord]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            items = data.get("artifacts", [])
        else:
            items = data
        if not isinstance(items, list):
            return []
        return [ArtifactRecord.from_dict(item) for item in items if isinstance(item, dict)]

    def _write(self, records: list[ArtifactRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"artifacts": [record.to_dict() for record in records]}
        fd, temp_path = tempfile.mkstemp(prefix=".artifacts.", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(temp_path).replace(self.path)
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass

    def upsert(self, record: ArtifactRecord) -> ArtifactRecord:
        self.upsert_many([record])
        return record

    def upsert_many(self, records: list[ArtifactRecord]) -> list[ArtifactRecord]:
        existing = {record.artifact_id: record for record in self._read() if record.artifact_id}
        for record in records:
            if record.artifact_id:
                for artifact_id, current in list(existing.items()):
                    same_backend_path = (
                        current.backend == record.backend
                        and normalize_backend_path(current.backend_path) == normalize_backend_path(record.backend_path)
                    )
                    if same_backend_path and artifact_id != record.artifact_id:
                        existing.pop(artifact_id, None)
                existing[record.artifact_id] = record
        ordered = sorted(existing.values(), key=lambda item: (item.type, item.asset_id, item.artifact_id))
        self._write(ordered)
        return records

    def get(self, artifact_id: str) -> Optional[ArtifactRecord]:
        artifact_id = (artifact_id or "").strip()
        if not artifact_id:
            return None
        for record in self._read():
            if record.artifact_id == artifact_id:
                return record
        return None

    def list(
        self,
        type: str | None = None,
        category: str | None = None,
        spawnable: bool | None = None,
        backend: str | None = None,
    ) -> list[ArtifactRecord]:
        records = self._read()
        if type:
            records = [record for record in records if record.type == type]
        if category:
            records = [record for record in records if record.category == category]
        if spawnable is not None:
            records = [record for record in records if record.spawnable is spawnable]
        if backend:
            records = [record for record in records if record.backend == backend]
        return records

    def find_by_backend_path(self, backend: str, backend_path: str) -> Optional[ArtifactRecord]:
        backend = (backend or "").strip()
        backend_path = normalize_backend_path(backend_path)
        if not backend or not backend_path:
            return None
        for record in self._read():
            if record.backend == backend and normalize_backend_path(record.backend_path) == backend_path:
                return record
        return None
