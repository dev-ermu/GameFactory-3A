"""Stable Unity editor process operations for UnityClient v1."""

import subprocess
from pathlib import Path
from typing import Any, Sequence

from .._internal.transport import (
    UnityEditorTransport,
    find_unity_binary,
)
from ..assets import UnityAssetsClient
from ..config import UnityClientConfig
from ..contracts import UnityOperationResult
from ._internal.bridge.udp import RuntimeUDPBridge
from .sessions import UnityRuntimeSessionsClient


class UnityRuntimeClient:
    """Launch and stop the Unity editor and manage runtime sessions."""

    def __init__(
        self,
        config: UnityClientConfig,
        assets: UnityAssetsClient,
    ) -> None:
        self._config = config
        self._assets = assets
        self._transport = UnityEditorTransport(config)
        self._player_processes: dict[int, subprocess.Popen[Any]] = {}
        self.sessions = UnityRuntimeSessionsClient(
            assets,
            bridge=RuntimeUDPBridge(
                config.runtime_host,
                config.runtime_port,
            ),
            input_host=config.runtime_host,
            input_port=config.runtime_port,
        )

    def launch_editor(
        self,
        *,
        scene_path: str = "",
        extra_args: Sequence[str] = (),
        dry_run: bool = False,
    ) -> dict[str, Any]:
        unity = find_unity_binary(self._config.unity_root)
        project_path = self._config.project_path
        if unity is None or not unity.exists():
            return UnityOperationResult.failure(
                "runtime.launch_editor",
                f"Unity editor binary was not found: "
                f"{unity or '<not configured>'}",
            ).to_dict()
        if project_path is None or not project_path.is_dir():
            return UnityOperationResult.failure(
                "runtime.launch_editor",
                "project_path does not resolve to an existing "
                "Unity project directory",
            ).to_dict()

        resolved_extra_args = [str(arg) for arg in extra_args]
        project_log = (
            project_path / "Library" / "GameFactory3A" / "Editor.log"
        )
        command = [
            str(unity),
            "-projectPath",
            str(project_path),
            "-logFile",
            str(project_log),
        ]
        if str(scene_path or "").strip():
            command.append(str(scene_path).strip())
        command.append(
            f"-A3GameRuntimeInputPort={self._config.runtime_port}"
        )
        command.extend(resolved_extra_args)
        payload: dict[str, Any] = {
            "command": command,
            "cwd": str(project_path),
            "scene_path": str(scene_path or ""),
            "runtime_input_host": self._config.runtime_host,
            "runtime_input_port": self._config.runtime_port,
            "dry_run": dry_run,
        }
        if dry_run:
            return UnityOperationResult.success(
                "runtime.launch_editor",
                payload=payload,
            ).to_dict()

        try:
            process = self._transport.launch_editor(
                scene_path=str(scene_path or ""),
                extra_args=resolved_extra_args,
            )
        except Exception as exc:
            return UnityOperationResult.failure(
                "runtime.launch_editor",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        # A Unity licensing/bootstrap failure can terminate the child before
        # the asynchronous launcher returns control to the caller. Report
        # that as a failed launch instead of claiming a running Editor.
        returncode = process.poll()
        if returncode is not None:
            log_tail = ""
            if project_log.is_file():
                log_tail = project_log.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[-4000:]
            return UnityOperationResult.failure(
                "runtime.launch_editor",
                f"Unity Editor exited during startup (code {returncode})",
                payload={
                    **payload,
                    "returncode": returncode,
                    "log_path": str(project_log),
                    "log_tail": log_tail,
                },
            ).to_dict()

        payload["process_id"] = process.pid
        return UnityOperationResult.success(
            "runtime.launch_editor",
            artifacts=[
                {
                    "type": "unity_editor_process",
                    "path": str(unity),
                    "state": "running",
                    "process_id": process.pid,
                }
            ],
            payload=payload,
        ).to_dict()

    def stop_editor(
        self,
        process_id: int,
    ) -> dict[str, Any]:
        stopped = self._transport.stop_editor(int(process_id))
        if not stopped:
            return UnityOperationResult.failure(
                "runtime.stop_editor",
                "UnityClient can stop only Editor processes that it "
                f"launched; unknown process_id: {process_id}",
            ).to_dict()
        return UnityOperationResult.success(
            "runtime.stop_editor",
            payload={"process_id": int(process_id)},
        ).to_dict()

    def launch_player(
        self,
        build_path: str | Path,
        *,
        extra_args: Sequence[str] = (),
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Launch a concrete native player artifact produced by build.project."""
        artifact = Path(build_path).expanduser().resolve(strict=False)
        executable = artifact
        if artifact.is_dir() and artifact.suffix.lower() == ".app":
            binaries = sorted(
                item
                for item in (artifact / "Contents" / "MacOS").iterdir()
                if item.is_file()
            ) if (artifact / "Contents" / "MacOS").is_dir() else []
            executable = binaries[0] if binaries else artifact
        if not executable.is_file():
            return UnityOperationResult.failure(
                "runtime.launch_player",
                f"Native Unity player executable was not found: {executable}",
            ).to_dict()
        command = [str(executable), *[str(item) for item in extra_args]]
        payload = {
            "command": command,
            "build_path": str(artifact),
            "executable": str(executable),
            "dry_run": dry_run,
        }
        if dry_run:
            return UnityOperationResult.success(
                "runtime.launch_player",
                payload=payload,
            ).to_dict()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(executable.parent),
                start_new_session=True,
            )
        except Exception as exc:
            return UnityOperationResult.failure(
                "runtime.launch_player",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        self._player_processes[process.pid] = process
        payload["process_id"] = process.pid
        return UnityOperationResult.success(
            "runtime.launch_player",
            artifacts=[
                {
                    "type": "unity_player_process",
                    "path": str(executable),
                    "state": "running",
                    "process_id": process.pid,
                }
            ],
            payload=payload,
        ).to_dict()

    def stop_player(self, process_id: int) -> dict[str, Any]:
        process = self._player_processes.pop(int(process_id), None)
        if process is None:
            return UnityOperationResult.failure(
                "runtime.stop_player",
                f"Unknown Unity player process_id: {process_id}",
            ).to_dict()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        return UnityOperationResult.success(
            "runtime.stop_player",
            payload={
                "process_id": int(process_id),
                "returncode": process.returncode,
            },
        ).to_dict()
