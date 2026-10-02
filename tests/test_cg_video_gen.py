"""
tests/test_cg_video_gen.py

Real-generation integration test for every task in a local JSONL file.

The selected backend is loaded once, then every JSONL task is sent through the
real gen_cg_video pipeline and each generated MP4 is verified. This is the
single real-generation test entry point for Seedance API, MiniMax H3 API, and
MiniMax H3 local checkpoints. The lightweight operator contract checks remain
in tests/harness/.

Backend selection is deliberately explicit so an agent cannot accidentally
start a paid API request or a large checkpoint download. Every run requires
``CG_VIDEO_BACKEND`` and ``CG_VIDEO_TEST_TASKS``. MiniMax also requires
``MINIMAX_H3_RUNTIME``.

Seedance API:
    ARK_API_KEY=... \
    CG_VIDEO_BACKEND=seedance \
    CG_VIDEO_TEST_TASKS=/path/to/cg_tasks.jsonl \
    python tests/test_cg_video_gen.py

MiniMax API:
    MINIMAX_API_KEY=... \
    CG_VIDEO_BACKEND=minimax-h3 \
    MINIMAX_H3_RUNTIME=api \
    CG_VIDEO_TEST_TASKS=/path/to/cg_tasks.jsonl \
    python tests/test_cg_video_gen.py

MiniMax local checkpoint:
    CG_VIDEO_BACKEND=minimax-h3 \
    MINIMAX_H3_RUNTIME=local \
    CG_VIDEO_CKPT=/path/to/MiniMax-H3 \
    CG_VIDEO_TEST_TASKS=/path/to/cg_tasks.jsonl \
    python tests/test_cg_video_gen.py

Set ``CG_VIDEO_TEST_TASK_ID`` to reproduce only one task from the JSONL.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

from PIL import Image

# ── repo root on path ───────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
# ───────────────────────────────────────────────────────────────────────────────

BACKEND = os.environ.get("CG_VIDEO_BACKEND")
CKPT = os.environ.get("CG_VIDEO_CKPT")
TASKS_ENV = os.environ.get("CG_VIDEO_TEST_TASKS")
TASK_ID_ENV = os.environ.get("CG_VIDEO_TEST_TASK_ID")
OUT_DIR = Path(
    os.environ.get("CG_VIDEO_TEST_OUT_DIR", _REPO_ROOT / "outputs" / "test_cg_video")
).expanduser()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be a boolean (1/0, true/false, yes/no, on/off): {value!r}"
    )


def _env_number(name: str, default: int | float, cast):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return cast(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a valid {cast.__name__}: {value!r}") from exc


def _read_tasks(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """Parse JSONL with actionable line-number errors before model loading."""
    tasks = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            task = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} is not valid JSON: {exc}") from exc
        if not isinstance(task, dict):
            raise TypeError(f"{path}:{lineno} must contain one JSON object")
        tasks.append((lineno, task))
    if not tasks:
        raise RuntimeError(f"Expected at least 1 test task in {path}; found 0")
    return tasks


def _resolve_image(
    path: Path, lineno: int, task_id: str, key: str, value: Any
) -> None:
    """Verify a mode-control image exists and can be decoded."""
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{path}:{lineno} task={task_id!r}: {key} must be a path string")
    image_path = Path(value).expanduser()
    if not image_path.is_absolute():
        candidate = _REPO_ROOT / image_path
        image_path = image_path if image_path.exists() else candidate
    if not image_path.is_file():
        raise FileNotFoundError(
            f"{path}:{lineno} task={task_id!r}: {key} does not exist: {image_path}"
        )
    try:
        with Image.open(image_path) as image:
            image.verify()
    except Exception as exc:
        raise ValueError(
            f"{path}:{lineno} task={task_id!r}: {key} is not a readable image: "
            f"{image_path}"
        ) from exc


def _preflight_tasks(
    path: Path,
    records: list[tuple[int, dict[str, Any]]],
    backend: str,
    runtime: str | None,
    resolution: str,
) -> list[dict[str, Any]]:
    """Validate the complete batch before API access or checkpoint loading."""
    from models.gen_cg_video import VideoGenerationMode

    all_modes = {mode.value for mode in VideoGenerationMode}
    minimax_api_modes = {
        VideoGenerationMode.TEXT_TO_VIDEO.value,
        VideoGenerationMode.FIRST_FRAME_TO_VIDEO.value,
    }
    seen_ids: set[str] = set()
    tasks = []

    for lineno, task in records:
        task_id = task.get("task_id")
        prefix = f"{path}:{lineno} task={task_id!r}"
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"{prefix}: task_id must be a non-empty string")
        if task_id in seen_ids:
            raise ValueError(f"{prefix}: duplicate task_id would overwrite its output")
        seen_ids.add(task_id)

        mode = task.get("mode", VideoGenerationMode.TEXT_TO_VIDEO.value)
        if mode not in all_modes:
            raise ValueError(
                f"{prefix}: unsupported mode {mode!r}; expected one of {sorted(all_modes)}"
            )
        prompt = task.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"{prefix}: prompt must be a non-empty string")
        duration = task.get("duration_sec", 5)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration <= 0
        ):
            raise ValueError(f"{prefix}: duration_sec must be a positive number")
        seed = task.get("seed", 42)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError(f"{prefix}: seed must be an integer")

        if backend == "minimax-h3" and runtime == "api":
            if mode not in minimax_api_modes:
                raise NotImplementedError(
                    f"{prefix}: MiniMax H3 API does not support {mode}; "
                    f"supported modes: {sorted(minimax_api_modes)}"
                )
            if duration not in (6, 10):
                raise ValueError(
                    f"{prefix}: MiniMax H3 API duration_sec must be 6 or 10"
                )
            if resolution.upper() == "1080P" and duration != 6:
                raise ValueError(f"{prefix}: MiniMax H3 API supports 1080P only for 6s")
        if backend == "minimax-h3" and runtime == "local" and duration > 15:
            raise ValueError(f"{prefix}: MiniMax H3 local duration_sec must be <= 15")

        first = task.get("first_frame_path")
        last = task.get("last_frame_path")
        references = task.get("reference_image_paths")
        expected = {
            VideoGenerationMode.TEXT_TO_VIDEO.value: (False, False, False),
            VideoGenerationMode.FIRST_FRAME_TO_VIDEO.value: (True, False, False),
            VideoGenerationMode.FIRST_LAST_FRAME_TO_VIDEO.value: (True, True, False),
            VideoGenerationMode.REFERENCE_TO_VIDEO.value: (False, False, True),
        }[mode]
        actual = (first is not None, last is not None, references is not None)
        if actual != expected:
            raise ValueError(
                f"{prefix}: mode={mode!r} requires first_frame_path={expected[0]}, "
                f"last_frame_path={expected[1]}, reference_image_paths={expected[2]}; "
                f"got {actual}"
            )
        if first is not None:
            _resolve_image(path, lineno, task_id, "first_frame_path", first)
        if last is not None:
            _resolve_image(path, lineno, task_id, "last_frame_path", last)
        if references is not None:
            if not isinstance(references, list) or not references:
                raise ValueError(
                    f"{prefix}: reference_image_paths must be a non-empty list"
                )
            if (
                backend == "minimax-h3"
                and runtime == "local"
                and len(references) > 9
            ):
                raise ValueError(
                    f"{prefix}: MiniMax H3 local supports at most 9 references"
                )
            for index, reference in enumerate(references):
                _resolve_image(
                    path, lineno, task_id, f"reference_image_paths[{index}]", reference
                )
        tasks.append(task)
    return tasks


def _backend_kwargs(backend: str, runtime: str | None) -> dict[str, Any]:
    """Mirror the real runner's model settings through documented env vars."""
    cache_dir = os.environ.get("GAMEFACTORY3A_API_CACHE")
    if backend == "seedance":
        return {
            "cache_dir": cache_dir,
            "timeout": _env_number("SEEDANCE_TASK_TIMEOUT", 1800, int),
            "poll_interval": _env_number("SEEDANCE_POLL_INTERVAL", 3.0, float),
            "max_retries": _env_number("SEEDANCE_MAX_RETRIES", 3, int),
            "resolution": os.environ.get("SEEDANCE_RESOLUTION", "720p"),
            "ratio": os.environ.get("SEEDANCE_RATIO", "16:9"),
            "generate_audio": _env_bool("SEEDANCE_GENERATE_AUDIO", True),
            "watermark": _env_bool("SEEDANCE_WATERMARK", False),
            "verbose": True,
        }
    return {
        "runtime": runtime,
        "comfyui_path": os.environ.get("COMFYUI_PATH"),
        "hf_cache_dir": os.environ.get("HUGGINGFACE_HUB_CACHE"),
        "hf_revision": os.environ.get("MINIMAX_H3_HF_REVISION"),
        "local_files_only": _env_bool("MINIMAX_LOCAL_FILES_ONLY"),
        "width": _env_number("MINIMAX_WIDTH", 864, int),
        "height": _env_number("MINIMAX_HEIGHT", 480, int),
        "fps": _env_number("MINIMAX_FPS", 24.0, float),
        "steps": _env_number("MINIMAX_STEPS", 20, int),
        "scheduler": os.environ.get("MINIMAX_SCHEDULER", "simple"),
        "sampler_mode": os.environ.get("MINIMAX_SAMPLER_MODE", "res_multistep"),
        "ref_image_size": os.environ.get("MINIMAX_REF_IMAGE_SIZE", "match"),
        "cache_dir": cache_dir,
        "timeout": _env_number("MINIMAX_TASK_TIMEOUT", 1800, int),
        "poll_interval": _env_number("MINIMAX_POLL_INTERVAL", 3.0, float),
        "max_retries": _env_number("MINIMAX_MAX_RETRIES", 3, int),
        "resolution": os.environ.get("MINIMAX_RESOLUTION", "768P"),
        "prompt_optimizer": _env_bool("MINIMAX_PROMPT_OPTIMIZER", True),
        "fast_pretreatment": _env_bool("MINIMAX_FAST_PRETREATMENT", False),
        "verbose": True,
    }


class TestGenCGVideoPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not BACKEND:
            raise RuntimeError(
                "CG_VIDEO_BACKEND must be explicitly set to 'seedance' or "
                "'minimax-h3' before running a real generation test"
            )
        if not TASKS_ENV:
            raise RuntimeError(
                "CG_VIDEO_TEST_TASKS must point to a local cg_tasks.jsonl"
            )

        cls.tasks_path = Path(TASKS_ENV).expanduser()
        if not cls.tasks_path.is_absolute():
            cls.tasks_path = _REPO_ROOT / cls.tasks_path
        if not cls.tasks_path.is_file():
            raise FileNotFoundError(f"CG task JSONL not found: {cls.tasks_path}")

        from pipeline.assets_gen.gen_cg_video.run import (
            BACKENDS,
            load_model,
            make_operator,
            resolve_ckpt,
        )

        if BACKEND not in BACKENDS:
            raise RuntimeError(
                f"Unknown CG_VIDEO_BACKEND={BACKEND!r}; choose one of "
                f"{sorted(BACKENDS)}"
            )

        runtime = None
        if BACKEND == "minimax-h3":
            runtime = os.environ.get("MINIMAX_H3_RUNTIME")
            if runtime not in {"api", "local"}:
                raise RuntimeError(
                    "MINIMAX_H3_RUNTIME must be explicitly set to 'api' or 'local' "
                    "before running a real generation test"
                )

        backend_kwargs = _backend_kwargs(BACKEND, runtime)
        records = _read_tasks(cls.tasks_path)
        if TASK_ID_ENV:
            records = [
                record for record in records if record[1].get("task_id") == TASK_ID_ENV
            ]
            if not records:
                raise RuntimeError(
                    f"CG_VIDEO_TEST_TASK_ID={TASK_ID_ENV!r} was not found in "
                    f"{cls.tasks_path}"
                )
        cls.tasks = _preflight_tasks(
            cls.tasks_path,
            records,
            BACKEND,
            runtime,
            str(backend_kwargs["resolution"]),
        )
        ckpt = resolve_ckpt(BACKEND, CKPT)
        modes = ", ".join(
            sorted({task.get("mode", "text_to_video") for task in cls.tasks})
        )
        print("[test] CG Video real-generation plan")
        print(f"       backend={BACKEND}  runtime={runtime or 'api'}  model={ckpt}")
        print(f"       tasks={len(cls.tasks)}  modes={modes}")
        print(f"       jsonl={cls.tasks_path}")
        print(f"       output={OUT_DIR}")
        print("[test] Preflight passed; loading the selected backend now.")

        cls.model = load_model(
            ckpt,
            device=os.environ.get("CG_VIDEO_DEVICE", "cuda"),
            backend=BACKEND,
            **backend_kwargs,
        )
        cls.operator = make_operator(cls.model, output_dir=str(OUT_DIR))

    @classmethod
    def tearDownClass(cls):
        model = getattr(cls, "model", None)
        if model is not None:
            model.unload()

    def test_run_all_tasks(self):
        from pipeline.assets_gen.gen_cg_video.run import run_from_jsonl

        results = run_from_jsonl(
            str(self.tasks_path), self.operator, task_filter=TASK_ID_ENV
        )

        self.assertEqual(len(results), len(self.tasks))
        for result in results:
            video = Path(result["video_path"])
            self.assertTrue(video.exists(), f"MP4 not found: {video}")
            self.assertGreater(
                video.stat().st_size, 1024, "MP4 file suspiciously small."
            )
            with video.open("rb") as stream:
                self.assertIn(
                    b"ftyp", stream.read(64), "Generated artifact is not an MP4."
                )
            self.assertGreater(result["elapsed_sec"], 0)
            print(
                f"  [ok] {result['task_id']} → {video.name}  "
                f"({result['elapsed_sec']}s)"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
