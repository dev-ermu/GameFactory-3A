"""
AudioGen batch/single runner.

一次运行只做一件事，由子命令决定：

* ``batch``    读 jsonl 任务清单批量执行——``--game`` 定位某个游戏的任务集，
               ``--tasks`` 直接指定文件；
* ``single``   用命令行参数就地拼一条任务，不读 jsonl。

单条模式的内容输入只有 ``--prompt``，生成哪一路由 ``--audio-type`` 指定——模型
把 text 与 prompt 当同一个输入槽（见 ``SeedAudioModel._build_request``）。

两条路径的参数是同构的：单条模式的每个参数都对应 jsonl 里的一个字段，所以单条
模式既是快速试听，也是批处理任务的样板。字段与
``outputs/samples/<game>/audio/audio_tasks.jsonl`` 一致::

    game_id  task_id  audio_type  text  prompt  speaker_id
    emotion  language  sound_category  duration_sec  sample_rate  seed

两种模式各有各的参数表：把对方的参数传进来会被 argparse 直接拒绝
（unrecognized arguments），不会被静默忽略。

进度与结果走标准库 ``logging``（级别 INFO，默认输出到 stderr），因此 stdout
不承载日志，管道里可以放心使用。

Examples:
    # 批量：跑某个游戏的全部 audio 任务
    python pipeline/assets_gen/gen_audio/run.py batch --game gameA_fighting_arena_unity

    # 批量：只跑一路，跳过另一个模型
    python pipeline/assets_gen/gen_audio/run.py batch --audio-type dialogue

    # 单条：一句台词
    python pipeline/assets_gen/gen_audio/run.py single --audio-type dialogue \\
        --prompt "发现目标" --task-id spotted_target

    # 单条：一个音效
    python pipeline/assets_gen/gen_audio/run.py single --audio-type sound_effect \\
        --prompt "a single close futuristic rifle shot" --task-id rifle_shot
"""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from config import settings

from operators.gen_audio.operator import GenAudioOperator  # noqa: E402
from pipeline.common import config, paths  # noqa: E402

if TYPE_CHECKING:
    from models.gen_audio.seed_audio_model import SeedAudioModel

logger = logging.getLogger(__name__)

TASK_KIND = "audio"
DEFAULT_SEED_AUDIO_MODEL = "seed-audio-1.0"

# audio_type的合法取值
AUDIO_TYPES = ("dialogue", "sound_effect")


def load_seed_audio_model(
    mode: str,
    model_id: str = DEFAULT_SEED_AUDIO_MODEL,
    speaker_id: str | None = None,
    timeout: int = DEFAULT_TASK_TIMEOUT,
) -> "SeedAudioModel":
    """为一个 AudioGen 槽位加载 Seed Audio 封装。

    延迟 import：`SeedAudioModel` 会连带拉起 numpy / requests / openai，而
    参数解析与 `--help` 都不需要它们。

    Args:
        mode: 槽位用途，`dialogue` 或 `sound_effect`，仅用于日志。
        model_id: 要调用的 API 模型标识。
        speaker_id: dialogue 槽位的默认发音人；留空则交给算子运行时决定。
        timeout: 单个任务的等待上限，秒。

    Returns:
        配置好的 `SeedAudioModel`。
    """
    from models.gen_audio.seed_audio_model import SeedAudioModel

    logger.info("Loading SeedAudioModel (%s) from API model: %s", mode, model_id)

    return SeedAudioModel(
        model_id,
        speaker_id=speaker_id or "",
        timeout=timeout,
        verbose=True,
    )


