import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from comfyui.gateway.app import (
    _failure_message,
    _output_image,
    _queued_prompt_ids,
    app,
    decode_generation_id,
    encode_generation_id,
)


API_KEY = "test-key-" + "x" * 40


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(stream, format="PNG")
    return stream.getvalue()


class GatewayHelpersTest(unittest.TestCase):
    def test_generation_id_round_trip_and_tamper_rejection(self):
        token = encode_generation_id(
            prompt_id="prompt-1", workflow_id="model-c-v1", output_node_id="3", secret=API_KEY
        )
        self.assertEqual(
            decode_generation_id(token, secret=API_KEY),
            {"p": "prompt-1", "w": "model-c-v1", "o": "3"},
        )
        with self.assertRaises(Exception):
            decode_generation_id(token + "x", secret=API_KEY)

    def test_extracts_output_and_failure(self):
        entry = {
            "outputs": {"3": {"images": [{"filename": "result.png", "subfolder": "ad", "type": "output"}]}},
            "status": {"status_str": "success"},
        }
        self.assertEqual(
            _output_image(entry, "3"),
            {"filename": "result.png", "subfolder": "ad", "type": "output"},
        )
        failed = {
            "status": {
                "status_str": "error",
                "messages": [["execution_error", {"exception_message": "model failed"}]],
            }
        }
        self.assertEqual(_failure_message(failed), "model failed")

    def test_extracts_queue_prompt_ids(self):
        self.assertEqual(_queued_prompt_ids([[1, "a"], [2, "b"]]), {"a", "b"})


class GatewayApiTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AD_CREATOR_GATEWAY_API_KEY": API_KEY}, clear=False)
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def test_requires_bearer_key(self):
        response = self.client.post(
            "/v1/generations", files={"image": ("input.png", _png(), "image/png")}
        )
        self.assertEqual(response.status_code, 401)

    def test_health_reports_misconfigured_gateway(self):
        with patch.dict(os.environ, {"AD_CREATOR_GATEWAY_API_KEY": ""}, clear=False):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"ok": False, "gateway": "misconfigured"})

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_submits_generation_and_returns_signed_job(self, submit_generation):
        submit_generation.return_value = ("prompt-123", "model-c-v1", "3")
        response = self.client.post(
            "/v1/generations",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"image": ("input.png", _png(), "image/png")},
            data={"composition": "medium", "background_style": "white", "strength": "low"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        decoded = decode_generation_id(payload["generation_id"], secret=API_KEY)
        self.assertEqual(decoded["p"], "prompt-123")


if __name__ == "__main__":
    unittest.main()
