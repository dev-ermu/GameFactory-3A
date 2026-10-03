"""Backend contracts for engine-specific asset pipeline plugins."""

from typing import Protocol

from .types import AssetQuery, ImportRequest, ValidationResult


class AssetImportBackend(Protocol):
    engine: str

    def import_asset(self, request: ImportRequest) -> dict:
        ...


class AssetQueryBackend(Protocol):
    engine: str

    def list_assets(self, query: AssetQuery) -> list[dict]:
        ...

    def list_all_groups(self, root_path: str = "") -> dict:
        ...


class AssetValidationBackend(Protocol):
    engine: str

    def validate_asset(self, request: ImportRequest) -> ValidationResult:
        ...


class AssetBackend(AssetImportBackend, AssetQueryBackend, AssetValidationBackend, Protocol):
    engine: str

    def default_destination(self, asset_type: str) -> str:
        ...



    def list_all_groups(self, root_path: str = "") -> dict:
        ...


class AssetBackendProvider(Protocol):
    engine: str

    def create(self) -> AssetBackend:
        ...
