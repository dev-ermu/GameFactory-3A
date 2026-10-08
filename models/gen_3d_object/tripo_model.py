"""
models/gen_3d_object/tripo_model.py

TripoModel — wrapper around Tripo3D's cloud 3D-generation API (image-to-3D and
text-to-3D), producing a GLB.

Reference: https://developers.tripo3d.ai/  (v3 API)

CONTRACT DEVIATIONS (model_require.md targets local-weight models; the rules that
replace it live in agent_skills/develop_harness/api_model_require.md):
  C1  R2.1/R2.2 → R9.1  `model_path` carries a *model version id*
                        ("v3.1-20260211"), not a weight location.
  C2  R2.3      → R9.2  `device` accepted for interface parity and ignored.
  C3  R3.6/R5.5 → R9.3  no @torch.no_grad(); torch is not involved.
  C4  R4.1-R4.3 → R9.4  `unload()` is a no-op that closes the HTTP session.
  C5  R3.3/R3.4 → R9.5  `seed` is forwarded as model_seed/texture_seed when the
                        provider accepts it; server-side reproducibility is NOT
                        guaranteed and is never faked locally.
  C6  R3.1      → R9.6  task-based API (submit → poll → download); `infer()`
                        blocks until completion or `timeout` (default 300 s).
                        A timeout error carries the `task_id`.
  C7  R1.2             uses the documented `infer_and_save(..., output_path)`
                        exception; the bytes-returning `infer()` exists alongside.
  C8  (new)     → R9.8  `cache_dir` prevents re-billing an identical request.
  C9  (new)     → R9.9  `max_retries` + exponential backoff; retryable (5xx/429/
                        transport) and terminal (400/401/402) failures are split.

环境变量（统一写在 `<repo>/.env`，见 `.env.example`）：
    TRIPO_API_KEY        在首次 infer() 调用时必需，构造时不需要。
    TRIPO_API_BASE       在首次 infer() 调用时必需。代码里不含端点示例，由你从
                         服务商控制台取当前值填入。
    `pip install requests` 仅 API 后端需要。

Usage:
    from models.gen_3d_object.tripo_model import TripoModel
    model = TripoModel(model_path="v3.1-20260211")
    path = model.infer_and_save(image, output_path="out/model.glb", seed=42)
    print(model.last_call_info)   # task_id, elapsed, credits, triangles
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from models.common import cloud_api
from models.common.glb_utils import glb_summary

logger = logging.getLogger(__name__)

#: `.env` 变量名。URL 一律由用户填写在该变量里，代码不保留任何 URL 字面量：
#: 服务商会改域名，写死的地址只会变成过期信息（R9.7）。
ENV_KEY = "TRIPO_API_KEY"
ENV_BASE = "TRIPO_API_BASE"

#: Short names accepted for `model_path`, mapped to the ids the API expects.
#: Unknown values are passed through untouched, so a version released after this
#: file was written still works without a code change.
MODEL_ALIASES: dict[str, str] = {
    "tripo": "v3.1-20260211",
    "tripo-v3.1": "v3.1-20260211",
    "v3.1": "v3.1-20260211",
    "tripo-v3.0": "v3.0-20250812",
    "v3.0": "v3.0-20250812",
    "tripo-v2.5": "v2.5-20250123",
    "v2.5": "v2.5-20250123",
    # P series — natively low-poly, the cheap option for mesh particles (B4.2).
    "tripo-p1": "P1-20260311",
    "p1": "P1-20260311",
}

DEFAULT_MODEL = "v3.1-20260211"

#: Terminal task states. Tripo reports lower-case; compared case-insensitively.
DONE_STATES = ("success", "succeeded", "finished", "completed")
FAILED_STATES = ("failed", "cancelled", "canceled", "banned", "expired", "unknown")

#: Output fields that have carried the download URL across API versions.
_MODEL_URL_KEYS = ("model_url", "pbr_model", "model", "base_model", "glb", "gltf")

#: `face_limit` range the service accepts **while `smart_low_poly` is on**.
#: Outside it the request is rejected with a terminal 400:
#:   "when smart_low_poly is enabled, face_limit must be between 500 and 20000
#:    (triangle mesh), got 30000"
#: Not in the public docs; found by calling it.
LOW_POLY_FACE_LIMIT_RANGE = (500, 20_000)


class TripoModel:
    """
    Cloud image-to-3D / text-to-3D through Tripo3D.

    Interchangeable with `Trellis2Model` in `Gen3DObjectOperator`: the
    `infer_and_save(image, output_path, seed, decimation_target, texture_size)`
    call signature is positionally identical (model_require.md R6).

    Args:
        model_path: [C1] Tripo model version id, or an alias from `MODEL_ALIASES`.
        device:     [C2] Accepted for interface parity, ignored. "cpu" is fine.
        api_key:    Explicit key; defaults to `$TRIPO_API_KEY`, read at first call.
        timeout:    [C6] Seconds to wait for one generation task.
        poll_interval: Seconds between status polls.
        max_retries: [C9] Extra attempts for retryable HTTP failures.
        cache_dir:  [C8] Directory for the response cache. None disables it.
        output_format: "glb" is produced natively. Any other format needs the
                    conversion endpoint — see `convert_path`.
        convert_path: API path of the format-conversion endpoint. Left as None
                    because it is not pinned down in the public v3 docs; set it
                    to enable `output_format="fbx"` without touching this file.
        low_poly:   [B4.3] Ask the service for clean low-poly topology
                    (`smart_low_poly`) instead of decimating locally.
        texture / pbr / quad / texture_quality / geometry_quality:
                    Forwarded verbatim to the generation endpoint.
        api_base:   覆盖 API 根地址。为 None 时读取 `.env` 中的 `$TRIPO_API_BASE`；
                    该变量缺失即报错（R9.7）。
        verbose:    Print task progress; off by default (R3.7).
    """

    #: Provider name, used for cache namespacing and log lines.
    PROVIDER = "tripo"

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        device: str = "cpu",
        *,
        api_key: Optional[str] = None,
        # Measured: image-to-3D with smart_low_poly took **601 s**, i.e. it would
        # have died one second past a 600 s budget. Timing out does not refund
        # the credits — the task finishes server-side and only the download is
        # lost — so the default errs long. The error carries the task_id.
        timeout: int = 1800,
        poll_interval: float = 3.0,
        max_retries: int = 3,
        cache_dir: Optional[str] = None,
        output_format: str = "glb",
        convert_path: Optional[str] = None,
        low_poly: bool = False,
        texture: bool = True,
        pbr: bool = True,
        quad: bool = False,
        texture_quality: str = "standard",
        geometry_quality: str = "standard",
        api_base: Optional[str] = None,
        http_timeout: int = 60,
        verbose: bool = False,
        **model_specific: Any,
    ):
        # [CONTRACT-DEVIATION C1] model_path is a version id, not a weight location.
        # [CONTRACT-DEVIATION C2] device accepted for interface parity, ignored.
        self.model_path = MODEL_ALIASES.get(str(model_path).lower(), model_path)
        self.device = device

        # R2.4 — every constructor argument lands on self before anything loads,
        # so unload()/reload round-trips without losing configuration.
        self.api_key = api_key
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        self.output_format = output_format.lower().lstrip(".")
        self.convert_path = convert_path
        self.low_poly = low_poly
        self.texture = texture
        self.pbr = pbr
        self.quad = quad
        self.texture_quality = texture_quality
        self.geometry_quality = geometry_quality
        # [R9.7] API 根地址是必填项，且在首次调用时才解析，因此构造函数既不要求
        # 凭证也不触网。端点由用户在 .env 里配置，代码不含任何 URL 示例。
        self.api_base = api_base
        self.http_timeout = http_timeout
        self.verbose = verbose
        self.model_specific = model_specific

        self._client: Optional[cloud_api.CloudAPIClient] = None
        self._cache = cloud_api.ResponseCache(cache_dir, self.PROVIDER)

        #: Record of the most recent **real** call: task_id, elapsed_sec, credits,
        #: triangles, bytes, cached. Operators copy it into meta.json (R9.8).
        self.last_call_info: dict[str, Any] = {}

    # ── plumbing ──────────────────────────────────────────────────────────────

    @property
    def client(self) -> cloud_api.CloudAPIClient:
        """
        HTTP 客户端，首次使用时创建。

        [C6/R9.7] API Key 与 API 根地址都在这里解析，而不是在 `__init__` 中，因此
        wrapper 可以在没有凭证的机器上被 import 和构造（`tests/harness/smoke.py`
        正是这么做的）。
        """
        if self._client is None:
            key = cloud_api.require_api_key(
                self.api_key, ENV_KEY, who="TripoModel")
            base = cloud_api.require_api_base(
                self.api_base, ENV_BASE, who="TripoModel")
            self._client = cloud_api.CloudAPIClient(
                base, key,
                timeout=self.http_timeout,
                max_retries=self.max_retries,
            )
        return self._client

    def unload(self) -> None:
        """[C4] Close the HTTP session. Idempotent, and safe before any call."""
        if self._client is not None:
            self._client.close()
            self._client = None

    close = unload

    @staticmethod
    def _unwrap(resp: Any) -> dict:
        """
        Strip Tripo's `{"code": 0, "data": {...}}` envelope.

        A non-zero `code` on an HTTP 200 is a terminal application error — the
        same request will fail the same way, so it must not be retried (R9.9).
        """
        if not isinstance(resp, dict):
            raise cloud_api.CloudAPIError(f"unexpected response type {type(resp).__name__}: {resp!r}")
        code = resp.get("code")
        if code not in (None, 0):
            message = resp.get("message") or resp.get("msg") or resp
            suggestion = resp.get("suggestion")
            raise cloud_api.CloudAPIRequestError(
                f"Tripo API error code={code}: {message}"
                + (f" — {suggestion}" if suggestion else ""),
                payload=resp,
            )
        data = resp.get("data")
        return data if isinstance(data, dict) else resp

    def _upload_image(self, png: bytes) -> str:
        """Upload PNG bytes, return the `file_token` used as generation input."""
        data = self._unwrap(self.client.request(
            "POST", "/files",
            files={"file": ("input.png", png, "image/png")},
        ))
        token = data.get("file_token") or data.get("image_token") or data.get("token")
        if not token:
            raise cloud_api.CloudAPIError(
                f"upload succeeded but no file_token in the response: {data}")
        return str(token)

    @staticmethod
    def _extract_model_url(task: dict) -> str:
        """Find the artifact URL in a finished task, across output field names."""
        output = task.get("output") or task.get("result") or {}
        for key in _MODEL_URL_KEYS:
            value = output.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
            if isinstance(value, dict) and isinstance(value.get("url"), str):
                return value["url"]
        raise cloud_api.CloudAPIError(
            f"task {task.get('task_id')} reported success but carries no model URL. "
            f"output={output!r}",
            task_id=task.get("task_id"), payload=task)

    def _fetch_task(self, task_id: str) -> dict:
        return self._unwrap(self.client.request("GET", f"/tasks/{task_id}"))

    # ── payload ───────────────────────────────────────────────────────────────

    def _clamp_face_limit(self, value: int) -> int:
        """
        Keep `face_limit` inside the range the service accepts.

        `Gen3DObjectOperator` forwards TRELLIS.2's default of 1 000 000, and with
        `low_poly=True` anything outside 500-20 000 is a terminal 400. Clamping
        (loudly) keeps the backends interchangeable (R6) rather than making the
        caller special-case each provider.
        """
        value = int(value)
        if not self.low_poly:
            return value
        low, high = LOW_POLY_FACE_LIMIT_RANGE
        clamped = max(low, min(value, high))
        if clamped != value:
            logger.warning("[tripo] face_limit %s clamped to %s "
                           "(smart_low_poly range %s-%s)", value, clamped, low, high)
        return clamped

    def _build_payload(
        self,
        *,
        prompt: Optional[str],
        negative_prompt: Optional[str],
        seed: Optional[int],
        decimation_target: Optional[int],
        provider_kwargs: dict,
    ) -> dict:
        """Generation parameters shared by the image and text endpoints."""
        payload: dict[str, Any] = {
            "model": self.model_path,
            "texture": self.texture,
            "pbr": self.pbr,
            "texture_quality": self.texture_quality,
            "geometry_quality": self.geometry_quality,
        }
        if self.quad:
            payload["quad"] = True
        if self.low_poly:
            # [B4.3] Ask the service for low-poly topology. Decimating a 2M-face
            # mesh locally wrecks UVs and normals; generating low-poly does not.
            payload["smart_low_poly"] = True
        if decimation_target:
            payload["face_limit"] = self._clamp_face_limit(decimation_target)
        if prompt:
            payload["prompt"] = prompt
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            # [CONTRACT-DEVIATION C5] forwarded, but the service does not promise
            # that the same seed reproduces the same mesh. Never faked locally.
            payload["model_seed"] = int(seed)
            payload["texture_seed"] = int(seed)
        payload.update(provider_kwargs)
        return payload

    # ── inference ─────────────────────────────────────────────────────────────

    def infer(
        self,
        image: Any = None,
        seed: int = 42,
        decimation_target: Optional[int] = None,
        texture_size: Optional[int] = None,
        *,
        prompt: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        image_url: Optional[str] = None,
        verbose: Optional[bool] = None,
        **provider_kwargs: Any,
    ) -> bytes:
        """
        Generate one 3D asset and return the model file bytes.

        [C6] Submits the task, polls until it finishes, downloads the artifact —
        all inside this call. Typical wall time is 20 s to 4 min.

        Args:
            image: Reference image as `PIL.Image.Image`, `np.ndarray` or PNG
                   `bytes`. Not a path (R3.2). Give `image`, `image_url` or
                   `prompt`; image wins when several are present.
            seed: [C5] Forwarded as `model_seed` / `texture_seed`. Reproducibility
                   is not guaranteed server-side.
            decimation_target: Target face count, forwarded as `face_limit`.
                   None leaves it to the service.
            texture_size: Accepted for signature parity with `Trellis2Model` and
                   **ignored** — Tripo exposes `texture_quality`, not a
                   resolution. Pass `texture_quality=` to the constructor.
            prompt: Text prompt for text-to-3D. [A4 decision] The operator slot is
                   image-to-3D today; accepting `prompt` here keeps text-to-3D
                   available without a second wrapper.
            negative_prompt: Text-to-3D only.
            image_url: Publicly reachable image URL, used instead of uploading.
            verbose: Override the constructor's verbosity for this call.
            **provider_kwargs: Merged into the request body verbatim, so a new
                   API parameter needs no change here.

        Returns:
            The model file as `bytes` — GLB unless `output_format`/`convert_path`
            say otherwise.

        Raises:
            CloudAPIAuthError: no or invalid `TRIPO_API_KEY`.
            CloudAPIQuotaError: out of credits (terminal, never retried).
            CloudTaskTimeout: not finished within `timeout`; carries `task_id`.
            CloudTaskFailed: the service rejected or failed the task.
        """
        verbose = self.verbose if verbose is None else verbose
        if image is None and image_url is None and not prompt:
            raise ValueError(
                "TripoModel.infer needs an image (`image=` / `image_url=`) or a "
                "text `prompt=`; got neither.")
        if texture_size is not None:
            # [CONTRACT-DEVIATION C2-style] accepted for parity, ignored.
            logger.debug("[tripo] texture_size=%s ignored; use texture_quality",
                         texture_size)
        if self.output_format != "glb" and not self.convert_path:
            raise NotImplementedError(
                f"TripoModel produces GLB; output_format={self.output_format!r} needs "
                f"Tripo's conversion endpoint, whose path is not pinned in the public "
                f"v3 docs. Either set convert_path=... on the constructor, use "
                f"MeshyModel(output_format='fbx') which returns FBX natively, or "
                f"convert the GLB with engine_adapters/blender/."
            )

        png = cloud_api.image_to_png_bytes(image) if image is not None else None
        use_image = png is not None or bool(image_url)
        payload = self._build_payload(
            # The image endpoint has no prompt field — sending one is a terminal
            # 400. An image plus a prompt means "use the image".
            prompt=None if use_image else prompt,
            negative_prompt=None if use_image else negative_prompt,
            seed=seed,
            decimation_target=decimation_target, provider_kwargs=provider_kwargs,
        )

        # [C8] Cache key covers everything that changes the output. The image is
        # represented by its hash, never its bytes, and the key never sees the API key.
        cache_key = cloud_api.request_hash({
            "provider": self.PROVIDER,
            "payload": payload,
            "image_sha256": cloud_api.bytes_hash(png) if png else None,
            "image_url": image_url,
            "output_format": self.output_format,
        })
        cached = self._cache.get(cache_key, ext=self.output_format)
        if cached is not None:
            self.last_call_info = {
                "provider": self.PROVIDER, "cached": True, "cache_key": cache_key,
                "bytes": len(cached), **glb_summary(cached),
            }
            return cached

        t0 = time.time()
        if png is not None:
            # `input` takes a file_token, a public URL or a previous task id.
            payload["input"] = self._upload_image(png)
            endpoint = "/generation/image-to-model"
        elif image_url:
            payload["input"] = image_url
            endpoint = "/generation/image-to-model"
        else:
            endpoint = "/generation/text-to-model"

        created = self._unwrap(self.client.request("POST", endpoint, json_body=payload))
        task_id = str(created.get("task_id") or created.get("id") or "")
        if not task_id:
            raise cloud_api.CloudAPIError(
                f"{endpoint} accepted the request but returned no task_id: {created}")
        if verbose:
            print(f"[tripo] task {task_id} submitted ({endpoint})")

        # Some responses already carry a finished task; only poll when they do not.
        state = str(created.get("status", "")).lower()
        if state in DONE_STATES:
            task = created
        else:
            task = cloud_api.poll_task(
                lambda: self._fetch_task(task_id),
                task_id=task_id,
                timeout=self.timeout,
                poll_interval=self.poll_interval,
                done_states=DONE_STATES,
                failed_states=FAILED_STATES,
                verbose=verbose,
            )

        data = self.client.download(self._extract_model_url(task))
        elapsed = time.time() - t0

        info = glb_summary(data) if self.output_format == "glb" else {"bytes": len(data)}
        self.last_call_info = {
            "provider": self.PROVIDER,
            "model": self.model_path,
            "task_id": task_id,
            "elapsed_sec": round(elapsed, 2),
            "credits": task.get("credits_consumed", task.get("credits")),
            "cached": False,
            "cache_key": cache_key,
            # The provider's own render — see the note in meshy_model.py.
            "preview_url": (task.get("output") or {}).get("rendered_image_url"),
            **info,
        }
        # R9.8 — one line per billed call: what it cost and what it produced.
        logger.info(
            "[tripo] task=%s model=%s %.1fs credits=%s triangles=%s bytes=%s",
            task_id, self.model_path, elapsed, self.last_call_info.get("credits"),
            info.get("triangles"), len(data),
        )
        if verbose:
            print(f"[tripo] {self.last_call_info}")

        self._cache.put(cache_key, data, {
            "provider": self.PROVIDER, "payload": payload,
            **{k: v for k, v in self.last_call_info.items() if k != "cache_key"},
        }, ext=self.output_format)
        return data

    def infer_and_save(
        self,
        image: Any = None,
        output_path: Optional[str] = None,
        seed: int = 42,
        decimation_target: Optional[int] = None,
        texture_size: Optional[int] = None,
        *,
        prompt: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        image_url: Optional[str] = None,
        verbose: Optional[bool] = None,
        **provider_kwargs: Any,
    ) -> str:
        """
        [C7] The documented R1.2 exception: run `infer()` and write the result.

        The path comes **in** from the caller and is never derived here — the
        operator owns artifact placement.

        Args:
            output_path: Destination file. Parent directories are created.
            (everything else: see `infer`)

        Returns:
            `str(output_path)`.
        """
        if not output_path:
            raise ValueError("output_path is required (model_require.md R1.2)")
        data = self.infer(
            image, seed, decimation_target, texture_size,
            prompt=prompt, negative_prompt=negative_prompt, image_url=image_url,
            verbose=verbose, **provider_kwargs,
        )
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return str(out)

    # ── account ───────────────────────────────────────────────────────────────

    def balance(self) -> dict:
        """
        Remaining credits: ``{"balance": float, "frozen": float}``.

        Cheap and unbilled — call it before a batch to check the budget (C4 note:
        this is the only method that talks to the API without generating).
        """
        return self._unwrap(self.client.request("GET", "/account/balance"))
