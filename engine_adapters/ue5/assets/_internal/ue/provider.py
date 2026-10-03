"""UE backend provider."""

from .backend import UEAssetBackend


class UEAssetBackendProvider:
    engine = "ue"

    def create(self) -> UEAssetBackend:
        return UEAssetBackend()
