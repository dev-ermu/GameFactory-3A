"""
operators/gen_audio/operator.py

GenAudioOperator routes one offline asset task to either an injected dialogue
model or an injected sound-effect model and exports a PCM16 WAV artifact.

Output modes:
  * per-game: resolved by ``pipeline.common.paths`` as one directory per task
  * legacy:   <output_dir>/<task_id>.wav
"""

import time
import wave
from pathlib import Path
from typing import Any, Optional

TASK_KIND = "audio"
AUDIO_FILENAME = "audio.wav"
SUPPORTED_AUDIO_TYPES = ("dialogue", "sound_effect")


class GenAudioOperator:
    """Generate dialogue or SFX with model objects supplied by ``run.py``."""

    def __init__(
        self,
        dialogue_model: Optional[Any] = None,
        sound_effect_model: Optional[Any] = None,
        output_dir: Optional[str] = None,
        run_id: str = "default",
        default_game_id: Optional[str] = None,
    ):
        self.dialogue_model = dialogue_model
        self.sound_effect_model = sound_effect_model
        self.run_id = run_id
        self.default_game_id = default_game_id
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_out_path(self, inp: dict, task_id: str) -> tuple[str, Path, Path]:
        if self.output_dir is not None:
            game_id = str(inp.get("game_id") or inp.get("game") or "")
            return game_id, self.output_dir, self.output_dir / f"{task_id}.wav"

        from pipeline.common import paths

        game_id = paths.infer_game_id(inp, fallback=self.default_game_id)
        task_dir = paths.task_output_dir(game_id, TASK_KIND, task_id, run_id=self.run_id)
        return game_id, task_dir, task_dir / AUDIO_FILENAME

    @staticmethod
    def _coerce_waveform(audio_result: dict) -> tuple[Any, int]:
        import numpy as np

        if not isinstance(audio_result, dict):
            raise TypeError("Audio models must return a dict with waveform and sample_rate.")
        if "waveform" not in audio_result or "sample_rate" not in audio_result:
            raise ValueError("Audio model result is missing `waveform` or `sample_rate`.")
        waveform = np.asarray(audio_result["waveform"], dtype=np.float32)
        if waveform.ndim == 1:
            waveform = waveform[None, :]
        if waveform.ndim != 2 or waveform.shape[-1] == 0:
            raise ValueError(f"Expected non-empty [channels, samples] audio, got {waveform.shape}")
        if waveform.shape[0] > waveform.shape[1] and waveform.shape[1] <= 8:
            waveform = waveform.T
        return waveform, int(audio_result["sample_rate"])

    @staticmethod
    def _write_wav(path: Path, waveform, sample_rate: int) -> None:
        import numpy as np

        path.parent.mkdir(parents=True, exist_ok=True)
        audio = np.asarray(waveform, dtype=np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1.0:
            audio = audio / peak
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).round().astype("<i2")
        interleaved = pcm.T.reshape(-1)
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(int(pcm.shape[0]))
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            wav_file.writeframes(interleaved.tobytes())

    def run(self, inp: dict) -> dict:
        """Generate exactly one dialogue or sound-effect WAV from a task dict."""
        from operators.gen_audio.funcs.generate_dialogue import generate_dialogue
        from operators.gen_audio.funcs.generate_sound_effect import generate_sound_effect
        from operators.gen_audio.funcs.prepare_reference_audio import prepare_reference_audio
        from operators.gen_audio.funcs.resample_audio import resample_audio

        task_id = str(inp.get("task_id", f"task_{int(time.time())}"))
        audio_type = str(inp.get("audio_type", "sound_effect"))
        if audio_type not in SUPPORTED_AUDIO_TYPES:
            raise ValueError(
                f"Unsupported audio_type {audio_type!r}; expected {SUPPORTED_AUDIO_TYPES}."
            )
        seed = int(inp.get("seed", 42))
        game_id, task_dir, audio_target = self._resolve_out_path(inp, task_id)

        reference_audio = None
        reference_path = inp.get("reference_audio_path")
        if reference_path:
            from pipeline.common import paths

            reference_path = paths.resolve_input_path(reference_path)
            reference_audio = prepare_reference_audio(reference_path)

        selected_model = (
            self.dialogue_model if audio_type == "dialogue" else self.sound_effect_model
        )
        t0 = time.time()
        if audio_type == "dialogue":
            audio_result = generate_dialogue(
                self.dialogue_model,
                str(inp.get("text", "")),
                seed=seed,
                language=str(inp.get("language", "Auto")),
                speaker_id=str(inp.get("speaker_id", "Vivian")),
                emotion=str(inp.get("emotion", "")),
                delivery=str(inp.get("delivery", "")),
                reference_audio=reference_audio,
                reference_text=inp.get("reference_text"),
            )
        else:
            audio_result = generate_sound_effect(
                self.sound_effect_model,
                str(inp.get("prompt", "")),
                seed=seed,
                duration_sec=inp.get("duration_sec"),
                num_steps=inp.get("num_steps"),
                cfg=inp.get("cfg"),
            )
        elapsed = time.time() - t0

        waveform, sample_rate = self._coerce_waveform(audio_result)
        requested_rate = inp.get("sample_rate")
        if requested_rate and int(requested_rate) != sample_rate:
            waveform = resample_audio(waveform, sample_rate, int(requested_rate))
            sample_rate = int(requested_rate)
        self._write_wav(audio_target, waveform, sample_rate)

        result = {
            "task_id": task_id,
            "audio_path": str(audio_target),
            "audio_type": audio_type,
            "sound_category": inp.get("sound_category"),
            "sample_rate": sample_rate,
            "channels": int(waveform.shape[0]),
            "duration_sec": round(float(waveform.shape[-1] / sample_rate), 4),
            "elapsed_sec": round(elapsed, 2),
            "game_id": game_id,
            "task_kind": TASK_KIND,
            "output_dir": str(task_dir),
            "model": type(selected_model).__name__ if selected_model is not None else None,
        }

        if self.output_dir is None:
            from pipeline.common import paths

            paths.write_task_meta(task_dir, {
                **result,
                "run_id": self.run_id,
                "prompt": inp.get("prompt"),
                "text": inp.get("text"),
                "speaker_id": inp.get("speaker_id"),
                "emotion": inp.get("emotion"),
                "language": inp.get("language"),
                "requested_duration_sec": inp.get("duration_sec"),
                "requested_sample_rate": inp.get("sample_rate"),
                "reference_audio_path": str(reference_path) if reference_path else None,
                "seed": seed,
            })
        return result

    def run_batch(self, inputs: list[dict]) -> list[dict]:
        """Run a list of audio tasks sequentially."""
        return [self.run(inp) for inp in inputs]
