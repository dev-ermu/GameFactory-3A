"""
SeedreamModel — wrapper around Volcengine Ark's Seedream image-generation API.

Interface parity with `QwenEditModel` (R6):
  ``infer(image, prompt, seed=42, steps=40) -> PIL.Image``

  ``steps`` is accepted for swappability but not forwarded — the Seedream API
  does not expose a diffusion-step count.  ``image`` may be ``None`` for pure
  text-to-image, or a ``PIL.Image`` for image-to-image / image editing.

环境变量（统一写在 `<repo>/.env`，见 `.env.example`）：
    ARK_API_KEY   在首次 infer() 调用时必需，构造时不需要。
    ARK_API_BASE  在首次 infer() 调用时必需。Volcengine Ark 端点只在报错信息里作为
                  示例给出，绝不会被静默采用——它并非在所有网络下都可达。
"""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from models.common import cloud_api

logger = logging.getLogger(__name__)

#: `.env` 变量名；URL 由用户填写在 `.env` 里，代码不保留 URL 字面量（R9.7）。
ENV_KEY = "ARK_API_KEY"
ENV_BASE = "ARK_API_BASE"
DEFAULT_MODEL = "doubao-seedream-5-0-260128"

MODEL_ALIASES: dict[str, str] = {
    "seedream": DEFAULT_MODEL,
    "seedream-5.0": DEFAULT_MODEL,
    "seedream-5-0": DEFAULT_MODEL,
    "seedream-3.0": "doubao-seedream-3-0-t2i-250415",
    "seedream-3-0-t2i": "doubao-seedream-3-0-t2i-250415",
    "seedream-3.0-t2i": "doubao-seedream-3-0-t2i-250415",
}

SUPPORTED_FORMATS = ("png", "jpeg", "jpg")


