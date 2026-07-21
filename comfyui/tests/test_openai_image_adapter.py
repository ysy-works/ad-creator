import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.adapters.openai_image import (
    OpenAIHTTPResponse,
    OpenAIImageExecutionError,
    load_published_preset,
    published_preset_slots,
    run_openai_image,
    _safe_error,
)


def _generated_base64(color: tuple[int, int, int] = (238, 232, 220)) -> str:
    stream = io.BytesIO()
    Image.new("RGB", (1024, 1280), color).save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


class StubTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, body, timeout_seconds):
        self.calls.append((url, headers, body, timeout_seconds))
        return OpenAIHTTPResponse(
            payload={
                "data": [{"b64_json": _generated_base64()}],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 240,
                    "total_tokens": 360,
                },
            },
            request_id="req_test_openai_2",
        )


class PublishedPresetTest(unittest.TestCase):
    def test_node_choices_are_derived_from_published_registry_slots(self):
        self.assertEqual(
            published_preset_slots(),
            ("natural_white__product_center", "wood__product_center"),
        )

    def test_registry_declares_twelve_slots_and_only_two_published(self):
        registry = json.loads(
            (COMFYUI_DIR / "presets" / "registry.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(registry["slots"]), 12)
        enabled = {
            slot_id: value["preset_id"]
            for slot_id, value in registry["slots"].items()
            if value["enabled"]
        }
        self.assertEqual(
            enabled,
            {
                "natural_white__product_center": "instagram_white_diffuse_wall_table_v1",
                "wood__product_center": "instagram_wood_45deg_relational_v3",
            },
        )

    def test_published_assets_and_prompt_roles_are_hash_verified(self):
        white = load_published_preset("natural_white__product_center")
        wood = load_published_preset("wood__product_center")

        self.assertEqual(white.provider_profile["model"], "gpt-image-2")
        self.assertEqual(white.provider_profile["quality"], "low")
        self.assertNotIn("input_fidelity", white.provider_profile)
        self.assertEqual(white.provider_image_paths, ())
        self.assertEqual(wood.provider_image_roles, ("sanitized_scene_hint",))
        self.assertNotIn("{{", white.prompt)
        self.assertIn("Sheet=instagram_white_diffuse_wall_table_sheet_v1", white.prompt)
        self.assertIn("material review board", wood.prompt)

    def test_unpublished_slot_is_rejected(self):
        with self.assertRaisesRegex(OpenAIImageExecutionError, "PRESET_NOT_READY"):
            load_published_preset("natural_white__product_large")


class OpenAIImageAdapterTest(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source.png"
        Image.new("RGB", (480, 640), (180, 90, 60)).save(source, format="PNG")
        return source

    def test_white_and_wood_use_gpt_image_2_low_and_return_4x5(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            client_request_ids: set[str] = set()
            for slot_id, expected_inputs in (
                ("natural_white__product_center", 1),
                ("wood__product_center", 2),
            ):
                transport = StubTransport()
                image, metadata = run_openai_image(
                    image_path=source,
                    preset_slot_id=slot_id,
                    api_key="test-key",
                    transport=transport,
                    run_id=f"test-{slot_id}",
                    audit_dir=root / "audit",
                )

                self.assertEqual(image.size, (880, 1100))
                self.assertEqual(metadata["model"], "gpt-image-2")
                self.assertEqual(metadata["quality"], "low")
                self.assertEqual(metadata["delivery_dimensions"], [880, 1100])
                self.assertEqual(metadata["automatic_retries"], 0)
                self.assertEqual(metadata["run_id"], f"test-{slot_id}")
                self.assertEqual(metadata["raw_dimensions"], [1024, 1280])
                self.assertEqual(len(metadata["prompt_sha256"]), 64)
                self.assertEqual(len(metadata["provider_profile_sha256"]), 64)
                self.assertTrue((root / "audit" / metadata["audit"]["raw_provider_filename"]).is_file())
                self.assertTrue((root / "audit" / metadata["audit"]["manifest_filename"]).is_file())
                self.assertEqual(len(transport.calls), 1)
                url, headers, body, timeout = transport.calls[0]
                self.assertEqual(url, "https://api.openai.com/v1/images/edits")
                self.assertEqual(headers["Authorization"], "Bearer test-key")
                self.assertTrue(
                    headers["Content-Type"].startswith("multipart/form-data; boundary=")
                )
                self.assertIn(b'name="model"\r\n\r\ngpt-image-2\r\n', body)
                self.assertIn(b'name="quality"\r\n\r\nlow\r\n', body)
                self.assertIn(b'name="size"\r\n\r\n1024x1280\r\n', body)
                self.assertNotIn(b"input_fidelity", body)
                self.assertEqual(body.count(b'name="image[]"'), expected_inputs)
                self.assertLess(body.index(b'filename="image-1.png"'), body.rindex(b"--"))
                self.assertEqual(timeout, 1200.0)
                self.assertNotEqual(headers["X-Client-Request-Id"], metadata["request_hash"])
                client_request_ids.add(headers["X-Client-Request-Id"])
            self.assertEqual(len(client_request_ids), 2)

    def test_missing_api_key_fails_before_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(Path(directory))
            transport = StubTransport()
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(OpenAIImageExecutionError, "OPENAI_API_KEY_MISSING"):
                    run_openai_image(
                        image_path=source,
                        preset_slot_id="natural_white__product_center",
                        api_key="",
                        transport=transport,
                    )
            self.assertEqual(transport.calls, [])

    def test_repeated_request_uses_a_unique_client_request_id(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(Path(directory))
            request_ids = []
            request_hashes = []
            for _ in range(2):
                transport = StubTransport()
                _, metadata = run_openai_image(
                    image_path=source,
                    preset_slot_id="natural_white__product_center",
                    api_key="test-key",
                    transport=transport,
                    run_id="same-logical-input",
                )
                request_ids.append(transport.calls[0][1]["X-Client-Request-Id"])
                request_hashes.append(metadata["request_hash"])
            self.assertNotEqual(request_ids[0], request_ids[1])
            self.assertEqual(request_hashes[0], request_hashes[1])

    def test_rejects_unexpected_provider_canvas_instead_of_cropping(self):
        class WrongCanvasTransport(StubTransport):
            def __call__(self, url, headers, body, timeout_seconds):
                stream = io.BytesIO()
                Image.new("RGB", (1024, 1536), "white").save(stream, format="PNG")
                return OpenAIHTTPResponse(
                    payload={
                        "data": [
                            {
                                "b64_json": base64.b64encode(stream.getvalue()).decode(
                                    "ascii"
                                )
                            }
                        ]
                    },
                    request_id="req_wrong_canvas",
                )

        with tempfile.TemporaryDirectory() as directory:
            source = self._source(Path(directory))
            with self.assertRaisesRegex(
                OpenAIImageExecutionError, "no crop was applied"
            ):
                run_openai_image(
                    image_path=source,
                    preset_slot_id="natural_white__product_center",
                    api_key="test-key",
                    transport=WrongCanvasTransport(),
                )

    def test_provider_error_message_is_not_reflected(self):
        code, message = _safe_error(
            json.dumps(
                {
                    "error": {
                        "code": "unexpected_error",
                        "message": "secret prompt and local path must not escape",
                    }
                }
            ).encode("utf-8")
        )
        self.assertEqual(code, "unexpected_error")
        self.assertEqual(message, "OpenAI rejected the image generation request.")

    def test_unwritable_audit_target_fails_before_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            not_a_directory = root / "audit-blocker"
            not_a_directory.write_text("file", encoding="utf-8")
            transport = StubTransport()
            with self.assertRaisesRegex(
                OpenAIImageExecutionError, "provider call was not started"
            ):
                run_openai_image(
                    image_path=source,
                    preset_slot_id="natural_white__product_center",
                    api_key="test-key",
                    transport=transport,
                    audit_dir=not_a_directory,
                )
            self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
