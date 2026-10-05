"""
engine_adapters/blender/runtime/send_command.py

Send JSON commands to a running runtime.

Plain Python with no `bpy`, so a Blender session can be driven from a shell that
has no Blender in it.

The file may hold one command object or an array of them, sent one datagram
each. The gap between them is not politeness: datagrams have no ordering
guarantee, and a spawn arriving after the action meant for it simply fails.

Usage:
    python -m engine_adapters.blender.runtime.send_command \\
        engine_adapters/blender/runtime/examples/visualize_only.json
    python -m engine_adapters.blender.runtime.send_command --port 30021 cmds.json
    python -m engine_adapters.blender.runtime.send_command \\
        --type render_snapshot --payload '{"samples": 16}'

向正在运行的运行时发送JSON命令。

该脚本使用纯Python编写，不依赖`bpy`模块，因此即便在没有安装Blender的Shell环境中也能操控Blender会话。

该文件可以包含一个命令对象或命令对象数组，每个命令会作为单独的数据报发送。命令之间的间隔并非出于礼貌考虑：数据报本身没有顺序保证，如果某个进程在对应的命令执行完毕后才启动，那么该命令就会失效。

使用方法：
    python -m engine_adapters.blender.runtime.send_command \\
        engine_adapters/blender/runtime/examples/visualize_only.json
    python -m engine_adapters.blender.runtime.send_command --port 30021 cmds.json
    python -m engine_adapters.blender.runtime.send_command \\
        --type render_snapshot --payload '{"samples": 16}'
"""

import argparse
import json
import socket
import sys
import time
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 30021

#: Seconds between packets. Enough for the receiving tick to pick up the last
#: one, which is what keeps a spawn ahead of the action that depends on it.
DEFAULT_GAP = 0.05


def send(commands: list, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
         gap: float = DEFAULT_GAP) -> int:
    """Send each command as one datagram. Returns how many were sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for command in commands:
            data = json.dumps(command).encode("utf-8")
            sock.sendto(data, (host, port))
            print(f"[send] {command.get('type', '?')} -> {host}:{port} "
                  f"({len(data)} bytes)")
            time.sleep(gap)
    finally:
        sock.close()
    return len(commands)


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send JSON commands to a running Blender runtime.")
    parser.add_argument("command_file", type=Path, nargs="?",
                        help="a command object, or an array of them")
    parser.add_argument("--type", help="send a single command of this type instead")
    parser.add_argument("--payload", default="{}",
                        help="JSON payload for --type (default: {})")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--gap", type=float, default=DEFAULT_GAP,
                        help=f"seconds between packets (default: {DEFAULT_GAP})")
    args = parser.parse_args(argv)

    if args.type:
        commands = [{"type": args.type, "payload": json.loads(args.payload)}]
    elif args.command_file:
        loaded = json.loads(args.command_file.read_text(encoding="utf-8"))
        commands = loaded if isinstance(loaded, list) else [loaded]
    else:
        parser.error("give a command file or --type")

    send(commands, host=args.host, port=args.port, gap=args.gap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
