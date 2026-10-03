"""Stable environment observation operations for UEClient v1."""

from typing import Any

from .._internal.transport import (
    PythonRPCTransport,
    RemoteControlClient,
)
from ..config import UEClientConfig
from ..contracts import UEDiagnostic, UEOperationResult


class UEObserveClient:
    def __init__(
        self,
        config: UEClientConfig,
        remote_control: RemoteControlClient,
        python_transport: PythonRPCTransport,
    ) -> None:
        self._config = config
        self._remote_control = remote_control
        self._python_transport = python_transport

    def check_status(
        self,
        *,
        timeout: float = 5.0,
        check_python: bool = True,
    ) -> dict[str, Any]:
        remote_ok = self._remote_control.check_connection(
            timeout=timeout
        )
        python_ok = False
        python_error = ""
        if check_python:
            try:
                result = self._python_transport.execute_json(
                    'result = {"ok": True}',
                    timeout=max(1, int(timeout)),
                )
                python_ok = bool(
                    isinstance(result, dict)
                    and result.get("ok")
                )
            except Exception as exc:
                python_error = f"{type(exc).__name__}: {exc}"

        diagnostics: list[UEDiagnostic] = []
        if not remote_ok:
            diagnostics.append(
                UEDiagnostic(
                    severity="warning",
                    code="UE_REMOTE_CONTROL_UNAVAILABLE",
                    message=(
                        "Unreal Remote Control is not reachable"
                    ),
                    source="remote_control",
                )
            )
        if check_python and not python_ok:
            diagnostics.append(
                UEDiagnostic(
                    severity="warning",
                    code="UE_PYTHON_UNAVAILABLE",
                    message=(
                        python_error
                        or "Unreal Python execution is unavailable"
                    ),
                    source="python_transport",
                )
            )

        ok = (
            remote_ok
            and (python_ok if check_python else True)
        )
        return UEOperationResult(
            operation="observe.check_status",
            ok=ok,
            diagnostics=tuple(diagnostics),
            errors=(
                ()
                if ok
                else ("Unreal environment is not ready",)
            ),
            payload={
                "api_version": self._config.api_version,
                "remote_control": {
                    "ok": remote_ok,
                    "url": self._config.remote_url,
                },
                "python_execution": {
                    "checked": check_python,
                    "ok": (
                        python_ok
                        if check_python
                        else None
                    ),
                    "transport": (
                        self._config.python_transport
                    ),
                },
            },
        ).to_dict()
