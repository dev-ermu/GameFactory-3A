"""Stable Agent-facing facade for blender environment operations."""

from pathlib import Path
from typing import Any

from .config import DEFAULT_API_VERSION, BlenderClientConfig
from .playtest import BlenderPlaytestClient


class BlenderClient:
    """Stable blender API. Construct from ``engine_adapters.blender``."""

    def __init__(
        self,
        project_path: str | Path | None = None,
        blender_root: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        self._config = BlenderClientConfig.resolve(
            project_path=project_path,
            blender_root=blender_root,
            api_version=api_version,
        )
        self.playtest = BlenderPlaytestClient(self._config)

    @property
    def api_version(self) -> str:
        return self._config.api_version

    def get_environment_info(self) -> dict[str, Any]:
        blender = self._config.blender_executable
        project_file = self._config.project_file
        return {
            "ok": True,
            "operation": "client.get_environment_info",
            "payload": {
                "api_version": self._config.api_version,
                "project_path": (
                    str(self._config.project_dir)
                    if self._config.project_dir is not None
                    else None
                ),
                "project_file": str(project_file) if project_file else None,
                "blender_root": (
                    str(self._config.blender_root)
                    if self._config.blender_root is not None
                    else None
                ),
                "blender_executable": str(blender) if blender else None,
            },
        }
