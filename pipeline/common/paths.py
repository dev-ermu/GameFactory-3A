"""
pipeline/common/paths.py

Single source of truth for every input / output path in 3AGameFactory.

The benchmark is authored **per game project**, so outputs are organized the same
way. An artifact is uniquely addressed by ``(game_id, run_id, task_kind, task_id)``::

    test_data/test_samples/<game_id>/<TaskDir>/...                        # inputs (read-only)
    test_data/outputs/<game_id>/<run_id>/<layer>/<task_kind>/<task_id>/   # outputs

Full output tree::

    test_data/outputs/                         # OUTPUT_ROOT ($AAAGF_OUTPUT_ROOT)
    └── gameA_cyberpunk_shooter/               # one dir per generated game project
        ├── latest -> 20260731_1032/           # symlink to the most recent run
        └── <run_id>/                          # "default", or a timestamp
            ├── run_meta.json                  # ckpts · seeds · git sha · argv
            ├── assets/
            │   ├── 3d_object/<task_id>/       # model.glb        + meta.json
            │   ├── tpose/<task_id>/           # tpose_fg.png     + meta.json
            │   ├── 3d_scene/<task_id>/
            │   ├── motion/<task_id>/
            │   ├── cg_video/<task_id>/
            │   └── audio/<task_id>/            # dialogue / sound-effect audio + meta.json
            ├── mechanic/<task_id>/            # engine project + demo_outputs/ + launch.sh
            ├── ui/<task_id>/
            ├── pipeline/<task_id>/            # end-to-end game-slice artifacts
            └── eval/
                ├── <task_kind>/<task_id>/     # metrics.json · build.log · judge_log.json
                └── summary.json               # aggregate over the whole run

The root stays next to the test set so any evaluator finds inputs and outputs side
by side. Generated artifacts get large — point ``$AAAGF_OUTPUT_ROOT`` at a scratch
disk to relocate the whole tree without touching code.

本模块**不依赖任何第三方库**，也不 import 任何 model，因此可以在任何地方安全 import
（包括纯 CPU 的工具与测试）。它唯一的项目内依赖是 `global_config`——那个只依赖标准库的
配置模块；导入它即完成 `<repo>/.env` 的解析，之后所有配置一律从 `settings` 对象读取。
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# `global_config` 位于顶层且只依赖标准库，因此 `models/` 可以 import 它而不必
# import `pipeline/`（model_require.md R1.1）。
_CONFIG_ROOT = Path(__file__).resolve().parents[2]
if str(_CONFIG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONFIG_ROOT))
import global_config as _global_config  # noqa: E402

# 过渡桥：把 `.env` 发布进 `os.environ`，供**尚未迁移**的读取方使用——目前是 6 个
# `engine_adapters/*/config.py`（它们在 `resolve()` 里读 `os.environ`）以及若干
# `models/` / `scripts/`。等这些全部改读 `settings` 之后，本行与 `global_config.load()`
# 一并删除。本模块自身的 `OUTPUT_ROOT` 已改读 `settings`，不再依赖这个副作用。
_global_config.load()

# ── Roots ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]

TEST_DATA_ROOT = REPO_ROOT / "test_data"
TEST_SAMPLES_ROOT = TEST_DATA_ROOT / "test_samples"

#: Output root — 即 `Settings.output_root`（`.env` 里的 `AAAGF_OUTPUT_ROOT`），
#: 默认 `<repo>/test_data/outputs`。
OUTPUT_ROOT = Path(_global_config.settings.output_root).expanduser()

#: Used when a task carries no game association (ad-hoc single-image demos).
UNASSIGNED_GAME = "_scratch"

#: Run id used when the caller does not ask for a fresh timestamped one.
DEFAULT_RUN_ID = "default"

LATEST_LINK = "latest"


# ── Task kinds ────────────────────────────────────────────────────────────────

#: task_kind -> layer directory. Layer A = assets, B = mechanic, C = ui.
TASK_LAYER: dict[str, str] = {
    # Layer A — asset generation
    "3d_object": "assets",
    "tpose": "assets",
    "3d_scene": "assets",
    "motion": "assets",
    "cg_video": "assets",
    "audio": "assets",
    # Layer B / C — code generation
    "mechanic": "mechanic",
    "ui": "ui",
    # End-to-end vertical slice
    "pipeline": "pipeline",
}

#: task_kind -> directory name inside ``test_samples/<game_id>/``.
TASK_INPUT_DIR: dict[str, str] = {
    "3d_object": "3D_object",
    "tpose": "tpose",
    "3d_scene": "3D_scene",
    "motion": "motion",
    "cg_video": "cg_video",
    "audio": "audio",
    "mechanic": "mechanic",
    "ui": "ui",
    "pipeline": "pipeline",
}

#: task_kind -> per-game task list filename inside ``TASK_INPUT_DIR``.
TASK_JSONL: dict[str, str] = {
    "3d_object": "object_tasks.jsonl",
    "tpose": "tpose_tasks.jsonl",
    "3d_scene": "scene_tasks.jsonl",
    "motion": "motion_tasks.jsonl",
    "cg_video": "cg_tasks.jsonl",
    "audio": "audio_tasks.jsonl",
    "mechanic": "mechanic_tasks.jsonl",
    "ui": "ui_tasks.jsonl",
    "pipeline": "pipeline_task.jsonl",
}

#: task_kind -> cross-game aggregate jsonl under ``test_samples/``.
TASK_COLLECT_JSONL: dict[str, str] = {
    "3d_object": "3D_object_gen_collect.jsonl",
    "tpose": "tpose_gen_collect.jsonl",
    "3d_scene": "3D_scene_gen_collect.jsonl",
    "motion": "motion_gen_collect.jsonl",
    "cg_video": "cg_video_collect.jsonl",
    "audio": "audio_gen_collect.jsonl",
    "mechanic": "mechanic_collect.jsonl",
    "ui": "ui_collect.jsonl",
    "pipeline": "pipeline_collect.jsonl",
}

#: Layer-A kinds only — what ``pipeline/assets_gen/`` covers.
ASSET_TASK_KINDS = tuple(k for k, v in TASK_LAYER.items() if v == "assets")


def check_kind(task_kind: str) -> str:
    """Raise a helpful error for an unregistered task kind."""
    if task_kind not in TASK_LAYER:
        raise ValueError(
            f"Unknown task_kind {task_kind!r}. Register it in "
            f"pipeline/common/paths.py first. Known: {sorted(TASK_LAYER)}"
        )
    return task_kind


# ── Input paths ───────────────────────────────────────────────────────────────

def game_input_dir(game_id: str) -> Path:
    """``test_data/test_samples/<game_id>/``"""
    return TEST_SAMPLES_ROOT / game_id


def task_input_dir(game_id: str, task_kind: str) -> Path:
    """``test_data/test_samples/<game_id>/<TaskDir>/``"""
    return game_input_dir(game_id) / TASK_INPUT_DIR[check_kind(task_kind)]


def task_jsonl(game_id: str, task_kind: str) -> Path:
    """``test_data/test_samples/<game_id>/<TaskDir>/<kind>_tasks.jsonl``"""
    return task_input_dir(game_id, task_kind) / TASK_JSONL[check_kind(task_kind)]


def collect_jsonl(task_kind: str) -> Path:
    """``test_data/test_samples/<kind>_collect.jsonl`` — cross-game task list."""
    return TEST_SAMPLES_ROOT / TASK_COLLECT_JSONL[check_kind(task_kind)]


def resolve_tasks_path(task_kind: str, tasks: str | None = None,
                       game_id: str | None = None) -> Path:
    """
    Standard task-list resolution shared by every ``run.py`` / ``eval.py``:

    explicit ``--tasks``  →  the game's own ``*_tasks.jsonl`` (if non-empty)
                          →  the cross-game ``*_collect.jsonl``.
    """
    if tasks:
        return resolve_input_path(tasks)
    if game_id:
        per_game = task_jsonl(game_id, task_kind)
        if per_game.exists() and per_game.stat().st_size > 0:
            return per_game
    return collect_jsonl(task_kind)


def list_games() -> list[str]:
    """Every game project directory present in the test set."""
    if not TEST_SAMPLES_ROOT.is_dir():
        return []
    return sorted(
        p.name
        for p in TEST_SAMPLES_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    )


def infer_game_id(task: dict, fallback: Optional[str] = None) -> str:
    """
    Resolve which game project a task belongs to.

    Priority: explicit ``game_id`` / ``game`` field  →  any path-like field that
    sits under ``test_samples/<game_id>/``  →  ``fallback``  →  ``UNASSIGNED_GAME``.
    """
    for key in ("game_id", "game"):
        if task.get(key):
            return str(task[key])

    for value in task.values():
        if not isinstance(value, str) or "test_samples" not in value:
            continue
        parts = Path(value).parts
        if "test_samples" in parts:
            idx = parts.index("test_samples")
            if idx + 1 < len(parts):
                return parts[idx + 1]

    return fallback or UNASSIGNED_GAME


def iter_tasks(tasks_path: str | Path, game_filter: str | None = None):
    """
    Yield ``(task_dict, game_id)`` from a jsonl, skipping blanks and comments.

    Every runner should iterate through this so `game_id` resolution and the
    `--game` filter behave identically across tasks.
    """
    with open(tasks_path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                task = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{tasks_path}:{lineno} is not valid JSON: {e}") from e
            game_id = infer_game_id(task)
            if game_filter and game_id != game_filter:
                continue
            yield task, game_id


# ── Output paths ──────────────────────────────────────────────────────────────

def new_run_id(prefix: str = "") -> str:
    """Timestamped run id, e.g. ``20260731_103200`` or ``qwen3b_20260731_103200``."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}" if prefix else stamp


