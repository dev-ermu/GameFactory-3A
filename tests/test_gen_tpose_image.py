"""
tests/test_gen_tpose_image.py

Integration test: loads QwenEditModel + RMBGModel, runs the gen_tpose_image
pipeline on the tasks in tpose_gen_collect.jsonl, asserts that transparent
T-pose PNG files are created.

Run from repo root:
    RMBG_CKPT=/path/to/RMBG-1.4 \
    python tests/test_tpose_gen.py
"""

import os
import sys
import unittest
from pathlib import Path

# ── repo root on path ─────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
# ─────────────────────────────────────────────────────────────────────────────

# The generator checkpoint is fixed (the pipeline's DEFAULT_GEN_CKPT); only the mask
# stage can be redirected at a local copy of the weights.
GEN_CKPT  = None
MASK_CKPT = os.environ.get("RMBG_CKPT",       "briaai/RMBG-1.4")
MASK_TYPE = os.environ.get("MASK_TYPE",       "rmbg")   # "rmbg" or "depth"
TASKS = _REPO_ROOT / "test_data" / "test_samples" / "tpose_gen_collect.jsonl"
OUT_DIR = _REPO_ROOT / "outputs" / "test_tpose"


class TestGenTPoseImagePipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from pipeline.assets_gen.gen_tpose_image.run import (
            load_gen_model,
            load_mask_model,
            make_operator,
        )
        cls.gen_model  = load_gen_model(GEN_CKPT)
        cls.mask_model = load_mask_model(MASK_CKPT, model_type=MASK_TYPE)
        cls.operator = make_operator(
            cls.gen_model,
            cls.mask_model,
            output_dir=str(OUT_DIR),
        )

    def test_tasks_jsonl_has_entries(self):
        import json
        tasks = [json.loads(l) for l in TASKS.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreaterEqual(len(tasks), 1, "Expected at least 1 test task in jsonl.")

    def test_run_all_tasks(self):
        from pipeline.assets_gen.gen_tpose_image.run import run_from_jsonl
        results = run_from_jsonl(str(TASKS), self.operator)

        self.assertGreaterEqual(len(results), 1)
        for r in results:
            rgba = Path(r["tpose_rgba_path"])
            self.assertTrue(rgba.exists(), f"RGBA T-pose not found: {rgba}")
            self.assertGreater(rgba.stat().st_size, 1024, "RGBA PNG suspiciously small.")
            if r.get("tpose_rgb_path"):
                rgb = Path(r["tpose_rgb_path"])
                self.assertTrue(rgb.exists(), f"RGB T-pose not found: {rgb}")
                self.assertGreater(rgb.stat().st_size, 1024, "RGB PNG suspiciously small.")
            self.assertGreater(r["elapsed_sec"], 0)
            print(f"  [ok] {r['task_id']} → {rgba.name}  ({r['elapsed_sec']}s)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
