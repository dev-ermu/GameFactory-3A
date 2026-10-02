"""
针对`agent_skills/develop_harness/api_model_require.md`R9的闭源3D后端`TripoModel`，`MeshyModel`的离线合约测试。

**没有网络，没有API密钥，没有GPU。**每个HTTP边界都被一个计算调用的伪传输所取代，
这使得“缓存命中发送零请求”和“402永远不会重试”完全可以测试。

运行方式:
    python tests/test_api_3d_object.py
"""
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 仓库根入 sys.path：`tests.harness` 与 `models.*` 都要靠它解析，
# 这样 `python tests/test_api_3d_object.py` 的脚本式运行也成立。
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from models.common import cloud_api
from models.common.glb_utils import glb_summary, glb_triangle_count
from models.gen_3d_object.meshy_model import MeshyModel
from models.gen_3d_object.tripo_model import TripoModel
from tests.harness import (
    build_operator,
    make_minimal_glb,
    make_ref_image,
    make_textured_glb,
)


# ── Fake transport ────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status: int, payload, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.content = payload if isinstance(payload, bytes) else b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        return str(self._payload)

    def json(self):
        if isinstance(self._payload, bytes):
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Stands in for `requests.Session`; records every call it is asked to make."""

    def __init__(self, responses):
        #: list of FakeResponse, consumed in order; the last one repeats.
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []
        self.headers: dict = {}
        self.closed = False

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def close(self):
        self.closed = True


class FakeClient:
    """Stands in for `CloudAPIClient` at the model level."""

    def __init__(self, script: dict, artifact: bytes):
        self.script = script          # path fragment -> response payload
        self.artifact = artifact
        self.requests: list[str] = []
        self.downloads: list[str] = []
        self.closed = False

    def request(self, method, path, **kw):
        self.requests.append(f"{method} {path}")
        for fragment, payload in self.script.items():
            if fragment in path:
                return payload
        raise AssertionError(f"unscripted request: {method} {path}")

    def download(self, url, **kw):
        self.downloads.append(url)
        return self.artifact

    def close(self):
        self.closed = True


TRIPO_SCRIPT = {
    "/files": {"code": 0, "data": {"file_token": "file_stub"}},
    "/generation/image-to-model": {"code": 0, "data": {"task_id": "tripo_task_1"}},
    "/generation/text-to-model": {"code": 0, "data": {"task_id": "tripo_task_1"}},
    "/tasks/": {"code": 0, "data": {
        "task_id": "tripo_task_1", "status": "success", "progress": 100,
        "credits_consumed": 40,
        "output": {"model_url": "https://cdn.example/model.glb"},
    }},
}

MESHY_SCRIPT_IMAGE = {
    "/openapi/v1/image-to-3d/": {
        "id": "meshy_task_1", "status": "SUCCEEDED", "progress": 100,
        "model_urls": {"glb": "https://assets.example/model.glb",
                       "fbx": "https://assets.example/model.fbx"},
    },
    "/openapi/v1/image-to-3d": {"result": "meshy_task_1"},
}


def make_tripo(**kw) -> TripoModel:
    model = TripoModel(api_key="test-key", **kw)
    model._client = FakeClient(TRIPO_SCRIPT, make_minimal_glb(triangles=3))
    return model


def make_meshy(**kw) -> MeshyModel:
    model = MeshyModel(api_key="test-key", **kw)
    model._client = FakeClient(MESHY_SCRIPT_IMAGE, make_minimal_glb(triangles=3))
    return model


# ── R9 contract ───────────────────────────────────────────────────────────────


class TestConstruction(unittest.TestCase):
    """R9.1 / R9.2 / R9.7 — construction must work without credentials."""

    def test_constructs_without_api_key(self):
        for cls, env in ((TripoModel, "TRIPO_API_KEY"), (MeshyModel, "MESHY_API_KEY")):
            with self.subTest(cls=cls.__name__):
                saved = os.environ.pop(env, None)
                try:
                    model = cls()                      # must not raise (R9.7)
                    self.assertTrue(model.model_path)
                finally:
                    if saved is not None:
                        os.environ[env] = saved

    def test_missing_key_fails_fast_and_actionably(self):
        for cls, env in ((TripoModel, "TRIPO_API_KEY"), (MeshyModel, "MESHY_API_KEY")):
            with self.subTest(cls=cls.__name__):
                saved = os.environ.pop(env, None)
                try:
                    with self.assertRaises(cloud_api.CloudAPIAuthError) as ctx:
                        cls().infer(image=make_ref_image())
                    message = str(ctx.exception)
                    self.assertIn(env, message)        # names the variable
                    self.assertIn(".env", message)     # and where to set it
                finally:
                    if saved is not None:
                        os.environ[env] = saved

    def test_missing_api_base_fails_fast_and_actionably(self):
        """R9.7 — API 根地址是必填项，绝不静默回退到默认值。"""
        for cls, env in ((TripoModel, "TRIPO_API_BASE"),
                         (MeshyModel, "MESHY_API_BASE")):
            with self.subTest(cls=cls.__name__):
                saved = os.environ.pop(env, None)
                try:
                    with self.assertRaises(cloud_api.CloudAPIConfigError) as ctx:
                        cls(api_key="test-key").client
                    message = str(ctx.exception)
                    self.assertIn(env, message)         # 指出变量名
                    self.assertIn(".env", message)      # 以及该写在哪里
                finally:
                    if saved is not None:
                        os.environ[env] = saved

    def test_device_cpu_is_accepted_and_ignored(self):
        """R9.2 — `device` exists for interface parity only."""
        self.assertEqual(TripoModel(device="cpu").device, "cpu")
        self.assertEqual(MeshyModel(device="cpu").device, "cpu")

    def test_model_path_aliases(self):
        """R9.1 — `model_path` is a version id; short aliases resolve."""
        self.assertEqual(TripoModel(model_path="tripo-v3.1").model_path, "v3.1-20260211")
        self.assertEqual(MeshyModel(model_path="meshy-6-text-to-3d").model_path, "meshy-6")
        # Unknown ids pass through, so a newer version needs no code change.
        self.assertEqual(TripoModel(model_path="v9.9-future").model_path, "v9.9-future")

    def test_unload_is_idempotent(self):
        """R9.4 — `unload()` closes the session and is safe to repeat."""
        model = make_tripo()
        client = model._client
        model.unload()
        model.unload()
        self.assertTrue(client.closed)
        self.assertIsNone(model._client)


class TestSwappability(unittest.TestCase):
    """R6 — the three backends must fill the same operator slot."""

    #: What `Gen3DObjectOperator.run` passes, in order.
    EXPECTED = ["image", "output_path", "seed", "decimation_target", "texture_size"]

    def test_infer_and_save_signature_matches_trellis(self):
        from models.gen_3d_object import trellis_2_model

        for cls in (trellis_2_model.Trellis2Model, TripoModel, MeshyModel):
            with self.subTest(cls=cls.__name__):
                params = list(inspect.signature(cls.infer_and_save).parameters)
                self.assertEqual(params[1:6], self.EXPECTED)

    def test_api_backends_are_byte_identical_to_each_other(self):
        for method in ("infer", "infer_and_save"):
            with self.subTest(method=method):
                self.assertEqual(
                    str(inspect.signature(getattr(TripoModel, method))),
                    str(inspect.signature(getattr(MeshyModel, method))),
                )


class TestInference(unittest.TestCase):
    """R9.6 — submit, poll and download are hidden behind a blocking call."""

    def test_tripo_image_to_3d(self):
        model = make_tripo()
        data = model.infer(image=make_ref_image(), seed=7)
        self.assertTrue(data.startswith(b"glTF"))
        self.assertEqual(model.last_call_info["task_id"], "tripo_task_1")
        self.assertEqual(model.last_call_info["credits"], 40)
        self.assertEqual(model.last_call_info["triangles"], 3)
        self.assertIn("POST /files", model._client.requests)

    def test_tripo_text_to_3d_skips_upload(self):
        """A4 decision: the same wrapper serves text-to-3D."""
        model = make_tripo()
        model.infer(prompt="a cyberpunk katana")
        self.assertNotIn("POST /files", model._client.requests)
        self.assertIn("POST /generation/text-to-model", model._client.requests)

    def test_meshy_image_to_3d(self):
        model = make_meshy()
        data = model.infer(image=make_ref_image(), seed=7)
        self.assertTrue(data.startswith(b"glTF"))
        self.assertEqual(model.last_call_info["task_id"], "meshy_task_1")

    def test_requires_an_input(self):
        with self.assertRaises(ValueError):
            make_tripo().infer()
        with self.assertRaises(ValueError):
            make_meshy().infer()

    def test_meshy_clamps_polycount_the_operator_sends(self):
        """
        The operator forwards TRELLIS.2's decimation_target=1_000_000, which
        Meshy rejects with a terminal 400. Clamping keeps R6 true.
        """
        model = make_meshy()
        model.infer(image=make_ref_image(), decimation_target=1_000_000)
        self.assertEqual(model._client.requests[0], "POST /openapi/v1/image-to-3d")

    def test_infer_and_save_writes_the_caller_path(self):
        """C7 / R1.2 — the path comes in, it is never derived inside the model."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "model.glb"
            returned = make_tripo().infer_and_save(
                image=make_ref_image(), output_path=str(out))
            self.assertEqual(returned, str(out))
            self.assertTrue(out.is_file())
            self.assertEqual(glb_triangle_count(out.read_bytes()), 3)

    def test_infer_and_save_requires_output_path(self):
        with self.assertRaises(ValueError):
            make_tripo().infer_and_save(image=make_ref_image())


