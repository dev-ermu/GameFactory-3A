"""Stable Agent-facing facade for three.js environment operations."""

from pathlib import Path
from typing import Any

from ._internal.transport import DevServerClient
from .animation import ThreeAnimationClient
from .assets import ThreeAssetsClient
from .bindings import ThreeBindingsClient
from .build import ThreeBuildClient
from .config import DEFAULT_API_VERSION, ThreeClientConfig
from .observe import ThreeObserveClient
from .plugin import ThreePluginClient
from .playtest import ThreePlaytestClient
from .preview import ThreePreviewClient
from .project import ThreeProjectClient
from .reflection import ThreeReflectionClient
from .runtime import ThreeRuntimeClient
from .testing import ThreeTestingClient
from .world import ThreeWorldClient


class ThreeClient:
    """
    Stable three.js environment API.

    Agent code must construct ThreeClient from
    `engine_adapters.three_js` and use its public namespace clients.
    Internal modules are version-specific and are not part of the API
    contract.
    """

    def __init__(
        self,
        project_path: str | Path | None = None,
        three_root: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
        *,
        host: str | None = None,
        port: int | None = None,
        runtime_host: str | None = None,
        runtime_port: int | None = None,
        package_manager: str | None = None,
        runtime_transport: str | None = None,
        node_root: str | Path | None = None,
    ) -> None:
        self._config = ThreeClientConfig.resolve(
            project_path=project_path,
            three_root=three_root,
            api_version=api_version,
            host=host,
            port=port,
            runtime_host=runtime_host,
            runtime_port=runtime_port,
            package_manager=package_manager,
            runtime_transport=runtime_transport,
            node_root=node_root,
        )
        transport = DevServerClient(
            self._config.dev_server_url,
            runtime_url=self._config.runtime_url,
        )

        self.project = ThreeProjectClient(self._config)
        self.build = ThreeBuildClient(self._config)
        self.testing = ThreeTestingClient(self._config)
        self.playtest = ThreePlaytestClient(self._config)
        self.plugin = ThreePluginClient(self._config)
        self.assets = ThreeAssetsClient(self._config)
        self.animation = ThreeAnimationClient(self.assets)
        self.bindings = ThreeBindingsClient(
            self._config,
            self.assets,
        )
        self.world = ThreeWorldClient(
            self._config,
            self.assets,
        )
        self.reflection = ThreeReflectionClient(
            self._config,
            self.assets,
        )
        self.preview = ThreePreviewClient(
            self._config,
            self.assets,
        )
        self.runtime = ThreeRuntimeClient(
            self._config,
            self.assets,
            transport,
        )
        self.observe = ThreeObserveClient(
            self._config,
            transport,
        )

    @property
    def api_version(self) -> str:
        return self._config.api_version

    def get_environment_info(self) -> dict[str, Any]:
        info = self.project.get_info()
        info["operation"] = "client.get_environment_info"
        info["payload"]["dev_server_url"] = (
            self._config.dev_server_url
        )
        info["payload"]["runtime_url"] = self._config.runtime_url
        info["payload"]["runtime_transport"] = (
            self._config.runtime_transport
        )
        info["payload"]["artifact_registry_path"] = str(
            self._config.artifact_registry_path
        )
        info["payload"]["world_registry_root"] = str(
            self._config.world_registry_root
        )
        info["payload"]["preview_root"] = str(
            self._config.preview_root
        )
        return info
