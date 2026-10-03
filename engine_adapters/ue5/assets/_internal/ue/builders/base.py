"""Base class for UE import script builders."""

from abc import ABC, abstractmethod

from engine_adapters.ue5.assets._internal.types import ImportRequest


class ScriptBuilder(ABC):
    @abstractmethod
    def build_import_script(self, request: ImportRequest, dest_path: str) -> str:
        raise NotImplementedError
