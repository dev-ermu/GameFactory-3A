"""Small dependency-free resampling step used before WAV export."""


def resample_audio(waveform, source_rate: int, target_rate: int):
    """Linearly resample a float waveform shaped ``[channels, samples]``."""
    import numpy as np

    data = np.asarray(waveform, dtype=np.float32)
    if source_rate == target_rate:
        return data
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("Audio sample rates must be positive integers.")
    if data.ndim != 2:
        raise ValueError(f"Expected [channels, samples] audio, got shape {data.shape}")
    old_size = data.shape[-1]
    new_size = max(1, round(old_size * target_rate / source_rate))
    old_positions = np.linspace(0.0, 1.0, old_size, endpoint=True)
    new_positions = np.linspace(0.0, 1.0, new_size, endpoint=True)
    return np.stack(
        [np.interp(new_positions, old_positions, channel) for channel in data],
        axis=0,
    ).astype(np.float32)
