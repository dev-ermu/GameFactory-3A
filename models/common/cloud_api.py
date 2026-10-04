"""
models/common/cloud_api.py

Shared plumbing for closed-source ("cloud API") model wrappers — the part of
Tripo / Meshy / Rodin / ElevenLabs / Kling wrappers that is identical no matter
what the provider generates.

契约见 `agent_skills/develop_harness/api_model_require.md` R9。
本模块实现 R9.6（submit → poll → download 藏在一次阻塞调用之后）、R9.7（凭证**与
API 根地址**都在调用时从配置读取）、R9.8（响应缓存，避免重跑二次计费）以及
R9.9（带退避的重试，区分可重试／终态失败）。

It knows nothing about 3D, audio or video — only HTTP, money and failure modes.

配置只有一个来源：`<repo>/.env`。import 本模块即会加载它（经 `config`），
因此脱离 Pipeline runner 单独使用的 wrapper 也能读到该文件。Key 与 API 根地址都是
必填项：硬编码端点不可取，因为公开端点并非在所有网络下都可达，而静默回退只会在
第一次计费调用时失败。

Dependencies: stdlib at import time; `requests` is imported lazily on first use
so `tests/harness/smoke.py` keeps working on a machine that does not have it.

Usage:
    from models.common import cloud_api

    # 只传环境变量名。URL 一律来自 `.env`，调用方不携带任何 URL 字面量。
    key = cloud_api.require_api_key(None, "TRIPO_API_KEY")
    base = cloud_api.require_api_base(None, "TRIPO_API_BASE")
    client = cloud_api.CloudAPIClient(base, key)
    data = client.request("POST", "/generation/text-to-model", json={...})
"""

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _load_project_env() -> None:
    """在**不** import `pipeline/` 的前提下让 `<repo>/.env` 生效（R1.1）。

    `config` 是顶层、纯标准库模块，因此 model 可以 import 它而不依赖编排层。
    找不到该模块也不致命：wrapper 会退回原来的行为，只读进程环境变量。
    """
    try:
        import config  # noqa: PLC0415
    except ModuleNotFoundError:
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            import config  # noqa: PLC0415
        except ModuleNotFoundError:  # pragma: no cover - vendored use
            return

    try:
        config.load()
    except Exception:  # pragma: no cover - configuration must never crash import
        logger.debug("[cloud_api] could not load .env", exc_info=True)


#: 在任何 wrapper 读取变量之前，先用 `.env` 填充 os.environ。
_load_project_env()

#: HTTP statuses worth retrying — transient by nature.
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

#: HTTP statuses that will never succeed on retry: bad request, auth, quota.
TERMINAL_STATUS: frozenset[int] = frozenset({400, 401, 402, 403, 404, 405, 413, 415, 422})


# ── Errors ────────────────────────────────────────────────────────────────────


