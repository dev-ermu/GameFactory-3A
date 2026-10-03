"""UDP transport for the A3GamePlayable runtime receiver."""

import json
import socket
from typing import Any


class RuntimeUDPBridge:
    """Send generic session commands to A3GamePlayable."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 30020,
    ) -> None:
        self.host = str(host or "127.0.0.1").strip()
        self.port = self._validate_port(port)

    def ensure_entity(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._without_transport_fields(kwargs)
        parameters = dict(payload.pop("parameters", {}) or {})
        for key in (
            "avatar_asset_path",
            "idle_animation_path",
            "move_animation_path",
            "actor_label",
        ):
            value = payload.pop(key, "")
            if value and key not in parameters:
                parameters[key] = value
        payload.pop("spawn_index", None)
        payload["parameters"] = parameters
        return self._send(
            {"type": "sync_session", **payload},
            kwargs,
        )

    def apply_input(self, **kwargs: Any) -> dict[str, Any]:
        return self._send(
            {
                "type": "input_state",
                **self._without_transport_fields(kwargs),
            },
            kwargs,
        )

    def mark_participant_offline(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._send(
            {
                "type": "participant_offline",
                **self._without_transport_fields(kwargs),
            },
            kwargs,
        )

    def destroy_entity(self, **kwargs: Any) -> dict[str, Any]:
        return self._send(
            {
                "type": "destroy_entity",
                **self._without_transport_fields(kwargs),
            },
            kwargs,
        )

    def _send(
        self,
        payload: dict[str, Any],
        routing: dict[str, Any],
    ) -> dict[str, Any]:
        host = str(
            routing.get("ue_input_host")
            or routing.get("input_host")
            or self.host
        )
        port = self._validate_port(
            routing.get("ue_input_port")
            or routing.get("input_port")
            or self.port
        )
        data = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        with socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        ) as sock:
            sent = sock.sendto(data, (host, port))
        if sent != len(data):
            raise OSError(
                f"UDP datagram was truncated: {sent}/{len(data)} bytes"
            )
        return {
            "ok": True,
            "transport": "udp",
            "message_type": payload["type"],
            "host": host,
            "port": port,
            "bytes_sent": sent,
        }

    @staticmethod
    def _without_transport_fields(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "ue_input_host",
                "ue_input_port",
                "input_host",
                "input_port",
            }
        }

    @staticmethod
    def _validate_port(value: Any) -> int:
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError(
                "Runtime UDP port must be between 1 and 65535"
            )
        return port
