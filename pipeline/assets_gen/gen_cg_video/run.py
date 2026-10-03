"""
pipeline/assets_gen/gen_cg_video/run.py

CG video generation runner. Seedance and the hybrid MiniMax H3 backend fill the
same model slot without changing the operator or task schema.
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
    "minimax-h3": ("MiniMax-Hailuo-2.3", "MINIMAX_VIDEO_MODEL"),
}

#: 每个云端后端需要哪个 `.env` 服务商。`minimax-h3` 的 `local` 运行方式完全不需要
#: 服务商，因此它只在 api 路线下才被校验。
BACKEND_PROVIDERS: dict[str, tuple[str, ...]] = {
    "seedance": ("ark",),
    "minimax-h3": ("minimax",),
}


def resolve_ckpt(backend: str, cli_value: str | None) -> str:
    """Resolve CLI > environment > backend default, matching the 3D runner."""
    import os

    default, env_var = BACKENDS[backend]
    return cli_value or os.environ.get(env_var) or default


def load_model(
    ckpt: str,
    device: str = "cuda",
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

    if backend == "minimax-h3":
        from models.gen_cg_video.minimax_h3_model import MiniMaxH3Model

        model = MiniMaxH3Model(
            model_path=ckpt,
            device=device,
            **backend_kwargs,
        )
        print(
            f"[run] Using MiniMaxH3Model ({model.runtime}), "
            f"model={model.model_path}"
        )
        return model
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
        help="Local weights/HF repo id or cloud model version. "
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
        help="Cloud output resolution; defaults to 720p (Seedance) or 768P (MiniMax)",
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
        "--prompt-optimizer",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="MiniMax: enable provider prompt optimization",
    )
    parser.add_argument(
        "--fast-pretreatment",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="MiniMax: reduce prompt optimization latency",
    )
    parser.add_argument(
        "--minimax-runtime",
        choices=("auto", "api", "local"),
        default=os.environ.get("MINIMAX_H3_RUNTIME", "auto"),
        help="MiniMax H3 execution route; auto treats Hailuo ids as API and paths/HF ids as local",
    )
    parser.add_argument(
        "--comfyui-path",
        default=os.environ.get("COMFYUI_PATH"),
        help="MiniMax H3 local: ComfyUI source directory",
    )
    parser.add_argument(
        "--minimax-hf-revision",
        default=os.environ.get("MINIMAX_H3_HF_REVISION"),
        help="Optional revision of the Comfy-Org/MiniMax-H3 weight repository",
    )
    parser.add_argument(
        "--hf-cache-dir",
        default=os.environ.get("HUGGINGFACE_HUB_CACHE"),
        help="Hugging Face snapshot cache for local model ids",
    )
    parser.add_argument(
        "--local-files-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Do not contact Hugging Face; require already cached snapshots",
    )
    parser.add_argument(
        "--sampler-mode",
        choices=("res_multistep", "euler"),
        default="res_multistep",
        help="MiniMax H3 native ComfyUI sampler",
    )
    parser.add_argument(
        "--minimax-steps",
        type=int,
        default=20,
        help="MiniMax H3 native ComfyUI sampling steps",
    )
    parser.add_argument(
        "--minimax-scheduler",
        default="simple",
        help="MiniMax H3 native ComfyUI scheduler (official default: simple)",
    )
    parser.add_argument(
        "--ref-image-size",
        choices=("match", "max"),
        default="match",
        help="MiniMax H3 local R2V reference resolution policy",
    )
    parser.add_argument("--fps", type=float, default=None, help="Local video frame rate")
    parser.add_argument("--height", type=int, default=None, help="Local video height")
    parser.add_argument("--width", type=int, default=None, help="Local video width")
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
    parser.add_argument("--device", default="cuda")

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
    if args.backend == "seedance":
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
    else:
        backend_kwargs = {
            "runtime": args.minimax_runtime,
            "comfyui_path": args.comfyui_path,
            "hf_cache_dir": args.hf_cache_dir,
            "hf_revision": args.minimax_hf_revision,
            "local_files_only": args.local_files_only,
            "width": args.width or 864,
            "height": args.height or 480,
            "fps": args.fps or 24.0,
            "steps": args.minimax_steps,
            "scheduler": args.minimax_scheduler,
            "sampler_mode": args.sampler_mode,
            "ref_image_size": args.ref_image_size,
            "cache_dir": args.cache_dir,
            "timeout": args.timeout,
            "poll_interval": args.poll_interval,
            "max_retries": args.max_retries,
            "resolution": args.resolution or "768P",
            "prompt_optimizer": args.prompt_optimizer,
            "fast_pretreatment": args.fast_pretreatment,
            "verbose": True,
        }
    # 在生成之前失败。Seedance 一定是云端；MiniMax H3 的 `api` / `local` 是在模型
    # 内部决定的，所以它的检查放在构造之后（构造本身免费），此时 `model.runtime` 已知。
    if args.backend == "seedance":
        config.require_cloud_or_exit(
            BACKEND_PROVIDERS["seedance"],
            context=f"CG-video backend {args.backend!r}",
        )

    model = load_model(
        ckpt,
        device=args.device,
        backend=args.backend,
        **backend_kwargs,
    )

    if args.backend == "minimax-h3":
        if getattr(model, "runtime", None) != "local":
            config.require_cloud_or_exit(
                BACKEND_PROVIDERS["minimax-h3"],
                context="CG-video backend 'minimax-h3' (api runtime)",
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
