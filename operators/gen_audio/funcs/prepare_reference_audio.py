"""Reference-audio loading step for voice-clone dialogue tasks."""

import wave
from pathlib import Path


def prepare_reference_audio(path: str | Path):
    """Load a reference clip as ``(mono float32 ndarray, sample_rate)``."""
    import numpy as np

    audio_path = Path(path)
    try:
        import soundfile as sf

        data, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=False)
        data = np.asarray(data, dtype=np.float32)
        if data.ndim == 2:
            data = data.mean(axis=1)
        return data, int(sample_rate)
    except ImportError:
        pass

    if audio_path.suffix.lower() != ".wav":
        raise RuntimeError(
            "Reading non-WAV reference audio requires `soundfile`: "
            "pip install soundfile"
        )
    with wave.open(str(audio_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data.astype(np.float32), int(sample_rate)
