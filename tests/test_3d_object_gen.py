"""
tests/test_3d_object_gen.py

Integration test: loads Trellis2, runs the gen_3d_object pipeline on the
2 tasks in 3D_object_gen_collect.jsonl, asserts GLB files are created.

Run from repo root:
    TRELLIS2_CKPT=/path/to/TRELLIS.2-4B python tests/test_3d_object_gen.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# ── repo root on path ─────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
# ─────────────────────────────────────────────────────────────────────────────

# Local path takes priority; if empty, Trellis2Model will download from HuggingFace.
CKPT = os.environ.get("TRELLIS2_CKPT", "microsoft/TRELLIS.2-4B")
TASKS = _REPO_ROOT / "test_data" / "test_samples" / "3D_object_gen_collect.jsonl"
OUT_DIR = _REPO_ROOT / "outputs" / "test_3d_object"


class TestGen3DObjectPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # CKPT defaults to HuggingFace repo id; set TRELLIS2_CKPT=/local/path
        # to skip download and use local weights.
        from pipeline.assets_gen.gen_3d_object.run import load_model, make_operator
        cls.model = load_model(CKPT)
        cls.operator = make_operator(cls.model, output_dir=str(OUT_DIR))

    def test_tasks_jsonl_has_two_entries(self):
        import json
        tasks = [json.loads(l) for l in TASKS.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(tasks), 2, "Expected exactly 2 test tasks in jsonl.")

    def test_run_all_tasks(self):
        from pipeline.assets_gen.gen_3d_object.run import run_from_jsonl
        results = run_from_jsonl(str(TASKS), self.operator)

        self.assertEqual(len(results), 2)
        for r in results:
            glb = Path(r["glb_path"])
            self.assertTrue(glb.exists(), f"GLB not found: {glb}")
            self.assertGreater(glb.stat().st_size, 1024, "GLB file suspiciously small.")
            self.assertGreater(r["elapsed_sec"], 0)
            print(f"  [ok] {r['task_id']} → {glb.name}  ({r['elapsed_sec']}s)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
