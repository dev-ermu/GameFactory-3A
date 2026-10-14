"""Tripo3D 与 Meshy3D 后端的离线契约测试。

不联网、不需要 API Key、不需要 GPU 与模型权重。从仓库根目录运行：

    python tests/test_api_3d_object.py

覆盖规范要点：
    R2.1  `model_id` 无默认值
    R6.1  凭证与 Base URL 在首次调用时才读取
    R6.3  Base URL 缺失时快速失败
    R8.2  终态故障不重试
    R11   两个后端接口签名一致
"""

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from models.base import BaseModel  # noqa: E402
from models.common import errors  # noqa: E402
from models.gen_3d_object import MeshyModel, TripoModel  # noqa: E402
from models.gen_3d_object.tripo_model import RECOMMENDED_MODEL_ID  # noqa: E402

# 测试期间清空这些配置项，避免读到开发者本机的 .env。
CREDENTIAL_FIELDS = {"tripo_api_key", "tripo_api_base", "meshy_api_key", "meshy_api_base"}


def blank_credentials():
    """返回把全部云端凭证置空的补丁器。"""
    from config import settings

    return mock.patch.multiple(settings, **{name: "" for name in CREDENTIAL_FIELDS})


class TestConstruction(unittest.TestCase):
    """构造阶段的契约。"""

    def test_constructs_without_api_key(self):
        """R6.1：构造对象不需要凭证，也不触碰网络。"""
        model = TripoModel(RECOMMENDED_MODEL_ID)

        self.assertEqual(model.model_id, RECOMMENDED_MODEL_ID)
        self.assertFalse(model.describe()["client_ready"])
        self.assertIsInstance(MeshyModel("meshy-5"), BaseModel)

    def test_model_id_is_required(self):
        """R2.1：`model_id` 没有默认值，调用方必须显式传入。"""
        with self.assertRaises(TypeError):
            TripoModel()

    def test_unsupported_model_id_is_rejected(self):
        """R9.2：无法支持的取值必须明确报错，不能静默降级。"""
        with self.assertRaises(ValueError):
            TripoModel("not-a-real-version")

    def test_unsupported_format_is_rejected(self):
        """R9.2：输出格式非法时给出可操作的错误。"""
        with self.assertRaises(ValueError):
            TripoModel(RECOMMENDED_MODEL_ID, output_format="xyz")

    def test_missing_key_fails_fast_and_actionably(self):
        """R6.2：缺少 API Key 时指出配置项名，且不发请求。"""
        model = TripoModel(RECOMMENDED_MODEL_ID, api_base="https://example.invalid")

        with blank_credentials():
            with self.assertRaises(errors.CloudModelConfigError) as ctx:
                model.request(b"png-bytes")

        message = str(ctx.exception)

        self.assertIn("tripo_api_key", message)
        self.assertIn(".env", message)

    def test_missing_api_base_fails_fast_and_actionably(self):
        """R6.3：Base URL 没有默认值，缺失时立即失败。"""
        model = TripoModel(RECOMMENDED_MODEL_ID, api_key="dummy")

        with blank_credentials():
            with self.assertRaises(errors.CloudModelConfigError) as ctx:
                model.request(b"png-bytes")

        message = str(ctx.exception)

        self.assertIn("tripo_api_base", message)
        self.assertIn("没有默认值", message)

    def test_unload_is_idempotent(self):
        """R4.2：多次调用 `release` 不应报错。"""
        model = TripoModel(RECOMMENDED_MODEL_ID)

        model.release()
        model.release()

        self.assertFalse(model.describe()["client_ready"])


class TestSwappability(unittest.TestCase):
    """R11：两个后端接口一致，算子才能不改动代码切换后端。"""

    BACKENDS = (TripoModel, MeshyModel)

    def test_signatures_match_the_operator_contract(self):
        """`request` 与 `request_and_save` 的签名在两个后端上完全一致。"""
        for method in ("request", "request_and_save"):
            signatures = {
                str(inspect.signature(getattr(cls, method))) for cls in self.BACKENDS
            }

            self.assertEqual(len(signatures), 1, f"{method} 签名不一致：{signatures}")

    def test_signature_accepts_the_operator_keywords(self):
        """算子传入的关键字必须能被签名接受。"""
        expected = {"image", "output_path", "seed", "decimation_target", "texture_size"}

        for cls in self.BACKENDS:
            params = inspect.signature(cls.request_and_save).parameters

            self.assertTrue(expected.issubset(set(params)))