def game_output_dir(game_id: str) -> Path:
    """``test_data/outputs/<game_id>/``"""
    return OUTPUT_ROOT / game_id


def run_dir(game_id: str, run_id: str = DEFAULT_RUN_ID) -> Path:
    """``test_data/outputs/<game_id>/<run_id>/`` — root of one generation run."""
    return game_output_dir(game_id) / run_id


def task_output_dir(
    game_id: str,
    task_kind: str,
    task_id: str,
    run_id: str = DEFAULT_RUN_ID,
    create: bool = True,
) -> Path:
    """
    ``test_data/outputs/<game_id>/<run_id>/<layer>/[<task_kind>/]<task_id>/``

    One directory per task, so an artifact ships alongside its preview,
    intermediates and ``meta.json`` without filename mangling.
    """
    check_kind(task_kind)
    layer = TASK_LAYER[task_kind]
    base = run_dir(game_id, run_id) / layer
    # assets/ is further split by kind; mechanic/ ui/ pipeline/ *are* the kind.
    if layer == "assets":
        base = base / task_kind
    path = base / task_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def eval_output_dir(
    game_id: str,
    task_kind: str,
    task_id: str,
    run_id: str = DEFAULT_RUN_ID,
    create: bool = True,
) -> Path:
    """``test_data/outputs/<game_id>/<run_id>/eval/<task_kind>/<task_id>/``"""
    check_kind(task_kind)
    path = run_dir(game_id, run_id) / "eval" / task_kind / task_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def eval_summary_path(game_id: str, run_id: str = DEFAULT_RUN_ID) -> Path:
    """``test_data/outputs/<game_id>/<run_id>/eval/summary.json``"""
    return run_dir(game_id, run_id) / "eval" / "summary.json"


