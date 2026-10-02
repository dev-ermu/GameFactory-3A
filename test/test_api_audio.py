"""
Offline contract tests for the Seed Audio dialogue and sound-effect backends.

No network, API key, GPU or model weights are used. Run from the repo root:
    python test/test_api_audio.py
"""
from __future__ import annotations

import base64
import inspect
import io
import os
import sys
import tempfile
import unittest
import uuid
import wave
from pathlib import Path
from unittest import mock

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from models.common import cloud_api  # noqa: E402
from models.gen_audio import seed_audio_model  # noqa: E402
from models.gen_audio.seed_audio_model import (  # noqa: E402
    CREATE_PATH,
    SeedAudioModel,
)
from models.gen_audio.seed_audio_utils import SeedAudioAPIClient  # noqa: E402


def make_wav(sample_rate: int = 24_000, duration: float = 0.25) -> bytes:
    samples = max(1, int(sample_rate * duration))
    t = np.arange(samples, dtype=np.float32) / sample_rate
    pcm = (0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()


class FakeClient(object):
    def __init__(self, response: dict, artifact: bytes | None = None):
        self.response = response
        self.artifact = artifact
        self.calls: list[tuple[str, str, dict]] = []
        self.downloads: list[str] = []
        self.closed = False

    def request(self, method: str, path: str, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.response

    def download(self, url: str, **kwargs):
        self.downloads.append(url)
        if self.artifact is None:
            raise AssertionError("download was not scripted")
        return self.artifact

    def close(self):
        self.closed = True


def make_model(mode: str = "dialogue", response: dict | None = None, **kwargs):
    audio = make_wav()
    response = response or {
        "status": 200,
        "body": {"audio": base64.b64encode(audio).decode("ascii"), "duration": 0.25},
    }
    model = SeedAudioModel(mode=mode, api_key="test-key", **kwargs)
    model._client = FakeClient(response, artifact=audio)
    return model


class TestConstruction(unittest.TestCase):
    def test_shared_client_contract_stays_provider_neutral(self):
        client = cloud_api.CloudAPIClient("https://api.example", "secret")
        self.assertEqual(client.auth_header, "Authorization")
        self.assertEqual(client.auth_template, "Bearer {key}")
        self.assertNotIn(
            "headers",
            inspect.signature(cloud_api.CloudAPIClient.request).parameters,
        )

    def test_no_endpoint_is_baked_into_the_wrapper(self):
        """端点必须来自 `.env`：模块里不得再残留任何默认 base 或完整 URL。"""
        self.assertFalse(hasattr(seed_audio_model, "DEFAULT_API_BASE"))
        self.assertFalse(hasattr(seed_audio_model, "API_ENDPOINT"))
        self.assertFalse(hasattr(seed_audio_model, "SIGNUP_URL"))
        self.assertIsNone(SeedAudioModel().api_base)

    def test_constructs_without_key_and_accepts_cpu(self):
        saved = os.environ.pop("SEED_AUDIO_API_KEY", None)
        try:
            model = SeedAudioModel(device="cpu")
            self.assertEqual(model.device, "cpu")
            self.assertIsNone(model._client)
        finally:
            if saved is not None:
                os.environ["SEED_AUDIO_API_KEY"] = saved

    def test_missing_key_is_actionable(self):
        saved_key = os.environ.pop("SEED_AUDIO_API_KEY", None)
        try:
            with self.assertRaises(cloud_api.CloudAPIAuthError) as ctx:
                SeedAudioModel().infer(text="发现目标")
            message = str(ctx.exception)
            self.assertIn("SEED_AUDIO_API_KEY", message)
        finally:
            if saved_key is not None:
                os.environ["SEED_AUDIO_API_KEY"] = saved_key

    def test_custom_api_key_header(self):
        client = SeedAudioModel(
            api_key="secret", api_base="https://example.test"
        ).client
        self.assertIsInstance(client, SeedAudioAPIClient)
        self.assertEqual(client.auth_header, "X-Api-Key")
        self.assertEqual(client.auth_template, "{key}")

    def test_missing_api_base_fails_fast_and_actionably(self):
        """R9.7 — API 根地址是必填项，绝不静默回退到默认值。"""
        saved = os.environ.pop("SEED_AUDIO_API_BASE", None)
        try:
            with self.assertRaises(cloud_api.CloudAPIConfigError) as ctx:
                SeedAudioModel(api_key="secret").client
            message = str(ctx.exception)
            self.assertIn("SEED_AUDIO_API_BASE", message)
            self.assertIn(".env", message)
        finally:
            if saved is not None:
                os.environ["SEED_AUDIO_API_BASE"] = saved

    def test_seed_audio_client_owns_request_headers(self):
        captured_headers = []

        class Response:
            ok = True
            status_code = 200
            headers = {}

            @staticmethod
            def json():
                return {"code": 0}

        class Session:
            def __init__(self):
                self.headers = {}

            def request(self, method, url, **kwargs):
                captured_headers.append(dict(self.headers))
                return Response()

            def close(self):
                pass

        class Requests:
            class ConnectionError(Exception):
                pass

            class Timeout(Exception):
                pass

            @staticmethod
            def Session():
                return Session()

        with mock.patch.object(cloud_api, "_requests", return_value=Requests):
            client = SeedAudioAPIClient(
                "https://api.example", "secret", max_retries=0
            )
            client.request("POST", "/create", json_body={"model": "seed-audio-1.0"})
            client.request("POST", "/create", json_body={"model": "seed-audio-1.0"})

        first_id = captured_headers[0]["X-Api-Request-Id"]
        second_id = captured_headers[1]["X-Api-Request-Id"]
        uuid.UUID(first_id)
        uuid.UUID(second_id)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(captured_headers[0]["X-Api-Key"], "secret")

    def test_unload_is_idempotent(self):
        model = make_model()
        client = model._client
        model.unload()
        model.unload()
        self.assertTrue(client.closed)
        self.assertIsNone(model._client)


class TestInference(unittest.TestCase):
    def test_dialogue_request_and_nested_response(self):
        model = make_model(mode="dialogue", speaker_id="speaker-resource-1")
        result = model.infer(
            text="发现目标",
            language="Chinese",
            instruct="Speak urgently.",
            speaker_id="Vivian",  # Qwen id must not replace the configured resource.
        )
        self.assertEqual(result["waveform"].shape[0], 1)
        self.assertEqual(result["sample_rate"], 24_000)
        method, path, kwargs = model._client.calls[0]
        self.assertEqual((method, path), ("POST", CREATE_PATH))
        payload = kwargs["json_body"]
        self.assertEqual(payload["model"], "seed-audio-1.0")
        self.assertIn("发现目标", payload["text_prompt"])
        self.assertIn("Speak urgently", payload["text_prompt"])
        self.assertEqual(payload["references"], [{"speaker": "speaker-resource-1"}])
        self.assertEqual(payload["audio_config"]["format"], "wav")

    def test_sound_effect_request(self):
        model = make_model(mode="sound_effect")
        model.infer(prompt="a close thunder crack", duration_sec=3.5, seed=9,
                    num_steps=4, cfg=4.5)
        payload = model._client.calls[0][2]["json_body"]
        self.assertIn("a close thunder crack", payload["text_prompt"])
        self.assertIn("3.5 seconds", payload["text_prompt"])
        self.assertNotIn("seed", payload)
        self.assertNotIn("num_steps", payload)
        self.assertNotIn("cfg", payload)

    def test_reference_audio_is_encoded_instead_of_speaker(self):
        model = make_model(mode="dialogue", speaker_id="configured-speaker")
        reference = np.zeros((1, 800), dtype=np.float32)
        model.infer(text="Hold position", reference_audio=(reference, 16_000),
                    reference_text="Reference line")
        reference_payload = model._client.calls[0][2]["json_body"]["references"][0]
        self.assertIn("audio_data", reference_payload)
        self.assertNotIn("speaker", reference_payload)
        self.assertNotIn("text", reference_payload)
        self.assertIn("@Audio1", model._client.calls[0][2]["json_body"]["text_prompt"])
        self.assertTrue(base64.b64decode(reference_payload["audio_data"]).startswith(b"RIFF"))

    def test_top_level_url_response_is_downloaded(self):
        response = {"code": 0, "url": "https://cdn.example/clip.wav"}
        model = make_model(mode="sound_effect", response=response)
        result = model.infer(prompt="one rifle shot")
        self.assertEqual(model._client.downloads, ["https://cdn.example/clip.wav"])
        self.assertGreater(result["waveform"].shape[-1], 0)

    def test_cache_hit_sends_zero_requests(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            first = make_model(mode="dialogue", cache_dir=cache_dir)
            first_result = first.infer(text="Cached line")
            self.assertEqual(len(first._client.calls), 1)

            second = make_model(mode="dialogue", cache_dir=cache_dir)
            second_result = second.infer(text="Cached line")
            self.assertEqual(second._client.calls, [])
            self.assertTrue(second.last_call_info["cached"])
            np.testing.assert_allclose(
                first_result["waveform"], second_result["waveform"], atol=1e-6
            )


class TestOperatorIntegration(unittest.TestCase):
    def test_one_seed_model_per_audio_slot(self):
        from operators.gen_audio.operator import GenAudioOperator

        dialogue = make_model(mode="dialogue")
        sound_effect = make_model(mode="sound_effect")
        with tempfile.TemporaryDirectory() as output_dir:
            operator = GenAudioOperator(
                dialogue_model=dialogue,
                sound_effect_model=sound_effect,
                output_dir=output_dir,
            )
            dialogue_result = operator.run({
                "task_id": "spotted", "audio_type": "dialogue", "text": "发现目标",
            })
            sfx_result = operator.run({
                "task_id": "rifle", "audio_type": "sound_effect",
                "prompt": "one futuristic rifle shot",
            })
            self.assertTrue(Path(dialogue_result["audio_path"]).is_file())
            self.assertTrue(Path(sfx_result["audio_path"]).is_file())
            self.assertEqual(len(dialogue._client.calls), 1)
            self.assertEqual(len(sound_effect._client.calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
