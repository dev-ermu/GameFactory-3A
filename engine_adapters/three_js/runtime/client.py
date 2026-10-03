"""Stable dev server and preview process operations for ThreeClient v1."""

import subprocess
import time
from typing import Any, Sequence

from .._internal.transport import DevServerClient, NodeToolchain
from ..assets import ThreeAssetsClient
from ..config import ThreeClientConfig
from ..contracts import ThreeOperationResult
from ._internal import WebRuntimeBridge
from .sessions import ThreeRuntimeSessionsClient


class ThreeRuntimeClient:
    def __init__(
        self,
        config: ThreeClientConfig,
        assets: ThreeAssetsClient,
        transport: DevServerClient,
    ) -> None:
        self._config = config
        self._transport = transport
        self._toolchain = NodeToolchain(config)
        self._processes: dict[int, subprocess.Popen[Any]] = {}
        self.sessions = ThreeRuntimeSessionsClient(
            assets,
            bridge=WebRuntimeBridge(transport),
        )

    def launch_dev_server(
        self,
        *,
        script: str = "dev",
        world: str = "",
        extra_args: Sequence[str] = (),
        wait_timeout: float = 60.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Start the configured Vite dev server process."""

        project_dir = self._config.project_dir
        project_file = self._config.project_file
        if project_dir is None or project_file is None:
            return ThreeOperationResult.failure(
                "runtime.launch_dev_server",
                "project_path is not configured",
            ).to_dict()
        if not project_file.is_file():
            return ThreeOperationResult.failure(
                "runtime.launch_dev_server",
                "project_path does not resolve to an existing "
                "package.json file",
            ).to_dict()
        manager = self._toolchain.package_manager
        if manager is None:
            return ThreeOperationResult.failure(
                "runtime.launch_dev_server",
                "Node package manager was not found: "
                f"{self._config.package_manager}",
            ).to_dict()
        if not (project_dir / "node_modules").is_dir():
            return ThreeOperationResult.failure(
                "runtime.launch_dev_server",
                "node_modules is missing; call "
                "project.install_dependencies() first",
            ).to_dict()

        command = [
            str(manager),
            "run",
            str(script or "dev"),
        ]
        arguments = [
            "--host",
            self._config.host,
            "--port",
            str(self._config.port),
            "--strictPort",
        ]
        arguments.extend(str(item) for item in extra_args)
        if self._config.package_manager == "npm":
            command.append("--")
        command.extend(arguments)

        environment = {
            "A3GAME_RUNTIME_HOST": self._config.runtime_host,
            "A3GAME_RUNTIME_PORT": str(self._config.runtime_port),
            "A3GAME_RUNTIME_TRANSPORT": (
                self._config.runtime_transport
            ),
        }
        if world:
            environment["A3GAME_WORLD"] = str(world)

        payload: dict[str, Any] = {
            "command": command,
            "cwd": str(project_dir),
            "script": str(script or "dev"),
            "dev_server_url": self._config.dev_server_url,
            "runtime_url": self._config.runtime_url,
            "world": str(world or ""),
            "environment": environment,
            "dry_run": dry_run,
        }
        if dry_run:
            return ThreeOperationResult.success(
                "runtime.launch_dev_server",
                payload=payload,
            ).to_dict()

        try:
            process = self._toolchain.spawn(
                command,
                cwd=project_dir,
                environment=environment,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "runtime.launch_dev_server",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        self._processes[process.pid] = process
        payload["process_id"] = process.pid

        deadline = time.monotonic() + max(0.0, float(wait_timeout))
        ready = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                payload["returncode"] = process.returncode
                self._processes.pop(process.pid, None)
                return ThreeOperationResult.failure(
                    "runtime.launch_dev_server",
                    "Dev server exited with code "
                    f"{process.returncode}",
                    payload=payload,
                ).to_dict()
            if self._transport.check_connection(timeout=2.0):
                ready = True
                break
            time.sleep(1.0)
        payload["ready"] = ready
        if not ready:
            return ThreeOperationResult.failure(
                "runtime.launch_dev_server",
                "Dev server did not answer at "
                f"{self._config.dev_server_url} after "
                f"{wait_timeout:.1f}s",
                payload=payload,
            ).to_dict()
        return ThreeOperationResult.success(
            "runtime.launch_dev_server",
            artifacts=[
                {
                    "type": "three_dev_server_process",
                    "path": self._config.dev_server_url,
                    "state": "running",
                    "process_id": process.pid,
                }
            ],
            payload=payload,
        ).to_dict()

    def stop_dev_server(
        self,
        process_id: int,
    ) -> dict[str, Any]:
        process = self._processes.get(int(process_id))
        if process is None:
            return ThreeOperationResult.failure(
                "runtime.stop_dev_server",
                "ThreeClient can stop only dev server processes that "
                f"it launched; unknown process_id: {process_id}",
            ).to_dict()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        self._processes.pop(process.pid, None)
        return ThreeOperationResult.success(
            "runtime.stop_dev_server",
            payload={
                "process_id": process.pid,
                "returncode": process.returncode,
            },
        ).to_dict()

    def preview_bundle(
        self,
        *,
        script: str = "preview",
        extra_args: Sequence[str] = (),
        wait_timeout: float = 60.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Serve the built bundle from `dist/` for evidence capture."""

        dist_root = self._config.dist_root
        if dist_root is None or not dist_root.is_dir():
            return ThreeOperationResult.failure(
                "runtime.preview_bundle",
                "dist/ was not found; call build.project() first",
            ).to_dict()
        result = self.launch_dev_server(
            script=script,
            extra_args=extra_args,
            wait_timeout=wait_timeout,
            dry_run=dry_run,
        )
        result["operation"] = "runtime.preview_bundle"
        return result