class CloudAPIError(RuntimeError):
    """
    Base class for every cloud-API failure.

    Attributes:
        status:   HTTP status code, when the failure came from a response.
        task_id:  Provider task id, when one had already been created — keep it,
                  a timed-out task usually finishes anyway and can be fetched
                  later (`api_model_require.md` R9.6).
        payload:  Decoded response body, truncated for readability.
    """

    retryable = False

    def __init__(self, message: str, *, status: Optional[int] = None,
                 task_id: Optional[str] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.task_id = task_id
        self.payload = payload


class CloudAPIAuthError(CloudAPIError):
    """401 / 403 — the key is missing, wrong, or lacks the entitlement."""


class CloudAPIQuotaError(CloudAPIError):
    """402 or a provider-specific "insufficient credits" body. Terminal."""


class CloudAPIRequestError(CloudAPIError):
    """400 / 404 / 422 — the request itself is wrong. Terminal."""


class CloudAPIServerError(CloudAPIError):
    """5xx and connection-level failures. Retryable."""

    retryable = True


class CloudAPIRateLimitError(CloudAPIServerError):
    """429 — retryable, honour `Retry-After` when present."""


class CloudTaskFailed(CloudAPIError):
    """The provider accepted the task and then reported failure."""


class CloudTaskTimeout(CloudAPIError):
    """The task did not reach a terminal state within `timeout` seconds."""


class CloudAPIConfigError(CloudAPIError):
    """必需配置项缺失，例如 API 根地址。

    属于终态错误：重试也无法变出一个不存在的配置项。
    """


# ── Credentials ───────────────────────────────────────────────────────────────


def require_api_key(value: Optional[str], env_var: str, *,
                    who: str = "This model") -> str:
    """
    Resolve an API key, failing fast with an actionable message (R1.6 / R9.7).

    Args:
        value:       Explicit key passed to the constructor, or None.
        env_var:     Environment variable to fall back to.
        who:         Name used in the error message.

    Returns:
        The key.

    Raises:
        CloudAPIAuthError: no key available.
    """
    key = value or os.environ.get(env_var)
    if key:
        return key.strip()
    raise CloudAPIAuthError(
        f"{who} needs an API key and none was found.\n"
        f"  1. set {env_var}=<your key> in .env          # never commit it\n"
        f"     (or pass api_key=... to the constructor)"
    )


def require_api_base(value: Optional[str], env_var: str, *,
                     who: str = "This model") -> str:
    """
    解析 API 根地址；未配置时立即失败（R9.7）。

    Base URL 是**必填**而非带默认值：公开端点并非在所有网络下都可达，硬编码的回退会
    一直表现得像「配置正常」，直到第一次计费调用失败。代码里同样不保留端点示例——
    服务商会改域名，过期示例只会误导；当前值从服务商控制台取。

    Args:
        value:      构造函数显式传入的 base，或 None。
        env_var:    回退读取的环境变量名。
        who:        出现在错误信息里的名称。

    Returns:
        去掉尾部斜杠的 base URL。

    Raises:
        CloudAPIConfigError: 拿不到 base URL。
    """
    base = (value or os.environ.get(env_var) or "").strip()
    if base:
        return base.rstrip("/")
    raise CloudAPIConfigError(
        f"{who} needs its API base URL and none was configured.\n"
        f"  1. copy the endpoint from the provider's console into {env_var} "
        f"in .env\n"
        f"  The base URL is required, not defaulted, because the public "
        f"endpoint is not reachable from every network."
    )


def redact(key: Optional[str]) -> str:
    """Key fingerprint safe to put in a log line or `meta.json`."""
    if not key:
        return "<unset>"
    return f"{key[:4]}…{key[-2:]} (len {len(key)})"


# ── HTTP ──────────────────────────────────────────────────────────────────────


def _requests():
    """Import `requests` lazily with an actionable message (R1.5 / R1.6)."""
    try:
        import requests  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - environment dependent
        raise ImportError(
            "Cloud-API model wrappers need the `requests` package:\n"
            "    bash scripts/asset_env_setup/cloud_api_install.sh\n"
            "    # or simply: python -m pip install requests\n"
            "(only needed for the API backends; the local-weight models and "
            "tests/harness/smoke.py do not import it.)"
        ) from e
    return requests


def _truncate(payload: Any, limit: int = 600) -> Any:
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    return text if len(text) <= limit else text[:limit] + f"… (+{len(text) - limit} chars)"


def classify_http_error(status: int, body: Any, *,
                        task_id: Optional[str] = None) -> CloudAPIError:
    """
    Map an HTTP status onto the right exception class (R9.9).

    The body is inspected too: providers happily answer 200/400 with a
    "not enough credits" payload, which must not be retried.
    """
    text = _truncate(body)
    low = str(text).lower()
    # Providers phrase "you are out of money" in prose, and the status code alone
    # does not distinguish it from a bad key: Tripo answers **403** with
    # "You don't have enough credit to create this task". Matching the body first
    # is what keeps "wrong key" and "no money" apart for the caller.
    if any(s in low for s in ("insufficient", "enough credit", "enough credits",
                              "out of credit", "purchase more credit",
                              "quota exceeded", "no credits", "balance")):
        return CloudAPIQuotaError(
            f"HTTP {status}: out of credits — {text}", status=status,
            task_id=task_id, payload=body)
    if status in (401, 403):
        return CloudAPIAuthError(
            f"HTTP {status}: authentication rejected — {text}", status=status,
            task_id=task_id, payload=body)
    if status == 402:
        return CloudAPIQuotaError(
            f"HTTP {status}: payment required — {text}", status=status,
            task_id=task_id, payload=body)
    if status == 429:
        return CloudAPIRateLimitError(
            f"HTTP {status}: rate limited — {text}", status=status,
            task_id=task_id, payload=body)
    if status in TERMINAL_STATUS:
        return CloudAPIRequestError(
            f"HTTP {status}: request rejected — {text}", status=status,
            task_id=task_id, payload=body)
    if status in RETRYABLE_STATUS or status >= 500:
        return CloudAPIServerError(
            f"HTTP {status}: server error — {text}", status=status,
            task_id=task_id, payload=body)
    return CloudAPIError(
        f"HTTP {status}: unexpected response — {text}", status=status,
        task_id=task_id, payload=body)


class CloudAPIClient:
    """
    Thin retrying HTTP client for one provider.

    Args:
        base_url:     Root of the API, without a trailing slash.
        api_key:      Bearer token.
        timeout:      Per-request socket timeout in seconds (not the task timeout).
        max_retries:  Extra attempts after the first one, for retryable failures.
        backoff:      Base of the exponential backoff, seconds.
        auth_header:  Header name / value template, for providers that do not
                      use `Authorization: Bearer <key>`.
        user_agent:   Sent as-is; helps providers attribute traffic.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: int = 60,
        max_retries: int = 3,
        backoff: float = 1.5,
        auth_header: str = "Authorization",
        auth_template: str = "Bearer {key}",
        user_agent: str = "3AGameFactory/0.1 (+https://github.com/OpenDCAI/GameFactory-3A)",
    ):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.auth_header = auth_header
        self.auth_template = auth_template
        self.user_agent = user_agent
        self._session = None

    # -- session ---------------------------------------------------------------

    @property
    def session(self):
        """Lazily created `requests.Session` (kept alive across polls)."""
        if self._session is None:
            requests = _requests()
            self._session = requests.Session()
            self._session.headers.update({
                self.auth_header: self.auth_template.format(key=self._api_key),
                "User-Agent": self.user_agent,
            })
        return self._session

    def close(self) -> None:
        """Idempotent — safe after a failed construction and safe to call twice."""
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None

    # -- requests --------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        expect_json: bool = True,
    ) -> Any:
        """
        Perform one API call, retrying retryable failures (R9.9).

        Args:
            method:      "GET" / "POST" / …
            path:        Path appended to `base_url`, or a full URL.
            json_body:   JSON payload.
            files/data:  multipart payload (`requests` semantics).
            params:      Query string.
            expect_json: Parse the response as JSON; otherwise return `bytes`.

        Returns:
            Parsed JSON (dict / list) or raw `bytes`.

        Raises:
            CloudAPIError subclass — terminal errors immediately, retryable ones
            after `max_retries` attempts.
        """
        requests = _requests()
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"

        last: Optional[CloudAPIError] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(
                    method, url, json=json_body, files=files, data=data,
                    params=params, timeout=self.timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                last = CloudAPIServerError(f"{method} {url} failed at transport level: {e}")
            else:
                if resp.ok:
                    if not expect_json:
                        return resp.content
                    try:
                        return resp.json()
                    except ValueError as e:
                        raise CloudAPIError(
                            f"{method} {url} returned {resp.status_code} with a "
                            f"non-JSON body: {_truncate(resp.text)}"
                        ) from e
                try:
                    body: Any = resp.json()
                except ValueError:
                    body = resp.text
                err = classify_http_error(resp.status_code, body)
                if not err.retryable:
                    raise err
                last = err
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        time.sleep(min(float(retry_after), 60.0))
                    except ValueError:
                        pass

            if attempt < self.max_retries:
                delay = self.backoff * (2 ** attempt)
                logger.warning("[cloud_api] %s %s attempt %d/%d failed (%s); retrying in %.1fs",
                               method, url, attempt + 1, self.max_retries + 1, last, delay)
                time.sleep(delay)

        assert last is not None
        raise last

    def download(self, url: str, *, max_bytes: Optional[int] = None) -> bytes:
        """
        Fetch a generated artifact. Signed asset URLs are short-lived — call this
        immediately after the task reports success.

        Args:
            url: Absolute URL from the task output.
            max_bytes: Reject anything larger, so a wrong URL cannot fill a disk.

        Returns:
            The file content.
        """
        content = self.request("GET", url, expect_json=False)
        if max_bytes is not None and len(content) > max_bytes:
            raise CloudAPIError(
                f"downloaded artifact is {len(content)} bytes, over the "
                f"{max_bytes} byte limit: {url}")
        if not content:
            raise CloudAPIError(f"downloaded artifact is empty: {url}")
        return content


# ── Polling ───────────────────────────────────────────────────────────────────


def poll_task(
    fetch: Callable[[], dict],
    *,
    task_id: str,
    timeout: float = 300.0,
    poll_interval: float = 3.0,
    done_states: Iterable[str],
    failed_states: Iterable[str],
    state_key: str = "status",
    progress_key: str = "progress",
    verbose: bool = False,
) -> dict:
    """
    Block until a provider task reaches a terminal state (R9.6).

    Args:
        fetch:         Callable returning the decoded task object.
        task_id:       Only used for messages — every error carries it.
        timeout:       Wall-clock budget in seconds.
        poll_interval: Seconds between polls.
        done_states:   States meaning success (compared case-insensitively).
        failed_states: States meaning failure.
        state_key:     Field holding the state.
        progress_key:  Field holding 0-100 progress, when the provider sends one.
        verbose:       Print progress; otherwise only DEBUG logs (R3.7).

    Returns:
        The task object in its successful terminal state.

    Raises:
        CloudTaskFailed:  provider reported failure.
        CloudTaskTimeout: budget exhausted; the task may still finish server-side,
                          the error carries `task_id` so it can be fetched later.
    """
    done = {s.lower() for s in done_states}
    failed = {s.lower() for s in failed_states}
    deadline = time.time() + timeout
    last_progress = -1

    while True:
        task = fetch()
        state = str(task.get(state_key, "")).lower()
        progress = task.get(progress_key)

        if progress != last_progress:
            last_progress = progress
            logger.debug("[cloud_api] task %s: %s (%s%%)", task_id, state, progress)
            if verbose:
                print(f"[cloud_api] task {task_id}: {state} ({progress}%)")

        if state in done:
            return task
        if state in failed:
            raise CloudTaskFailed(
                f"task {task_id} ended as {state!r}: {_truncate(task)}",
                task_id=task_id, payload=task)

        remaining = deadline - time.time()
        if remaining <= 0:
            raise CloudTaskTimeout(
                f"task {task_id} still {state!r} after {timeout:.0f}s. It may still "
                f"finish server-side — query it with the task id above, or raise "
                f"`timeout=` on the model.",
                task_id=task_id, payload=task)
        time.sleep(min(poll_interval, remaining))


# ── Response cache ────────────────────────────────────────────────────────────


def request_hash(payload: dict) -> str:
    """
    Stable sha256 over a request description (R9.8).

    The payload must contain everything that changes the output — model version,
    prompt, image bytes hash, every generation parameter, the output format.
    Never put the API key in it.
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bytes_hash(data: bytes) -> str:
    """sha256 of a binary input, e.g. the reference image."""
    return hashlib.sha256(data).hexdigest()


class ResponseCache:
    """
    Content-addressed cache of generated artifacts.

    A cloud call costs credits, so an identical request must never be sent twice
    (R9.8). Layout::

        <cache_dir>/<provider>/<hash>.<ext>        the artifact
        <cache_dir>/<provider>/<hash>.meta.json    request description + task id

    Args:
        cache_dir: Root directory. `None` disables caching entirely.
        provider:  Sub-directory name, so two providers never collide.
    """

    def __init__(self, cache_dir: Optional[str | Path], provider: str):
        self.root = Path(cache_dir).expanduser() / provider if cache_dir else None
        self.provider = provider

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def _paths(self, key: str, ext: str) -> tuple[Path, Path]:
        assert self.root is not None
        return self.root / f"{key}.{ext}", self.root / f"{key}.meta.json"

    def get(self, key: str, ext: str = "glb") -> Optional[bytes]:
        """Cached artifact bytes, or None. Performs no network I/O, ever."""
        if not self.enabled:
            return None
        blob, _ = self._paths(key, ext)
        if blob.is_file() and blob.stat().st_size > 0:
            logger.info("[cloud_api] cache hit (%s): %s", self.provider, blob.name)
            return blob.read_bytes()
        return None

    def put(self, key: str, data: bytes, meta: dict, ext: str = "glb") -> Path:
        """Store an artifact plus the request that produced it. Returns its path."""
        if not self.enabled:
            return Path()
        blob, meta_path = self._paths(key, ext)
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        meta_path.write_text(
            json.dumps({**meta, "cache_key": key, "bytes": len(data)},
                       indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return blob


# ── Input encoding ────────────────────────────────────────────────────────────


def image_to_png_bytes(image: Any) -> bytes:
    """
    Normalize an image input to PNG bytes.

    Accepts a `PIL.Image.Image`, raw `bytes` (returned unchanged), or a
    `np.ndarray`. Paths are rejected on purpose — `model_require.md` R3.2 says a
    model takes the object, not a path.

    Returns:
        PNG-encoded bytes (RGBA preserved when present).
    """
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    if isinstance(image, (str, Path)):
        raise TypeError(
            "models take an image object, not a path (model_require.md R3.2). "
            "Open it in the operator: Image.open(path).convert('RGBA')"
        )

    from io import BytesIO  # noqa: PLC0415

    from PIL import Image as PILImage  # noqa: PLC0415

    if not isinstance(image, PILImage.Image):
        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            np = None  # type: ignore[assignment]
        if np is not None and isinstance(image, np.ndarray):
            image = PILImage.fromarray(image)
        else:
            raise TypeError(
                f"unsupported image type {type(image).__name__}; expected "
                f"PIL.Image.Image, numpy.ndarray or bytes"
            )

    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def image_to_data_uri(image: Any, mime: str = "image/png") -> str:
    """PNG data URI (`data:image/png;base64,…`) for providers that take one inline."""
    import base64  # noqa: PLC0415

    payload = base64.b64encode(image_to_png_bytes(image)).decode("ascii")
    return f"data:{mime};base64,{payload}"
