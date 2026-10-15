"""重试逻辑的离线单元测试：判定依据是 `Response` 状态码而非异常。

不联网、不需要 API Key、不需要 `.env`。从仓库根目录运行：

    python tests/test_retry_response.py

覆盖规范要点：
    R8.1  可重试故障按指数退避重试
    R8.2  限流、5xx、传输层故障可重试；参数、鉴权、额度错误是终态
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from models import base  # noqa: E402
from models.base import BaseModel  # noqa: E402
from models.common import errors  # noqa: E402


class FakeResponse:
    """最小可用的 HTTP 响应替身，字段与 `requests` / `httpx2` 对齐。"""

    def __init__(self, status_code: int, payload: object = None) -> None:
        """保存状态码；`payload` 为字典时序列化成响应体文本。"""
        self.status_code = status_code
        self.text = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload or {}, ensure_ascii=False)
        )


class StatusCarryingError(Exception):
    """模拟自带响应的 SDK 异常（如 OpenAI 的 `APIStatusError`）。"""

    def __init__(self, status_code: int) -> None:
        """把状态码挂在异常上。"""
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class StubModel(BaseModel):
    """只为测试重试逻辑而存在的最小实现。"""

    provider = "stub"
    display_name = "Stub"
    api_key_field = "stub_api_key"
    api_base_field = "stub_api_base"

    def request(self) -> str:
        """占位实现，测试不经过真实的 `request()`。"""
        return "ok"


def _fake_get_str(field_name: str) -> str:
    """让配置读取返回假凭据，避免测试依赖本机 `.env`。"""
    return "test-key" if field_name.endswith("api_key") else "https://example.invalid/v1"


class RetryTestCase(unittest.TestCase):
    """构造一个不联网的实例，并把退避等待换成空操作。"""

    def setUp(self) -> None:
        """打桩配置与 `time.sleep`，让重试循环瞬时跑完。"""
        patcher = mock.patch.object(base, "config_get_str", side_effect=_fake_get_str)
        patcher.start()
        self.addCleanup(patcher.stop)

        sleeper = mock.patch.object(base.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

        self.model = StubModel("stub-model", poll_interval=0.01, max_retries=3)


class TestRetryableStatus(unittest.TestCase):
    """R8.2：状态码分类表。"""

    def test_retryable_statuses(self) -> None:
        """限流、超时类与 5xx 都值得重试。"""
        for status in (408, 409, 425, 429, 500, 502, 503, 504, 599):
            self.assertTrue(BaseModel.is_retryable_status(status), status)

    def test_terminal_statuses(self) -> None:
        """参数、鉴权、额度错误与成功响应都不是可重试状态。"""
        for status in (200, 201, 204, 301, 400, 401, 402, 403, 404, 422):
            self.assertFalse(BaseModel.is_retryable_status(status), status)


class TestResponseDrivenRetry(RetryTestCase):
    """R8.1：重试判断直接读 `Response`，不经过异常。"""

    def test_success_returns_the_response_unchanged(self) -> None:
        """2xx 只调用一次，原样返回。"""
        response = FakeResponse(200, {"data": "ok"})
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1
            return response

        self.assertIs(self.model.call_with_retry(operation), response)
        self.assertEqual(calls["n"], 1)
        self.sleep.assert_not_called()

    def test_rate_limit_response_is_retried_then_succeeds(self) -> None:
        """429 会重试，第二次成功后返回该响应。"""
        responses = iter([FakeResponse(429, {"message": "slow down"}), FakeResponse(200)])
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1
            return next(responses)

        result = self.model.call_with_retry(operation)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(calls["n"], 2)
        self.sleep.assert_called_once()

    def test_server_error_response_is_retried_then_succeeds(self) -> None:
        """5xx 与 429 走同一条重试路径。"""
        responses = iter([FakeResponse(503), FakeResponse(502), FakeResponse(200)])
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1
            return next(responses)

        result = self.model.call_with_retry(operation)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(calls["n"], 3)

    def test_terminal_response_is_not_retried(self) -> None:
        """400/401/402 立即返回，交给调用方的 `_parse_body` 翻成异常。"""
        for status in (400, 401, 402, 403):
            with self.subTest(status=status):
                response = FakeResponse(status)
                calls = {"n": 0}

                def operation() -> FakeResponse:
                    calls["n"] += 1
                    return response

                self.assertIs(self.model.call_with_retry(operation), response)
                self.assertEqual(calls["n"], 1)

    def test_retryable_response_gives_up_after_max_retries(self) -> None:
        """次数用尽后返回最后一次响应，由调用方报错。"""
        response = FakeResponse(503, {"message": "upstream down"})
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1
            return response

        self.assertIs(self.model.call_with_retry(operation), response)
        self.assertEqual(calls["n"], self.model.max_retries + 1)


class TestExceptionFallback(RetryTestCase):
    """R8.2：还没拿到响应就抛出的异常，按异常类型兜底。"""

    def test_transport_error_is_retried(self) -> None:
        """标准库超时属于传输层故障，值得重试。"""
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1

            if calls["n"] < 2:
                raise TimeoutError("read timed out")

            return FakeResponse(200)

        self.assertEqual(self.model.call_with_retry(operation).status_code, 200)
        self.assertEqual(calls["n"], 2)

    def test_terminal_failure_is_raised_immediately(self) -> None:
        """终态故障只调用一次操作函数。"""
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1
            raise errors.CloudModelAuthError("401")

        with self.assertRaises(errors.CloudModelAuthError):
            self.model.call_with_retry(operation)

        self.assertEqual(calls["n"], 1)

    def test_exception_status_code_drives_the_decision(self) -> None:
        """异常自带状态码时，沿用同一套状态码判断。"""
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1

            if calls["n"] < 2:
                raise StatusCarryingError(429)

            return FakeResponse(200)

        self.assertEqual(self.model.call_with_retry(operation).status_code, 200)
        self.assertEqual(calls["n"], 2)

    def test_exception_status_code_can_be_terminal(self) -> None:
        """异常带 400 时不再重试。"""
        calls = {"n": 0}

        def operation() -> FakeResponse:
            calls["n"] += 1
            raise StatusCarryingError(400)

        with self.assertRaises(StatusCarryingError):
            self.model.call_with_retry(operation)

        self.assertEqual(calls["n"], 1)


class TestErrorMessage(unittest.TestCase):
    """R8.2：从响应体里读出服务商给出的错误说明。"""

    def test_reads_message_field(self) -> None:
        """多数国产服务商使用 `message` 字段。"""
        self.assertEqual(
            BaseModel._error_message(FakeResponse(429, {"message": "slow down"})),
            "slow down",
        )

    def test_reads_nested_error_message(self) -> None:
        """OpenAI 协议把原因放在 `error.message`。"""
        response = FakeResponse(400, {"error": {"message": "invalid prompt"}})
        self.assertEqual(BaseModel._error_message(response), "invalid prompt")

    def test_falls_back_to_raw_text(self) -> None:
        """非 JSON 报文退回截断后的原文。"""
        self.assertEqual(
            BaseModel._error_message(FakeResponse(503, "<html>gateway</html>")),
            "<html>gateway</html>",
        )

    def test_returns_empty_without_a_body(self) -> None:
        """没有 `text` 属性时返回空串，不影响重试。"""

        class Bare:
            status_code = 503

        self.assertEqual(BaseModel._error_message(Bare()), "")


class TestStatusCodeExtraction(unittest.TestCase):
    """状态码提取对响应与异常都成立。"""

    def test_reads_from_response(self) -> None:
        """响应对象直接带 `status_code`。"""
        self.assertEqual(BaseModel._status_code(FakeResponse(503)), 503)

    def test_reads_from_exception(self) -> None:
        """异常实例上带 `status_code`。"""
        self.assertEqual(BaseModel._status_code(StatusCarryingError(429)), 429)

    def test_reads_from_exception_response(self) -> None:
        """异常只带 `.response` 时从响应上取（如 `requests.HTTPError`）。"""

        class Wrapper(Exception):
            def __init__(self) -> None:
                super().__init__("boom")
                self.response = FakeResponse(500)

        self.assertEqual(BaseModel._status_code(Wrapper()), 500)

    def test_returns_none_for_plain_values(self) -> None:
        """字典、字符串这类返回值没有状态码。"""
        for value in ({"status": "processing"}, "ok", None, 42):
            self.assertIsNone(BaseModel._status_code(value), repr(value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
