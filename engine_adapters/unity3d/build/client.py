"""Stable build operations for UnityClient v1."""

import re
import sys
from pathlib import Path
from typing import Any, Sequence

from .._internal.transport import UnityEditorTransport, find_unity_binary
from ..config import UnityClientConfig
from ..contracts import UnityDiagnostic, UnityOperationResult


_DIAGNOSTIC_PATTERN = re.compile(
    r"^(?P<file>.*?)(?:\((?P<line>\d+),\s*(?P<column>\d+)\))?"
    r":\s*(?P<severity>error|warning)\s+"
    r"(?P<code>CS\d+):\s*(?P<message>.+)$"
)


def _diagnostics(output: str) -> list[UnityDiagnostic]:
    result: list[UnityDiagnostic] = []
    for line in output.splitlines():
        match = _DIAGNOSTIC_PATTERN.match(line.strip())
        if not match:
            continue
        result.append(
            UnityDiagnostic(
                severity=match.group("severity").lower(),
                message=match.group("message").strip(),
                code=str(match.group("code") or ""),
                file=str(match.group("file") or "").strip(),
                line=int(match.group("line")) if match.group("line") else None,
                column=(
                    int(match.group("column"))
                    if match.group("column")
                    else None
                ),
                source="unity_compiler",
            )
        )
    return result


def _default_output(project_path: Path, target: str) -> Path:
    root = project_path / "Builds" / target
    names = {
        "StandaloneWindows": "Game.exe",
        "StandaloneWindows64": "Game.exe",
        "StandaloneOSX": "Game.app",
        "StandaloneLinux64": "Game.x86_64",
    }
    return root / names[target] if target in names else root


def _host_target() -> str:
    if sys.platform == "darwin":
        return "StandaloneOSX"
    if sys.platform.startswith("linux"):
        return "StandaloneLinux64"
    return "StandaloneWindows64"


def _resolve_output(project_path: Path, target: str, output_path: str) -> Path:
    if str(output_path or "").strip():
        path = Path(output_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        return path.resolve(strict=False)
    return _default_output(project_path, target).resolve(strict=False)


def _player_artifact_exists(path: Path, target: str) -> bool:
    if target == "WebGL":
        return path.is_dir() and (path / "index.html").is_file()
    return path.exists()


class UnityBuildClient:
    """Invoke BuildPipeline.BuildPlayer and require a concrete player artifact."""

    def __init__(self, config: UnityClientConfig) -> None:
        self._config = config
        self._transport = UnityEditorTransport(config)

    def project(
        self,
        *,
        target: str = "",
        configuration: str = "Development",
        clean: bool = False,
        output_path: str = "",
        scenes: Sequence[str] = (),
        dry_run: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        unity = find_unity_binary(self._config.unity_root)
        project_path = self._config.project_path
        if unity is None or not unity.exists():
            return UnityOperationResult.failure(
                "build.project",
                f"Unity editor binary was not found: {unity or '<not configured>'}",
            ).to_dict()
        if project_path is None or not project_path.is_dir():
            return UnityOperationResult.failure(
                "build.project",
                "project_path does not resolve to an existing Unity project directory",
            ).to_dict()

        resolved_target = str(target).strip() or _host_target()
        resolved_scenes = [str(scene) for scene in scenes if str(scene).strip()]
        resolved_output = _resolve_output(
            project_path,
            resolved_target,
            output_path,
        )
        args = {
            "target": resolved_target,
            "output_path": str(resolved_output),
            "configuration": str(configuration or "Development"),
            "clean": bool(clean),
            "scenes": resolved_scenes,
        }
        invocation = self._transport.execute_method(
            "BuildPlayer.RunFromCLI",
            args=args,
            timeout=(
                int(timeout)
                if timeout is not None
                else self._config.editor_batchmode_timeout
            ),
            dry_run=dry_run,
        )
        payload: dict[str, Any] = {
            **{
                key: value
                for key, value in invocation.items()
                if key not in {"ok", "warnings", "errors", "error"}
            },
            "target": resolved_target,
            "platform": resolved_target,
            "configuration": str(configuration or "Development"),
            "clean": bool(clean),
            "output_path": str(resolved_output),
            "scenes": resolved_scenes,
            "dry_run": dry_run,
        }
        if dry_run:
            return UnityOperationResult.success(
                "build.project",
                artifacts=[
                    {
                        "type": "unity_player",
                        "path": str(resolved_output),
                        "state": "planned",
                    }
                ],
                payload=payload,
            ).to_dict()

        output = "\n".join(
            str(invocation.get(key) or "") for key in ("stdout", "stderr")
        )
        diagnostics = _diagnostics(output)
        if not invocation.get("ok"):
            errors = [str(item) for item in invocation.get("errors") or []]
            error = str(invocation.get("error") or "")
            if error:
                errors.insert(0, error)
            return UnityOperationResult.failure(
                "build.project",
                *(errors or ["Unity BuildPipeline.BuildPlayer failed"]),
                diagnostics=diagnostics,
                payload=payload,
            ).to_dict()

        reported_output = Path(
            str(invocation.get("outputPath") or resolved_output)
        )
        if not _player_artifact_exists(reported_output, resolved_target):
            return UnityOperationResult.failure(
                "build.project",
                f"Unity reported success but the player artifact is missing: {reported_output}",
                diagnostics=diagnostics,
                payload=payload,
            ).to_dict()

        payload["output_path"] = str(reported_output)
        return UnityOperationResult.success(
            "build.project",
            diagnostics=diagnostics,
            artifacts=[
                {
                    "type": "unity_player",
                    "path": str(reported_output),
                    "state": "ready",
                    "target": resolved_target,
                }
            ],
            payload=payload,
        ).to_dict()
