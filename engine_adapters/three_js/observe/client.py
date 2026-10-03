"""Stable environment observation operations for ThreeClient v1."""

from typing import Any

from .._internal.transport import DevServerClient, NodeToolchain
from ..config import ThreeClientConfig
from ..contracts import ThreeDiagnostic, ThreeOperationResult


class ThreeObserveClient:
    def __init__(
        self,
        config: ThreeClientConfig,
        transport: DevServerClient,
    ) -> None:
        self._config = config
        self._transport = transport
        self._toolchain = NodeToolchain(config)

    def check_status(
        self,
        *,
        timeout: float = 5.0,
        check_runtime: bool = True,
    ) -> dict[str, Any]:
        """Report toolchain, project, dev server, and runtime readiness."""

        diagnostics: list[ThreeDiagnostic] = []

        node = self._toolchain.node
        node_version = self._toolchain.node_version(timeout=timeout)
        node_ok = node is not None and bool(node_version)
        if not node_ok:
            diagnostics.append(
                ThreeDiagnostic(
                    severity="error",
                    code="THREE_NODE_UNAVAILABLE",
                    message=(
                        "Node executable was not found; configure "
                        "node_root or add node to PATH"
                    ),
                    source="node_toolchain",
                )
            )
        manager = self._toolchain.package_manager
        manager_ok = manager is not None
        if not manager_ok:
            diagnostics.append(
                ThreeDiagnostic(
                    severity="error",
                    code="THREE_PACKAGE_MANAGER_UNAVAILABLE",
                    message=(
                        "Node package manager was not found: "
                        f"{self._config.package_manager}"
                    ),
                    source="node_toolchain",
                )
            )

        project_dir = self._config.project_dir
        project_file = self._config.project_file
        project_ok = bool(project_file and project_file.is_file())
        if not project_ok:
            diagnostics.append(
                ThreeDiagnostic(
                    severity="error",
                    code="THREE_PROJECT_MISSING",
                    message=(
                        "project_path does not resolve to an existing "
                        "package.json file"
                    ),
                    source="project",
                )
            )
        dependencies_ok = bool(
            project_dir and (project_dir / "node_modules").is_dir()
        )
        if project_ok and not dependencies_ok:
            diagnostics.append(
                ThreeDiagnostic(
                    severity="warning",
                    code="THREE_DEPENDENCIES_MISSING",
                    message=(
                        "node_modules is missing; call "
                        "project.install_dependencies()"
                    ),
                    source="project",
                )
            )
        framework_ok = bool(
            project_dir
            and (
                project_dir
                / "packages"
                / "a3game-playable"
                / "package.json"
            ).is_file()
        )
        if project_ok and not framework_ok:
            diagnostics.append(
                ThreeDiagnostic(
                    severity="warning",
                    code="THREE_FRAMEWORK_MISSING",
                    message=(
                        "A3GamePlayable runtime framework is not "
                        "installed; call plugin.install_framework()"
                    ),
                    source="framework",
                )
            )

        dev_server_ok = self._transport.check_connection(
            timeout=timeout
        )
        if not dev_server_ok:
            diagnostics.append(
                ThreeDiagnostic(
                    severity="warning",
                    code="THREE_DEV_SERVER_UNAVAILABLE",
                    message=(
                        "Dev server is not reachable at "
                        f"{self._config.dev_server_url}"
                    ),
                    source="dev_server",
                )
            )
        runtime_ok = False
        if check_runtime:
            runtime_ok = self._transport.check_runtime_channel(
                timeout=timeout
            )
            if not runtime_ok:
                diagnostics.append(
                    ThreeDiagnostic(
                        severity="warning",
                        code="THREE_RUNTIME_CHANNEL_UNAVAILABLE",
                        message=(
                            "Runtime control channel is not reachable "
                            f"at {self._config.runtime_url}"
                        ),
                        source="runtime_channel",
                    )
                )

        ok = (
            node_ok
            and manager_ok
            and project_ok
            and dependencies_ok
            and dev_server_ok
            and (runtime_ok if check_runtime else True)
        )
        return ThreeOperationResult(
            operation="observe.check_status",
            ok=ok,
            diagnostics=tuple(diagnostics),
            errors=(
                ()
                if ok
                else ("three.js environment is not ready",)
            ),
            payload={
                "api_version": self._config.api_version,
                "engine": "three_js",
                "engine_version": self._config.engine_version,
                "node": {
                    "ok": node_ok,
                    "path": str(node or ""),
                    "version": node_version,
                },
                "package_manager": {
                    "ok": manager_ok,
                    "name": self._config.package_manager,
                    "path": str(manager or ""),
                },
                "project": {
                    "ok": project_ok,
                    "path": str(project_file or ""),
                    "dependencies_installed": dependencies_ok,
                    "framework_installed": framework_ok,
                },
                "dev_server": {
                    "ok": dev_server_ok,
                    "url": self._config.dev_server_url,
                },
                "runtime_channel": {
                    "checked": check_runtime,
                    "ok": runtime_ok if check_runtime else None,
                    "url": self._config.runtime_url,
                    "transport": self._config.runtime_transport,
                },
            },
        ).to_dict()
