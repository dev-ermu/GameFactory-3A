"""Contracts for the Editor asset import pipeline."""

from dataclasses import dataclass, field
from time import time
from typing import Any, Protocol
from uuid import uuid4

from engine_adapters.ue5.assets._internal.artifacts.models import ArtifactRecord
from engine_adapters.ue5.assets._internal.types import ImportRequest, ValidationResult


PIPELINE_STATES = (
    "created",
    "inspected",
    "imported",
    "post_processed",
    "validated",
    "built",
    "registered",
    "failed",
)


def new_job_id() -> str:
    return f"imp_{uuid4().hex[:12]}"


@dataclass
class ImportJob:
    """One execution of one source import request."""

    job_id: str
    request: ImportRequest
    state: str = "created"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition(self, state: str) -> None:
        if state not in PIPELINE_STATES:
            raise ValueError(f"Unsupported import pipeline state: {state}")
        self.state = state
        self.updated_at = time()


@dataclass
class ImportResult:
    """Mutable state passed through every import pipeline stage."""

    job: ImportJob
    source: dict[str, Any] = field(default_factory=dict)
    inspect: dict[str, Any] = field(default_factory=dict)
    imported_assets: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    state: str = "created"
    raw_result: dict[str, Any] = field(default_factory=dict)

    def advance(self, state: str) -> None:
        self.job.transition(state)
        self.state = state

    def add_warning(self, message: str) -> None:
        if message and message not in self.warnings:
            self.warnings.append(message)

    def add_error(self, message: str) -> None:
        if message and message not in self.errors:
            self.errors.append(message)

    def to_dict(self) -> dict[str, Any]:
        request = self.job.request
        result = {
            "job": {
                "job_id": self.job.job_id,
                "state": self.job.state,
                "created_at": self.job.created_at,
                "updated_at": self.job.updated_at,
                "metadata": dict(self.job.metadata),
                "request": {
                    "src_path": request.src_path,
                    "asset_type": request.type_key,
                    "dst_path": request.dst_path,
                    "options": dict(request.options),
                },
            },
            "state": self.state,
            "source": dict(self.source),
            "inspect": dict(self.inspect),
            "imported_assets": list(self.imported_assets),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "raw_result": dict(self.raw_result),
            "pipeline_state": self.state,
        }
        # Preserve the existing AssetService/API result shape while exposing
        # the richer pipeline state alongside it.
        result.update(self.raw_result)
        raw_warnings = self.raw_result.get("warnings") or []
        raw_errors = self.raw_result.get("errors") or []
        result["state"] = self.state
        result["pipeline_state"] = self.state
        result["warnings"] = list(dict.fromkeys([*raw_warnings, *self.warnings]))
        result["errors"] = list(dict.fromkeys([*raw_errors, *self.errors]))
        result["artifacts"] = [artifact.to_dict() for artifact in self.artifacts]
        return result


class Inspector(Protocol):
    def inspect(self, result: ImportResult) -> None:
        ...


class Importer(Protocol):
    def import_asset(self, result: ImportResult) -> None:
        ...


class PostProcessor(Protocol):
    def post_process(self, result: ImportResult) -> None:
        ...


class Validator(Protocol):
    def validate(self, result: ImportResult) -> None:
        ...


class ArtifactBuilder(Protocol):
    def build(self, result: ImportResult) -> None:
        ...


class ArtifactRepository(Protocol):
    def save(self, artifacts: list[ArtifactRecord]) -> None:
        ...

    def load(self, artifact_id: str) -> ArtifactRecord | None:
        ...

    def search(self, **filters: Any) -> list[ArtifactRecord]:
        ...

    def delete(self, artifact_id: str) -> bool:
        ...


__all__ = [
    "ArtifactBuilder",
    "ArtifactRepository",
    "ImportJob",
    "ImportResult",
    "Importer",
    "Inspector",
    "PIPELINE_STATES",
    "PostProcessor",
    "ValidationResult",
    "Validator",
    "new_job_id",
]