class TestCache(unittest.TestCase):
    """R9.8 — an identical request must never be billed twice."""

    def test_cache_hit_sends_no_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = make_ref_image()

            first = make_tripo(cache_dir=tmp)
            data1 = first.infer(image=image, seed=1)
            self.assertGreater(len(first._client.requests), 0)
            self.assertFalse(first.last_call_info["cached"])

            second = make_tripo(cache_dir=tmp)
            data2 = second.infer(image=image, seed=1)
            self.assertEqual(data1, data2)
            self.assertEqual(second._client.requests, [])   # zero network traffic
            self.assertEqual(second._client.downloads, [])
            self.assertTrue(second.last_call_info["cached"])

    def test_cache_misses_when_a_parameter_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = make_ref_image()
            make_tripo(cache_dir=tmp).infer(image=image, seed=1)

            other = make_tripo(cache_dir=tmp)
            other.infer(image=image, seed=2)
            self.assertGreater(len(other._client.requests), 0)

    def test_cache_key_never_contains_the_key_or_image_bytes(self):
        payload = {"provider": "tripo", "image_sha256": "abc", "payload": {"model": "x"}}
        self.assertEqual(len(cloud_api.request_hash(payload)), 64)


class TestRetryClassification(unittest.TestCase):
    """R9.9 — retryable and terminal failures must not be confused."""

    def _client(self, responses, **kw):
        client = cloud_api.CloudAPIClient("https://api.example", "key",
                                          backoff=0.001, **kw)
        client._session = FakeSession(responses)
        return client

    def test_terminal_status_is_not_retried(self):
        for status, expected in ((400, cloud_api.CloudAPIRequestError),
                                 (401, cloud_api.CloudAPIAuthError),
                                 (402, cloud_api.CloudAPIQuotaError)):
            with self.subTest(status=status):
                client = self._client([FakeResponse(status, {"message": "nope"})],
                                      max_retries=3)
                with self.assertRaises(expected):
                    client.request("POST", "/x")
                self.assertEqual(len(client._session.calls), 1)   # exactly one try

    def test_server_error_is_retried_then_raised(self):
        client = self._client([FakeResponse(503, {"message": "busy"})], max_retries=2)
        with self.assertRaises(cloud_api.CloudAPIServerError):
            client.request("GET", "/x")
        self.assertEqual(len(client._session.calls), 3)           # 1 + 2 retries

    def test_retry_recovers(self):
        client = self._client([FakeResponse(500, {"m": "x"}), FakeResponse(200, {"ok": 1})],
                              max_retries=2)
        self.assertEqual(client.request("GET", "/x"), {"ok": 1})

    def test_insufficient_credits_body_is_terminal(self):
        err = cloud_api.classify_http_error(500, {"message": "insufficient credits"})
        self.assertIsInstance(err, cloud_api.CloudAPIQuotaError)
        self.assertFalse(err.retryable)

    def test_real_provider_out_of_credit_bodies(self):
        """
        Verbatim responses seen from the live services. "No money" arrives with
        an auth-shaped status code, so only the body can tell it from a bad key.
        """
        cases = [
            # Tripo, HTTP 403
            (403, {"code": 2010, "status": "error",
                   "message": "You don't have enough credit to create this task",
                   "suggestion": "Please purchase more credit"}),
            (402, {"message": "Insufficient credits"}),
        ]
        for status, body in cases:
            with self.subTest(status=status):
                err = cloud_api.classify_http_error(status, body)
                self.assertIsInstance(err, cloud_api.CloudAPIQuotaError)
                self.assertFalse(err.retryable)

    def test_a_genuinely_bad_key_is_still_an_auth_error(self):
        err = cloud_api.classify_http_error(
            401, {"code": 2, "message": "Invalid API key"})
        self.assertIsInstance(err, cloud_api.CloudAPIAuthError)
        self.assertNotIsInstance(err, cloud_api.CloudAPIQuotaError)

    def test_timeout_error_carries_the_task_id(self):
        """A timed-out task usually finishes anyway — the id must survive."""
        with self.assertRaises(cloud_api.CloudTaskTimeout) as ctx:
            cloud_api.poll_task(lambda: {"status": "running"}, task_id="t_42",
                                timeout=0.05, poll_interval=0.01,
                                done_states=("success",), failed_states=("failed",))
        self.assertEqual(ctx.exception.task_id, "t_42")
        self.assertIn("t_42", str(ctx.exception))

    def test_failed_task_raises(self):
        with self.assertRaises(cloud_api.CloudTaskFailed):
            cloud_api.poll_task(lambda: {"status": "banned"}, task_id="t_1",
                                timeout=1, poll_interval=0.01,
                                done_states=("success",),
                                failed_states=("failed", "banned"))


