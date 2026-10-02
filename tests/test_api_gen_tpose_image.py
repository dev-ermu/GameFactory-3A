"""
Paid集成测试：
加载Seedream Model，RMBG Model，运行与“gen_tpose_image” pipeline相同的tpose_gen_collect.json任务，
并断言成功创建透明的T形PNG文件。

Run from repo root:
    ARK_API_KEY=your-key \
    AAAGF_RUN_SEEDREAM_LIVE=1 \
    SEEDREAM_MODEL=doubao-seedream-5-0-260128 \
    RMBG_CKPT=briaai/RMBG-1.4 \
    python -m unittest tests.test_api_gen_tpose_image -v

Identical Seedream requests reuse the response cache unless
``AAAGF_SEEDREAM_DISABLE_CACHE=1`` is set.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

# ── repo root on path ─────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
# ─────────────────────────────────────────────────────────────────────────────

_RUN_LIVE = os.environ.get("AAAGF_RUN_SEEDREAM_LIVE") == "1"

# Keep this configuration block structurally aligned with test_gen_tpose_image.py.
GEN_CKPT = os.environ.get("SEEDREAM_MODEL", "doubao-seedream-5-0-260128")
MASK_CKPT = os.environ.get("RMBG_CKPT", "briaai/RMBG-1.4")
MASK_TYPE = "rmbg"
TASKS = _REPO_ROOT / "test_data" / "test_samples" / "tpose_gen_collect.jsonl"
OUT_DIR = _REPO_ROOT / "outputs" / "test_api_tpose"
CACHE_DIR = OUT_DIR / "cache"


class TestAPIGenTPoseImagePipeline(unittest.TestCase):
    """Seedream backend + unchanged RMBG backend over the canonical task JSONL."""

    @classmethod
    def setUpClass(cls):
        cls.gen_model = None
        cls.mask_model = None
        cls.operator = None

    @classmethod
    def _load_pipeline(cls):
        if cls.operator is not None:
            return
        if not os.environ.get("ARK_API_KEY"):
            raise RuntimeError(
                "ARK_API_KEY is required when AAAGF_RUN_SEEDREAM_LIVE=1"
            )

        from pipeline.assets_gen.gen_tpose_image.run import (
            load_gen_model,
            load_mask_model,
            make_operator,
        )

        disable_cache = os.environ.get("AAAGF_SEEDREAM_DISABLE_CACHE") == "1"
        cls.gen_model = load_gen_model(
            GEN_CKPT,
            backend="seedream",
            cache_dir=None if disable_cache else str(CACHE_DIR),
            size=os.environ.get("SEEDREAM_SIZE", "2048x2048"),
            watermark=os.environ.get("SEEDREAM_WATERMARK", "0") == "1",
            verbose=True,
        )
        cls.mask_model = load_mask_model(
            MASK_CKPT,
            device=os.environ.get("MASK_DEVICE", "cuda"),
            model_type=MASK_TYPE,
        )
        cls.operator = make_operator(
            cls.gen_model,
            cls.mask_model,
            output_dir=str(OUT_DIR),
        )

    @classmethod
    def tearDownClass(cls):
        for name in ("gen_model", "mask_model"):
            model = getattr(cls, name, None)
            if model is not None:
                model.unload()

    def test_tasks_jsonl_has_entries(self):
        tasks = [
            json.loads(line)
            for line in TASKS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(tasks), 1, "Expected at least 1 test task in jsonl.")

    def test_run_all_tasks(self):
        if not _RUN_LIVE:
            self.skipTest(
                "paid Seedream test requires AAAGF_RUN_SEEDREAM_LIVE=1"
            )
        self._load_pipeline()

        from pipeline.assets_gen.gen_tpose_image.run import run_from_jsonl

        results = run_from_jsonl(str(TASKS), self.operator)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(type(self.mask_model).__name__, "RMBGModel")
        for result in results:
            rgba_path = Path(result["tpose_rgba_path"])
            self.assertTrue(
                rgba_path.exists(),
                f"RGBA T-pose not found: {rgba_path}",
            )
            self.assertGreater(
                rgba_path.stat().st_size,
                1024,
                "RGBA PNG suspiciously small.",
            )
            with Image.open(rgba_path) as rgba:
                self.assertEqual(rgba.mode, "RGBA")
                alpha = np.asarray(rgba.getchannel("A"))
                self.assertLess(
                    int(alpha.min()),
                    255,
                    "RMBG output has no transparent pixels.",
                )
                self.assertGreater(
                    int(alpha.max()),
                    0,
                    "RMBG output is fully transparent.",
                )

            if result.get("tpose_rgb_path"):
                rgb_path = Path(result["tpose_rgb_path"])
                self.assertTrue(
                    rgb_path.exists(),
                    f"RGB T-pose not found: {rgb_path}",
                )
                self.assertGreater(
                    rgb_path.stat().st_size,
                    1024,
                    "RGB PNG suspiciously small.",
                )

            self.assertGreater(result["elapsed_sec"], 0)
            self.assertEqual(self.gen_model.last_call_info["provider"], "seedream")
            print(
                f"  [ok] {result['task_id']} → {rgba_path.name}  "
                f"({result['elapsed_sec']}s)"
            )


class TestSeedreamModelOffline(unittest.TestCase):
    """Small wrapper contract checks that spend no credits."""

    def test_construct_no_key(self):
        from models.gen_image.seedream_model import SeedreamModel

        model = SeedreamModel()
        self.assertEqual(model.PROVIDER, "seedream")
        self.assertEqual(model.model_path, GEN_CKPT)
        model.unload()

    def test_unload_idempotent(self):
        from models.gen_image.seedream_model import SeedreamModel

        model = SeedreamModel(device="cpu")
        model.unload()
        model.unload()

    def test_empty_prompt_raises(self):
        from models.gen_image.seedream_model import SeedreamModel

        model = SeedreamModel()
        with self.assertRaises(ValueError):
            model.infer(prompt="", seed=42)
        model.unload()


if __name__ == "__main__":
    unittest.main(verbosity=2)
