"""
pipeline/assets_gen/gen_cg_video/run.py

CG video generation runner. The Seedance cloud API fills the model slot.
"""

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.common import config, paths  # noqa: E402

TASK_KIND = "cg_video"
DEFAULT_CKPT = "doubao-seedance-2-0-260128"
DEFAULT_TASKS = paths.collect_jsonl(TASK_KIND)

# backend -> (default checkpoint/model id, environment override)
BACKENDS: dict[str, tuple[str, str]] = {
    "seedance": (DEFAULT_CKPT, "SEEDANCE_MODEL"),
}

BACKEND_PROVIDERS: dict[str, tuple[str, ...]] = {
    "seedance": ("ark",),
}


def resolve_ckpt(backend: str, cli_value: str | None) -> str:
    """Resolve CLI > environment > backend default, matching the 3D runner."""
    import os

    default, env_var = BACKENDS[backend]
    return cli_value or os.environ.get(env_var) or default


def load_model(
    ckpt: str,
    device: str = "cpu",
    backend: str = "seedance",
    **backend_kwargs,
):
    """Load the selected CG-video model backend."""
    if backend == "seedance":
        from models.gen_cg_video.seedance_model import SeedanceModel

        print(f"[run] Using SeedanceModel (cloud API), model={ckpt}")
        return SeedanceModel(
            model_path=ckpt,
            device=device,
            **backend_kwargs,
        )

    raise ValueError(f"Unknown backend {backend!r}. Known: {sorted(BACKENDS)}")


def make_operator(
    model,
    output_dir: str | None = None,
    run_id: str = paths.DEFAULT_RUN_ID,
    default_game_id: str | None = None,
):
    """Inject one loaded backend into the model-agnostic operator."""
    from operators.gen_cg_video.operator import GenCGVideoOperator

    return GenCGVideoOperator(
        model=model,
        output_dir=output_dir,
        run_id=run_id,
        default_game_id=default_game_id,
    )


def generate(inp: dict, operator) -> dict:
    """Generate one task through the public operator entry point."""
    return operator.run(inp)


def run_from_jsonl(
    tasks_path: str,
    operator,
    game_filter: str | None = None,
    task_filter: str | None = None,
) -> list[dict]:
    """Run every selected task from a standard 3AGameFactory JSONL file."""
    results = []
    for task, game_id in paths.iter_tasks(tasks_path, game_filter=game_filter):
        if task_filter and task.get("task_id") != task_filter:
            continue
        print(
            f"[run] game={game_id}  task_id={task.get('task_id', '?')}  "
            f"mode={task.get('mode', 'text_to_video')}"
        )
        result = generate(task, operator)
        print(
            f"       → video={result['video_path']}  "
            f"({result['elapsed_sec']}s)"
        )
        call = getattr(getattr(operator, "model", None), "last_call_info", None)
        if call:
            print(
                f"       → provider_task={call.get('task_id')}  "
                f"bytes={call.get('bytes')}  cached={call.get('cached')}"
            )
        results.append(result)
    return results


def main() -> None:
    import os

    parser = argparse.ArgumentParser(description="Run CG video generation.")
    parser.add_argument(
        "--backend",
        default=os.environ.get("GAMEFACTORY3A_VIDEO_BACKEND", "seedance"),
        choices=sorted(BACKENDS),
        help="Video model backend",
    )
    parser.add_argument(
        "--ckpt",
        default=None,
        help="Cloud model version. "
             "Precedence: flag > environment > backend default",
    )
    parser.add_argument(
        "--cache-dir",
        default=config.api_cache_dir(),
        help="Reuse identical billed requests without network traffic "
             "(default: $GAMEFACTORY3A_API_CACHE)",
    )
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--resolution",
        default=None,
        help="Cloud output resolution; defaults to 720p",
    )
    parser.add_argument("--ratio", default="16:9")
    parser.add_argument(
        "--generate-audio",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--watermark",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--game",
        default=None,
        help=f"Game project id. Known: {paths.list_games() or '<none>'}",
    )
    parser.add_argument(
        "--tasks",
        default=None,
        help="Explicit JSONL path, overriding the --game lookup",
    )
    parser.add_argument("--run-id", default=paths.DEFAULT_RUN_ID)
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Legacy flat output directory",
    )
    parser.add_argument("--device", default="cpu")

    # Single-task mode. Without --prompt, the runner uses JSONL batch mode.
    parser.add_argument("--prompt", default=None)
    parser.add_argument(
        "--mode",
        default="text_to_video",
        choices=(
            "text_to_video",
            "first_frame_to_video",
            "first_last_frame_to_video",
            "reference_to_video",
        ),
    )
    parser.add_argument("--first-frame", default=None)
    parser.add_argument("--last-frame", default=None)
    parser.add_argument(
        "--reference-image",
        action="append",
        default=None,
        help="Ordered reference image; repeat the flag for multiple images",
    )
    parser.add_argument("--duration-sec", type=float, default=5)
    parser.add_argument(
        "--task-id",
        default=None,
        help="Task id for single-prompt mode, or JSONL task filter in batch mode",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    run_id = paths.new_run_id() if args.run_id == "auto" else args.run_id
    ckpt = resolve_ckpt(args.backend, args.ckpt)
    backend_kwargs = {
        "cache_dir": args.cache_dir,
        "timeout": args.timeout,
        "poll_interval": args.poll_interval,
        "max_retries": args.max_retries,
        "resolution": args.resolution or "720p",
        "ratio": args.ratio,
        "generate_audio": args.generate_audio,
        "watermark": args.watermark,
        "verbose": True,
    }
    # 在生成之前失败：云端后端需要 `.env` 里的凭证。
    config.require_cloud_or_exit(
        BACKEND_PROVIDERS[args.backend],
        context=f"CG-video backend {args.backend!r}",
    )

    model = load_model(
        ckpt,
        device=args.device,
        backend=args.backend,
        **backend_kwargs,
    )

    operator = make_operator(
        model,
        output_dir=args.out_dir,
        run_id=run_id,
        default_game_id=args.game,
    )

    if args.prompt is not None:
        task = {
            "game_id": args.game,
            "task_id": args.task_id or "demo",
            "mode": args.mode,
            "prompt": args.prompt,
            "duration_sec": args.duration_sec,
            "seed": args.seed,
        }
        if args.first_frame:
            task["first_frame_path"] = args.first_frame
        if args.last_frame:
            task["last_frame_path"] = args.last_frame
        if args.reference_image:
            task["reference_image_paths"] = args.reference_image
        result = generate(task, operator)
        print(f"[run] Done: {result}")
        return

    tasks_path = paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)
    print(f"[run] run_id={run_id}  tasks={paths.rel_to_repo(tasks_path)}")
    results = run_from_jsonl(
        str(tasks_path),
        operator,
        game_filter=args.game,
        task_filter=args.task_id,
    )
    if not results:
        print("[run] No matching tasks — nothing to do.")
        return

    if args.out_dir:
        summary_path = Path(args.out_dir) / "results_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"[run] Wrote summary → {summary_path}")
    else:
        for summary_path in paths.write_results_summary(results, TASK_KIND, run_id):
            print(f"[run] Wrote summary → {paths.rel_to_repo(summary_path)}")


if __name__ == "__main__":
    main()
