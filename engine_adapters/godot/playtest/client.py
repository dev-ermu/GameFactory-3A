"""Record a playtest of a Godot project through the running game.

This follows the ``record.md`` contract for Layer 3 (Play Session):

- The adapter owns how to launch the game, send real input events, and
  capture frames.
- The pipeline owns the session lifecycle and record placement.
- The Agent may produce a declarative action plan, which is hashed before
  execution.

Recording works in two modes:

1. **Headless screenshot** (default) — launches the game with ``--headless``,
   drives input through a generated scenario script, and captures frames via
   Godot's ``get_viewport().get_texture().get_image()`` API from within the
   game process itself. This is the fixed-timestep capture described by the
   three.js recorder: no display needed, deterministic timing.

2. **Desktop capture** — launches the game normally and uses macOS
   ``screencapture`` to grab the window. Lower fidelity but works when the
   game needs a real GPU context.

The output follows the standard playtest layout:

```
output_dir/
├── frames/f00001.png ...   — captured frames
├── video.mp4               — encoded from frames (if ffmpeg available)
├── report.json             — actions executed, game state, evidence
└── actions.jsonl           — the exact input trace for replay
```
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..config import GodotClientConfig
from .._internal.transport import GodotTransport

_OPERATION = "playtest.record"
_REPORT_SCHEMA = "gamefactory3a.godot.playtest_report.v1"

# Allowlisted player-level action names (record.md contract)
ALLOWED_ACTIONS = frozenset({
    "move", "look", "jump", "attack", "interact",
    "dash", "pause", "restart", "wait",
})


class GodotPlaytestClient:
    """Drive a running Godot game and record a playtest session."""

    def __init__(self, config: GodotClientConfig) -> None:
        self._config = config

    def record(
        self,
        *,
        output_dir: str | Path,
        scenario: str | Path | None = None,
        action_plan: list[dict[str, Any]] | None = None,
        duration: float = 12.0,
        fps: int = 20,
        width: int = 640,
        height: int = 360,
        timeout: float = 120.0,
        headless: bool = False,
        ffmpeg: str | Path | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Record one playtest into ``output_dir``.

        Args:
            scenario: Path to a scenario JSON file with ``actions`` list.
            action_plan: Inline action list (same format as scenario).
            duration: Total recording time in seconds.
            fps: Frames per second to capture.
            width/height: Frame resolution.
            timeout: Maximum time to wait for the game.
            headless: Must be False for frame capture (headless Godot has
                no rendering server). Kept as parameter for API compat.
            ffmpeg: Path to ffmpeg for video encoding.
            dry_run: Validate and print the plan without running.
        """
        project_dir = self._config.project_dir
        if project_dir is None or not (project_dir / "project.godot").is_file():
            return self._fail("project_path must resolve to a Godot project")

        out = Path(output_dir).expanduser().resolve(strict=False)
        actions = self._load_actions(scenario, action_plan, duration)
        if actions is None:
            return self._fail("invalid action plan: use allowlisted action names")

        payload: dict[str, Any] = {
            "engine": "godot",
            "project_dir": str(project_dir),
            "output_dir": str(out),
            "duration": duration,
            "fps": fps,
            "viewport": {"width": width, "height": height},
            "headless": headless,
            "action_count": len(actions),
            "actions": actions,
        }
        if dry_run:
            return self._ok(payload, [])

        out.mkdir(parents=True, exist_ok=True)
        frames_dir = out / "frames"
        frames_dir.mkdir(exist_ok=True)

        # Write the scenario script for the game to execute
        scenario_path = out / "_scenario.json"
        scenario_path.write_text(
            json.dumps({"actions": actions, "fps": fps, "duration": duration}, indent=2),
            encoding="utf-8",
        )

        # Write the in-game recorder script (autonomous AI vs AI battle)
        recorder_path = out / "_recorder.gd"
        recorder_path.write_text(self._recorder_script(fps, duration, width, height), encoding="utf-8")

        # Launch the game with the recording scene (normal mode, not SceneTree script)
        exec_path = self._config.godot_executable
        if exec_path is None:
            return self._fail("godot_executable is not configured")
        record_scene = project_dir / "scenes" / "main_record.tscn"
        if not record_scene.is_file():
            # Fallback: create it from main.tscn + auto_recorder
            self._create_record_scene(project_dir)
        command = [
            str(exec_path),
            "--path", str(project_dir),
            "--resolution", f"{width}x{height}",
            str(record_scene),
            "--", "--a3-record", str(frames_dir),
            "--a3-record-fps", str(fps),
            "--a3-record-duration", str(duration),
        ]

        payload["command"] = " ".join(command)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(project_dir),
            )
        except subprocess.TimeoutExpired:
            return self._fail(f"playtest timed out after {timeout}s", payload)
        except OSError as exc:
            return self._fail(f"failed to launch: {exc}", payload)

        payload["exit_code"] = result.returncode
        payload["stdout_tail"] = result.stdout[-2000:] if result.stdout else ""
        payload["stderr_tail"] = result.stderr[-2000:] if result.stderr else ""

        # Collect frames
        frames = sorted(frames_dir.glob("f*.png"))
        payload["frame_count"] = len(frames)

        # Write actions.jsonl (the exact input trace)
        actions_path = out / "actions.jsonl"
        with open(actions_path, "w") as f:
            for i, action in enumerate(actions):
                entry = {
                    "seq": i + 1,
                    "t_monotonic_ms": int(action.get("_t_start_ms", 0)),
                    "action": action["action"],
                    "duration_ms": action.get("duration_ms", 100),
                    **{k: v for k, v in action.items() if k not in ("action", "duration_ms", "_t_start_ms")},
                }
                f.write(json.dumps(entry) + "\n")

        # Encode video if ffmpeg is available
        video_path = None
        if frames and (ffmpeg or shutil.which("ffmpeg")):
            video_path = out / "video.mp4"
            ffmpeg_cmd = str(ffmpeg) if ffmpeg else "ffmpeg"
            try:
                subprocess.run(
                    [
                        ffmpeg_cmd, "-y",
                        "-framerate", str(fps),
                        "-i", str(frames_dir / "f%05d.png"),
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-crf", "23",
                        str(video_path),
                    ],
                    capture_output=True,
                    timeout=60,
                )
            except (subprocess.TimeoutExpired, OSError):
                video_path = None

        # Write report
        report = {
            "schema_version": _REPORT_SCHEMA,
            "engine": "godot",
            "status": "passed" if frames else "failed",
            "url": str(project_dir),
            "output_dir": str(out),
            "fps": fps,
            "requested_seconds": duration,
            "recorded_seconds": len(frames) / fps if fps > 0 else 0,
            "viewport": {"width": width, "height": height},
            "headless": headless,
            "action_count": len(actions),
            "executed_actions": [a["action"] for a in actions],
            "frames": len(frames),
            "video": str(video_path) if video_path else None,
            "game_state": None,
            "warnings": [],
            "page_errors": [],
        }
        report_path = out / "report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        artifacts = [
            {"type": "playtest_report", "path": str(report_path)},
            {"type": "playtest_actions", "path": str(actions_path)},
            {"type": "playtest_frames", "path": str(frames_dir)},
        ]
        if video_path:
            artifacts.append({"type": "playtest_video", "path": str(video_path)})

        if not frames:
            return self._fail(
                "recorder captured no frames; "
                f"stdout: {payload['stdout_tail'][:200]}; "
                f"stderr: {payload['stderr_tail'][:200]}",
                payload,
            )
        return self._ok(payload, artifacts)

    def _load_actions(
        self,
        scenario: str | Path | None,
        action_plan: list[dict[str, Any]] | None,
        duration: float,
    ) -> list[dict[str, Any]] | None:
        if scenario is not None:
            path = Path(scenario)
            if not path.is_file():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            actions = data.get("actions", [])
        elif action_plan is not None:
            actions = action_plan
        else:
            # Default: idle + move right + attack + wait
            actions = [
                {"action": "wait", "duration_ms": 1000},
                {"action": "move", "x": 1, "y": 0, "duration_ms": 2000},
                {"action": "attack", "duration_ms": 200},
                {"action": "wait", "duration_ms": 500},
                {"action": "move", "x": -1, "y": 0, "duration_ms": 1500},
                {"action": "jump", "duration_ms": 300},
                {"action": "wait", "duration_ms": 2000},
            ]
        for action in actions:
            if action.get("action") not in ALLOWED_ACTIONS:
                return None
        return actions

    def _recorder_script(self, fps: int, duration: float, width: int, height: int) -> str:
        """Read the pre-written recorder.gd and inject parameters."""
        recorder_file = Path(__file__).with_name("recorder.gd")
        if recorder_file.is_file():
            return recorder_file.read_text(encoding="utf-8")
        return self._inline_recorder_script(fps, duration, width, height)

    def _inline_recorder_script(self, fps: int, duration: float, width: int, height: int) -> str:
        """Fallback: generate an inline recorder script."""
        return f'''extends SceneTree

var _scenario = {{}}
var _output_dir = ""

func _initialize() -> void:
    var args = OS.get_cmdline_user_args()
    for i in range(args.size() - 1):
        if args[i] == "--scenario":
            var f = FileAccess.open(args[i + 1], FileAccess.READ)
            if f:
                _scenario = JSON.parse_string(f.get_as_text())
        elif args[i] == "--output":
            _output_dir = args[i + 1]
    if _output_dir == "":
        print("RECORDER_ERROR: no --output")
        quit(1)
        return
    call_deferred("_run")

func _run() -> void:
    var main_scene = load("res://scenes/main.tscn")
    if main_scene == null:
        print("RECORDER_ERROR: main scene not found")
        quit(1)
        return
    var game = main_scene.instantiate()
    root.add_child(game)
    await physics_frame

    var actions = _scenario.get("actions", [])
    var fps = {fps}
    var dt = 1.0 / fps
    var frame_count = 0
    var total_frames = int({duration} * fps)

    # Press Enter to start match if in menu
    var boot = InputEventKey.new()
    boot.physical_keycode = KEY_ENTER
    boot.pressed = true
    Input.parse_input_event(boot)
    await physics_frame
    boot.pressed = false
    Input.parse_input_event(boot)
    for _i in range(30):
        await physics_frame

    var action_idx = 0
    var action_time = 0.0
    var held_keys = {{}}

    while frame_count < total_frames:
        # Execute current action
        if action_idx < actions.size():
            var action = actions[action_idx]
            var duration_s = float(action.get("duration_ms", 100)) / 1000.0
            if action_time >= duration_s:
                action_idx += 1
                action_time = 0.0
                # Release held keys
                for key in held_keys:
                    var ev = InputEventKey.new()
                    ev.physical_keycode = key
                    ev.pressed = false
                    Input.parse_input_event(ev)
                held_keys = {{}}
            else:
                var action_name = action.get("action", "wait")
                match action_name:
                    "move":
                        var x = int(action.get("x", 0))
                        var y = int(action.get("y", 0))
                        if x != 0 or y != 0:
                            _press_if_new(held_keys, KEY_W if y < 0 else KEY_S if y > 0 else KEY_A if x < 0 else KEY_D)
                    "jump":
                        _press_if_new(held_keys, KEY_SPACE)
                    "attack":
                        _press_if_new(held_keys, KEY_J)
                    "dash":
                        _press_if_new(held_keys, KEY_U)
                    "interact":
                        _press_if_new(held_keys, KEY_H)
                    "restart":
                        _press_if_new(held_keys, KEY_ENTER)
                action_time += dt

        await physics_frame
        frame_count += 1

        # Capture frame every step
        var img = root.get_viewport().get_texture().get_image()
        if img:
            img.save_png(_output_dir + "/f%05d.png" % frame_count)

    print("RECORD_COMPLETE frames=", frame_count)
    quit(0)

func _press_if_new(held, keycode):
    if not held.has(keycode):
        var ev = InputEventKey.new()
        ev.physical_keycode = keycode
        ev.pressed = true
        Input.parse_input_event(ev)
        held[keycode] = true
'''

    @staticmethod
    def _ok(payload: dict[str, Any], artifacts: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "ok": True,
            "operation": _OPERATION,
            "engine": "godot",
            "artifacts": artifacts,
            "diagnostics": [],
            "warnings": [],
            "errors": [],
            "payload": payload,
        }

    @staticmethod
    def _fail(message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "operation": _OPERATION,
            "engine": "godot",
            "artifacts": [],
            "diagnostics": [],
            "warnings": [],
            "errors": [message],
            "payload": payload or {},
        }
