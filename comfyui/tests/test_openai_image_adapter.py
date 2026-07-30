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
    default_published_preset_slot,
    OpenAIHTTPResponse,
    OpenAIImageExecutionError,
    load_published_preset,
    published_preset_slots,
    validated_preset_slots,
    run_openai_image,
    _safe_error,
)


def _generated_base64(
    color: tuple[int, int, int] = (238, 232, 220),
    size: tuple[int, int] = (1024, 1280),
) -> str:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


class StubTransport:
    def __init__(self, size: tuple[int, int] = (1024, 1280)):
        self.calls = []
        self.size = size

    def __call__(self, url, headers, body, timeout_seconds):
        self.calls.append((url, headers, body, timeout_seconds))
        return OpenAIHTTPResponse(
            payload={
                "data": [{"b64_json": _generated_base64(size=self.size)}],
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
            (
                "natural_white__product_large",
                "natural_white__product_center",
                "natural_white__aerial_shot",
                "natural_white__handheld_lifestyle",
                "wood__product_large",
                "wood__product_center",
                "wood__aerial_shot",
                "wood__handheld_lifestyle",
                "vivid__product_large",
                "vivid__product_center",
                "vivid__aerial_shot",
                "vivid__handheld_lifestyle",
            ),
        )

    def test_default_is_declared_by_the_registry(self):
        self.assertEqual(default_published_preset_slot(), "wood__product_center")

    def test_quality_defaults_to_medium_and_all_three_profiles_resolve(self):
        default = load_published_preset("wood__product_center")
        low = load_published_preset("wood__product_center", quality="low")
        high = load_published_preset("wood__product_center", quality="high")
        self.assertEqual(default.provider_profile["quality"], "medium")
        self.assertEqual(low.provider_profile["quality"], "low")
        self.assertEqual(high.provider_profile["quality"], "high")
        with self.assertRaisesRegex(OpenAIImageExecutionError, "Unsupported"):
            load_published_preset("wood__product_center", quality="ultra")

    def test_reviewed_presets_remain_available_for_validation(self):
        self.assertEqual(
            validated_preset_slots(),
            (),
        )

    def test_registry_declares_twelve_slots_and_reviewed_presets_are_published(self):
        registry = json.loads(
            (COMFYUI_DIR / "presets" / "registry.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(registry["slots"]), 12)
        enabled = {
            slot_id: value["preset_id"]
            for slot_id, value in registry["slots"].items()
            if value["enabled"] and value["status"] == "published"
        }
        self.assertEqual(
            enabled,
            {
                "natural_white__product_large": "instagram_white_diffuse_closeup_v1",
                "natural_white__product_center": "instagram_white_diffuse_wall_table_v1",
                "natural_white__aerial_shot": "instagram_white_neutral_overhead_spatial_v1",
                "natural_white__handheld_lifestyle": "instagram_white_direct_handheld_refined_v5",
                "wood__product_large": "instagram_wood_calm_window_closeup_v1",
                "wood__product_center": "tokyo_a6_relational_scene_hint_v4",
                "wood__aerial_shot": "instagram_wood_cane_brownie_overhead_v1",
                "wood__handheld_lifestyle": "instagram_wood_handheld_two_person_v1",
                "vivid__product_large": "instagram_dark_grey_closeup_v1",
                "vivid__product_center": "instagram_dark_grey_medium_v1",
                "vivid__aerial_shot": "instagram_dark_grey_aerial_v1",
                "vivid__handheld_lifestyle": "instagram_dark_grey_handheld_v1",
            },
        )

    def test_published_assets_and_prompt_roles_are_hash_verified(self):
        white = load_published_preset("natural_white__product_center")
        handheld = load_published_preset(
            "natural_white__handheld_lifestyle",
            container_mode="adopt_reference",
            serving_temperature="cold",
        )
        wood = load_published_preset("wood__product_center")

        self.assertEqual(white.provider_profile["model"], "gpt-image-2")
        self.assertEqual(white.provider_profile["quality"], "medium")
        self.assertNotIn("input_fidelity", white.provider_profile)
        self.assertEqual(white.provider_image_paths, ())
        self.assertEqual(handheld.provider_image_roles, ("sanitized_scene_hint",))
        self.assertEqual(handheld.brand_default_mode, "none")
        self.assertIn("unbranded straight-sided clear plastic cold-drink cup", handheld.prompt)
        self.assertEqual(
            wood.provider_image_roles,
            ("wood_medium_source_container_scene_hint",),
        )
        self.assertEqual(wood.container_mode, "reconstruct_source")
        self.assertFalse(wood.brand_input_enabled)
        self.assertEqual(wood.brand_default_mode, "none")
        self.assertLessEqual(len(wood.prompt), 12000)
        self.assertNotIn("{{", white.prompt)
        self.assertIn("Sheet=instagram_white_diffuse_wall_table_sheet_v1", white.prompt)
        self.assertIn("three-point group", wood.prompt)
        self.assertEqual(wood.aspect_ratio, "4:5")

    def test_white_and_wood_medium_resolve_both_cup_modes(self):
        white_source = load_published_preset(
            "natural_white__product_center",
            container_mode="reconstruct_source",
            serving_temperature="auto",
        )
        white_reference = load_published_preset(
            "natural_white__product_center",
            container_mode="adopt_reference",
            serving_temperature="auto",
        )
        wood_source = load_published_preset(
            "wood__product_center",
            container_mode="reconstruct_source",
            serving_temperature="auto",
        )
        wood_reference = load_published_preset(
            "wood__product_center",
            container_mode="adopt_reference",
            serving_temperature="auto",
        )

        self.assertEqual(white_source.provider_image_roles, ())
        self.assertEqual(
            white_reference.provider_image_roles,
            ("white_medium_reference_cup_hint",),
        )
        self.assertIn("short straight-sided clear glass tumbler", white_reference.prompt)
        self.assertIn(
            "Use the right-panel cup only for scale, position, perspective and contact",
            white_reference.prompt,
        )
        self.assertEqual(
            wood_source.provider_image_roles,
            ("wood_medium_source_container_scene_hint",),
        )
        self.assertEqual(
            wood_reference.provider_image_roles,
            ("wood_medium_reference_container_scene_hint",),
        )
        self.assertIn("rounded clear-glass vessel", wood_reference.prompt)
        for contract in (white_source, white_reference, wood_source, wood_reference):
            self.assertEqual(contract.serving_temperature, "source_authoritative")
            self.assertEqual(
                contract.temperature_resolution_source,
                "user_product_image",
            )

    def test_white_medium_random_control_group_sends_exactly_one_board(self):
        with patch(
            "ad_creator.runtime.preset_contract.secrets.choice",
            side_effect=lambda candidates: candidates[0],
        ):
            first = load_published_preset(
                "natural_white__product_center",
                container_mode="adopt_reference",
                serving_temperature="auto",
            )
        with patch(
            "ad_creator.runtime.preset_contract.secrets.choice",
            side_effect=lambda candidates: candidates[-1],
        ):
            last = load_published_preset(
                "natural_white__product_center",
                container_mode="adopt_reference",
                serving_temperature="auto",
            )

        self.assertEqual(
            first.provider_image_roles,
            ("white_medium_reference_cup_hint",),
        )
        self.assertEqual(len(first.provider_image_paths), 1)
        self.assertEqual(
            first.provider_image_paths[0].name,
            "white-medium-control-distant-v2.png",
        )
        self.assertEqual(
            last.provider_image_paths[0].name,
            "white-medium-control-diagonal-table-v2.png",
        )

    def test_closeup_source_cup_mode_preserves_visible_sleeve_and_branding_only(self):
        for slot_id in ("natural_white__product_large", "vivid__product_large"):
            source_cup = load_published_preset(
                slot_id,
                container_mode="reconstruct_source",
                serving_temperature="auto",
            )
            reference_cup = load_published_preset(
                slot_id,
                container_mode="adopt_reference",
                serving_temperature="cold",
            )

            self.assertIn("every physically attached sleeve", source_cup.prompt)
            self.assertIn("real source logo, wordmark or label", source_cup.prompt)
            self.assertIn(
                "replace it with a plain generic sleeve",
                source_cup.prompt.lower(),
            )
            self.assertNotIn("every physically attached sleeve", reference_cup.prompt)
            self.assertIn("without a logo, wordmark", reference_cup.prompt)

        dark_source = load_published_preset(
            "vivid__product_large",
            container_mode="reconstruct_source",
            serving_temperature="auto",
        )
        self.assertIn(
            "preserve the source-visible straw and lid state exactly",
            dark_source.prompt,
        )
        self.assertNotIn(
            "an iced beverage must NEVER include a straw",
            dark_source.prompt,
        )

    def test_wood_handheld_resolves_final_mode_specific_hints(self):
        adopted = load_published_preset(
            "wood__handheld_lifestyle",
            container_mode="adopt_reference",
            serving_temperature="auto",
        )
        reconstructed = load_published_preset(
            "wood__handheld_lifestyle",
            container_mode="reconstruct_source",
            serving_temperature="auto",
        )
        self.assertEqual(
            adopted.provider_image_roles,
            ("reference_cup_pose_light_and_scene_evidence",),
        )
        self.assertEqual(
            reconstructed.provider_image_roles,
            ("source_cup_pose_light_and_scene_evidence",),
        )
        self.assertIn("lower-left 7–8 o’clock", reconstructed.prompt)
        self.assertIn("5–7%", reconstructed.prompt)
        self.assertEqual(reconstructed.serving_temperature, "source_authoritative")

    def test_dark_grey_handheld_separates_user_and_reference_hints(self):
        adopted = load_published_preset(
            "vivid__handheld_lifestyle",
            container_mode="adopt_reference",
            serving_temperature="auto",
        )
        reconstructed = load_published_preset(
            "vivid__handheld_lifestyle",
            container_mode="reconstruct_source",
            serving_temperature="auto",
        )
        self.assertEqual(
            adopted.provider_image_roles,
            ("dark_grey_handheld_double_wall_reference",),
        )
        self.assertEqual(
            reconstructed.provider_image_roles,
            ("dark_grey_handheld_user_pose_only",),
        )
        self.assertEqual(adopted.serving_temperature, "source_authoritative")
        self.assertEqual(reconstructed.serving_temperature, "source_authoritative")

    def test_reported_reference_cup_presets_compile_without_source_cup_conflicts(self):
        expected_reference_roles = {
            "natural_white__product_center": ("white_medium_reference_cup_hint",),
            "wood__product_center": ("wood_medium_reference_container_scene_hint",),
            "vivid__product_large": ("raw_dark_grey_closeup_reference",),
            "vivid__product_center": ("raw_dark_grey_glass_wall_reference",),
            "vivid__handheld_lifestyle": (
                "dark_grey_handheld_double_wall_reference",
            ),
        }

        for slot_id, expected_roles in expected_reference_roles.items():
            with self.subTest(slot_id=slot_id):
                adopted = load_published_preset(
                    slot_id,
                    container_mode="adopt_reference",
                    serving_temperature="auto",
                )
                reconstructed = load_published_preset(
                    slot_id,
                    container_mode="reconstruct_source",
                    serving_temperature="auto",
                )

                self.assertEqual(adopted.container_mode, "adopt_reference")
                self.assertEqual(adopted.provider_image_roles, expected_roles)
                self.assertIn("Container mode=adopt_reference", adopted.prompt)
                self.assertNotIn(
                    "Reconstruct the user's cup/container design",
                    adopted.prompt,
                )
                self.assertNotIn(
                    "source cup semantics reconstructed",
                    adopted.prompt,
                )
                self.assertEqual(
                    reconstructed.container_mode,
                    "reconstruct_source",
                )
                self.assertIn(
                    "Container mode=reconstruct_source",
                    reconstructed.prompt,
                )

    def test_white_handheld_resolves_its_two_declared_cup_policies(self):
        adopted = load_published_preset(
            "natural_white__handheld_lifestyle",
            container_mode="adopt_reference",
            serving_temperature="auto",
        )
        reconstructed = load_published_preset(
            "natural_white__handheld_lifestyle",
            container_mode="reconstruct_source",
            serving_temperature="auto",
        )
        self.assertEqual(adopted.provider_image_roles, ("sanitized_scene_hint",))
        self.assertEqual(adopted.serving_temperature, "cold")
        self.assertEqual(adopted.temperature_resolution_source, "preset_default")
        self.assertEqual(reconstructed.serving_temperature, "source_authoritative")

    def test_validated_presets_resolve_both_declared_container_modes(self):
        white_closeup = load_published_preset(
            "natural_white__product_large",
            container_mode="adopt_reference",
            serving_temperature="auto",
            allowed_statuses=("published",),
        )
        white_reference = load_published_preset(
            "natural_white__aerial_shot",
            container_mode="adopt_reference",
            allowed_statuses=("published",),
        )
        white_source = load_published_preset(
            "natural_white__aerial_shot",
            container_mode="reconstruct_source",
            allowed_statuses=("published",),
        )
        wood_reference = load_published_preset(
            "wood__product_large",
            container_mode="adopt_reference",
            serving_temperature="cold",
            allowed_statuses=("published",),
        )
        wood_source = load_published_preset(
            "wood__product_large",
            container_mode="reconstruct_source",
            allowed_statuses=("published",),
        )
        self.assertEqual(white_reference.container_mode, "adopt_reference")
        self.assertEqual(white_source.container_mode, "reconstruct_source")
        self.assertEqual(
            white_reference.provider_image_roles,
            ("reference_cup_geometry_and_companion_scene_evidence",),
        )
        self.assertEqual(
            white_source.provider_image_roles,
            ("user_cup_placement_and_companion_scene_evidence",),
        )
        self.assertEqual(white_closeup.container_mode, "adopt_reference")
        self.assertEqual(white_closeup.serving_temperature, "cold")
        self.assertEqual(white_closeup.aspect_ratio, "4:5")
        self.assertEqual(
            wood_reference.provider_image_roles,
            ("reference_cup_geometry_light_and_companion_evidence",),
        )
        self.assertEqual(
            wood_source.provider_image_roles,
            ("source_cup_geometry_light_and_companion_evidence",),
        )
        for preset in (white_reference, white_source, wood_reference, wood_source):
            self.assertLessEqual(1 + len(preset.provider_image_paths), 4)
            self.assertIn("Brand input is disabled", preset.prompt)
        self.assertEqual(wood_reference.brand_default_mode, "preset_typography")
        self.assertIn("CAFE AMERICANO", wood_reference.prompt)

    def test_cold_reference_container_rejects_hot_and_unknown_state(self):
        for serving_temperature in ("hot",):
            with self.assertRaises(OpenAIImageExecutionError):
                load_published_preset(
                    "wood__product_large",
                    container_mode="adopt_reference",
                    serving_temperature=serving_temperature,
                    allowed_statuses=("published",),
                )
        auto = load_published_preset(
            "wood__product_large",
            container_mode="adopt_reference",
            serving_temperature="auto",
        )
        self.assertEqual(auto.serving_temperature, "source_authoritative")
class OpenAIImageAdapterTest(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source.png"
        Image.new("RGB", (480, 640), (180, 90, 60)).save(source, format="PNG")
        return source

    def test_white_and_wood_use_gpt_image_2_medium_and_return_4x5(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            client_request_ids: set[str] = set()
            for slot_id, maximum_inputs, submitted_inputs in (
                ("natural_white__product_center", 2, 1),
                ("wood__product_center", 2, 2),
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

                self.assertEqual(image.size, (1024, 1280))
                self.assertEqual(metadata["model"], "gpt-image-2")
                self.assertEqual(metadata["quality"], "medium")
                self.assertEqual(metadata["delivery_dimensions"], [1024, 1280])
                self.assertEqual(metadata["aspect_ratio"], "4:5")
                self.assertEqual(metadata["aspect_status"], "published")
                self.assertEqual(metadata["source_preprocessing"]["uploaded_dimensions"], [480, 640])
                self.assertFalse(metadata["source_preprocessing"]["upscaled"])
                self.assertEqual(metadata["source_preprocessing"]["max_long_edge"], 1536)
                self.assertEqual(metadata["automatic_retries"], 0)
                self.assertFalse(metadata["brand_input_enabled"])
                self.assertEqual(metadata["maximum_provider_inputs"], maximum_inputs)
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
                self.assertIn(b'name="quality"\r\n\r\nmedium\r\n', body)
                self.assertIn(b'name="size"\r\n\r\n1024x1280\r\n', body)
                self.assertNotIn(b"input_fidelity", body)
                self.assertEqual(body.count(b'name="image[]"'), submitted_inputs)
                self.assertLess(body.index(b'filename="image-1.jpg"'), body.rindex(b"--"))
                self.assertEqual(timeout, 1200.0)
                self.assertNotEqual(headers["X-Client-Request-Id"], metadata["request_hash"])
                client_request_ids.add(headers["X-Client-Request-Id"])
            self.assertEqual(len(client_request_ids), 2)

    def test_square_uses_native_canvas_without_portrait_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(Path(directory))
            transport = StubTransport(size=(1024, 1024))
            image, metadata = run_openai_image(
                image_path=source,
                preset_slot_id="wood__product_center",
                aspect_ratio="1:1",
                api_key="test-key",
                transport=transport,
            )
            self.assertEqual(image.size, (1024, 1024))
            self.assertEqual(metadata["raw_dimensions"], [1024, 1024])
            self.assertEqual(metadata["aspect_ratio"], "1:1")
            self.assertEqual(metadata["aspect_status"], "published")
            self.assertIn(b'name="size"\r\n\r\n1024x1024\r\n', transport.calls[0][2])

    def test_source_preprocessing_supports_auditable_1536_and_3072_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large.png"
            Image.new("RGB", (2400, 3200), "white").save(source, format="PNG")
            hashes = []
            dimensions = []
            for edge in (1536, 3072):
                with patch.dict(
                    "os.environ", {"AD_CREATOR_OPENAI_SOURCE_MAX_EDGE": str(edge)}
                ):
                    _, metadata = run_openai_image(
                        image_path=source,
                        preset_slot_id="natural_white__product_center",
                        api_key="test-key",
                        transport=StubTransport(),
                    )
                dimensions.append(metadata["source_preprocessing"]["uploaded_dimensions"])
                hashes.append(metadata["request_hash"])
            self.assertEqual(dimensions, [[1152, 1536], [2304, 3072]])
            self.assertNotEqual(hashes[0], hashes[1])

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
