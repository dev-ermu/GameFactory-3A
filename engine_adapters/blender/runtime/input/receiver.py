"""
engine_adapters/blender/runtime/input/receiver.py

UDP listener for JSON commands.

Datagrams, not a stream, because the sender is usually a controller emitting
input at frame rate and a dropped packet is better than a stalled one. Each
datagram is one complete command:

    {"type": "trigger_vfx", "payload": {"vfx_kind": "particle"}}

This runs on a background thread and deliberately imports no `bpy`. It hands
`(type, payload)` to a callback that must only queue the command; see
`subsystem.Subsystem` for why.
"""

import json
import socket
import threading
from typing import Callable, Optional

#: A command is small. This is the practical ceiling on a UDP payload and any
#: sane command fits many times over, so a larger one means a malformed sender.
MAX_DATAGRAM = 65535


class CommandReceiver:
    def __init__(self, listen_port: int = 30021,
                 on_command: Optional[Callable[[str, dict], bool]] = None,
                 bind_host: str = "0.0.0.0") -> None:
        self.listen_port = listen_port
        self.on_command = on_command
        self.bind_host = bind_host
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.bind_host, self.listen_port))
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="blender-runtime-udp")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        try:
            if self._sock is not None:
                # Closing under the blocking recvfrom is what wakes the thread.
                self._sock.close()
        finally:
            self._sock = None

    def _loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while self._running:
            try:
                data, _sender = sock.recvfrom(MAX_DATAGRAM)
            except OSError:
                break  # socket closed by stop()
            try:
                message = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                print(f"[runtime] dropped malformed packet: {e}")
                continue
            if self.on_command is not None:
                self.on_command(message.get("type", ""), message.get("payload", {}))