class SeedreamModel:
    """Cloud image generation through Seedream (Doubao image model).

    The generation entry points are :meth:`infer` and :meth:`infer_and_save`,
    matching the interface of ``QwenEditModel`` so the two are swappable in any
    operator slot (R6).

    When ``image`` is provided the model performs image-to-image editing;
    when ``image`` is ``None`` it performs text-to-image generation.
    """

    PROVIDER = "seedream"
    SUPPORTED_FORMATS = frozenset(SUPPORTED_FORMATS)

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        device: str = "cuda",
        *,
        api_key: Optional[str] = None,
        timeout: int = 300,
        max_retries: int = 3,
        cache_dir: Optional[str] = None,
        output_format: str = "png",
        size: str = "2048x2048",
        watermark: bool = False,
        response_format: str = "url",
        api_base: Optional[str] = None,
        http_timeout: int = 60,
        verbose: bool = False,
    ):
        # [CONTRACT-DEVIATION C1] Version id, not a local weight path.
        # [CONTRACT-DEVIATION C2] Kept for swappable model construction; ignored.
        self.model_path = MODEL_ALIASES.get(str(model_path).lower(), model_path)
        self.device = device
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        self.output_format = str(output_format).lower().lstrip(".")
        self.size = size
        self.watermark = watermark
        self.response_format = response_format
        # [R9.7] 必填项，且在首次调用时才解析。端点由用户在 .env 里配置，代码
        # 不含任何 URL 示例。
        self.api_base = api_base
        self.http_timeout = http_timeout
        self.verbose = verbose

        if self.output_format not in SUPPORTED_FORMATS:
            raise ValueError(
                f"output_format={self.output_format!r} is not supported by "
                f"SeedreamModel; use one of {sorted(SUPPORTED_FORMATS)}"
            )

        self._client: Optional[cloud_api.CloudAPIClient] = None
        self._cache = cloud_api.ResponseCache(cache_dir, self.PROVIDER)
        self.last_call_info: dict[str, Any] = {}

    @property
    def client(self) -> cloud_api.CloudAPIClient:
        """首次使用时创建带鉴权的 HTTP 客户端（R9.7）。"""
        if self._client is None:
            key = cloud_api.require_api_key(
                self.api_key, ENV_KEY, who="SeedreamModel"
            )
            base = cloud_api.require_api_base(
                self.api_base, ENV_BASE, who="SeedreamModel"
            )
            self._client = cloud_api.CloudAPIClient(
                base,
                key,
                timeout=self.http_timeout,
                max_retries=self.max_retries,
            )
        return self._client

    def unload(self) -> None:
        """[C4] Close the HTTP session; safe before use and safe twice."""
        if self._client is not None:
            self._client.close()
            self._client = None

    close = unload

    # -- payload ---------------------------------------------------------------

    def _build_payload(
        self,
        prompt: str,
        image: Optional[Image.Image],
        seed: int,
        provider_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_path,
            "prompt": prompt,
            # [CONTRACT-DEVIATION C5] Forwarded, but not guaranteed deterministic.
            "seed": seed,
            "size": self.size,
            "watermark": self.watermark,
            "response_format": self.response_format,
        }
        if image is not None:
            # Image-to-image: pass the reference as a base64 data URI.
            png_bytes = cloud_api.image_to_png_bytes(image)
            payload["image"] = cloud_api.image_to_data_uri(png_bytes)
        payload.update(provider_kwargs)
        return payload

    def _cache_descriptor(
        self,
        prompt: str,
        image: Optional[Image.Image],
        seed: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        image_hash: Optional[str] = None
        if image is not None:
            png_bytes = cloud_api.image_to_png_bytes(image)
            image_hash = cloud_api.bytes_hash(png_bytes)
        return {
            "provider": self.PROVIDER,
            "model": self.model_path,
            "prompt": prompt,
            "image_sha256": image_hash,
            "seed": seed,
            "payload": payload,
            "output_format": self.output_format,
        }

    # -- API call --------------------------------------------------------------

    @staticmethod
    def _unwrap(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise cloud_api.CloudAPIError(
                f"unexpected Seedream response type {type(response).__name__}: {response!r}"
            )
        if response.get("error"):
            code = response.get("code")
            message = response.get("error") if isinstance(response.get("error"), str) else response.get("message")
            classified = cloud_api.classify_http_error(400, response)
            raise type(classified)(
                f"Seedream API error: {message}", payload=response,
            )
        code = response.get("code")
        if code not in (None, 0, "0"):
            message = response.get("message") or response.get("msg") or response
            classified = cloud_api.classify_http_error(400, response)
            raise type(classified)(
                f"Seedream API error: code={code}: {message}", payload=response,
            )
        data = response.get("data")
        if isinstance(data, list) and data:
            return response
        if isinstance(data, dict):
            return response
        return response

    @staticmethod
    def _extract_image_url(response: dict[str, Any]) -> str:
        """Extract the generated image URL from the API response."""
        data = response.get("data")
        if isinstance(data, list) and data:
            item = data[0]
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
        raise cloud_api.CloudAPIError(
            f"Seedream response has no image URL: {response}",
            payload=response,
        )

    @staticmethod
    def _extract_image_b64(response: dict[str, Any]) -> str:
        """Extract a base64-encoded image from the API response."""
        data = response.get("data")
        if isinstance(data, list) and data:
            item = data[0]
            if isinstance(item, dict):
                b64 = item.get("b64_json")
                if isinstance(b64, str) and b64:
                    return b64
        raise cloud_api.CloudAPIError(
            f"Seedream response has no b64_json field: {response}",
            payload=response,
        )

    def _generate(self, payload: dict[str, Any]) -> bytes:
        """POST to /images/generations and download the image bytes.

        Seedream's API is synchronous — the image URL (or base64) is returned
        in the same response, no polling needed.
        """
        response = self._unwrap(self.client.request(
            "POST", "/images/generations", json_body=payload
        ))

        if self.response_format == "b64_json":
            import base64
            b64 = self._extract_image_b64(response)
            return base64.b64decode(b64)

        url = self._extract_image_url(response)
        return self.client.download(url)

    @staticmethod
    def _decode_image(data: bytes) -> Image.Image:
        """Decode raw image bytes into a PIL Image (RGB)."""
        return Image.open(io.BytesIO(data)).convert("RGB")

    # -- public API (matches QwenEditModel interface, R6) -----------------------

    def infer(
        self,
        image: Optional[Image.Image] = None,
        prompt: str = "",
        seed: int = 42,
        steps: int = 40,
        **provider_kwargs: Any,
    ) -> Image.Image:
        """Generate (or edit) an image and return it as a PIL Image.

        Args:
            image:  Reference PIL image for image-to-image editing.
                    Pass ``None`` for pure text-to-image.
            prompt: Text prompt describing the desired output.
            seed:   Random seed; server-side reproducibility is not guaranteed.
            steps:  Accepted for interface parity with ``QwenEditModel`` but
                    **not forwarded** — the Seedream API has no diffusion-step
                    parameter.
            **provider_kwargs: Seedream request fields overriding constructor
                    defaults (e.g. ``size`` or ``watermark``).

        Returns:
            Generated PIL image (RGB).
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        verbose = bool(provider_kwargs.pop("verbose", self.verbose))
        payload = self._build_payload(prompt, image, seed, provider_kwargs)
        cache_key = cloud_api.request_hash(
            self._cache_descriptor(prompt, image, seed, payload)
        )

        cached = self._cache.get(cache_key, ext=self.output_format)
        if cached is not None:
            self.last_call_info = {
                "provider": self.PROVIDER,
                "model": self.model_path,
                "cached": True,
                "cache_key": cache_key,
                "bytes": len(cached),
            }
            return self._decode_image(cached)

        t0 = time.time()
        data = self._generate(payload)
        elapsed = time.time() - t0

        self.last_call_info = {
            "provider": self.PROVIDER,
            "model": self.model_path,
            "elapsed_sec": round(elapsed, 2),
            "bytes": len(data),
            "cached": False,
        }
        self._cache.put(
            cache_key, data, self.last_call_info, ext=self.output_format
        )
        logger.info(
            "[seedream] elapsed=%.1fs bytes=%d",
            elapsed, len(data),
        )
        return self._decode_image(data)

    def infer_and_save(
        self,
        image: Optional[Image.Image] = None,
        output_path: str = "",
        prompt: str = "",
        seed: int = 42,
        steps: int = 40,
        **provider_kwargs: Any,
    ) -> str:
        """[C7] Generate one image, save to the caller's path, and return it."""
        if not output_path:
            raise ValueError("output_path is required (model_require.md R1.2)")
        result = self.infer(image, prompt=prompt, seed=seed, steps=steps,
                            **provider_kwargs)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fmt = "JPEG" if self.output_format in ("jpeg", "jpg") else "PNG"
        result.save(str(out), format=fmt)
        return str(out)

    # -- compatibility alias (matches QwenEditModel.edit) -----------------------

    def edit(
        self,
        image: Image.Image,
        prompt: str,
        seed: int = 42,
        steps: int = 40,
    ) -> Image.Image:
        """Compatibility alias; production operators use the canonical ``infer()``."""
        return self.infer(image, prompt=prompt, seed=seed, steps=steps)
