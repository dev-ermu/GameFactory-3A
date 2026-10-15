"""豆包语音（Seed Audio）模型生成封装。

Seed Audio没有提供OpenAI协议接口。因此按照官方文档发送HTTP请求：
HTTP请求头部需包含
{
    "Content-Type": "application/json",
    "X-Api-Key": "<your_api_key>",
    "X-Api-Request-Id": str(uuid.uuid4()),
}

官方文档：https://docs.volcengine.com/docs/6561/2550782
"""

import base64
import io
import json
import wave

import numpy as np
import requests

from models.base import BaseModel
from models.common import errors

# 服务端单次生成时长上限，单位秒。
MAX_DURATION_SEC = 120.0


class SeedAudioModel(BaseModel):
    """豆包语音音频生成模型。"""
    provider = "豆包语音-火山引擎"
    display_name = "seed audio 1.0"
    api_key_field = "seed_audio_api_key"
    api_base_field = "seed_audio_api_base"

    def __init__(
        self,
        model_id: str,
        *,
        speaker_id: str = "",
        timeout: int = 600,
        poll_interval: float = 10.0,
        max_retries: int = 3,
        output_format: str = "wav",
        verbose: bool = False,
    ) -> None:
        """保存豆包语音特有参数，其余交给基类。"""
        super().__init__(
            model_id,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
            output_format=output_format,
            verbose=verbose,
        )
        self.speaker_id = speaker_id

    def auth_headers(self, api_key: str) -> dict[str, str]:
        """豆包语音使用 `X-Api-Key` 单头鉴权。"""
        return {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": self.model_id,
            "Content-Type": "application/json",
        }

    def request(
        self,
        text: str | None = None,
        *,
        prompt: str | None = None,
        speaker_id: str | None = None,
        duration_sec: float | None = None,
        seed: int | None = None,
        language: str = "Auto",
        instruct: str = "",
        reference_audio: tuple[object, int] | None = None,
        reference_text: str | None = None,
        num_steps: int | None = None,
        cfg: float | None = None,
    ) -> dict:
        """生成一段音频并返回波形。

        Args:
            text: 待合成的文本。
            prompt: 自然语言描述，用于音效生成；与 `text` 二选一。
            speaker_id: 发音人标识，留空则用构造时的配置。
            duration_sec: 期望时长，单次不超过 120 秒。
            seed: 为插槽兼容而保留，豆包语音不支持该参数，会被忽略。
            language: 语种标识，例如 `Auto`、`zh`。
            instruct: 演唱或解说风格指令。
            reference_audio: 参考音频与其采样率，形如 `(数组, 采样率)`。
            reference_text: 参考音频对应的文本，用于对齐。
            num_steps: 为插槽兼容而保留，豆包语音不支持，会被忽略。
            cfg: 为插槽兼容而保留，豆包语音不支持，会被忽略。

        Returns:
            形如 `{"waveform": np.ndarray, "sample_rate": int}` 的字典，
            其中 `waveform` 形状为 `[声道数, 采样点数]`，取值范围 [-1, 1]。
        """
        del seed, num_steps, cfg

        payload = self._build_request(
            text=text,
            prompt=prompt,
            duration_sec=duration_sec,
            speaker_id=speaker_id,
            language=language,
            instruct=instruct,
            reference_audio=reference_audio,
            reference_text=reference_text,
        )

        # todo 垃圾AI，我叫他不要使用client.post，它还是继续使用
        client = self.http_client()
        response = self.call_with_retry(
            lambda: client.post(
                self.api_base, json=payload, timeout=(30.0, float(self.timeout))
            )
        )
        body = self._parse_body(response)

        return decode_wav_bytes(base64.b64decode(body["data"]))

    def _build_request(
        self,
        text: str | None,
        prompt: str | None,
        duration_sec: float | None,
        speaker_id: str | None,
        language: str,
        instruct: str,
        reference_audio: tuple[object, int] | None,
        reference_text: str | None,
    ) -> dict:
        """构造豆包语音的请求体。

        规范 R3.2 要求输入是对象而非路径，因此这里只接受文本或提示词。
        """
        source = text if text else prompt

        if not source or not source.strip():
            raise ValueError("豆包语音需要 text 或 prompt 其中之一，两者都不能为空")

        if duration_sec is not None and duration_sec > MAX_DURATION_SEC:
            raise ValueError(
                f"duration_sec 不能超过 {MAX_DURATION_SEC} 秒，服务端单次生成上限如此"
            )

        payload: dict = {
            "model": self.model_id,
            "text": str(source),
            "stream": False,
            "voice": {"type": "builtin", "name": speaker_id or self.speaker_id},
            "audio_params": {
                "format": self.output_format,
                "sample_rate": 24000,
                "speech_rate": 0,
                "language": language,
            },
        }

        if duration_sec is not None:
            payload["audio_params"]["duration"] = duration_sec

        if instruct:
            payload["instruct"] = instruct

        if reference_audio is not None:
            waveform, sample_rate = reference_audio
            payload["references"] = [
                {
                    "type": "audio",
                    "audio": encode_wav_base64(waveform, sample_rate),
                    "text": reference_text or "",
                }
            ]

        return payload

    def _parse_body(self, response: requests.Response) -> dict:
        """解析响应并把 HTTP 状态映射为对应异常。

        对应规范 R8.2 与 R8.3：判定依据是响应体内容而非仅状态码，
        因为豆包语音在额度不足时也会返回 401，只看状态码无法与
        密钥错误区分。
        """
        status = int(response.status_code)
        text = response.text or ""

        try:
            body = json.loads(text) if text else {}
        except json.JSONDecodeError:
            body = {}

        if 200 <= status < 300:
            data = body.get("data")

            if not data:
                raise errors.CloudModelServerError(
                    f"豆包语音响应中没有音频数据：{text[:200]}"
                )

            return body

        reason = str(
            body.get("message") or body.get("error", {}).get("message") or text[:200]
        )

        if status in (400, 422):
            raise errors.CloudModelRequestError(f"豆包语音拒绝了该请求：{reason}")

        if status == 402:
            raise errors.CloudModelQuotaError(f"豆包语音额度不足：{reason}")

        if status in (401, 403):
            if "余额" in reason or "欠费" in reason or "quota" in reason.lower():
                raise errors.CloudModelQuotaError(f"豆包语音额度不足：{reason}")
            raise errors.CloudModelAuthError(f"豆包语音鉴权失败：{reason}")

        if status == 429:
            raise errors.CloudModelRateLimitError(f"豆包语音触发限流：{reason}")

        if status >= 500:
            raise errors.CloudModelServerError(f"豆包语音服务端错误 {status}：{reason}")

        raise errors.CloudModelRequestError(f"豆包语音返回未预期的状态 {status}：{reason}")

