import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from PIL import Image


CUSTOM_NODES_DIR = Path(__file__).resolve().parents[1] / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.adapters import model_c


class FakeResponse:
    def __init__(self, payload: bytes, url: str = "http://model-c.internal:8001/outputs/generated.png"):
        self.payload = payload
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self.payload

    def geturl(self) -> str:
        return self.url


class ModelCAdapterTest(unittest.TestCase):
    def test_posts_expected_fields_and_downloads_result(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (8, 8), "white").save(source)
            generated = io.BytesIO()
            Image.new("RGB", (8, 8), (255, 253, 240)).save(generated, format="PNG")
            metadata = {
                "success": True,
                "image_url": "/outputs/generated.png",
                "composition": "medium",
                "background_style": "wood",
                "strength": "medium",
                "seed": 42,
            }

            calls = []

            def fake_urlopen(request, timeout):
                calls.append((request, timeout))
                if isinstance(request, urllib.request.Request):
                    return FakeResponse(json.dumps(metadata).encode("utf-8"))
                return FakeResponse(generated.getvalue())

            with patch.dict(
                "os.environ",
                {
                    "AD_CREATOR_MODEL_C_URL": "http://model-c.internal:8001",
                    "AD_CREATOR_MODEL_C_TIMEOUT_SECONDS": "30",
                },
                clear=False,
            ), patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result, image_bytes = model_c.run_model_c(
                    image_path=source,
                    composition="medium",
                    background_style="wood",
                    strength="medium",
                    seed=42,
                )

            self.assertEqual(result, metadata)
            self.assertEqual(image_bytes, generated.getvalue())
            self.assertEqual(len(calls), 2)
            request, timeout = calls[0]
            self.assertEqual(request.full_url, "http://model-c.internal:8001/generate")
            self.assertEqual(request.method, "POST")
            self.assertEqual(timeout, 30.0)
            body = request.data
            self.assertIn(b'name="composition"\r\n\r\nmedium', body)
            self.assertIn(b'name="background_style"\r\n\r\nwood', body)
            self.assertIn(b'name="strength"\r\n\r\nmedium', body)
            self.assertIn(b'name="seed"\r\n\r\n42', body)
            self.assertIn(b'name="image"; filename="source.png"', body)
            self.assertEqual(calls[1][0], "http://model-c.internal:8001/outputs/generated.png")

    def test_preserves_model_error_code(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (8, 8), "white").save(source)
            payload = json.dumps(
                {
                    "detail": {
                        "error_code": "CUDA_OUT_OF_MEMORY",
                        "error_message": "out of memory",
                    }
                }
            ).encode("utf-8")
            error = urllib.error.HTTPError(
                "http://127.0.0.1:8001/generate",
                500,
                "Internal Server Error",
                {},
                io.BytesIO(payload),
            )

            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(model_c.ModelCExecutionError) as caught:
                    model_c.run_model_c(
                        image_path=source,
                        composition="medium",
                        background_style="wood",
                        strength="medium",
                        seed=None,
                    )

            self.assertEqual(caught.exception.code, "CUDA_OUT_OF_MEMORY")
            self.assertEqual(caught.exception.result["error_code"], "CUDA_OUT_OF_MEMORY")

    def test_rejects_external_result_url(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (8, 8), "white").save(source)
            metadata = {"success": True, "image_url": "https://other.example/result.png"}

            with patch(
                "urllib.request.urlopen",
                return_value=FakeResponse(json.dumps(metadata).encode("utf-8")),
            ):
                with self.assertRaises(model_c.ModelCExecutionError) as caught:
                    model_c.run_model_c(
                        image_path=source,
                        composition="medium",
                        background_style="wood",
                        strength="medium",
                        seed=None,
                    )

            self.assertEqual(caught.exception.code, "INVALID_RESULT_URL")

    def test_rejects_result_redirect_to_external_url(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (8, 8), "white").save(source)
            metadata = {"success": True, "image_url": "/outputs/generated.png"}
            responses = [
                FakeResponse(json.dumps(metadata).encode("utf-8")),
                FakeResponse(b"not-read", url="http://metadata.internal/result.png"),
            ]

            with patch("urllib.request.urlopen", side_effect=responses):
                with self.assertRaises(model_c.ModelCExecutionError) as caught:
                    model_c.run_model_c(
                        image_path=source,
                        composition="medium",
                        background_style="wood",
                        strength="medium",
                        seed=None,
                    )

            self.assertEqual(caught.exception.code, "INVALID_RESULT_URL")


if __name__ == "__main__":
    unittest.main()