def run_from_jsonl(
    tasks_path: str,
    operator: GenAudioOperator,
    game_filter: str | None = None,
    audio_type_filter: str | None = None,
) -> list[dict[str, Any]]:
    """逐条执行 jsonl 里的任务，可选按游戏或 audio_type 过滤。

    Args:
        tasks_path: 任务清单路径。
        operator: 已装配好的算子。
        game_filter: 只跑该游戏的任务。
        audio_type_filter: 只跑该 `audio_type` 的任务。

    Returns:
        每个成功任务的 `operator.run()` 结果。
    """
    results: list[dict[str, Any]] = []

    for task, game_id in paths.iter_tasks(tasks_path, game_filter=game_filter):
        audio_type = task.get("audio_type", "sound_effect")

        if audio_type_filter and audio_type != audio_type_filter:
            continue

        logger.info(
            "game=%s  task_id=%s  audio_type=%s",
            game_id, task.get("task_id", "?"), audio_type,
        )

        result = operator.run(task)

        logger.info("  -> audio=%s  (%ss)", result["audio_path"], result["elapsed_sec"])
        results.append(result)

    return results


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器"""
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--seed-audio-model",
        default=settings.seed_audio_model,
        help="Seed Audio API model id.",
    )
    common_parser.add_argument(
        "--speaker-id",
        default=settings.seed_audio_speaker_id,
        help="Speaker resource id; a task's own speaker_id wins over it.",
    )
    common_parser.add_argument(
        "--game",
        default=None,
        help=f"Game project id. Known: {paths.list_games() or '<none>'}",
    )
    common_parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds to wait for one task",
    )

    layout = common_parser.add_mutually_exclusive_group()
    layout.add_argument(
        "--run-id",
        default=paths.DEFAULT_RUN_ID,
        help="Run directory name; 'auto' for a timestamp",
    )
    layout.add_argument(
        "--out-dir",
        default=None,
        help="Legacy flat output dir; bypasses the per-game layout",
    )

    # 子命令，分为批量执行，单次执行两种模式
    parser = argparse.ArgumentParser(
        description="Generate dialogue and game SFX assets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    batch = subparsers.add_parser(
        "batch",
        parents=[common_parser],
        help="Read a jsonl task list and run every task.",
        description="批量执行任务，从指定jsonl文件中读取任务信息",
    )
    batch.add_argument(
        "--tasks",
        default=None,
        help="Explicit jsonl path (overrides the --game task-list lookup)",
    )
    batch.add_argument(
        "--audio-type",
        choices=AUDIO_TYPES,
        default=None,
        help="Run only this route (default: both).",
    )

    # 单次执行模式
    single = subparsers.add_parser(
        "single",
        parents=[common_parser],
        help="Build one task from the flags below and generate it.",
        description="单次执行任务，从参数中获取任务信息",
    )
    single.add_argument(
        "--audio-type",
        choices=AUDIO_TYPES,
        required=True,
        help="Which route to generate: dialogue or sound_effect.",
    )
    single.add_argument(
        "--prompt",
        required=True,
        help="Content for the model. For dialogue this is the spoken line.",
    )

    single.add_argument("--task-id", default=None, help="Task id (default: demo)")
    single.add_argument("--emotion", default=None, help="Delivery emotion")
    single.add_argument("--delivery", default=None, help="Extra delivery direction")
    single.add_argument("--language", default=None, help="Language tag (default: Auto)")
    single.add_argument(
        "--sample-rate",
        type=int,
        default=None,
        help="Requested sample rate; the operator resamples to it",
    )
    single.add_argument("--seed", type=int, default=None, help="Random seed (default: 42)")

    sfx_only = single.add_argument_group(
        "sound_effect only",
        "Only used when --audio-type sound_effect.",
    )
    sfx_only.add_argument(
        "--sound-category",
        choices=["one_shot", "ambience", "foley"],
        default=None,
        help="SFX category (default: one_shot)",
    )
    sfx_only.add_argument(
        "--duration-sec",
        type=float,
        default=None,
        help="Requested duration in seconds",
    )

    return parser


def build_single_task(args: argparse.Namespace) -> dict[str, Any]:
    """把命令行参数拼成一条任务，字段与 jsonl 任务一致。

    `--prompt` 落到该路真正消费的字段上：dialogue 用 `text`，sound_effect 用
    `prompt`（见 `GenAudioOperator.run`）。

    只写有值的键：算子对缺失字段有自己的默认值（例如 `speaker_id` 缺省为
    "Vivian"），显式塞 None 反而会被算子 `str()` 成 "None"。

    Args:
        args: 已解析的命令行参数。

    Returns:
        可直接交给算子运行的任务字典。
    """
    route = args.audio_type
    task: dict[str, Any] = {
        "task_id": args.task_id or "demo",
        "audio_type": route,
        "language": args.language or "Auto",
        "emotion": args.emotion or "",
        "delivery": args.delivery or "",
        "seed": 42 if args.seed is None else args.seed,
    }

    if args.game:
        task["game_id"] = args.game

    if route == "dialogue":
        task["text"] = args.prompt
    else:
        task["prompt"] = args.prompt

    if args.speaker_id:
        task["speaker_id"] = args.speaker_id

    if route == "sound_effect":
        task["sound_category"] = args.sound_category or "one_shot"

    if args.duration_sec is not None:
        task["duration_sec"] = args.duration_sec

    if args.sample_rate is not None:
        task["sample_rate"] = args.sample_rate

    return task


def build_operator(
    args: argparse.Namespace,
    active_filter: str | None,
    run_id: str,
) -> GenAudioOperator:
    """按需要加载模型槽位并装配算子。

    只加载本次要跑的那一路，避免为用不到的模型做无效初始化。

    Args:
        args: 已解析的命令行参数。
        active_filter: 本次要跑的 `audio_type`；`None` 表示两路都跑（批量模式）。
        run_id: 输出目录名。

    Returns:
        装配好的 `GenAudioOperator`。
    """
    # 在加载模型之前先失败：Seed Audio 槽位需要 `.env` 配置。
    if active_filter != "sound_effect":
        config.require_cloud_or_exit(("seed_audio",), context="dialogue slot")

    if active_filter != "dialogue":
        config.require_cloud_or_exit(("seed_audio",), context="sound-effect slot")

    dialogue_model = None
    sound_effect_model = None

    if active_filter != "sound_effect":
        dialogue_model = load_seed_audio_model(
            "dialogue",
            model_id=args.seed_audio_model,
            speaker_id=args.speaker_id,
            timeout=args.timeout,
        )

    if active_filter != "dialogue":
        sound_effect_model = load_seed_audio_model(
            "sound_effect",
            model_id=args.seed_audio_model,
            timeout=args.timeout,
        )

    return GenAudioOperator(
        dialogue_model=dialogue_model,
        sound_effect_model=sound_effect_model,
        output_dir=args.out_dir,
        run_id=run_id,
        default_game_id=args.game,
    )


def run_single(args: argparse.Namespace) -> None:
    """单条模式：用命令行拼一条任务，生成一份音频。"""
    run_id = paths.new_run_id() if args.run_id == "auto" else args.run_id
    operator = build_operator(args, args.audio_type, run_id)

    logger.info("Done: %s", operator.run(build_single_task(args)))


def run_batch(args: argparse.Namespace) -> None:
    """批量模式：读 jsonl 逐条生成，并按游戏写汇总。"""
    run_id = paths.new_run_id() if args.run_id == "auto" else args.run_id
    operator = build_operator(args, args.audio_type, run_id)

    tasks_path = paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)

    logger.info("run_id=%s  tasks=%s", run_id, paths.rel_to_repo(tasks_path))

    results = run_from_jsonl(
        str(tasks_path),
        operator,
        game_filter=args.game,
        audio_type_filter=args.audio_type,
    )

    if not results:
        logger.warning("No matching tasks — nothing to do.")
        return

    if args.out_dir:
        # 旧的扁平布局：汇总写在产物旁边，只给调试用。
        summary_path = Path(args.out_dir) / "results_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        logger.info("Wrote summary -> %s", summary_path)
        return

    for summary_path in paths.write_results_summary(results, TASK_KIND, run_id):
        logger.info("Wrote summary -> %s", paths.rel_to_repo(summary_path))


def main() -> None:
    # 可执行入口必须自己配置日志：不配置时根 logger 停在默认的 WARNING 级别，
    # 全部 INFO 输出会静默消失。库代码不配置日志，入口必须。
    
    LOG_FORMAT = "%(levelname)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "batch":
        run_batch(args)
        return

    run_single(args)


if __name__ == "__main__":
    main()
