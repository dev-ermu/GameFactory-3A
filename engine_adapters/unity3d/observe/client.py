"""Stable environment observation operations for UnityClient v1."""

from typing import Any

from .._internal.transport import (
    UnityEditorTransport,
    find_unity_binary,
)
from ..config import UnityClientConfig
from ..contracts import UnityDiagnostic, UnityOperationResult


class UnityObserveClient:
    """Probe Unity environment readiness (binary, project, editor)."""

    def __init__(
        self,
        config: UnityClientConfig,
        transport: UnityEditorTransport,
    ) -> None:
        self._config = config
        self._transport = transport

    def check_status(
        self,
        *,
        timeout: float = 5.0,
        check_editor: bool = True,
    ) -> dict[str, Any]:
        unity = find_unity_binary(self._config.unity_root)
        project_path = self._config.project_path

        editor_binary_exists = (
            unity is not None and unity.exists()
        )
        project_path_exists = (
            project_path is not None
            and project_path.is_dir()
        )

        editor_ready = False
        editor_error = ""
        editor_result: dict[str, Any] = {}
        if check_editor:
            try:
                result = self._transport.execute_method(
                    "StatusCheck.RunFromCLI",
                    timeout=max(1, int(timeout)),
                )
                if isinstance(result, dict):
                    editor_result = result
                editor_ready = bool(
                    isinstance(result, dict)
                    and result.get("ok")
                )
                if not editor_ready and isinstance(result, dict):
                    errors = [str(item) for item in result.get("errors") or []]
                    editor_error = str(result.get("error") or "")
                    if not editor_error and errors:
                        editor_error = "; ".join(errors)
            except Exception as exc:
                editor_error = (
                    f"{type(exc).__name__}: {exc}"
                )

        diagnostics: list[UnityDiagnostic] = []
        if not editor_binary_exists:
            diagnostics.append(
                UnityDiagnostic(
                    severity="warning",
                    code="UNITY_EDITOR_BINARY_NOT_FOUND",
                    message=(
                        "Unity editor binary was not found"
                    ),
                    source="observe",
                )
            )
        if not project_path_exists:
            diagnostics.append(
                UnityDiagnostic(
                    severity="warning",
                    code="UNITY_PROJECT_PATH_NOT_FOUND",
                    message=(
                        "Unity project path does not exist"
                    ),
                    source="observe",
                )
            )
        if check_editor and not editor_ready:
            diagnostics.append(
                UnityDiagnostic(
                    severity="warning",
                    code="UNITY_EDITOR_NOT_READY",
                    message=(
                        editor_error
                        or "Unity editor is not reachable"
                    ),
                    source="transport",
                )
            )

        ok = (
            editor_binary_exists
            and project_path_exists
            and (editor_ready if check_editor else True)
        )
        return UnityOperationResult(
            operation="observe.check_status",
            ok=ok,
            diagnostics=tuple(diagnostics),
            errors=(
                ()
                if ok
                else ("Unity environment is not ready",)
            ),
            payload={
                "api_version": self._config.api_version,
                "editor_binary_exists": editor_binary_exists,
                "editor_binary_path": (
                    str(unity) if unity is not None else ""
                ),
                "project_path_exists": project_path_exists,
                "project_path": (
                    str(project_path)
                    if project_path is not None
                    else ""
                ),
                "editor_ready": editor_ready,
                "editor_checked": check_editor,
                "editor_result": editor_result,
                "remote_url": self._config.remote_url,
                "runtime_input_host": (
                    self._config.runtime_host
                ),
                "runtime_input_port": (
                    self._config.runtime_port
                ),
            },
        ).to_dict()
