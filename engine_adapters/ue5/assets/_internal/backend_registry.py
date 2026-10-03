"""Lazy registry for asset pipeline backends."""

import os
from threading import RLock

from .backend import AssetBackend, AssetBackendProvider


class AssetBackendRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AssetBackendProvider] = {}
        self._instances: dict[str, AssetBackend] = {}
        self._lock = RLock()

    def register(self, name: str, provider: AssetBackendProvider) -> None:
        key = self._normalize_name(name)
        with self._lock:
            self._providers[key] = provider
            self._instances.pop(key, None)

    def get(self, name: str = "") -> AssetBackend:
        key = self._normalize_name(
            name
            or os.environ.get(
                "A3GAME_UE_ASSET_BACKEND",
                os.environ.get("A3GAME_ASSET_BACKEND", "ue"),
            )
        )
        with self._lock:
            if key not in self._providers:
                supported = ", ".join(sorted(self._providers)) or "(none)"
                raise KeyError(f"Unknown asset backend: {key}. Registered backends: {supported}")
            if key not in self._instances:
                self._instances[key] = self._providers[key].create()
            return self._instances[key]

    def registered_names(self) -> list[str]:
        with self._lock:
            return sorted(self._providers)

    @staticmethod
    def _normalize_name(name: str) -> str:
        return (name or "").strip().lower().replace("-", "_")


_DEFAULT_REGISTRY: AssetBackendRegistry | None = None


def create_default_backend_registry() -> AssetBackendRegistry:
    from engine_adapters.ue5.assets._internal.ue.provider import UEAssetBackendProvider

    registry = AssetBackendRegistry()
    registry.register("ue", UEAssetBackendProvider())
    return registry


def get_default_backend_registry() -> AssetBackendRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = create_default_backend_registry()
    return _DEFAULT_REGISTRY
