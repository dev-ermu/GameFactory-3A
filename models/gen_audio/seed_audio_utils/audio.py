"""WAV conversion helpers used at the Seed Audio HTTP boundary."""

import base64
import io
import wave
from typing import Any


def _as_channels_first(waveform: Any):
    import numpy as np

    audio = np.asarray(waveform, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[None, :]
    if audio.ndim != 2 or audio.shape[-1] == 0:
        raise ValueError(
            f"reference audio must be non-empty [channels, samples], got {audio.shape}"
        )
    if audio.shape[0] > audio.shape[1] and audio.shape[1] <= 8:
        audio = audio.T
    return audio


def encode_wav_base64(waveform: Any, sample_rate: int) -> str:
    """Encode an in-memory waveform as base64 PCM16 WAV for ``references``."""
    import numpy as np

    audio = _as_channels_first(waveform)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).round().astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(int(pcm.shape[0]))
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm.T.reshape(-1).tobytes())
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def decode_wav_bytes(data: bytes) -> dict[str, Any]:
    """Decode an uncompressed WAV response into the AudioGen memory contract."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())
            compression = wav_file.getcomptype()
    except (EOFError, wave.Error) as exc:
        raise ValueError(
            "Seed Audio returned data that is not a readable WAV file. "
            "Keep output_format='wav' for the current AudioGen operator."
        ) from exc

    if compression != "NONE":
        raise ValueError(f"compressed WAV is not supported (compression={compression!r})")
    if not frames:
        raise ValueError("Seed Audio returned an empty WAV file")

    if sample_width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        values = (raw[:, 0].astype(np.int32)
                  | (raw[:, 1].astype(np.int32) << 8)
                  | (raw[:, 2].astype(np.int32) << 16))
        values = np.where(values & 0x800000, values - 0x1000000, values)
        samples = values.astype(np.float32) / 8388608.0
    elif sample_width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported WAV sample width: {sample_width} bytes")

    if samples.size % channels:
        raise ValueError("WAV sample count is not divisible by its channel count")
    waveform = samples.reshape(-1, channels).T.astype(np.float32, copy=False)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}
