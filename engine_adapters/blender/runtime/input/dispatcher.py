"""
engine_adapters/blender/runtime/input/dispatcher.py

Maps a command name to the runtime call that performs it.

The handlers are deliberately thin: read the payload, supply defaults, call one
module. Anything longer than a few lines belongs in the module being called, so
that the command table stays readable as the contract it is — this file is the
answer to "what can I send the runtime?".

Payload keys are optional wherever a sensible default exists, because commands
are hand-written as often as they are generated.

将命令名称映射到执行该命令的运行时调用。

这些处理函数刻意设计得较为简单：仅读取参数、设置默认值，然后调用相应模块。任何超过几行的逻辑都应放在被调用的模块中，这样命令表就能保持其作为契约的可读性——该文件正是回答“我能向运行时发送什么命令？”这个问题的答案。

只要存在合理的默认值，参数键就是可选的，因为命令往往是手动编写而非自动生成的。
"""

from typing import Callable, Dict, Optional, Tuple


def _xyz(payload: dict, key: str,
         default: Optional[Tuple[float, float, float]] = None):
    """A 3-vector from JSON, which has lists where Blender wants tuples."""
    if key not in payload or payload[key] is None:
        return default
    return tuple(float(v) for v in payload[key])


class CommandDispatcher:
    def __init__(self, players, stage, camera, vfx, session,
                 blend_scene, generated_scene=None) -> None:
        self.players = players
        self.stage = stage
        self.camera = camera
        self.vfx = vfx
        self.session = session
        self.blend_scene = blend_scene
        self.generated_scene = generated_scene
        self._handlers: Dict[str, Callable[[dict], bool]] = {
            "ensure_player":         self._ensure_player,
            "destroy_player":        self._destroy_player,
            "load_action":           self._load_action,
            "apply_input":           self._apply_input,
            "load_scene":            self._load_scene,
            "import_scene":          self._import_scene,
            "clear_scene":           self._clear_scene,
            "set_preview_character": self._set_preview_character,
            "play_preview_action":   self._play_preview_action,
            "apply_camera_input":    self._apply_camera_input,
            "trigger_vfx":           self._trigger_vfx,
            "clear_vfx":             self._clear_vfx,
            "join_world":            self._join_world,
            "leave_world":           self._leave_world,
            "destroy_session":       self._destroy_session,
            "render_snapshot":       self._render_snapshot,
            "save_blend":            self._save_blend,
            "dump_scene_report":     self._dump_scene_report,
        }

    def commands(self) -> tuple:
        """Every command this runtime accepts, sorted. Used by `--list`."""
        return tuple(sorted(self._handlers))

    def dispatch(self, command: str, payload: dict) -> bool:
        handler = self._handlers.get(command)
        if handler is None:
            print(f"[runtime] unknown command {command!r}; "
                  f"known: {', '.join(self.commands())}")
            return False
        return handler(payload or {})

    # ── Players ───────────────────────────────────────────────────────────────

    def _ensure_player(self, p: dict) -> bool:
        self.players.ensure_player(
            entity_id=p["entity_id"],
            asset_path=p["obj_path"],
            spawn_location=_xyz(p, "spawn_location"),
            spawn_rotation=_xyz(p, "rotation"),
        )
        return True

    def _destroy_player(self, p: dict) -> bool:
        return self.players.destroy_player(p["entity_id"])

    def _load_action(self, p: dict) -> bool:
        from ..assets.actions import bind_action, load_action

        player = self.players.get(p["entity_id"])
        if player is None:
            print(f"[runtime] load_action: no player {p['entity_id']!r}")
            return False
        action = load_action(p["action_path"])
        bind_action(player.obj_name, action,
                    loop=p.get("loop", True),
                    play_rate=p.get("play_rate", 1.0))
        player.action_name = action
        return True

    def _apply_input(self, p: dict) -> bool:
        player = self.players.get(p["entity_id"])
        if player is None:
            return False
        player.apply_input(
            move_x=p.get("move_x", 0.0), move_y=p.get("move_y", 0.0),
            run=p.get("run", False), jump=p.get("jump", False),
            yaw=p.get("yaw", 0.0), pitch=p.get("pitch", 0.0),
        )
        return True

    # ── Scene ─────────────────────────────────────────────────────────────────

    def _load_scene(self, p: dict) -> bool:
        self.blend_scene.load_scene(p.get("scene_path", ""),
                                    link=p.get("link", False))
        return True

    def _import_scene(self, p: dict) -> bool:
        """Pull in a generated environment — glb / usd / ply / obj / fbx."""
        if self.generated_scene is None:
            print("[runtime] import_scene: no generated-scene importer wired")
            return False
        self.generated_scene.import_generated_scene(
            scene_path=p["scene_path"],
            collection_name=p.get("collection_name", "generated_scene"),
            scale=p.get("scale", 1.0),
            location=_xyz(p, "location", (0.0, 0.0, 0.0)),
            replace_existing=p.get("replace_existing", True),
        )
        return True

    def _clear_scene(self, p: dict) -> bool:
        self.blend_scene.clear_runtime_objects()
        return True

    def _set_preview_character(self, p: dict) -> bool:
        self.stage.set_character(p["obj_path"],
                                 scale=p.get("scale", 1.0),
                                 yaw=p.get("yaw", 0.0))
        if p.get("reframe", True):
            self.stage.reframe()
        return True

    def _play_preview_action(self, p: dict) -> bool:
        self.stage.play_action(p["action_path"],
                               loop=p.get("loop", True),
                               play_rate=p.get("play_rate", 1.0))
        return True

    def _apply_camera_input(self, p: dict) -> bool:
        self.camera.apply_input(
            yaw_delta=p.get("yaw_delta", 0.0),
            pitch_delta=p.get("pitch_delta", 0.0),
            zoom_delta=p.get("zoom_delta", 0.0),
            pan_y_delta=p.get("pan_y", 0.0),
            pan_z_delta=p.get("pan_z", 0.0),
        )
        return True

    # ── VFX ───────────────────────────────────────────────────────────────────

    def _trigger_vfx(self, p: dict) -> bool:
        self.vfx.trigger(
            kind=p["vfx_kind"],
            location=_xyz(p, "location"),
            entity_id=p.get("entity_id"),
            params=p.get("params", {}),
        )
        return True

    def _clear_vfx(self, p: dict) -> bool:
        if "name" in p:
            return self.vfx.clear(p["name"])
        return self.vfx.clear_all() >= 0

    # ── Session ───────────────────────────────────────────────────────────────

    def _join_world(self, p: dict) -> bool:
        return self.session.join_world(p)

    def _leave_world(self, p: dict) -> bool:
        return self.session.leave_world(p)

    def _destroy_session(self, p: dict) -> bool:
        return self.session.destroy_session(p)

    # ── Visualization ─────────────────────────────────────────────────────────

    def _render_snapshot(self, p: dict) -> bool:
        from ..snapshot import render_snapshot

        render_snapshot(
            filepath=p.get("filepath", ""),
            resolution=tuple(p.get("resolution", (1280, 720))),
            engine=p.get("engine", "CYCLES"),
            samples=int(p.get("samples", 32)),
        )
        return True

    def _save_blend(self, p: dict) -> bool:
        from ..snapshot import save_blend

        save_blend(filepath=p.get("filepath", ""))
        return True

    def _dump_scene_report(self, p: dict) -> bool:
        from ..snapshot import dump_scene_report

        dump_scene_report(filepath=p.get("filepath", ""))
        return True