def results_summary_path(game_id: str, task_kind: str,
                         run_id: str = DEFAULT_RUN_ID) -> Path:
    """``test_data/outputs/<game_id>/<run_id>/<task_kind>_results_summary.json``"""
    check_kind(task_kind)
    return run_dir(game_id, run_id) / f"{task_kind}_results_summary.json"


def run_meta_path(game_id: str, run_id: str = DEFAULT_RUN_ID) -> Path:
    """``test_data/outputs/<game_id>/<run_id>/run_meta.json``"""
    return run_dir(game_id, run_id) / "run_meta.json"


# ── Run bookkeeping ───────────────────────────────────────────────────────────

def _git_sha() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def update_latest_link(game_id: str, run_id: str) -> None:
    """Repoint ``<game_id>/latest`` at ``run_id`` (best effort, never fatal)."""
    if run_id == LATEST_LINK:
        return
    link = game_output_dir(game_id) / LATEST_LINK
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(run_id, target_is_directory=True)
    except OSError:
        pass  # filesystem without symlink support — not fatal


def write_run_meta(
    game_id: str,
    run_id: str = DEFAULT_RUN_ID,
    *,
    task_kind: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> Path:
    """Record how a run was produced, so results stay reproducible."""
    path = run_meta_path(game_id, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "game_id": game_id,
        "run_id": run_id,
        "task_kind": task_kind,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "argv": sys.argv,
    }
    if extra:
        meta.update(extra)

    if path.exists():  # merge with an earlier task_kind in the same run
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            history = prev.pop("history", [])
            history.append(prev)
            meta["history"] = history
        except (json.JSONDecodeError, OSError):
            pass

    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_task_meta(task_dir: str | Path, meta: dict[str, Any]) -> Path:
    """Write ``<task_dir>/meta.json`` next to the artifacts."""
    d = Path(task_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return path


def write_results_summary(results: list[dict], task_kind: str,
                         run_id: str = DEFAULT_RUN_ID) -> list[Path]:
    """
    Group ``run()`` results by ``game_id`` and write one summary per game,
    refresh ``run_meta.json`` and the ``latest`` symlink.

    Returns the summary paths written.
    """
    check_kind(task_kind)
    grouped: dict[str, list[dict]] = {}
    for r in results:
        grouped.setdefault(r.get("game_id") or UNASSIGNED_GAME, []).append(r)

    written = []
    for game_id, items in grouped.items():
        path = results_summary_path(game_id, task_kind, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
        write_run_meta(game_id, run_id, task_kind=task_kind,
                       extra={"num_tasks": len(items)})
        update_latest_link(game_id, run_id)
        written.append(path)
    return written


# ── Misc ──────────────────────────────────────────────────────────────────────

def resolve_input_path(path_like: str | Path) -> Path:
    """Resolve a possibly repo-relative input path (jsonl paths are repo-relative)."""
    p = Path(path_like)
    if p.is_absolute() or p.exists():
        return p
    return REPO_ROOT / p


def rel_to_repo(path: str | Path) -> str:
    """Repo-relative string if possible, else the absolute path — for logs / meta."""
    p = Path(path).resolve()
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)
