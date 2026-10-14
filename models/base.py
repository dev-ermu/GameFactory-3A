"""云端大模型封装的抽象基类。

所有模型封装共享的能力集中在这里，具体模型只需要实现 `request()`：
统一的客户端构建、可重试故障的指数退避、远程任务的轮询、生成结果的强制落盘。
把这些放进基类而不是各模型重复实现，是因为规范 R8 要求重试分类在所有服务商
之间保持一致——一处判断错了，其他封装会跟着错。

子类通过自己的 `__init__` 追加服务商特有参数，再调用 `super().__init__()`，
不使用 `**kwargs` 这类模糊容器，便于 IDE 与类型检查器给出准确提示。

规范条款对照：
    R2.1  `model_id` 是调用 API 时真实使用的模型标识，无默认值
    R2.2  构造参数一律存入 `self`
    R3.2  输入是对象而非路径，由子类负责校验
    R4.1  客户端复用 keep-alive 连接池
    R4.2  `bind_session` 用于延续上一次的服务端会话
    R5.2  `timeout` 与 `poll_interval` 为构造参数，默认超时偏长
    R5.3  超时异常必须携带 `task_id`
    R6.1  凭证与 Base URL 在首次调用时才读取
    R6.3  Base URL 必填，代码不猜测、不改写
    R7.1  生成结果必须落盘
    R8    可重试与终态故障分离
"""

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx2
from openai import OpenAI

from config import settings
from models.common import errors


