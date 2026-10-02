"""
AudioGen batch/demo runner.

One registered ``audio`` task exposes two asset routes. Each route can use a
local model or the Seed Audio cloud API:
  * ``audio_type=dialogue``     -> Qwen3-TTS (default) / Seed Audio
  * ``audio_type=sound_effect`` -> Woosh-DFlow (default) / Seed Audio

Examples:
    python pipeline/assets_gen/gen_audio/run.py --game gameA_cyberpunk_shooter
    python pipeline/assets_gen/gen_audio/run.py --only-audio-type dialogue
    python pipeline/assets_gen/gen_audio/run.py --audio-type dialogue \
        --text "发现目标" --task-id spotted_target
    python pipeline/assets_gen/gen_audio/run.py --audio-type sound_effect \
        --prompt "a single futuristic rifle shot" --task-id rifle_shot
    python pipeline/assets_gen/gen_audio/run.py --dialogue-backend seed_audio \
        --audio-type dialogue --text "发现目标" \
        --cache-dir test_data/outputs/_api_cache
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.common import config, paths  # noqa: E402
from models.gen_audio.woosh_utils import (  # noqa: E402
    DEFAULT_WOOSH_RELEASE_BASE_URL,
)

TASK_KIND = "audio"
DEFAULT_DIALOGUE_CKPT = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DEFAULT_SOUND_EFFECT_CKPT = str(_REPO_ROOT / "checkpoints" / "Woosh-DFlow")
DEFAULT_WOOSH_AE_CKPT = str(_REPO_ROOT / "checkpoints" / "Woosh-AE")
DEFAULT_WOOSH_TEXT_CONDITIONER_CKPT = str(
    _REPO_ROOT / "checkpoints" / "TextConditionerA"
)
DEFAULT_SEED_AUDIO_MODEL = "seed-audio-1.0"
DIALOGUE_BACKENDS = ("qwen3_tts", "seed_audio")
SOUND_EFFECT_BACKENDS = ("woosh", "seed_audio")
DEFAULT_TASKS = paths.collect_jsonl(TASK_KIND)


def load_dialogue_model(ckpt: str, device: str = "cuda"):
    from models.gen_audio.qwen3_tts_model import Qwen3TTSModel

    print(f"[run] Loading Qwen3TTSModel from: {ckpt}")
    return Qwen3TTSModel(model_path=ckpt, device=device)


def load_sound_effect_model(
    ckpt: str,
    device: str = "cuda",
    num_steps: int = 4,
    cfg: float = 4.5,
    autoencoder_ckpt: str | None = None,
    text_conditioner_ckpt: str | None = None,
    auto_download: bool = True,
    release_base_url: str | None = None,
):
    from models.gen_audio.woosh_model import WooshDFlowModel

    release_base_url = release_base_url or os.environ.get(
        "WOOSH_RELEASE_BASE_URL",
        DEFAULT_WOOSH_RELEASE_BASE_URL,
    )
    print(f"[run] Loading WooshDFlowModel from: {ckpt}")
    print(f"[run]   Woosh-AE from: {autoencoder_ckpt}")
    print(f"[run]   TextConditionerA from: {text_conditioner_ckpt}")
    return WooshDFlowModel(
        model_path=ckpt,
        device=device,
        autoencoder_path=autoencoder_ckpt,
        text_conditioner_path=text_conditioner_ckpt,
        auto_download=auto_download,
        release_base_url=release_base_url,
        num_steps=num_steps,
        cfg=cfg,
    )


def load_seed_audio_model(
    mode: str,
    model_id: str = DEFAULT_SEED_AUDIO_MODEL,
    device: str = "cpu",
    cache_dir: str | None = None,
    speaker_id: str | None = None,
    api_base: str | None = None,
    http_timeout: int = 300,
    sample_rate: int = 24_000,
):
    """Load the synchronous Seed Audio API wrapper for one AudioGen slot."""
    from models.gen_audio.seed_audio_model import SeedAudioModel

    print(f"[run] Loading SeedAudioModel ({mode}) from API model: {model_id}")
    return SeedAudioModel(
        model_path=model_id,
        device=device,
        mode=mode,
        cache_dir=cache_dir,
        speaker_id=speaker_id,
        api_base=api_base,
        http_timeout=http_timeout,
        sample_rate=sample_rate,
        verbose=True,
    )


def make_operator(
    dialogue_model=None,
    sound_effect_model=None,
    output_dir: str | None = None,
    run_id: str = paths.DEFAULT_RUN_ID,
    default_game_id: str | None = None,
):
    """Wire the two model slots into the model-agnostic AudioGen operator."""
    from operators.gen_audio.operator import GenAudioOperator

    return GenAudioOperator(
        dialogue_model=dialogue_model,
        sound_effect_model=sound_effect_model,
        output_dir=output_dir,
        run_id=run_id,
        default_game_id=default_game_id,
    )


def generate(inp: dict, operator) -> dict:
    """Generate one audio asset."""
    return operator.run(inp)


def run_from_jsonl(
    tasks_path: str,
    operator,
    game_filter: str | None = None,
    audio_type_filter: str | None = None,
) -> list[dict]:
    """Run AudioGen tasks, optionally restricting dialogue or sound effects."""
    results = []
    for task, game_id in paths.iter_tasks(tasks_path, game_filter=game_filter):
        audio_type = task.get("audio_type", "sound_effect")
        if audio_type_filter and audio_type != audio_type_filter:
            continue
        print(
            f"[run] game={game_id}  task_id={task.get('task_id', '?')}  "
            f"audio_type={audio_type}"
        )
        result = generate(task, operator)
        print(f"       -> audio={result['audio_path']}  ({result['elapsed_sec']}s)")
        results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dialogue and game SFX assets.")
    parser.add_argument(
        "--dialogue-backend",
        choices=DIALOGUE_BACKENDS,
        default=os.environ.get("AAAGF_DIALOGUE_BACKEND", "qwen3_tts"),
        help="Dialogue model slot: local Qwen3-TTS or the Seed Audio API.",
    )
    parser.add_argument(
        "--sound-effect-backend",
        choices=SOUND_EFFECT_BACKENDS,
        default=os.environ.get("AAAGF_SOUND_EFFECT_BACKEND", "woosh"),
        help="Sound-effect model slot: local Woosh or the Seed Audio API.",
    )
    parser.add_argument(
        "--dialogue-ckpt",
        default=os.environ.get("QWEN3_TTS_CKPT", DEFAULT_DIALOGUE_CKPT),
    )
    parser.add_argument(
        "--sound-effect-ckpt",
        default=os.environ.get("WOOSH_DFLOW_CKPT", DEFAULT_SOUND_EFFECT_CKPT),
    )
    parser.add_argument(
        "--woosh-ae-ckpt",
        default=os.environ.get("WOOSH_AE_CKPT", DEFAULT_WOOSH_AE_CKPT),
    )
    parser.add_argument(
        "--woosh-text-conditioner-ckpt",
        default=os.environ.get(
            "WOOSH_TEXT_CONDITIONER_CKPT",
            DEFAULT_WOOSH_TEXT_CONDITIONER_CKPT,
        ),
    )
    parser.add_argument(
        "--woosh-release-base-url",
        default=os.environ.get(
            "WOOSH_RELEASE_BASE_URL",
            DEFAULT_WOOSH_RELEASE_BASE_URL,
        ),
        help="Official release base URL, or a mirror with the same zip filenames.",
    )
    parser.add_argument(
        "--no-auto-download",
        action="store_false",
        dest="auto_download",
        help="Fail instead of downloading missing Woosh checkpoints.",
    )
    parser.add_argument(
        "--seed-audio-model",
        default=os.environ.get("SEED_AUDIO_MODEL", DEFAULT_SEED_AUDIO_MODEL),
        help="Seed Audio API model id.",
    )
    parser.add_argument(
        "--seed-audio-api-base",
        default=config.get("SEED_AUDIO_API_BASE"),
        help="Override the Seed Audio API root configured in .env.",
    )
    parser.add_argument(
        "--seed-audio-speaker-id",
        default=os.environ.get("SEED_AUDIO_SPEAKER_ID"),
        help="Optional Seed Audio speaker resource id; Qwen speaker names are not reused.",
    )
    parser.add_argument(
        "--seed-audio-sample-rate",
        type=int,
        default=24_000,
        choices=[8000, 16000, 24000, 32000, 44100, 48000],
    )
    parser.add_argument(
        "--seed-audio-timeout",
        type=int,
        default=300,
        help="Per-request HTTP timeout in seconds for Seed Audio.",
    )
    parser.add_argument(
        "--cache-dir",
        default=config.api_cache_dir(),
        help="Cloud API response cache; reuse identical requests instead of "
             "paying twice (default: $AAAGF_API_CACHE).",
    )
    parser.add_argument("--game", default=None,
                        help=f"Game project id. Known: {paths.list_games() or '<none>'}")
    parser.add_argument("--tasks", default=None,
                        help="Explicit jsonl path (overrides the --game task-list lookup)")
    parser.add_argument("--run-id", default=paths.DEFAULT_RUN_ID,
                        help="Run directory name; 'auto' for a timestamp")
    parser.add_argument("--out-dir", default=None,
                        help="Legacy flat output dir; bypasses the per-game layout")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--woosh-steps", type=int, default=4)
    parser.add_argument("--woosh-cfg", type=float, default=4.5)
    parser.add_argument(
        "--only-audio-type",
        choices=["dialogue", "sound_effect"],
        default=None,
        help="Batch mode: run only one route and avoid loading the unused model.",
    )
    # Single-demo mode.
    parser.add_argument("--audio-type", choices=["dialogue", "sound_effect"], default=None)
    parser.add_argument("--text", default=None, help="Exact dialogue text (single-demo mode)")
    parser.add_argument("--prompt", default=None, help="SFX prompt (single-demo mode)")
    parser.add_argument("--task-id", default="demo")
    parser.add_argument("--speaker-id", default="Vivian")
    parser.add_argument("--emotion", default="")
    parser.add_argument("--delivery", default="")
    parser.add_argument("--language", default="Auto")
    parser.add_argument("--sound-category", choices=["one_shot", "ambience", "foley"],
                        default="one_shot")
    parser.add_argument("--duration-sec", type=float, default=None)
    parser.add_argument("--sample-rate", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    run_id = paths.new_run_id() if args.run_id == "auto" else args.run_id
    single_demo = args.audio_type is not None or args.text is not None or args.prompt is not None
    route = args.audio_type
    if single_demo and route is None:
        route = "dialogue" if args.text is not None else "sound_effect"
    if single_demo:
        if route == "dialogue" and not args.text:
            parser.error("A dialogue demo requires --text.")
        if route == "sound_effect" and not args.prompt:
            parser.error("A sound-effect demo requires --prompt.")

    active_filter = route if single_demo else args.only_audio_type

    # 在加载模型之前先失败：Seed Audio 槽位需要 `.env` 配置。
    if active_filter != "sound_effect" and args.dialogue_backend == "seed_audio":
        config.require_cloud_or_exit(
            ("seed_audio",), context="dialogue backend 'seed_audio'")
    if active_filter != "dialogue" and args.sound_effect_backend == "seed_audio":
        config.require_cloud_or_exit(
            ("seed_audio",), context="sound-effect backend 'seed_audio'")

    dialogue_model = None
    sound_effect_model = None
    if active_filter != "sound_effect":
        if args.dialogue_backend == "seed_audio":
            dialogue_model = load_seed_audio_model(
                "dialogue",
                model_id=args.seed_audio_model,
                device=args.device,
                cache_dir=args.cache_dir,
                speaker_id=args.seed_audio_speaker_id,
                api_base=args.seed_audio_api_base,
                http_timeout=args.seed_audio_timeout,
                sample_rate=args.seed_audio_sample_rate,
            )
        else:
            dialogue_model = load_dialogue_model(args.dialogue_ckpt, device=args.device)
    if active_filter != "dialogue":
        if args.sound_effect_backend == "seed_audio":
            sound_effect_model = load_seed_audio_model(
                "sound_effect",
                model_id=args.seed_audio_model,
                device=args.device,
                cache_dir=args.cache_dir,
                api_base=args.seed_audio_api_base,
                http_timeout=args.seed_audio_timeout,
                sample_rate=args.seed_audio_sample_rate,
            )
        else:
            sound_effect_model = load_sound_effect_model(
                args.sound_effect_ckpt,
                device=args.device,
                num_steps=args.woosh_steps,
                cfg=args.woosh_cfg,
                autoencoder_ckpt=args.woosh_ae_ckpt,
                text_conditioner_ckpt=args.woosh_text_conditioner_ckpt,
                auto_download=args.auto_download,
                release_base_url=args.woosh_release_base_url,
            )
    operator = make_operator(
        dialogue_model,
        sound_effect_model,
        output_dir=args.out_dir,
        run_id=run_id,
        default_game_id=args.game,
    )

    if single_demo:
        task = {
            "game_id": args.game,
            "task_id": args.task_id,
            "audio_type": route,
            "text": args.text,
            "prompt": args.prompt,
            "speaker_id": args.speaker_id,
            "emotion": args.emotion,
            "delivery": args.delivery,
            "language": args.language,
            "sound_category": args.sound_category if route == "sound_effect" else None,
            "duration_sec": args.duration_sec,
            "sample_rate": args.sample_rate,
            "seed": args.seed,
        }
        print(f"[run] Done: {generate(task, operator)}")
        return

    tasks_path = paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)
    print(f"[run] run_id={run_id}  tasks={paths.rel_to_repo(tasks_path)}")
    results = run_from_jsonl(
        str(tasks_path),
        operator,
        game_filter=args.game,
        audio_type_filter=args.only_audio_type,
    )
    if not results:
        print("[run] No matching tasks — nothing to do.")
        return

    if args.out_dir:
        summary_path = Path(args.out_dir) / "results_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"[run] Wrote summary -> {summary_path}")
    else:
        for summary_path in paths.write_results_summary(results, TASK_KIND, run_id):
            print(f"[run] Wrote summary -> {paths.rel_to_repo(summary_path)}")


if __name__ == "__main__":
    main()
