"""
engine_adapters/blender/runtime/serve.py

Start the runtime and keep ticking it.

The loop is the whole program: drain whatever the UDP thread queued, advance the
characters by the elapsed time, sleep. Elapsed time is measured rather than
assumed — a tick that imported a hundred-megabyte world took a second, not a
thirtieth of one, and using the nominal step after a stall teleports every
character that was mid-jump.

Run (inside an interpreter that has `bpy`):
    python -m engine_adapters.blender.runtime.serve --port 30021

Or through Blender itself:
    blender --background --factory-startup \\
        --python engine_adapters/blender/runtime/serve.py -- --port 30021
启动运行时并持续执行相关逻辑。

整个程序就是一个循环：处理UDP线程中积压的数据、根据经过的时间推进角色状态，然后进入休眠。这里采用实际测量的时间而非预设值——毕竟导入一个百兆字节大小的世界数据可能需要1秒而非1/30秒；如果在程序卡顿后仍使用预设的时间步长，正在跳跃中的角色就会被瞬间传送。

在已安装`bpy`模块的解释器中运行：
    python -m engine_adapters.blender.runtime.serve --port 30021

也可以通过Blender本身启动：
    blender --background --factory-startup \\
        --python engine_adapters/blender/runtime/serve.py -- --port 30021
"""

import argparse
import sys
import time
from pathlib import Path

#: Nominal tick rate. Input arrives at whatever rate the sender manages; this
#: only sets how finely movement is integrated between packets.
DEFAULT_TICK_HZ = 30.0

#: A tick this long means something blocked — an import, a bake, a render.
#: Movement is clamped to it so a stall slows the world instead of teleporting it.
MAX_STEP_SECONDS = 0.25


def _ensure_importable() -> None:
    """
    Put the repository root on the path when run as a loose script: `blender
    --python <file>` executes with no package context, and this package is built
    from relative imports.
    """
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _script_argv() -> list:
    """Blender passes the script's own arguments after a bare `--`."""
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return sys.argv[1:]


def serve(port: int = 30021, tick_hz: float = DEFAULT_TICK_HZ) -> int:
    _ensure_importable()
    from engine_adapters.blender.runtime.subsystem import Subsystem  # noqa: PLC0415

    subsystem = Subsystem.get()
    subsystem.start(listen_port=port)
    print(f"[runtime] ticking at {tick_hz:g} Hz; Ctrl-C to stop")

    step = 1.0 / tick_hz
    previous = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            elapsed = min(now - previous, MAX_STEP_SECONDS)
            previous = now

            subsystem.drain_pending()
            subsystem.session.consume_latest_inputs(subsystem.players)
            subsystem.players.tick(elapsed)

            # Sleep out the remainder of the budget, not the whole step, or the
            # tick rate drifts down by however long the work took.
            time.sleep(max(0.0, step - (time.monotonic() - now)))
    except KeyboardInterrupt:
        print()
    finally:
        subsystem.shutdown()
    return 0


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Blender playable runtime.")
    parser.add_argument("--port", type=int, default=30021,
                        help="UDP port for JSON commands (default: 30021)")
    parser.add_argument("--tick-hz", type=float, default=DEFAULT_TICK_HZ,
                        help=f"tick rate (default: {DEFAULT_TICK_HZ:g})")
    args = parser.parse_args(_script_argv() if argv is None else argv)
    return serve(port=args.port, tick_hz=args.tick_hz)


if __name__ == "__main__":
    sys.exit(main())
