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


用于接收JSON指令的UDP监听器。

这里采用数据报而非流传输方式，因为发送方通常是按帧率发送输入信号的控制器，丢弃一个数据包总比导致系统卡顿要好。每个数据报对应一条完整的指令：

    {"type": "trigger_vfx", "payload": {"vfx_kind": "particle"}}

该监听器在后台线程中运行，且刻意不导入`bpy`模块。它会将`(type, payload)`参数传递给回调函数，该函数只需将指令加入队列即可；具体原因可参见`subsystem.Subsystem`的相关说明。
"""

import json
import socket
import threading
from typing import Callable, Optional

#: A command is small. This is the practical ceiling on a UDP payload and any
#: sane command fits many times over, so a larger one means a malformed sender.
# 指令数据量较小。这是UDP数据包的实际容量上限，任何合理的指令都能被多次封装进去，因此若数据包过大则说明发送方存在格式错误。
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
