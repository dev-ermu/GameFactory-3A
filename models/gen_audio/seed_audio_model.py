"""
SeedAudioModel — synchronous Volcengine/ByteDance Seed Audio 1.0 API backend.

The same provider can fill either AudioGen model slot: construct it with
``mode="dialogue"`` for character lines or ``mode="sound_effect"`` for SFX,
foley and ambience. It returns the same in-memory waveform contract as Qwen3-TTS
and Woosh, so artifact writing remains in ``GenAudioOperator``.

请求路径：`{SEED_AUDIO_API_BASE}/api/v3/tts/create`。路径属于 API 契约，base 由
`.env` 提供 —— 代码里不含任何 URL 字面量。

环境变量（统一写在 `<repo>/.env`，见 `.env.example`）：
    SEED_AUDIO_API_KEY       首次真实 API 请求时必需
    SEED_AUDIO_API_BASE      首次真实 API 请求时必需；代码不含端点示例，绝不静默回退
    SEED_AUDIO_MODEL         可选，模型 id（默认 seed-audio-1.0）
    SEED_AUDIO_SPEAKER_ID    可选，服务商侧的音色资源 id
"""
from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Optional

from models.common import cloud_api
from models.gen_audio.seed_audio_utils import (
    SeedAudioAPIClient,
    decode_wav_bytes,
    encode_wav_base64,
)

#: `.env` 变量名；URL 由用户填写在 `.env` 里，代码不保留 URL 字面量（R9.7）。
ENV_KEY = "SEED_AUDIO_API_KEY"
ENV_BASE = "SEED_AUDIO_API_BASE"
DEFAULT_MODEL = "seed-audio-1.0"
#: 请求路径，拼接在 `.env` 配置的 base 之后（路径属于 API 契约，不是用户配置）。
CREATE_PATH = "/api/v3/tts/create"
SUPPORTED_MODES = ("dialogue", "sound_effect")


