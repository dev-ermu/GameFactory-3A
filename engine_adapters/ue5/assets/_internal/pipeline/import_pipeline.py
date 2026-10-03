"""Generic orchestration for Editor import pipelines."""

from abc import ABC, abstractmethod

from engine_adapters.ue5.assets._internal.types import ImportRequest

from .contracts import ImportJob, ImportResult, new_job_id


class ImportPipeline(ABC):
    """Run one consistent lifecycle over one mutable ImportResult."""

    def run(self, request: ImportRequest, job_id: str = "") -> ImportResult:
        job = ImportJob(job_id=job_id or new_job_id(), request=request)
        result = ImportResult(job=job)
        stages = (
            ("inspected", self.inspect),
            ("imported", self.import_asset),
            ("post_processed", self.post_process),
            ("validated", self.validate),
            ("built", self.build),
            ("registered", self.register),
        )
        try:
            for state, stage in stages:
                if result.errors:
                    break
                stage(result)
                if result.errors:
                    break
                result.advance(state)
        except Exception as exc:
            result.add_error(f"{type(exc).__name__}: {exc}")

        if result.errors:
            result.advance("failed")
        return result

    @abstractmethod
    def inspect(self, result: ImportResult) -> None:
        ...

    @abstractmethod
    def import_asset(self, result: ImportResult) -> None:
        ...

    @abstractmethod
    def post_process(self, result: ImportResult) -> None:
        ...

    @abstractmethod
    def validate(self, result: ImportResult) -> None:
        ...

    @abstractmethod
    def build(self, result: ImportResult) -> None:
        ...

    @abstractmethod
    def register(self, result: ImportResult) -> None:
        ...


__all__ = ["ImportPipeline"]
