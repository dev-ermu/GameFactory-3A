"""
tests/test_audio_gen.py

Integration test: loads Qwen3-TTS + Woosh-DFlow, runs the gen_audio pipeline
on the tasks in audio_gen_collect.jsonl, and asserts WAV files are created.

Run from repo root:
    QWEN3_TTS_CKPT=/path/to/Qwen3-TTS-12Hz-0.6B-CustomVoice \
    WOOSH_DFLOW_CKPT=/path/to/Woosh-DFlow \
    WOOSH_AE_CKPT=/path/to/Woosh-AE \
    WOOSH_TEXT_CONDITIONER_CKPT=/path/to/TextConditionerA \
    python tests/test_audio_gen.py
"""
from __future__ import annotations

import os
import sys
import unittest
import wave
from pathlib import Path

# -- repo root on path ---------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
# -----------------------------------------------------------------------------

# Local paths take priority. Qwen3-TTS can fall back to its Hugging Face repo;
# Missing Woosh checkpoints are downloaded from the official release on first use.
DIALOGUE_CKPT = os.environ.get(
    "QWEN3_TTS_CKPT",
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
)
SOUND_EFFECT_CKPT = os.environ.get(
    "WOOSH_DFLOW_CKPT",
    str(_REPO_ROOT / "checkpoints" / "Woosh-DFlow"),
)
WOOSH_AE_CKPT = os.environ.get(
    "WOOSH_AE_CKPT",
    str(_REPO_ROOT / "checkpoints" / "Woosh-AE"),
)
WOOSH_TEXT_CONDITIONER_CKPT = os.environ.get(
    "WOOSH_TEXT_CONDITIONER_CKPT",
    str(_REPO_ROOT / "checkpoints" / "TextConditionerA"),
)
TASKS = _REPO_ROOT / "test_data" / "test_samples" / "audio_gen_collect.jsonl"
OUT_DIR = _REPO_ROOT / "outputs" / "test_audio"


class TestGenAudioPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from pipeline.assets_gen.gen_audio.run import (
            load_dialogue_model,
            load_sound_effect_model,
            make_operator,
        )

        cls.dialogue_model = load_dialogue_model(DIALOGUE_CKPT)
        cls.sound_effect_model = load_sound_effect_model(
            SOUND_EFFECT_CKPT,
            autoencoder_ckpt=WOOSH_AE_CKPT,
            text_conditioner_ckpt=WOOSH_TEXT_CONDITIONER_CKPT,
        )
        cls.operator = make_operator(
            cls.dialogue_model,
            cls.sound_effect_model,
            output_dir=str(OUT_DIR),
        )

    def test_tasks_jsonl_has_both_audio_types(self):
        import json

        tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
        self.assertGreaterEqual(len(tasks), 2, "Expected at least 2 audio test tasks.")
        self.assertEqual(
            {task.get("audio_type") for task in tasks},
            {"dialogue", "sound_effect"},
            "Expected both dialogue and sound_effect tasks in the jsonl.",
        )

    def test_run_all_tasks(self):
        from pipeline.assets_gen.gen_audio.run import run_from_jsonl

        results = run_from_jsonl(str(TASKS), self.operator)

        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(
            {result["audio_type"] for result in results},
            {"dialogue", "sound_effect"},
        )
        for result in results:
            audio_path = Path(result["audio_path"])
            self.assertTrue(audio_path.exists(), f"WAV not found: {audio_path}")
            self.assertGreater(
                audio_path.stat().st_size,
                1024,
                "WAV file suspiciously small.",
            )
            with wave.open(str(audio_path), "rb") as wav_file:
                self.assertGreater(wav_file.getnframes(), 0)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), result["sample_rate"])
                self.assertEqual(wav_file.getnchannels(), result["channels"])
            self.assertGreater(result["duration_sec"], 0)
            self.assertGreaterEqual(result["elapsed_sec"], 0)
            print(
                f"  [ok] {result['task_id']} -> {audio_path.name}  "
                f"({result['elapsed_sec']}s)"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
