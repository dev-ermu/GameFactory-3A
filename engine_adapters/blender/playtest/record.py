#!/usr/bin/env python3
"""bpy-side playtest recorder (counterpart of three_js/playtest/record.mjs).

Fixed-timestep capture via ``Game.run(source=...)``. Input goes through
``ScriptedSource``; do not move actors directly. The report on disk is the
result — ``blender --python`` always exits 0.
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("GAMEFACTORY3A_ROOT", str(_REPO_ROOT))

from engine_adapters.blender.game import controls  # noqa: E402
from engine_adapters.blender.game.controls import ScriptedSource  # noqa: E402
from engine_adapters.blender.game.kernel import Game, script_argv  # noqa: E402
from engine_adapters.blender.game.recorder import write_report  # noqa: E402

REPORT_SCHEMA = "a3game.playtest_report.v1"
_HELD = re.compile(
    r"forward|back|left|right|run|walk|sprint|strafe|crouch|up|down|"
    r"accel|brake|throttle|steer|block|handbrake|move_",
    re.I,
)
_AXIS_POSITIVE = {
    "move_y": "forward",
    "move_x": "right",
    "throttle": "throttle",
    "brake": "brake",
    "steer": "steer_right",
}
_AXIS_NEGATIVE = {
    "move_y": "back",
    "move_x": "left",
    "steer": "steer_left",
}


def discover_actions(game) -> dict[str, Any]:
    """playtest_actions, then genre bindings, then WASD. Movement is held; verbs are tapped."""
    declared = getattr(game, "playtest_actions", None)
    try:
        if callable(declared):
            declared = declared()
    except Exception:  # noqa: BLE001 - discovery must not kill the take
        declared = None
    if isinstance(declared, list) and declared:
        return {"source": "declared", "actions": list(declared)}

    genre = str(getattr(game, "genre", "") or "")
    axes, buttons = controls.bindings_for(genre) if genre else ({}, {})
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def push(action_id: str, extra: dict[str, Any]) -> None:
        if not action_id or action_id in seen:
            return
        seen.add(action_id)
        actions.append({"id": action_id, **extra})

    for field, keys in buttons.items():
        code = str(keys[0]) if keys else ""
        if not code:
            continue
        extra: dict[str, Any] = {"label": field}
        if code == "LEFTMOUSE":
            extra["mouse"] = True
        elif _HELD.search(field):
            extra["keys"] = [code]
        else:
            extra["taps"] = [code]
        push(field, extra)

    for field, pair in axes.items():
        positive, negative = pair
        if positive:
            push(_AXIS_POSITIVE.get(field, f"{field}_pos"), {
                "keys": [str(positive[0])], "label": field,
            })
        if negative:
            push(_AXIS_NEGATIVE.get(field, f"{field}_neg"), {
                "keys": [str(negative[0])], "label": field,
            })
    if actions:
        return {"source": "bindings", "actions": actions}

    return {
        "source": "fallback",
        "actions": [
            {"id": "forward", "keys": ["W"]},
            {"id": "left", "keys": ["A"]},
            {"id": "right", "keys": ["D"]},
            {"id": "jump", "taps": ["SPACE"]},
            {"id": "primary", "mouse": True},
        ],
    }


def normalize(raw: Iterable[Any], source: str, budget_seconds: float) -> list[dict[str, Any]]:
    actions = []
    for index, item in enumerate(raw or ()):
        if not isinstance(item, dict):
            continue
        duration = item.get("duration")
        try:
            seconds = float(duration) if float(duration) > 0 else 0.0
        except (TypeError, ValueError):
            seconds = 0.0
        actions.append({
            "id": str(item.get("id") or item.get("name") or f"{source}_{index + 1}"),
            "label": str(item.get("label") or item.get("id") or ""),
            "keys": [str(k) for k in (item.get("keys") or [])],
            "taps": [str(k) for k in (item.get("taps") or [])],
            "mouse": bool(item.get("mouse")),
            "seconds": seconds,
            "source": source,
        })
    share = max(0.4, budget_seconds / max(1, len(actions)))
    remaining = budget_seconds
    planned: list[dict[str, Any]] = []
    for action in actions:
        if remaining <= 0:
            break
        seconds = round(min(action["seconds"] or share, remaining), 4)
        remaining = round(remaining - seconds, 4)
        planned.append({**action, "seconds": seconds})
    return planned


def to_input_timeline(
    actions: Sequence[dict[str, Any]],
    *,
    fps: int,
    look: bool = False,
) -> list[dict[str, Any]]:
    """Map actions onto ``ScriptedSource`` spans."""
    dt = 1.0 / max(1, int(fps))
    spans: list[dict[str, Any]] = []
    t = 0.0
    for action in actions:
        seconds = float(action.get("seconds") or dt)
        end = t + seconds
        held = [str(k) for k in (action.get("keys") or [])]
        if action.get("mouse") and "LEFTMOUSE" not in held:
            held.append("LEFTMOUSE")
        if held:
            spans.append({"from": round(t, 4), "to": round(end, 4), "keys": held})
        for tap in action.get("taps") or []:
            spans.append({
                "from": round(t, 4),
                "to": round(t + dt, 4),
                "keys": [str(tap)],
            })
        if look:
            # FPS: a static camera records a wall.
            spans.append({
                "from": round(t, 4),
                "to": round(end, 4),
                "mouse": [12.0, 0.0],
            })
        t = end
    return spans


def _load_game_class(path: Path) -> type[Game]:
    spec = importlib.util.spec_from_file_location("a3game_playtest_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    found = [
        obj for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, Game) and obj is not Game
    ]
    if not found:
        raise RuntimeError(f"{path} defines no kernel.Game subclass")
    return found[-1]


def _encode_frames(video: Path, frames_dir: Path, fps: int, ffmpeg: str | None) -> int:
    binary = (
        ffmpeg
        or os.environ.get("A3GAME_PLAYTEST_FFMPEG")
        or os.environ.get("FFMPEG")
        or shutil.which("ffmpeg")
    )
    if not binary:
        return 0
    frames_dir.mkdir(parents=True, exist_ok=True)
    encoded = subprocess.run(
        [
            str(binary), "-y", "-loglevel", "error",
            "-i", str(video),
            "-vf", f"fps={int(fps)}",
            str(frames_dir / "f%05d.jpg"),
        ],
        capture_output=True, text=True, errors="replace",
    )
    if encoded.returncode != 0:
        return 0
    return len(sorted(frames_dir.glob("f*.jpg")))


def _copy_png_sequence(src: Path, frames_dir: Path) -> int:
    frames_dir.mkdir(parents=True, exist_ok=True)
    pngs = sorted(src.glob("*.png"))
    for index, png in enumerate(pngs):
        shutil.copy2(png, frames_dir / f"f{index:05d}{png.suffix}")
    return len(pngs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record one blender playtest.")
    parser.add_argument("--game", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--device", default="CPU")
    parser.add_argument("--action-plan", default="")
    parser.add_argument("--spec", default="")
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--no-render", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else script_argv())
    game_path = Path(args.game).expanduser().resolve(strict=False)
    out = Path(args.output_dir).expanduser().resolve(strict=False)
    frames_dir = out / "frames"
    report_path = out / "report.json"
    out.mkdir(parents=True, exist_ok=True)
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "engine": "blender",
        "status": "failed",
        "game": str(game_path),
        "output_dir": str(out),
        "fps": int(args.fps),
        "requested_seconds": float(args.duration),
        "viewport": {"width": int(args.width), "height": int(args.height)},
        "action_source": "",
        "actions": [],
        "executed_actions": [],
        "frames": 0,
        "recorded_seconds": 0,
        "fixed_tick": True,
        "crash": "",
        "page_errors": [],
        "console_errors": [],
        "warnings": [],
        "video": None,
        "game_state": None,
    }

    try:
        game_class = _load_game_class(game_path)
        spec: dict[str, Any] = {}
        if args.spec:
            spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        spec["duration_sec"] = float(args.duration)
        spec["fps"] = int(args.fps)
        spec["resolution"] = (int(args.width), int(args.height))
        spec["samples"] = int(args.samples)

        game = game_class(spec, out)
        genre = str(getattr(game, "genre", "") or "")

        if args.action_plan:
            plan_path = Path(args.action_plan).expanduser().resolve(strict=False)
            parsed = json.loads(plan_path.read_text(encoding="utf-8"))
            discovered = {
                "source": "plan",
                "actions": parsed.get("actions", parsed) if isinstance(parsed, dict) else parsed,
            }
            report["action_plan"] = str(plan_path)
        else:
            discovered = discover_actions(game)
        report["action_source"] = discovered["source"]
        report["actions"] = normalize(
            discovered.get("actions") or [],
            discovered["source"],
            float(args.duration),
        )
        if discovered["source"] == "fallback":
            report["warnings"].append(
                "Game published no bindings; recorded a generic keyboard smoke plan."
            )
        if not report["actions"]:
            raise RuntimeError("No actions to record")

        source = ScriptedSource(
            to_input_timeline(
                report["actions"],
                fps=int(args.fps),
                look=genre in {"fps", "rpg"},
            ),
            genre or "fps",
            fps=int(args.fps),
        )

        game_report = game.run(
            render=not args.no_render,
            device=args.device,
            source=source,
        )
        ticks = int(game_report.get("ticks") or game.frame or 0)
        report["frames"] = ticks
        report["recorded_seconds"] = round(ticks / max(1, int(args.fps)), 2)
        report["game_state"] = {
            "ok": game_report.get("ok"),
            "genre": game_report.get("genre"),
            "driven_by": game_report.get("driven_by"),
            "metrics": game_report.get("metrics") or {},
            "event_counts": game_report.get("event_counts") or {},
            "problems": game_report.get("problems") or [],
        }
        report["warnings"].extend(str(w) for w in (game_report.get("warnings") or []))

        fps = max(1, int(args.fps))
        for action in report["actions"]:
            steps = max(1, round(float(action["seconds"]) * fps))
            report["executed_actions"].append({
                "id": action["id"],
                "source": action["source"],
                "frames": steps,
                "ok": True,
            })

        artifacts = game_report.get("artifacts") or {}
        video = artifacts.get("video")
        if video and Path(video).is_file():
            dest = out / "video.mp4"
            src = Path(video)
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            report["video"] = str(dest)
            extracted = _encode_frames(dest, frames_dir, fps, args.ffmpeg or None)
            if extracted:
                report["frames"] = extracted
            else:
                report["warnings"].append(
                    "Video written but JPEG frame extraction was skipped "
                    "(no ffmpeg, or ffmpeg failed)."
                )
        elif args.no_render:
            report["warnings"].append(
                "No video: --no-render. Baked ticks are in session.blend; "
                "re-run without --no-render for a clip."
            )
        else:
            png_dir = artifacts.get("frames_dir")
            if png_dir and Path(png_dir).is_dir():
                copied = _copy_png_sequence(Path(png_dir), frames_dir)
                if copied:
                    report["frames"] = copied
            if not report.get("video"):
                report["warnings"].append("Recorder produced no video.mp4")

        report["status"] = "completed" if report["frames"] > 0 else "failed"
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        report["crash"] = str(exc).split("\n")[0][:200]
        report["status"] = "failed" if not report["frames"] else "completed"
        if report["executed_actions"]:
            report["executed_actions"][-1]["ok"] = False
            report["executed_actions"][-1]["error"] = report["crash"]
        report["warnings"].append(f"{type(exc).__name__}: {exc}")
    finally:
        write_report(report_path, report)

    if os.environ.get("AAAGF_BLENDER_EXIT_ON_DONE"):
        raise SystemExit(0 if report.get("status") == "completed" else 1)
    return 0 if report.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