class BaseModel(ABC):
    """云端大模型封装的公共基类。"""

    # 子类覆盖：用于报错信息的服务商名称
    provider: str = "cloud"

    # 子类覆盖：展示给用户的可读名称
    display_name: str = "CloudModel"

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: int = 1800,
        poll_interval: float = 10.0,
        max_retries: int = 3,
        output_format: str = "glb",
        verbose: bool = False,
    ) -> None:
        """保存全部构造参数，供子类在首次调用时使用。"""
        self.model_id = model_id
        self.api_key = api_key
        self.api_base = api_base
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.output_format = output_format
        self.verbose = verbose

        self._client: OpenAI | None = None
        self._http_client: httpx2.Client | None = None
        self._previous_response_id: str | None = None

    @abstractmethod
    def request(self, *args: Any, **kwargs: Any) -> Any:
        """执行一次模型调用，由子类按服务商协议实现。"""
        pass

    def credential_spec(self) -> tuple[str, str]:
        """返回该模型需要的 `(密钥配置项名, Base URL 配置项名)`。

        子类必须覆盖。基类只认这两个名字，凭据的实际读取由 `resolve_credential`
        统一完成，避免各模型自行去碰环境变量。
        """
        pass
    
    # ── 凭证与端点 ────────────────────────────────────────────────

    def resolve_credential(self) -> tuple[str, str]:
        """读取 API Key 与 API Base URL，缺失时给出可操作的报错。

        规范 R6.1 要求延迟到首次调用才读取，因为测试存根会在没有任何凭证的
        机器上实例化模型对象；R6.3 要求 Base URL 没有默认值——服务商随时
        可能更换地址，代码猜测只会在第一次计费调用时才暴露问题。
        """
        key_field, base_field = self.credential_spec()

        api_key = self.api_key or getattr(settings, key_field, "")
        api_base = self.api_base or getattr(settings, base_field, "")

        if not api_key:
            raise errors.CloudModelConfigError(
                f"{self.display_name} 缺少 API Key。请在 .env 中填写 {key_field}，"
                f"再重试。本次调用未向服务商发起请求，不消耗额度。"
            )
        if not api_base:
            raise errors.CloudModelConfigError(
                f"{self.display_name} 缺少 API Base URL。请在 .env 中填写 "
                f"{base_field}，再重试。Base URL 没有默认值，代码不会猜测。"
            )

        return str(api_key), str(api_base)

    def openai_client(self) -> OpenAI:
        """返回复用 keep-alive 连接池的 OpenAI 客户端，首次调用时构建。

        对应规范 R4.1 与 R3.1：优先使用官方 Python 包与 Responses API。
        客户端在多次调用之间复用，HTTP 连接不会被反复建立。
        """
        if self._client is None:
            api_key, api_base = self.resolve_credential()
            self._client = OpenAI(api_key=api_key, base_url=api_base, max_retries=0)

        return self._client

    def http_client(self) -> httpx2.Client:
        """返回原生 HTTP 客户端，供未提供 OpenAI 协议的厂商使用。

        豆包语音 TTS、通义万相图像生成等服务商有自己的接口形态，无法套用
        OpenAI SDK，此时退回直接发 HTTP 请求。Base URL 按用户填写原样传入，
        符合规范 R6.4：代码不做任何拼接或改写。
        """
        if self._http_client is None:
            api_key, api_base = self.resolve_credential()
            self._http_client = httpx2.Client(
                base_url=api_base,
                headers=self.auth_headers(api_key),
                timeout=httpx2.Timeout(float(self.timeout), connect=30.0),
                limits=httpx2.Limits(max_connections=8, max_keepalive_connections=4),
            )

        return self._http_client

    def auth_headers(self, api_key: str) -> dict[str, str]:
        """返回该服务商要求的鉴权头，子类可覆盖。"""
        return {"Authorization": f"Bearer {api_key}"}

    def build_payload(self) -> dict[str, Any]:
        """返回本次调用的公共请求体字段，子类可覆盖或忽略。

        多数服务商会返回 `task_id`、额度消耗等公共信息，集中在这里可以
        让子类只关心自己特有的部分。
        """
        return {}

    # ── 会话延续 ────────────────────────────────────────────────────

    def bind_session(self, response_id: str) -> None:
        """记住上一次的响应标识，供后续修改类调用复用（R4.2）。"""
        self._previous_response_id = response_id

    @property
    def session_id(self) -> str | None:
        """返回当前绑定的会话标识。"""
        return self._previous_response_id

    def release(self) -> None:
        """关闭底层连接，释放网络资源。重复调用是安全的。"""
        if self._client is not None:
            self._client.close()

        if self._http_client is not None:
            self._http_client.close()

        self._client = None
        self._http_client = None
        self._previous_response_id = None

    # ── 重试 ────────────────────────────────────────────────────────

    def is_retryable(self, exc: BaseException) -> bool:
        """判断异常是否值得重试。

        对应规范 R8.2：可重试的是限流、5xx 与传输层故障；参数错误、
        认证失败、额度不足属于终态，重试只会浪费额度。
        """
        if isinstance(exc, errors.CloudTaskError):
            return False

        if isinstance(
            exc,
            (
                errors.CloudModelConfigError,
                errors.CloudModelAuthError,
                errors.CloudModelQuotaError,
                errors.CloudModelRequestError,
            ),
        ):
            return False

        return isinstance(
            exc,
            (
                errors.CloudModelRateLimitError,
                errors.CloudModelServerError,
                errors.CloudModelNetworkError,
            ),
        )

    def call_with_retry(self, operation: Callable[[], Any]) -> Any:
        """执行一次调用，遇到可重试故障时按指数退避重试。

        对应规范 R8.1。退避基数取 `poll_interval`，让不同服务商共享同一套
        节奏；终态故障立即抛出，不做任何等待。
        """
        attempt = 0

        while True:
            try:
                return operation()
            except Exception as exc:
                if not self.is_retryable(exc) or attempt >= self.max_retries:
                    raise

                delay = max(self.poll_interval, 2.0) * (2 ** attempt)

                if self.verbose:
                    print(f"[{self.display_name}] 可重试故障，{delay:.1f}s 后重试：{exc}")

                time.sleep(delay)
                attempt += 1

    # ── 远程任务 ────────────────────────────────────────────────────

    def poll_task(
        self,
        task_id: str,
        fetch: Callable[[], Mapping[str, Any]],
        finished: Sequence[str] = ("succeeded", "completed", "success"),
        failed: Sequence[str] = ("failed", "cancelled", "failure"),
    ) -> Mapping[str, Any]:
        """轮询远程任务直到进入终态。

        对应规范 R5。默认超时偏长（R5.2）——超时不退款，任务仍会在服务端
        跑完，短超时会在最需要结果的时刻丢掉整笔额度；超时抛出的异常携带
        `task_id`（R5.3），调用方可据此事后取回结果。
        """
        deadline = time.monotonic() + self.timeout
        terminal_ok = {s.lower() for s in finished}
        terminal_bad = {s.lower() for s in failed}

        while True:
            payload = self.call_with_retry(fetch)
            state = str(payload.get("status", "")).lower()

            if state in terminal_ok:
                return payload

            if state in terminal_bad:
                reason = str(
                    payload.get("error") or payload.get("message") or "服务端未说明原因"
                )
                raise errors.CloudTaskError(
                    f"{self.display_name} 任务 {task_id} 失败：{reason}"
                )

            if time.monotonic() >= deadline:
                raise errors.CloudTaskTimeout(
                    f"{self.display_name} 任务 {task_id} 等待超过 {self.timeout} 秒。"
                    f"任务仍在服务端执行，可凭该 task_id 稍后取回结果，无需重新提交。",
                    task_id=task_id,
                )

            time.sleep(self.poll_interval)
    
    # ── 产物落盘 ────────────────────────────────────────────────────

    def persist(self, payload: bytes, directory: str | Path, filename: str) -> Path:
        """把生成结果写入磁盘并返回路径。

        对应规范 R7.1：无论结果是否令人满意，生成出来的资源都必须保存，
        代码不允许丢弃——重新调用一次是要付费的。目录由调用方给出，模型
        自身不构造业务路径（R1.2）。
        """
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)

        target = target_dir / filename
        target.write_bytes(payload)

        return target

    def record_call(
        self,
        directory: str | Path,
        task_id: str | None,
        elapsed_sec: float,
        credit: float | None,
        output_bytes: int,
    ) -> Path:
        """记录一次真实调用的计费信息，供审计与成本追踪。

        对应规范 R7.2。任何生成结果旁边都应留下这份记录，写明任务标识、
        耗时、消耗额度与产物体积。
        """
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "call_record.json"

        record = {
            "provider": self.provider,
            "model_id": self.model_id,
            "task_id": task_id,
            "elapsed_sec": round(elapsed_sec, 2),
            "credit": credit,
            "output_bytes": output_bytes,
            "output_format": self.output_format,
        }

        target.write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return target

    def save_payload(self, payload: bytes, output_path: str | Path) -> str:
        """把产物写到调用方指定的路径并返回该路径。

        对应规范 R1.2 的例外情形：服务商返回的产物（如自带纹理图集的 GLB）
        不适合在内存中反复搬运时才提供。路径完全由调用方决定，模型不会
        自行拼接或创建业务目录结构。
        """
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

        return str(target)

    def describe(self) -> dict[str, Any]:
        """返回模型当前配置的可读摘要，便于日志与排查。

        不含 API Key，只列出模型标识与连接状态。
        """
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "output_format": self.output_format,
            "client_ready": self._client is not None or self._http_client is not None,
            "session_id": self._previous_response_id,
        }
