"""
engine_adapters/blender/runtime/subsystem.py

Owns the runtime's parts and the queue between the network and Blender.

`bpy` is not thread-safe and operators must run on the thread that owns the
scene, so the UDP receiver never touches Blender — it parses a datagram onto
`_pending`, and only `drain_pending()`, called from the tick loop on the main
thread, turns one into a `bpy.ops` call. Every deadlock and silent corruption
this runtime could have comes from crossing that boundary.

该类负责管理运行时的各个组件，以及网络与Blender之间的命令队列。

由于`bpy`并非线程安全，且操作必须在与场景所属的同一线程中执行，因此UDP接收器绝不会直接操作Blender——它会将接收到的数据报解析后存入`_pending`队列；只有从主线程的tick循环中调用的`drain_pending()`方法，才会将队列中的指令转换为`bpy.ops`调用。该运行时可能出现的所有死锁和隐蔽的数据损坏问题，都源于跨越了这一线程边界。
"""

import queue
from typing import Optional, Tuple

#: Blender's command port. The UE runtime in this repo's sibling adapter
#: conventionally takes 30020; keeping them distinct lets both run at once.
DEFAULT_PORT = 30021

#: How many queued commands one tick is allowed to run. A burst of imports can
#: each take seconds, and draining without a cap would stall the tick loop.
DEFAULT_MAX_OPS_PER_TICK = 32


class Subsystem:
    """
    Process-wide handle on the running scene.

    A singleton because there is exactly one `bpy` scene per process; `get()`
    is how the scripts and any interactive console reach the same instance.
    """

    _instance: Optional["Subsystem"] = None

    def __init__(self) -> None:
        self.receiver = None
        self.dispatcher = None
        self.players = None
        self.stage = None
        self.camera = None
        self.vfx = None
        self.session = None
        self._pending: "queue.Queue[Tuple[str, dict]]" = queue.Queue()

    @classmethod
    def get(cls) -> "Subsystem":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the singleton. For tests and for restarting inside one process."""
        if cls._instance is not None:
            cls._instance.stop()
        cls._instance = None

    def start(self, listen_port: int = DEFAULT_PORT, *, listen: bool = True) -> None:
        """
        Build the scene and, unless `listen` is off, open the command port.

        `listen=False` gives the same wired dispatcher with no socket, which is
        how `selftest.py` drives the runtime without touching the network.
        """
        from .input.dispatcher import CommandDispatcher
        from .input.receiver import CommandReceiver
        from .players.manager import PlayerManager
        from .scene import blend_scene, generated_scene
        from .scene.camera import CameraController
        from .scene.stage import PreviewStage
        from .session.world_session import WorldSessionManager
        from .vfx.manager import VFXManager

        self.players = PlayerManager()
        self.stage = PreviewStage()
        self.stage.ensure()
        self.camera = CameraController()
        self.camera.push()
        self.vfx = VFXManager()
        self.session = WorldSessionManager()

        self.dispatcher = CommandDispatcher(
            players=self.players,
            stage=self.stage,
            camera=self.camera,
            vfx=self.vfx,
            session=self.session,
            blend_scene=blend_scene,
            generated_scene=generated_scene,
        )

        if listen:
            self.receiver = CommandReceiver(listen_port=listen_port,
                                            on_command=self._enqueue)
            self.receiver.start()
            print(f"[runtime] listening on UDP :{listen_port}")

    def _enqueue(self, command: str, payload: dict) -> bool:
        """Called on the receiver thread. Must not touch `bpy`."""
        self._pending.put((command, payload))
        return True

    def drain_pending(self, max_ops: int = DEFAULT_MAX_OPS_PER_TICK) -> int:
        """
        Run queued commands. **Main thread only** — this is where `bpy` is used.

        A failing command is reported and dropped rather than propagated: one
        bad asset path should not take the session down.
        """
        done = 0
        while done < max_ops:
            try:
                command, payload = self._pending.get_nowait()
            except queue.Empty:
                break
            try:
                self.dispatcher.dispatch(command, payload)
            except Exception as e:  # noqa: BLE001 - a live session outlives one bad command
                print(f"[runtime] {command} failed: {e}")
            done += 1
        return done

    def pending_count(self) -> int:
        return self._pending.qsize()

    def stop(self) -> None:
        """Close the command port. The scene is left as it is."""
        if self.receiver is not None:
            self.receiver.stop()
            self.receiver = None
        print("[runtime] stopped")

    def shutdown(self) -> None:
        """
        Stop, and leave Blender in a state it can actually exit from.

        A Mantaflow domain that has ever coexisted with a flow object breaks
        Blender's own teardown: the process faults on the way out, after all the
        work is done, which reads as a failed run to anything checking an exit
        code. Deleting the objects and their modifiers does not undo it, only
        emptying the file does — so a session that used smoke or fire is wiped
        before the interpreter is allowed to close.
        """
        self.stop()
        if self.vfx is not None and self.vfx.spawned_fluid:
            import bpy  # noqa: PLC0415

            bpy.ops.wm.read_factory_settings(use_empty=True)
            print("[runtime] scene released (a fluid simulation ran this session)")
