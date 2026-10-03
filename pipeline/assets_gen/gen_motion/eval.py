"""Evaluate existing motion artifacts without invoking models or Blender."""

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.common import paths  # noqa: E402


TASK_KIND = "motion"


def _result_for_task(
    game_id: str,
    run_id: str,
    task_id: str,
    task_type: str,
) -> dict:
    root = paths.task_output_dir(
        game_id,
        TASK_KIND,
        task_id,
        run_id=run_id,
        create=False,
    )
    return {
        "task_id": task_id,
        "retargeted_fbx_path": str(root / "retargeted.fbx"),
        "anim_only_fbx_path": str(root / "animation.fbx"),
        "mapping_path": str(root / "mapping.json"),
        "retarget_info_path": str(root / "retarget_info.json"),
        "rig_path": str(root / "rig.txt"),
        "skeleton_path": str(root / "skeleton.txt"),
        "mesh_obj_path": str(root / "mesh.obj"),
        "motion_bvh_path": str(root / "motion.bvh"),
        "raw_motion_bvh_path": str(root / "motion_raw.bvh"),
        "ik_motion_bvh_path": str(root / "motion_ik.bvh"),
        "joints_npy_path": str(root / "joints.npy"),
        "preview_mp4_path": str(root / "preview.mp4"),
        "game_id": game_id,
        "task_kind": TASK_KIND,
        "task_type": task_type,
        "output_dir": str(root),
        "elapsed_sec": 0.0,
    }


def evaluate_tasks(
    tasks_path: str,
    *,
    game_filter: str | None,
    run_id: str,
) -> list[dict[str, Any]]:
    """Score existing motion artifacts and continue past individual errors."""
    from operators.gen_motion.operator import GenMotionOperator

    operator = GenMotionOperator(run_id=run_id)
    scores = []
    for task, inferred_game in paths.iter_tasks(
        tasks_path,
        game_filter=game_filter,
    ):
        game_id = str(task.get("game_id") or inferred_game or game_filter or "")
        task_id = str(task.get("task_id") or "")
        metrics_dir = paths.eval_output_dir(
            game_id,
            TASK_KIND,
            task_id,
            run_id=run_id,
        )
        metrics_path = metrics_dir / "metrics.json"
        try:
            result = _result_for_task(
                game_id,
                run_id,
                task_id,
                str(task.get("task_type", "retarget")),
            )
            if not bool(task.get("export_anim_only", True)):
                result["anim_only_fbx_path"] = None
            score = operator.eval(result, task)
        except Exception as exc:
            score = {
                "task_id": task_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
        metrics_path.write_text(
            json.dumps(score, indent=2),
            encoding="utf-8",
        )
        print(f"[eval] {game_id}/{task_id} -> {metrics_path}")
        scores.append({"game_id": game_id, **score})
    return scores


def _aggregate(scores: list[dict[str, Any]]) -> dict[str, Any]:
    numeric: dict[str, list[float]] = {}
    for score in scores:
        if "error" in score:
            continue
        for key, value in score.items():
            if isinstance(value, bool):
                numeric.setdefault(key, []).append(float(value))
            elif isinstance(value, (int, float)):
                numeric.setdefault(key, []).append(float(value))
    means = {
        key: round(statistics.fmean(values), 4)
        for key, values in numeric.items()
        if values
    }
    return {
        "task_kind": TASK_KIND,
        "task_count": len(scores),
        "error_count": sum("error" in item for item in scores),
        "metric_means": means,
        "tasks": scores,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", default=None)
    parser.add_argument("--run-id", default=paths.DEFAULT_RUN_ID)
    parser.add_argument("--tasks", default=None)
    args = parser.parse_args()

    tasks_path = paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)
    scores = evaluate_tasks(
        str(tasks_path),
        game_filter=args.game,
        run_id=args.run_id,
    )
    if not scores:
        print("[eval] No matching tasks - nothing to evaluate.")
        return

    by_game: dict[str, list[dict[str, Any]]] = {}
    for score in scores:
        by_game.setdefault(score["game_id"], []).append(score)
    for game_id, game_scores in by_game.items():
        summary_path = paths.eval_summary_path(game_id, args.run_id)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(_aggregate(game_scores), indent=2),
            encoding="utf-8",
        )
        print(f"[eval] summary -> {summary_path}")


if __name__ == "__main__":
    main()
