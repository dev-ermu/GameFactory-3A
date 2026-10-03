"""Private Unreal Remote Control transport."""

import json
from typing import Any
from urllib import error, request


def _format_remote_control_error(
    body: str,
) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"errorMessage": body.strip()}
    return str(
        payload.get("errorMessage")
        or payload.get("message")
        or body.strip()
    )


class RemoteControlClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._opener = request.build_opener(
            request.ProxyHandler({})
        )

    def check_connection(self, timeout: float = 5.0) -> bool:
        try:
            response = self._opener.open(
                request.Request(
                    f"{self.base_url}/remote/info",
                    method="GET",
                ),
                timeout=timeout,
            )
            return response.status == 200
        except (error.HTTPError, error.URLError, TimeoutError):
            return False

    def call_object(
        self,
        object_path: str,
        function_name: str,
        parameters: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        body = json.dumps(
            {
                "objectPath": object_path,
                "functionName": function_name,
                "parameters": parameters or {},
            }
        ).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/remote/object/call",
            data=body,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        try:
            response = self._opener.open(
                http_request,
                timeout=timeout,
            )
            response_text = response.read().decode(
                "utf-8",
                errors="replace",
            )
        except error.HTTPError as exc:
            response_text = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            message = _format_remote_control_error(
                response_text
            )
            raise RuntimeError(
                "UE Remote Control call failed "
                f"({exc.code}): {message}"
            ) from exc
        except (error.URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"UE Remote Control call failed: {exc}"
            ) from exc
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return {
                "ok": True,
                "response": response_text,
            }

    def execute_python(
        self,
        script: str,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        return self.call_object(
            "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
            "ExecutePythonCommand",
            {"PythonCommand": script},
            timeout=timeout,
        )
