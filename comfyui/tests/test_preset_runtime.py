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
    def _resolve_published(self, slot_id: str):
        try:
            return resolve_preset_contract(slot_id, registry_path=REGISTRY)
        except PresetRuntimeError as exc:
            if exc.code != "SERVING_TEMPERATURE_REVIEW_REQUIRED":
                raise
            return resolve_preset_contract(
                slot_id,
                serving_temperature="cold",
                registry_path=REGISTRY,
            )

    def test_runtime_has_no_preset_id_branch_literals(self):
        runtime_dir = CUSTOM_NODES_DIR / "ad_creator" / "runtime"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(runtime_dir.glob("*.py"))
        )
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        preset_ids = {
            value["preset_id"]
            for value in registry["slots"].values()
            if isinstance(value, dict) and isinstance(value.get("preset_id"), str)
        } | set(registry.get("alternatives", {}))
        for preset_id in preset_ids:
            self.assertNotIn(preset_id, source)

    def test_all_published_contracts_use_global_caps_and_disabled_branding(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        published = [
            slot_id
            for slot_id, value in registry["slots"].items()
            if value.get("enabled") is True and value.get("status") == "published"
        ]
        self.assertTrue(published)
        for slot_id in published:
            contract = self._resolve_published(slot_id)
            self.assertEqual(contract.maximum_product_sources, 3)
            self.assertEqual(contract.maximum_reference_controls, 1)
            self.assertLessEqual(contract.maximum_provider_inputs, 4)
            self.assertLessEqual(1 + len(contract.provider_image_paths), 4)
            self.assertFalse(contract.brand_input_enabled)
            self.assertLessEqual(len(contract.prompt), 12_000)
            self.assertIn("Brand input is disabled", contract.prompt)

    def test_white_handheld_has_atomic_temperature_and_cup_policy(self):
        adopted = resolve_preset_contract(
            "natural_white__handheld_lifestyle",
            container_mode="adopt_reference",
            serving_temperature="auto",
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
        self.assertEqual(adopted.temperature_resolution_source, "preset_default")
        self.assertEqual(reconstructed.serving_temperature, "source_authoritative")
        self.assertIn("unbranded straight-sided clear plastic cold-drink cup", adopted.prompt)
        self.assertIn("Preserve the source beverage recipe", reconstructed.prompt)

    def test_auto_temperature_uses_only_the_user_product_image(self):
        contract = resolve_preset_contract(
            "wood__product_center",
            serving_temperature="auto",
            registry_path=REGISTRY,
        )
        self.assertEqual(contract.serving_temperature, "source_authoritative")
        self.assertEqual(
            contract.temperature_resolution_source,
            "user_product_image",
        )
        self.assertIn("Image 1 is the sole authority", contract.prompt)
        self.assertIn(
            "Reference and control images have no beverage or serving-state authority",
            contract.prompt,
        )
        self.assertIn("do not invent ice, condensation or steam", contract.prompt)

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

    def test_passed_manifest_bundles_are_complete_and_hash_verified(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        manifest_path = REGISTRY.parent / registry["passed_presets_manifest"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["default_slot_id"], registry["default_preset_slot"])
        bundles = {item["preset_id"]: item for item in manifest["presets"]}
        self.assertIn("instagram_white_direct_handheld_refined_v5", bundles)
        for item in bundles.values():
            path = manifest_path.parent / item["bundle"]
            self.assertTrue(path.is_file())
            content = path.read_bytes()
            if path.suffix.lower() in {".json", ".txt"}:
                content = content.replace(b"\r\n", b"\n")
            self.assertEqual(
                hashlib.sha256(content).hexdigest(),
                item["bundle_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