def decode_wav_bytes(data: bytes) -> dict:
    """把 WAV 字节流解码成内存中的波形。

    Args:
        data: 未压缩的 WAV 文件内容。

    Returns:
        `{"waveform": np.ndarray, "sample_rate": int}`，波形形状为
        `[声道数, 采样点数]`，取值范围 [-1, 1]。
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())
            compression = wav_file.getcomptype()
    except (EOFError, wave.Error) as exc:
        raise ValueError(
            "豆包语音返回的数据不是可读的 WAV 文件，请保持 output_format='wav'"
        ) from exc

    if compression != "NONE":
        raise ValueError(f"暂不支持压缩过的 WAV（compression={compression!r}）")

    if not frames:
        raise ValueError("豆包语音返回了空的 WAV 文件")

    samples = _decode_samples(frames, sample_width)
    remainder = samples.size % channels

    if remainder:
        raise ValueError("WAV 采样点数无法被声道数整除")

    waveform = samples.reshape(-1, channels).T.astype(np.float32, copy=False)

    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def _decode_samples(frames: bytes, sample_width: int) -> np.ndarray:
    """按采样位宽把 PCM 字节流转换为归一化的 float32 波形。

    Args:
        frames: WAV 文件中的原始帧数据。
        sample_width: 每个采样的字节数，支持 1 到 4。

    Returns:
        一维 `float32` 数组，取值范围 [-1, 1]。
    """
    if sample_width == 1:
        raw = np.frombuffer(frames, dtype=np.uint8).astype(np.int32)
        return (raw - 128) / 128.0

    if sample_width == 2:
        return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0

    if sample_width == 3:
        packed = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        values = (
            packed[:, 0].astype(np.int32)
            | (packed[:, 1].astype(np.int32) << 8)
            | (packed[:, 2].astype(np.int32) << 16)
        )
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float32) / 8388608.0

    if sample_width == 4:
        return np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0

    raise ValueError(f"不支持的 WAV 采样位宽：{sample_width} 字节")

def encode_wav_base64(waveform, sample_rate: int) -> str:
    """把内存中的波形编码为 base64 的 PCM16 WAV。

    Args:
        waveform: 一维或二维数组，形状为 `[采样点数]` 或 `[声道数, 采样点数]`，
            取值范围 [-1, 1]。
        sample_rate: 采样率，单位 Hz。

    Returns:
        base64 编码的 WAV 字符串，可直接放进请求体的参考音频字段。
    """
    audio = np.asarray(waveform, dtype=np.float32)

    if audio.ndim == 1:
        audio = audio[None, :]

    if audio.ndim != 2 or audio.shape[-1] == 0:
        raise ValueError(
            f"参考音频必须是非空的 [声道数, 采样点数]，收到 {audio.shape}"
        )

    if audio.shape[0] > audio.shape[1] and audio.shape[1] <= 8:
        audio = audio.T

    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).round().astype("<i2")
    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(int(pcm.shape[0]))
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm.T.reshape(-1).tobytes())

    return base64.b64encode(buffer.getvalue()).decode("ascii")