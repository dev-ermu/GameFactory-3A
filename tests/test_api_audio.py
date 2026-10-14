"""豆包语音（Seed Audio）后端的离线契约测试。

不联网、不需要 API Key。从仓库根目录运行：

    python tests/test_api_audio.py

覆盖规范要点：
    R2.1  `model_id` 无默认值
    R6.1  凭证在首次调用时才读取
    R6.2  缺失凭证时给出可操作指引
    R8.3  依响应体而非状态码区分额度与鉴权失败
"""

import io
import sys
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from models.common import errors  # noqa: E402
from models.gen_audio.seed_audio_model import (  # noqa: E402
    MAX_DURATION_SEC,
    SeedAudioModel,
    decode_wav_bytes,
    encode_wav_base64,
)

# 测试期间清空凭证，避免读到开发者本机的 .env。
CREDENTIAL_FIELDS = {"seed_audio_api_key", "seed_audio_api_base"}


def blank_credentials():
    """返回把豆包语音凭证置空的补丁器。"""
    from config import settings

    return mock.patch.multiple(settings, **{name: "" for name in CREDENTIAL_FIELDS})


def make_wav(sample_rate: int = 24_000, duration: float = 0.25, channels: int = 1) -> bytes:
    """生成一段测试用的 WAV 字节。"""
    samples = max(1, int(sample_rate * duration))
    t = np.arange(samples, dtype=np.float32) / sample_rate
    wave_data = 0.2 * np.sin(2 * np.pi * 220 * t)
    pcm = (np.tile(wave_data, (channels, 1)) * 32767).astype("<i2")

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.T.reshape(-1).tobytes())

    return buffer.getvalue()


class FakeResponse:
    """模拟 httpx 的响应对象。"""

    def __init__(self, status_code: int, payload: dict):
        """保存状态码与响应体。"""
        self.status_code = status_code
        self.text = payload if isinstance(payload, str) else __import__("json").dumps(
            payload, ensure_ascii=False
        )


class TestConstruction(unittest.TestCase):
    """构造阶段的契约。"""

    def test_constructs_without_api_key(self):
        """R6.1：构造对象不需要凭证。"""
        model = SeedAudioModel("seed-audio-1.0")

        self.assertEqual(model.model_id, "seed-audio-1.0")
        self.assertFalse(model.describe()["client_ready"])

    def test_model_id_is_required(self):
        """R2.1：`model_id` 没有默认值。"""
        with self.assertRaises(TypeError):
            SeedAudioModel()

    def test_credential_spec_points_at_seed_audio(self):
        """R10.1：凭证项名由模型自己声明。"""
        self.assertEqual(
            SeedAudioModel("seed-audio-1.0").credential_spec(),
            ("seed_audio_api_key", "seed_audio_api_base"),
        )

    def test_auth_header_is_the_single_header_form(self):
        """豆包语音使用 `X-Api-Key` 单头鉴权。"""
        model = SeedAudioModel("seed-audio-1.0")
        headers = model.auth_headers("KEY")

        self.assertEqual(headers["X-Api-Key"], "KEY")
        self.assertEqual(headers["X-Api-Resource-Id"], "seed-audio-1.0")


class TestRequestValidation(unittest.TestCase):
    """请求入参的校验。"""

    def setUp(self):
        """构造一个不带凭证的实例。"""
        self.model = SeedAudioModel("seed-audio-1.0")

    def test_requires_text_or_prompt(self):
        """R3.2：`text` 与 `prompt` 至少给一个。"""
        with self.assertRaises(ValueError):
            self.model.request("")

    def test_rejects_duration_beyond_the_provider_limit(self):
        """R9.2：超过服务商上限时明确报错，不静默截断。"""
        with self.assertRaises(ValueError) as ctx:
            self.model.request(text="测试", duration_sec=MAX_DURATION_SEC + 1)

        self.assertIn("120", str(ctx.exception))


class TestErrorClassification(unittest.TestCase):
    """R8.3：依据响应体区分额度不足与密钥错误。"""

    def setUp(self):
        """构造一个实例。"""
        self.model = SeedAudioModel("seed-audio-1.0")

    def test_missing_key_reports_the_variable_name(self):
        """R6.2：缺少凭证时给出配置项名。"""
        with blank_credentials():
            with self.assertRaises(errors.CloudModelConfigError) as ctx:
                self.model.request(text="你好")

        message = str(ctx.exception)

        self.assertIn("seed_audio_api_key", message)
        self.assertIn(".env", message)

    def test_out_of_credit_body_is_a_quota_error(self):
        """401 但响应体说明余额不足时，应归为额度问题而非鉴权问题。"""
        body = FakeResponse(401, {"message": "账户余额不足，请充值"})

        with self.assertRaises(errors.CloudModelQuotaError):
            self.model._parse_body(body)

    def test_genuinely_bad_key_is_still_an_auth_error(self):
        """401 且响应体是密钥问题，归为鉴权失败。"""
        body = FakeResponse(401, {"message": "the API key is missing or invalid"})

        with self.assertRaises(errors.CloudModelAuthError):
            self.model._parse_body(body)

    def test_rate_limit_is_retryable(self):
        """429 归为可重试故障。"""
        body = FakeResponse(429, {"message": "slow down"})

        with self.assertRaises(errors.CloudModelRateLimitError):
            self.model._parse_body(body)

    def test_empty_data_is_a_server_error(self):
        """响应体没有音频数据时归为服务端错误。"""
        body = FakeResponse(200, {"data": ""})

        with self.assertRaises(errors.CloudModelServerError):
            self.model._parse_body(body)
class TestWaveformHelpers(unittest.TestCase):
    """WAV 编解码的往返一致性。"""

    def test_decode_returns_the_documented_shape(self):
        """解码结果形状为 `[声道数, 采样点数]`。"""
        result = decode_wav_bytes(make_wav(duration=0.1, channels=2))

        self.assertEqual(result["sample_rate"], 24_000)
        self.assertEqual(result["waveform"].shape[0], 2)
        self.assertEqual(result["waveform"].dtype.name, "float32")

    def test_decoded_samples_stay_in_range(self):
        """解码后的取值应落在 [-1, 1]。"""
        result = decode_wav_bytes(make_wav(duration=0.05))

        self.assertLessEqual(float(np.abs(result["waveform"]).max()), 1.0)

    def test_encode_then_decode_is_stable(self):
        """编码后再解码，采样率与数据长度保持一致。"""
        original = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
        encoded = encode_wav_base64(original, 24_000)

        import base64

        decoded = decode_wav_bytes(base64.b64decode(encoded))

        self.assertEqual(decoded["sample_rate"], 24_000)
        self.assertEqual(decoded["waveform"].shape[-1], original.shape[-1])

    def test_rejects_empty_input(self):
        """空数据无法解码成有效波形。"""
        with self.assertRaises(Exception):
            decode_wav_bytes(b"")


class TestOperatorIntegration(unittest.TestCase):
    """确认算子层调用的是新接口名。"""

    def test_audio_operators_call_request(self):
        """两个音频算子都不应再调用旧接口名。"""
        for name in ("generate_dialogue.py", "generate_sound_effect.py"):
            source = (
                _REPO_ROOT / "operators" / "gen_audio" / "funcs" / name
            ).read_text(encoding="utf-8")

            self.assertIn("model.request(", source)
            self.assertNotIn("model.infer(", source)


if __name__ == "__main__":
    unittest.main()