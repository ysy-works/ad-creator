import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.runtime import (
    PresetRuntimeError,
    execute_product_transforms,
    resolve_preset_contract,
)


REGISTRY = COMFYUI_DIR / "presets" / "registry.json"


class PresetRuntimeTest(unittest.TestCase):
    def test_runtime_has_no_preset_id_branch_literals(self):
        runtime_dir = CUSTOM_NODES_DIR / "ad_creator" / "runtime"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(runtime_dir.glob("*.py"))
        )
        for preset_id in (
            "tokyo_a6_relational_scene_hint_v4",
            "instagram_white_diffuse_wall_table_v1",
            "instagram_white_neutral_overhead_spatial_v1",
            "instagram_white_direct_handheld_refined_v5",
            "instagram_wood_calm_window_closeup_v1",
        ):
            self.assertNotIn(preset_id, source)

    def test_all_active_contracts_use_four_input_cap_and_disabled_branding(self):
        cases = (
            ("natural_white__product_center", "published", "default", "auto"),
            ("wood__product_center", "published", "default", "auto"),
            ("natural_white__handheld_lifestyle", "published", "reconstruct_source", "auto"),
            ("natural_white__handheld_lifestyle", "published", "adopt_reference", "cold"),
            ("natural_white__aerial_shot", "validated", "adopt_reference", "auto"),
            ("natural_white__aerial_shot", "validated", "reconstruct_source", "auto"),
            ("wood__product_large", "validated", "adopt_reference", "cold"),
            ("wood__product_large", "validated", "reconstruct_source", "auto"),
        )
        for slot_id, status, mode, temperature in cases:
            contract = resolve_preset_contract(
                slot_id,
                container_mode=mode,
                serving_temperature=temperature,
                registry_path=REGISTRY,
                allowed_statuses=(status,),
            )
            self.assertEqual(contract.maximum_product_sources, 3)
            self.assertEqual(contract.maximum_reference_controls, 1)
            self.assertLessEqual(contract.maximum_provider_inputs, 4)
            self.assertLessEqual(1 + len(contract.provider_image_paths), 4)
            self.assertFalse(contract.brand_input_enabled)
            self.assertLessEqual(len(contract.prompt), 12000)
            self.assertIn("Brand input is disabled", contract.prompt)

    def test_white_handheld_requires_explicit_cold_state_when_adopting_reference_cup(self):
        with self.assertRaises(PresetRuntimeError) as raised:
            resolve_preset_contract(
                "natural_white__handheld_lifestyle",
                container_mode="adopt_reference",
                serving_temperature="auto",
                registry_path=REGISTRY,
            )
        self.assertEqual(raised.exception.code, "SERVING_TEMPERATURE_REVIEW_REQUIRED")

        adopted = resolve_preset_contract(
            "natural_white__handheld_lifestyle",
            container_mode="adopt_reference",
            serving_temperature="cold",
            registry_path=REGISTRY,
        )
        reconstructed = resolve_preset_contract(
            "natural_white__handheld_lifestyle",
            container_mode="reconstruct_source",
            serving_temperature="auto",
            registry_path=REGISTRY,
        )
        self.assertEqual(adopted.provider_image_roles, ("sanitized_scene_hint",))
        self.assertEqual(adopted.serving_temperature, "cold")
        self.assertEqual(reconstructed.serving_temperature, "source_authoritative")
        self.assertIn("unbranded straight-sided clear plastic cold-drink cup", adopted.prompt)
        self.assertIn("Preserve the source beverage recipe", reconstructed.prompt)

    def test_wood_closeup_keeps_default_cafe_americano_until_logo_ui_exists(self):
        contract = resolve_preset_contract(
            "wood__product_large",
            container_mode="adopt_reference",
            serving_temperature="cold",
            registry_path=REGISTRY,
            allowed_statuses=("validated",),
        )
        brand = contract.runtime_policy["brand_input_policy"]
        self.assertEqual(contract.brand_default_mode, "preset_typography")
        self.assertEqual(brand["preset_typography"][0]["text"], "CAFE AMERICANO")
        self.assertFalse(brand["future_user_logo_override"]["enabled"])
        self.assertEqual(
            brand["future_user_logo_override"]["replacement_action"],
            "replace_default_typography_only",
        )
        self.assertIn('exact text "CAFE AMERICANO"', contract.prompt)
        self.assertIn("future per-image user-logo override remains inactive", contract.prompt)

    def test_wood_adopt_reference_temperature_guard_is_atomic(self):
        for temperature in ("auto", "hot"):
            with self.assertRaises(PresetRuntimeError):
                resolve_preset_contract(
                    "wood__product_large",
                    container_mode="adopt_reference",
                    serving_temperature=temperature,
                    registry_path=REGISTRY,
                    allowed_statuses=("validated",),
                )

    def test_declared_crop_uses_analyzed_geometry_or_audited_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (100, 80), "white").save(source)
            operation = (
                {
                    "type": "crop_product_by_analysis_geometry",
                    "fallback": "full_user_image",
                },
            )
            with execute_product_transforms(source, operation) as (path, audit):
                self.assertEqual(path, source.resolve())
                self.assertEqual(audit[0]["status"], "fallback")
            analysis = {"geometry": {"container_bbox_pixels": [10, 20, 70, 60]}}
            with execute_product_transforms(
                source, operation, product_analysis=analysis
            ) as (path, audit):
                self.assertNotEqual(path, source.resolve())
                with Image.open(path) as cropped:
                    self.assertEqual(cropped.size, (60, 40))
                self.assertEqual(audit[0]["status"], "applied")

    def test_passed_retention_manifest_has_exact_user_approved_set(self):
        manifest_path = COMFYUI_DIR / "presets" / "passed-presets.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["default_preset_id"], "tokyo_a6_relational_scene_hint_v4")
        self.assertEqual(
            [item["preset_id"] for item in manifest["presets"]],
            [
                "tokyo_a6_relational_scene_hint_v4",
                "instagram_white_diffuse_wall_table_v1",
                "instagram_wood_45deg_relational_v3",
                "instagram_white_direct_handheld_refined_v5",
            ],
        )
        for item in manifest["presets"]:
            path = manifest_path.parent / item["bundle"]
            self.assertTrue(path.is_file())
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                item["bundle_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