class TestInference(unittest.TestCase):
    """请求阶段的契约。"""

    def test_requires_an_input(self):
        """R3.2：图生模要有 image，文生模要有 prompt。"""
        model = TripoModel(RECOMMENDED_MODEL_ID)

        with self.assertRaises(ValueError):
            model.request()

    def test_request_and_save_requires_output_path(self):
        """R1.2：输出路径必须由调用方提供。"""
        model = TripoModel(RECOMMENDED_MODEL_ID)

        with self.assertRaises(ValueError):
            model.request_and_save(b"png", "")

    def test_request_and_save_writes_the_caller_path(self):
        """R1.2：产物写到调用方指定的路径，不自行拼接业务目录。"""
        model = TripoModel(RECOMMENDED_MODEL_ID)

        with mock.patch.object(model, "_generate", return_value=b"GLB-BYTES"):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "nested" / "model.glb"
                written = model.save_payload(b"GLB-BYTES", target)

                self.assertTrue(Path(written).is_file())
                self.assertEqual(Path(written).read_bytes(), b"GLB-BYTES")


class TestRetryClassification(unittest.TestCase):
    """R8.2 / R8.3：可重试与终态故障必须分开。"""

    def setUp(self):
        """构造一个不联网的模型实例。"""
        self.model = TripoModel(RECOMMENDED_MODEL_ID, poll_interval=0.01)

    def test_terminal_failures_are_not_retryable(self):
        """鉴权、额度、参数、配置类故障都不该重试。"""
        terminal = [
            errors.CloudModelAuthError("401"),
            errors.CloudModelQuotaError("402"),
            errors.CloudModelRequestError("400"),
            errors.CloudModelConfigError("missing key"),
            errors.CloudTaskError("task failed"),
        ]

        for exc in terminal:
            self.assertFalse(self.model.is_retryable(exc), exc.__class__.__name__)

    def test_transient_failures_are_retryable(self):
        """限流、服务端错误、网络故障都应重试。"""
        transient = [
            errors.CloudModelRateLimitError("429"),
            errors.CloudModelServerError("503"),
            errors.CloudModelNetworkError("reset"),
        ]

        for exc in transient:
            self.assertTrue(self.model.is_retryable(exc), exc.__class__.__name__)

    def test_terminal_failure_is_raised_immediately(self):
        """终态故障只调用一次操作函数。"""
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise errors.CloudModelAuthError("401")

        with self.assertRaises(errors.CloudModelAuthError):
            self.model.call_with_retry(boom)

        self.assertEqual(calls["n"], 1)

    def test_retry_recovers_on_a_transient_failure(self):
        """可重试故障在第二次尝试成功。"""
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1

            if calls["n"] < 2:
                raise errors.CloudModelServerError("503")

            return "ok"

        self.assertEqual(self.model.call_with_retry(flaky), "ok")
        self.assertEqual(calls["n"], 2)

    def test_timeout_error_carries_the_task_id(self):
        """R5.3：超时异常必须带 `task_id`，任务仍在服务端跑。"""
        self.model.timeout = 0

        with self.assertRaises(errors.CloudTaskTimeout) as ctx:
            self.model.poll_task("task-abc", lambda: {"status": "processing"})

        self.assertEqual(ctx.exception.task_id, "task-abc")

    def test_failed_task_raises(self):
        """任务进入失败终态时抛出 `CloudTaskError`。"""
        states = iter([{"status": "failed", "message": "mesh is degenerate"}])

        with self.assertRaises(errors.CloudTaskError) as ctx:
            self.model.poll_task("task-1", lambda: next(states))

        self.assertIn("degenerate", str(ctx.exception))


class TestUnsupportedBackend(unittest.TestCase):
    """Meshy 因未在大陆备案而停用，占位实现必须明确报错。"""

    def test_request_reports_the_backend_is_unavailable(self):
        model = MeshyModel("meshy-5")

        with self.assertRaises(errors.CloudModelConfigError) as ctx:
            model.request(b"png")

        self.assertIn("备案", str(ctx.exception))

    def test_request_and_save_reports_the_backend_is_unavailable(self):
        model = MeshyModel("meshy-5")

        with self.assertRaises(errors.CloudModelConfigError):
            model.request_and_save(b"png", "out.glb")


class TestOperatorIntegration(unittest.TestCase):
    """确认算子层调用的是新接口名。"""

    def test_operator_calls_request_and_save(self):
        """算子源码中不应再出现旧接口名。"""
        source = (
            _REPO_ROOT / "operators" / "gen_3d_object" / "operator.py"
        ).read_text(encoding="utf-8")

        self.assertIn("request_and_save", source)
        self.assertNotIn("infer_and_save", source)


if __name__ == "__main__":
    unittest.main()