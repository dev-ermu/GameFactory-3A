"""
SeedanceModel — wrapper around Volcengine Ark's Seedance video-generation API.

Reference: https://www.volcengine.com/docs/82379/1520757

CONTRACT DEVIATIONS (model_require.md targets local-weight models;
                     see agent_skills/develop_harness/api_model_require.md):
  C1  R2.1/R2.2 -> R9.1  `model_path` carries a model version id.
  C2  R2.3      -> R9.2  `device` is accepted for parity and ignored.
  C3  R3.6      -> R9.3  no torch inference context; this is an HTTP API.
  C4  R4.1-R4.3 -> R9.4  `unload()` closes the HTTP session.
  C5  R3.3/R3.4 -> R9.5  `seed` is forwarded; reproducibility is not guaranteed.
  C6  R3.1      -> R9.6  submit, poll and download are hidden by `infer()`.
  C7  R1.2              `infer_and_save(..., output_path)` writes caller's path.
  C8  (new)     -> R9.8  identical billed requests use the response cache.
  C9  (new)     -> R9.9  shared HTTP retries classify terminal failures.

环境变量（统一写在 `<repo>/.env`，见 `.env.example`）：
    ARK_API_KEY   在首次 infer() 调用时必需，构造时不需要。
    ARK_API_BASE  在首次 infer() 调用时必需。只作示例、绝不静默回退，因为 Ark 端点
                  并非在所有网络下都可达。
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from models.common import cloud_api
from models.gen_cg_video.utils import VideoGenerationInput, VideoGenerationMode

logger = logging.getLogger(__name__)

#: `.env` 变量名；URL 由用户填写在 `.env` 里，代码不保留 URL 字面量（R9.7）。
ENV_KEY = "ARK_API_KEY"
ENV_BASE = "ARK_API_BASE"
DEFAULT_MODEL = "doubao-seedance-2-0-260128"

MODEL_ALIASES: dict[str, str] = {
    "seedance": DEFAULT_MODEL,
    "seedance-2.0": DEFAULT_MODEL,
    "seedance-2-0": DEFAULT_MODEL,
    "seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
    "seedance-2-0-fast": "doubao-seedance-2-0-fast-260128",
}

DONE_STATES = ("succeeded", "success", "completed")
FAILED_STATES = ("failed", "canceled", "cancelled", "expired")
SUPPORTED_FORMATS = ("mp4",)


class SeedanceModel:
    """Cloud video generation through Seedance 2.0.

    The only generation entry points are :meth:`infer` and
    :meth:`infer_and_save`. ``request.mode`` selects text, first-frame,
    first/last-frame or reference-image generation.
    """

    PROVIDER = "seedance"
    SUPPORTED_MODES = frozenset(VideoGenerationMode)

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        device: str = "cuda",
        *,
        api_key: Optional[str] = None,
        timeout: int = 1800,
        poll_interval: float = 3.0,
        max_retries: int = 3,
        cache_dir: Optional[str] = None,
        output_format: str = "mp4",
        resolution: str = "720p",
        ratio: str = "adaptive",
        generate_audio: bool = True,
        watermark: bool = False,
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
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        self.output_format = str(output_format).lower().lstrip(".")
        self.resolution = resolution
        self.ratio = ratio
        self.generate_audio = generate_audio
        self.watermark = watermark
        # [R9.7] 必填项，且在首次调用时才解析。端点由用户在 .env 里配置，代码
        # 不含任何 URL 示例。
        self.api_base = api_base
        self.http_timeout = http_timeout
        self.verbose = verbose

        if self.output_format not in SUPPORTED_FORMATS:
            raise ValueError(
                f"output_format={self.output_format!r} is not supported by "
                f"SeedanceModel; use {SUPPORTED_FORMATS[0]!r}"
            )

        self._client: Optional[cloud_api.CloudAPIClient] = None
        self._cache = cloud_api.ResponseCache(cache_dir, self.PROVIDER)
        self.last_call_info: dict[str, Any] = {}

    @property
    def client(self) -> cloud_api.CloudAPIClient:
        """首次使用时创建带鉴权的 HTTP 客户端（R9.7）。"""
        if self._client is None:
            key = cloud_api.require_api_key(
                self.api_key, ENV_KEY, who="SeedanceModel"
            )
            base = cloud_api.require_api_base(
                self.api_base, ENV_BASE, who="SeedanceModel"
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

    @staticmethod
    def _application_error(
        response: dict[str, Any], message: Any
    ) -> cloud_api.CloudAPIError:
        """Classify an error carried inside an otherwise successful HTTP response."""
        classified = cloud_api.classify_http_error(400, response)
        return type(classified)(f"Seedance API error: {message}", payload=response)

    @staticmethod
    def _unwrap(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise cloud_api.CloudAPIError(
                f"unexpected Seedance response type {type(response).__name__}: {response!r}"
            )
        if response.get("error"):
            raise SeedanceModel._application_error(response, response["error"])
        code = response.get("code")
        if code not in (None, 0, "0"):
            message = response.get("message") or response.get("msg") or response
            raise SeedanceModel._application_error(
                response, f"code={code}: {message}"
            )
        data = response.get("data")
        return data if isinstance(data, dict) else response

    @staticmethod
    def _image_parts(request: VideoGenerationInput) -> list[tuple[str, bytes]]:
        images: list[tuple[str, bytes]] = []
        if request.mode is VideoGenerationMode.FIRST_FRAME_TO_VIDEO:
            assert request.first_frame is not None
            images.append(("first_frame", cloud_api.image_to_png_bytes(request.first_frame)))
        elif request.mode is VideoGenerationMode.FIRST_LAST_FRAME_TO_VIDEO:
            assert request.first_frame is not None and request.last_frame is not None
            images.extend((
                ("first_frame", cloud_api.image_to_png_bytes(request.first_frame)),
                ("last_frame", cloud_api.image_to_png_bytes(request.last_frame)),
            ))
        elif request.mode is VideoGenerationMode.REFERENCE_TO_VIDEO:
            images.extend(
                ("reference_image", cloud_api.image_to_png_bytes(image))
                for image in request.reference_images
            )
        return images

    def _build_payload(
        self,
        request: VideoGenerationInput,
        images: list[tuple[str, bytes]],
        provider_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": cloud_api.image_to_data_uri(png)},
                "role": role,
            }
            for role, png in images
        )
        payload: dict[str, Any] = {
            "model": self.model_path,
            "content": content,
            "duration": request.duration_sec,
            # [CONTRACT-DEVIATION C5] Forwarded, but not guaranteed deterministic.
            "seed": request.seed,
            "resolution": self.resolution,
            "ratio": self.ratio,
            "generate_audio": self.generate_audio,
            "watermark": self.watermark,
        }
        payload.update(provider_kwargs)
        return payload

    def _cache_descriptor(
        self,
        request: VideoGenerationInput,
        images: list[tuple[str, bytes]],
        payload: dict[str, Any],
        *,
        content_overridden: bool = False,
    ) -> dict[str, Any]:
        # Keep the established descriptor for normal requests so existing paid
        # cache entries remain valid. If an advanced caller overrides `content`,
        # preserve all of it while hashing large/sensitive image URL values.
        content = payload.get("content")
        if not content_overridden:
            cache_content: Any = [{"type": "text", "text": request.prompt}]
        elif isinstance(content, list):
            cache_content = []
            for item in content:
                if not isinstance(item, dict) or "image_url" not in item:
                    cache_content.append(item)
                    continue
                safe_item = {
                    key: value
                    for key, value in item.items()
                    if key != "image_url"
                }
                safe_item["image_url_sha256"] = cloud_api.request_hash(
                    {"image_url": item["image_url"]}
                )
                cache_content.append(safe_item)
        else:
            cache_content = content

        payload_for_cache = {**payload, "content": cache_content}
        return {
            "provider": self.PROVIDER,
            "mode": request.mode.value,
            "payload": payload_for_cache,
            "images": [
                {"role": role, "sha256": cloud_api.bytes_hash(png)}
                for role, png in images
            ],
            "output_format": self.output_format,
        }

    def _submit(self, payload: dict[str, Any]) -> str:
        response = self._unwrap(self.client.request(
            "POST", "/contents/generations/tasks", json_body=payload
        ))
        task_id = response.get("id") or response.get("task_id")
        if not task_id:
            raise cloud_api.CloudAPIError(
                f"Seedance accepted the request but returned no task id: {response}",
                payload=response,
            )
        return str(task_id)

    def _fetch_task(self, task_id: str) -> dict[str, Any]:
        return self._unwrap(self.client.request(
            "GET", f"/contents/generations/tasks/{task_id}"
        ))

    def _wait(self, task_id: str, *, verbose: bool) -> dict[str, Any]:
        return cloud_api.poll_task(
            lambda: self._fetch_task(task_id),
            task_id=task_id,
            timeout=self.timeout,
            poll_interval=self.poll_interval,
            done_states=DONE_STATES,
            failed_states=FAILED_STATES,
            verbose=verbose,
        )

    @staticmethod
    def _video_url(task: dict[str, Any]) -> str:
        for container_name in ("content", "output", "result"):
            container = task.get(container_name)
            if isinstance(container, dict):
                for key in ("video_url", "url"):
                    value = container.get(key)
                    if isinstance(value, str) and value.startswith("http"):
                        return value
        for key in ("video_url", "url"):
            value = task.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        raise cloud_api.CloudAPIError(
            f"Seedance task {task.get('id') or task.get('task_id')} succeeded "
            f"without a video URL: {task}",
            task_id=str(task.get("id") or task.get("task_id") or "") or None,
            payload=task,
        )

    def infer(
        self,
        request: VideoGenerationInput,
        **provider_kwargs: Any,
    ) -> bytes:
        """Generate a video and return the downloaded MP4 bytes.

        Args:
            request: Validated prompt, duration and mode-specific PIL images.
            **provider_kwargs: Seedance request fields overriding constructor defaults.

        Returns:
            MP4 artifact bytes.
        """
        if not isinstance(request, VideoGenerationInput):
            raise TypeError(
                "request must be models.gen_cg_video.VideoGenerationInput, "
                f"not {type(request).__name__}"
            )
        if request.mode not in self.SUPPORTED_MODES:
            supported = ", ".join(sorted(mode.value for mode in self.SUPPORTED_MODES))
            raise NotImplementedError(
                f"{type(self).__name__} does not support {request.mode.value}; "
                f"supported modes: {supported}"
            )

        # ``verbose`` controls local polling logs; it is not a Seedance field.
        verbose = bool(provider_kwargs.pop("verbose", self.verbose))
        images = self._image_parts(request)
        content_overridden = "content" in provider_kwargs
        payload = self._build_payload(request, images, provider_kwargs)
        cache_key = cloud_api.request_hash(
            self._cache_descriptor(
                request,
                images,
                payload,
                content_overridden=content_overridden,
            )
        )
        cached = self._cache.get(cache_key, ext=self.output_format)
        if cached is not None:
            self.last_call_info = {
                "provider": self.PROVIDER,
                "model": self.model_path,
                "mode": request.mode.value,
                "cached": True,
                "cache_key": cache_key,
                "bytes": len(cached),
            }
            return cached

        t0 = time.time()
        task_id = self._submit(payload)
        task = self._wait(task_id, verbose=verbose)
        data = self.client.download(self._video_url(task))
        elapsed = time.time() - t0

        self.last_call_info = {
            "provider": self.PROVIDER,
            "model": self.model_path,
            "mode": request.mode.value,
            "task_id": task_id,
            "elapsed_sec": round(elapsed, 2),
            "bytes": len(data),
            "cached": False,
            "usage": task.get("usage"),
        }
        self._cache.put(
            cache_key, data, self.last_call_info, ext=self.output_format
        )
        logger.info(
            "[seedance] task=%s mode=%s elapsed=%.1fs bytes=%d",
            task_id, request.mode.value, elapsed, len(data),
        )
        return data

    def infer_and_save(
        self,
        request: VideoGenerationInput,
        output_path: str,
        **provider_kwargs: Any,
    ) -> str:
        """[C7] Generate one video, save to the caller's path, and return it."""
        if not output_path:
            raise ValueError("output_path is required (model_require.md R1.2)")
        data = self.infer(request, **provider_kwargs)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return str(out)
