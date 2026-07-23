import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.runtime import execute_product_transforms, resolve_preset_contract


REGISTRY = COMFYUI_DIR / "presets" / "registry.json"


class PresetRuntimeTest(unittest.TestCase):
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

    def test_all_published_contracts_use_global_caps_and_preset_policy(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        published = [
            slot_id
            for slot_id, value in registry["slots"].items()
            if value.get("enabled") is True and value.get("status") == "published"
        ]
        self.assertTrue(published)
        for slot_id in published:
            contract = resolve_preset_contract(
                slot_id,
                registry_path=REGISTRY,
            )
            self.assertEqual(contract.maximum_product_sources, 3)
            self.assertEqual(contract.maximum_reference_controls, 1)
            self.assertLessEqual(contract.maximum_provider_inputs, 4)
            self.assertLessEqual(1 + len(contract.provider_image_paths), 4)
            self.assertFalse(contract.brand_input_enabled)
            self.assertLessEqual(len(contract.prompt), 12_000)
            self.assertIn("Brand input is disabled", contract.prompt)

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


if __name__ == "__main__":
    unittest.main()
