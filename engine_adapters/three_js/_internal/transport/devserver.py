"""Dev server and runtime control transport for the three.js adapter."""

import json
import urllib.error
import urllib.request
from typing import Any


class DevServerClient:
    """Probe a running Vite dev server and its runtime control channel."""

    def __init__(
        self,
        dev_server_url: str,
        runtime_url: str = "",
    ) -> None:
        self._dev_server_url = dev_server_url.rstrip("/")
        self._runtime_url = (runtime_url or "").rstrip("/")

    @property
    def dev_server_url(self) -> str:
        return self._dev_server_url

    @property
    def runtime_url(self) -> str:
        return self._runtime_url

    def check_connection(self, *, timeout: float = 5.0) -> bool:
        """Report whether the dev server answers an HTTP request."""

        return self._probe(self._dev_server_url, timeout=timeout)

    def check_runtime_channel(self, *, timeout: float = 5.0) -> bool:
        """Report whether the runtime control channel answers."""

        if not self._runtime_url:
            return False
        return self._probe(
            f"{self._runtime_url}/healthz",
            timeout=timeout,
        )

    def call_runtime(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Send one JSON command to the runtime control channel."""

        if not self._runtime_url:
            raise RuntimeError(
                "runtime control channel is not configured"
            )
        body = json.dumps(
            {
                "command": str(command),
                "payload": dict(payload or {}),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._runtime_url}/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                "three.js runtime rejected command "
                f"{command!r}: HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                "three.js runtime control channel is unreachable at "
                f"{self._runtime_url}: {exc}"
            ) from exc
        if not raw.strip():
            return {}
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "three.js runtime returned invalid JSON for command "
                f"{command!r}"
            ) from exc
        if not isinstance(decoded, dict):
            raise RuntimeError(
                "three.js runtime must return a JSON object for "
                f"command {command!r}"
            )
        return decoded

    @staticmethod
    def _probe(url: str, *, timeout: float) -> bool:
        if not url:
            return False
        try:
            with urllib.request.urlopen(
                url,
                timeout=timeout,
            ) as response:
                return 200 <= int(response.status) < 500
        except urllib.error.HTTPError as exc:
            return 200 <= int(exc.code) < 500
        except Exception:
            return False
