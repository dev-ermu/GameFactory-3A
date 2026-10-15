"""
pipeline/assets_gen/gen_tpose_image/run.py

T-pose image generation demo runner.

Loads SeedreamModel (cloud API) and injects it into
GenTPoseImageOperator, reads tasks from
outputs/samples/tpose_gen_collect.jsonl (or a single game's
tpose_tasks.jsonl), and writes PNG outputs grouped per game project:

    outputs/runs/<game_id>/<run_id>/assets/tpose/<task_id>/tpose_fg.png

Usage:
    # Run all tasks in the default jsonl
    python pipeline/assets_gen/gen_tpose_image/run.py

    # Only one game project (prefers that game's own tpose_tasks.jsonl)
    python pipeline/assets_gen/gen_tpose_image/run.py --game gameA_cyberpunk_shooter

    # Fresh timestamped run dir instead of overwriting <game>/default/
    python pipeline/assets_gen/gen_tpose_image/run.py --run-id auto


    # Legacy flat output (bypasses the per-game layout; debugging only)
    python pipeline/assets_gen/gen_tpose_image/run.py --out-dir outputs/tpose

    # Single demo (image only, no jsonl)
    python pipeline/assets_gen/gen_tpose_image/run.py \
        --image path/to/character.png --task-id my_test \
        --description "A cheerful anime character with a red hat."
"""

import argparse
import json
import sys
from pathlib import Path

# ── Make repo root importable regardless of CWD ───────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ──────────────────────────────────────────────────────────────────────────────

from pipeline.common import config, paths  # noqa: E402

# Registered task kind — keys into paths.TASK_* tables.
TASK_KIND = "tpose"

# Default model identifiers. The selected backend decides which one is used
# when --gen-ckpt is omitted.
DEFAULT_SEEDREAM_MODEL = "doubao-seedream-5-0-260128"
DEFAULT_TASKS = paths.collect_jsonl(TASK_KIND)


def load_gen_model(
    model_id: str | None = None,
    backend: str = "seedream",
    **model_kwargs,
):
    """Load the selected image-generation backend."""
    if backend == "seedream":
        from models.gen_image.seedream_model import SeedreamModel
        resolved = model_id or DEFAULT_SEEDREAM_MODEL
        print(f"[run] Loading SeedreamModel (API): {resolved}")
        return SeedreamModel(resolved, **model_kwargs)
    raise ValueError(
        f"unsupported image generation backend {backend!r}; expected 'seedream'"
    )


def make_operator(
    gen_model,
    output_dir: str | None = None,
    run_id: str = paths.DEFAULT_RUN_ID,
    default_game_id: str | None = None,
):
    """
    Build the operator.

    Leave `output_dir` unset for the per-game layout. Passing it keeps the legacy
    flat `<output_dir>/<task_id>_tpose_fg.png` behaviour.
    """
    from operators.gen_tpose_image.operator import GenTPoseImageOperator
    return GenTPoseImageOperator(
        gen_model=gen_model,
        output_dir=output_dir,
        run_id=run_id,
        default_game_id=default_game_id,
    )


def generate(inp: dict, operator) -> dict:
    """Thin wrapper so eval.py can import and reuse."""
    return operator.run(inp)


def run_from_jsonl(tasks_path: str, operator, game_filter: str | None = None) -> list[dict]:
    """Iterate a jsonl file and run each task, optionally restricted to one game."""
    results = []
    for task, game_id in paths.iter_tasks(tasks_path, game_filter=game_filter):
        print(f"[run] game={game_id}  task_id={task.get('task_id', '?')}  "
              f"image={task.get('image_path', '?')}")
        result = generate(task, operator)
        print(f"       → rgba={result['tpose_rgba_path']}  ({result['elapsed_sec']}s)")
        results.append(result)
    return results


def main():
    import os

    parser = argparse.ArgumentParser(description="Run T-pose generation.")
    parser.add_argument(
        "--gen-backend",
        default=os.environ.get("TPOSE_GEN_BACKEND", "seedream"),
        choices=["seedream"],
        help="Image-gen backend. Only the Seedream cloud API is available.",
    )
    parser.add_argument(
        "--gen-ckpt",
        default=None,
        help="Model checkpoint/version; omitted selects the backend-specific env/default",
    )
    parser.add_argument("--game",      default=None,
                        help=f"Game project id. Known: {paths.list_games() or '<none>'}")
    parser.add_argument("--tasks",     default=None,
                        help="Explicit jsonl path (overrides the --game task-list lookup)")
    parser.add_argument("--run-id",    default=paths.DEFAULT_RUN_ID,
                        help="Run directory name; 'auto' for a timestamp")
    parser.add_argument("--out-dir",   default=None,
                        help="Legacy flat output dir; bypasses the per-game layout")
                        # Single-demo mode
    parser.add_argument("--image",       default=None, help="Path to a single image (demo mode)")
    parser.add_argument("--task-id",     default="demo")
    parser.add_argument("--description", default="")
    parser.add_argument("--seed",        type=int, default=42)
    parser.add_argument("--steps",       type=int, default=40)
    parser.add_argument("--target-size", type=int, default=1024)
    args = parser.parse_args()

    run_id = paths.new_run_id() if args.run_id == "auto" else args.run_id

    gen_ckpt = args.gen_ckpt or config.settings.seedream_model

    # 在加载任何东西之前先失败：云端生成后端需要 `.env` 里的凭证。
    if args.gen_backend == "seedream":
        config.require_cloud_or_exit(
            ("ark",), context="T-pose generator backend 'seedream'")

    gen_model = load_gen_model(
        gen_ckpt,
        backend=args.gen_backend,
    )
    operator = make_operator(gen_model, output_dir=args.out_dir,
                             run_id=run_id, default_game_id=args.game)

    if args.image:
        result = generate(
            {
                "image_path":  args.image,
                "task_id":     args.task_id,
                "game_id":     args.game,
                "description": args.description,
                "seed":        args.seed,
                "steps":       args.steps,
                "target_size": args.target_size,
            },
            operator,
        )
        print(f"[run] Done: {result}")
        return

    tasks_path = paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)
    print(f"[run] run_id={run_id}  tasks={paths.rel_to_repo(tasks_path)}")
    results = run_from_jsonl(str(tasks_path), operator, game_filter=args.game)
    if not results:
        print("[run] No matching tasks — nothing to do.")
        return

    if args.out_dir:
        # Legacy flat mode: keep the single summary next to the artifacts.
        summary_path = Path(args.out_dir) / "results_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"[run] Wrote summary → {summary_path}")
    else:
        for p in paths.write_results_summary(results, TASK_KIND, run_id):
            print(f"[run] Wrote summary → {paths.rel_to_repo(p)}")


if __name__ == "__main__":
    main()