class SeedAudioModel:
    """Generate dialogue or game sounds through Seed Audio's synchronous API."""

    PROVIDER = "seed_audio"

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        device: str = "cpu",
        *,
        mode: str = "dialogue",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        speaker_id: Optional[str] = None,
        cache_dir: Optional[str] = None,
        sample_rate: int = 24_000,
        output_format: str = "wav",
        speech_rate: int = 0,
        loudness_rate: int = 0,
        pitch_rate: int = 0,
        enable_subtitle: bool = False,
        http_timeout: int = 300,
        max_retries: int = 3,
        verbose: bool = False,
        **model_specific: Any,
    ):
        self.model_path = model_path
        self.device = device  # accepted for model-slot parity; the service is remote
        self.mode = str(mode).lower()
        self.api_key = api_key
        # [R9.7] 必填项，且在首次调用时才解析。端点由用户在 .env 里配置，代码
        # 不含任何 URL 示例。
        self.api_base = api_base
        self.speaker_id = speaker_id or os.environ.get("SEED_AUDIO_SPEAKER_ID")
        self.cache_dir = cache_dir
        self.sample_rate = int(sample_rate)
        self.output_format = output_format.lower().lstrip(".")
        self.speech_rate = int(speech_rate)
        self.loudness_rate = int(loudness_rate)
        self.pitch_rate = int(pitch_rate)
        self.enable_subtitle = bool(enable_subtitle)
        self.http_timeout = int(http_timeout)
        self.max_retries = int(max_retries)
        self.verbose = verbose
        self.model_specific = model_specific

        if self.mode not in SUPPORTED_MODES:
            raise ValueError(f"mode={mode!r}; expected one of {SUPPORTED_MODES}")
        if self.output_format != "wav":
            raise ValueError(
                "SeedAudioModel currently requires output_format='wav' so it can "
                "return the AudioGen waveform contract without optional codecs."
            )
        if self.sample_rate not in (8000, 16000, 24000, 32000, 44100, 48000):
            raise ValueError(f"unsupported Seed Audio sample_rate: {self.sample_rate}")
        if not -50 <= self.speech_rate <= 100:
            raise ValueError("speech_rate must be in [-50, 100]")
        if not -50 <= self.loudness_rate <= 100:
            raise ValueError("loudness_rate must be in [-50, 100]")
        if not -12 <= self.pitch_rate <= 12:
            raise ValueError("pitch_rate must be in [-12, 12]")

        self._client: Optional[SeedAudioAPIClient] = None
        self._cache = cloud_api.ResponseCache(cache_dir, self.PROVIDER)
        self.last_call_info: dict[str, Any] = {}

    @property
    def client(self) -> SeedAudioAPIClient:
        """惰性解析凭证，使构造与 harness 运行都不触网。"""
        if self._client is None:
            key = cloud_api.require_api_key(
                self.api_key,
                ENV_KEY,
                who="SeedAudioModel",
            )
            base = cloud_api.require_api_base(
                self.api_base,
                ENV_BASE,
                who="SeedAudioModel",
            )
            self._client = SeedAudioAPIClient(
                base,
                key,
                timeout=self.http_timeout,
                max_retries=self.max_retries,
            )
        return self._client

    def unload(self) -> None:
        """Close the HTTP session. Safe before use and safe to call repeatedly."""
        if self._client is not None:
            self._client.close()
            self._client = None

    close = unload

    def _text_prompt(
        self,
        *,
        text: Optional[str],
        prompt: Optional[str],
        instruct: str,
        language: str,
        duration_sec: Optional[float],
    ) -> str:
        if self.mode == "dialogue":
            value = (text or prompt or "").strip()
            if not value:
                raise ValueError("Seed Audio dialogue mode requires non-empty text.")
            directions = []
            if instruct.strip():
                directions.append(instruct.strip())
            if language and language.lower() != "auto":
                directions.append(f"Speak in {language}.")
            if directions:
                return f"{value}\nVoice direction: {' '.join(directions)}"
            return value

        value = (prompt or text or "").strip()
        if not value:
            raise ValueError("Seed Audio sound_effect mode requires a non-empty prompt.")
        if duration_sec is not None:
            duration = float(duration_sec)
            if not 0 < duration <= 120:
                raise ValueError("duration_sec must be greater than 0 and at most 120")
            value = f"{value}. Approximately {duration:g} seconds long."
        return value

    def _payload(
        self,
        text_prompt: str,
        *,
        reference_audio: Optional[tuple[Any, int]],
        provider_kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], Optional[str]]:
        audio_config = {
            "format": self.output_format,
            "sample_rate": self.sample_rate,
            "speech_rate": self.speech_rate,
            "loudness_rate": self.loudness_rate,
            "pitch_rate": self.pitch_rate,
            "subtitle": self.enable_subtitle,
        }
        payload: dict[str, Any] = {
            "model": self.model_path,
            "text_prompt": text_prompt,
            "audio_config": audio_config,
        }
        if not self.enable_subtitle:
            audio_config.pop("subtitle")

        reference_hash = None
        if reference_audio is not None:
            waveform, rate = reference_audio
            encoded = encode_wav_base64(waveform, int(rate))
            raw = base64.b64decode(encoded)
            decoded_reference = decode_wav_bytes(raw)
            reference_duration = (
                decoded_reference["waveform"].shape[-1]
                / decoded_reference["sample_rate"]
            )
            if reference_duration > 30:
                raise ValueError(
                    f"Seed Audio reference clip is {reference_duration:.2f}s; maximum is 30s"
                )
            if len(raw) > 10 * 1024 * 1024:
                raise ValueError("Seed Audio reference clip exceeds the 10 MiB API limit")
            reference_hash = cloud_api.bytes_hash(raw)
            reference: dict[str, Any] = {"audio_data": encoded}
            payload["references"] = [reference]
        elif self.speaker_id:
            payload["references"] = [{"speaker": self.speaker_id}]

        # Explicit provider fields allow forward compatibility without changing
        # the operator. Protected core fields cannot be accidentally replaced.
        for key, value in provider_kwargs.items():
            if value is not None and key not in payload:
                payload[key] = value
        return payload, reference_hash

    @staticmethod
    def _response_body(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise cloud_api.CloudAPIError(
                f"Seed Audio returned an unexpected response: {response!r}"
            )
        body = response.get("body") if isinstance(response.get("body"), dict) else response
        code = body.get("code", response.get("status", 200))
        if code not in (None, 0, 200, "0", "200", "success", "Success"):
            raise cloud_api.CloudAPIRequestError(
                f"Seed Audio rejected the generation request: "
                f"code={code!r}, message={body.get('message')!r}",
                payload=response,
            )
        return body

    def infer(
        self,
        text: Optional[str] = None,
        seed: int = 42,
        language: str = "Auto",
        speaker_id: Optional[str] = None,
        instruct: str = "",
        reference_audio: Optional[tuple[Any, int]] = None,
        reference_text: Optional[str] = None,
        *,
        prompt: Optional[str] = None,
        duration_sec: Optional[float] = None,
        num_steps: Optional[int] = None,
        cfg: Optional[float] = None,
        **provider_kwargs: Any,
    ) -> dict[str, Any]:
        """Synchronously generate one clip and return ``waveform`` + sample rate.

        ``seed``, ``num_steps`` and ``cfg`` are accepted for slot compatibility;
        Seed Audio 1.0's public API does not expose them, so they are not faked or
        sent. Likewise, the task's Qwen speaker name is intentionally ignored;
        configure a real provider resource with ``SEED_AUDIO_SPEAKER_ID``.
        """
        del seed, speaker_id, reference_text, num_steps, cfg
        text_prompt = self._text_prompt(
            text=text,
            prompt=prompt,
            instruct=instruct,
            language=language,
            duration_sec=duration_sec,
        )
        if reference_audio is not None and "@Audio1" not in text_prompt:
            text_prompt = f"Use @Audio1 as the voice reference. {text_prompt}"
        if len(text_prompt) > 3000:
            raise ValueError("Seed Audio text_prompt exceeds the 3000-character API limit")
        payload, reference_hash = self._payload(
            text_prompt,
            reference_audio=reference_audio,
            provider_kwargs=provider_kwargs,
        )
        cache_description = {
            "provider": self.PROVIDER,
            "model": self.model_path,
            "mode": self.mode,
            "payload": {
                **payload,
                "references": (
                    [{"audio_sha256": reference_hash}]
                    if reference_hash
                    else payload.get("references")
                ),
            },
        }
        cache_key = cloud_api.request_hash(cache_description)
        audio_bytes = self._cache.get(cache_key, ext="wav")
        cached = audio_bytes is not None

        response_body: dict[str, Any] = {}
        if audio_bytes is None:
            if self.verbose:
                print(f"[seed_audio] generating {self.mode}: {text_prompt[:100]}")
            response = self.client.request(
                "POST",
                CREATE_PATH,
                json_body=payload,
            )
            response_body = self._response_body(response)
            encoded_audio = response_body.get("audio")
            if isinstance(encoded_audio, str) and encoded_audio:
                try:
                    audio_bytes = base64.b64decode(encoded_audio, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise cloud_api.CloudAPIError(
                        "Seed Audio response contained invalid base64 audio",
                        payload=response,
                    ) from exc
            else:
                audio_url = response_body.get("url")
                if not isinstance(audio_url, str) or not audio_url.startswith("http"):
                    raise cloud_api.CloudAPIError(
                        "Seed Audio response contained neither base64 `audio` nor a valid `url`",
                        payload=response,
                    )
                audio_bytes = self.client.download(audio_url, max_bytes=100 * 1024 * 1024)
            self._cache.put(cache_key, audio_bytes, cache_description, ext="wav")

        assert audio_bytes is not None
        result = decode_wav_bytes(audio_bytes)
        self.last_call_info = {
            "provider": self.PROVIDER,
            "model": self.model_path,
            "mode": self.mode,
            "cached": cached,
            "cache_key": cache_key,
            "bytes": len(audio_bytes),
            "duration_sec": result["waveform"].shape[-1] / result["sample_rate"],
            "response_duration_sec": (
                response_body.get("original_duration") or response_body.get("duration")
            ),
        }
        return result