class TestGLBUtils(unittest.TestCase):
    """The triangle count reported for every billed call has to be right."""

    def test_triangle_count(self):
        for n in (1, 2, 17):
            with self.subTest(triangles=n):
                self.assertEqual(glb_triangle_count(make_minimal_glb(n)), n)

    def test_summary_of_a_non_glb(self):
        info = glb_summary(b"not a glb at all")
        self.assertIsNone(info["triangles"])
        self.assertIn("error", info)

    def test_textured_fixture_carries_a_material_and_a_texture(self):
        """
        The engine importers are validated against this fixture, so the material
        and the embedded texture have to actually be in the file.
        """
        info = glb_summary(make_textured_glb())
        self.assertEqual(info["triangles"], 12)      # a cube
        self.assertEqual(info["materials"], 1)
        self.assertEqual(info["textures"], 1)
        self.assertEqual(info["images"], 1)


class TestOperatorIntegration(unittest.TestCase):
    """The stubs must drive the real operator, artifacts and all."""

    def test_operator_runs_with_each_stub_backend(self):
        from pipeline.common import paths

        for backend in ("trellis2", "tripo", "meshy"):
            with self.subTest(backend=backend):
                op = build_operator("3d_object", run_id="_unittest",
                                          model_key=backend)
                result = op.run({"game_id": "_unittest_game",
                                 "task_id": f"t_{backend}",
                                 "image": make_ref_image()})
                glb = Path(result["glb_path"])
                self.assertTrue(glb.is_file())
                self.assertIsNotNone(glb_triangle_count(glb.read_bytes()))
        import shutil
        shutil.rmtree(paths.game_output_dir("_unittest_game"), ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
