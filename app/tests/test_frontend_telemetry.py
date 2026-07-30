import io
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from app.api.router import _load_references
from app.main import app
from app.model import model


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(stream, format="PNG")
    return stream.getvalue()


class FrontendTelemetryApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    @patch("app.api.router.generate_styled_image")
    def test_generate_returns_generation_id_without_changing_image_payload(
        self, generate_styled_image
    ):
        generate_styled_image.return_value = (
            Image.new("RGB", (8, 8), "white"),
            "signed-generation-id",
        )
        reference_id = _load_references()[0]["id"]

        response = self.client.post(
            "/generate",
            files={"product_image": ("product.png", _png(), "image/png")},
            data={
                "reference_id": reference_id,
                "workflow_id": "gpt-image-2-v1",
                "aspect_ratio": "1:1",
                "cup_source": "uploaded",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["generation_id"],
            "signed-generation-id",
        )
        self.assertTrue(response.json()["result_image"].startswith("data:image/png;base64,"))
        self.assertEqual(
            generate_styled_image.call_args.kwargs["cup_source"],
            "uploaded",
        )

    @patch("app.api.router.generate_styled_image")
    def test_generate_requires_valid_cup_source(self, generate_styled_image):
        reference_id = _load_references()[0]["id"]
        common = {
            "files": {"product_image": ("product.png", _png(), "image/png")},
            "data": {
                "reference_id": reference_id,
                "workflow_id": "gpt-image-2-v1",
                "aspect_ratio": "1:1",
            },
        }

        missing = self.client.post("/generate", **common)
        invalid = self.client.post(
            "/generate",
            files=common["files"],
            data={**common["data"], "cup_source": "default"},
        )

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(invalid.status_code, 422)
        generate_styled_image.assert_not_called()

    @patch("app.api.router.record_frontend_completion")
    def test_frontend_completion_is_forwarded_once(self, record):
        response = self.client.post(
            "/telemetry/frontend-completed",
            json={
                "generation_id": "signed-generation-id",
                "duration_ms": 12_345,
            },
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"accepted": True})
        record.assert_called_once_with(
            generation_id="signed-generation-id",
            duration_ms=12_345,
        )


class FrontendTelemetryGatewayClientTest(unittest.TestCase):
    def test_cup_source_maps_to_gateway_container_mode(self):
        self.assertEqual(
            model._container_mode_from_cup_source("uploaded"),
            "reconstruct_source",
        )
        self.assertEqual(
            model._container_mode_from_cup_source("model"),
            "adopt_reference",
        )
        for invalid in (None, "", "default", "adopt_reference"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    model._container_mode_from_cup_source(invalid)

    def test_generation_submits_gateway_container_mode_not_frontend_alias(self):
        for cup_source, expected in (
            ("uploaded", "reconstruct_source"),
            ("model", "adopt_reference"),
        ):
            with (
                self.subTest(cup_source=cup_source),
                patch.object(model, "GATEWAY_BASE_URL", "https://gateway.example"),
                patch.object(model, "GATEWAY_API_KEY", "secret-key"),
                patch.object(
                    model,
                    "_submit_generation",
                    side_effect=RuntimeError("submission captured"),
                ) as submit,
            ):
                with self.assertRaisesRegex(RuntimeError, "submission captured"):
                    model._generate_with_gpt_image_2(
                        Image.new("RGB", (8, 8), "white"),
                        {"id": "natural_white__product_center"},
                        aspect_ratio="1:1",
                        cup_source=cup_source,
                    )

                payload = submit.call_args.args[2]
                self.assertEqual(payload["container_mode"], expected)
                self.assertNotIn("cup_source", payload)

    def test_gateway_request_uses_server_secret_and_expected_payload(self):
        response = Mock(status_code=202)
        with (
            patch.object(model, "GATEWAY_BASE_URL", "https://gateway.example"),
            patch.object(model, "GATEWAY_API_KEY", "secret-key"),
            patch.object(model.requests, "post", return_value=response) as post,
        ):
            model.record_frontend_completion("signed-id", 4_321)

        post.assert_called_once_with(
            (
                "https://gateway.example/v1/generations/signed-id"
                "/client-observations/frontend-completed"
            ),
            headers={"Authorization": "Bearer secret-key"},
            json={"duration_ms": 4_321},
            timeout=10,
        )


if __name__ == "__main__":
    unittest.main()
