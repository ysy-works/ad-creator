import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PIL import Image


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.runtime import (
    PresetRuntimeError,
    execute_product_transforms,
    resolve_preset_contract,
)
from ad_creator.runtime import preset_contract as runtime_contract


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
            self.assertLessEqual(
                len(contract.prompt),
                contract.runtime_policy["maximum_prompt_characters"],
            )
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

    def test_pending_wood_overhead_uses_the_shared_runtime_contract(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        bundle_path = REGISTRY.parent / "wood__aerial_shot" / "preset.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        candidate_registry = deepcopy(registry)
        candidate_bundle = deepcopy(bundle)
        candidate_registry["slots"]["wood__aerial_shot"]["enabled"] = True
        candidate_registry["slots"]["wood__aerial_shot"]["status"] = "validated"
        candidate_bundle["status"] = "validated"
        candidate_bundle["source_review_status"] = "pending_provider_visual_validation"
        original_read_json = runtime_contract._read_json

        def read_candidate(path: Path):
            resolved = Path(path).resolve()
            if resolved == REGISTRY.resolve():
                return candidate_registry
            if resolved == bundle_path.resolve():
                return candidate_bundle
            return original_read_json(path)

        with patch.object(runtime_contract, "_read_json", side_effect=read_candidate):
            adopted = resolve_preset_contract(
                "wood__aerial_shot",
                serving_temperature="auto",
                registry_path=REGISTRY,
                allowed_statuses=("validated",),
            )
            reconstructed = resolve_preset_contract(
                "wood__aerial_shot",
                container_mode="reconstruct_source",
                serving_temperature="auto",
                registry_path=REGISTRY,
                allowed_statuses=("validated",),
            )

        self.assertEqual(adopted.container_mode, "adopt_reference")
        self.assertEqual(adopted.serving_temperature, "source_authoritative")
        self.assertEqual(adopted.temperature_resolution_source, "user_product_image")
        self.assertEqual(
            adopted.provider_image_roles,
            ("sanitized_wood_cane_brownie_control_board",),
        )
        self.assertEqual(reconstructed.container_mode, "reconstruct_source")
        self.assertEqual(reconstructed.serving_temperature, "source_authoritative")
        for contract in (adopted, reconstructed):
            self.assertEqual(
                [contract.delivery_width, contract.delivery_height], [1024, 1280]
            )
            self.assertEqual(contract.safe_crop, "none_exact_4x5")
            self.assertFalse(contract.bbox_qa["crop_allowed"])
            self.assertLessEqual(
                len(contract.prompt),
                contract.runtime_policy["maximum_prompt_characters"],
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

    def test_dark_grey_container_modes_separate_source_identity_and_branding(self):
        reconstructed = resolve_preset_contract(
            "vivid__product_center",
            container_mode="reconstruct_source",
            serving_temperature="cold",
            registry_path=REGISTRY,
        )
        adopted = resolve_preset_contract(
            "vivid__product_center",
            container_mode="adopt_reference",
            serving_temperature="cold",
            registry_path=REGISTRY,
        )
        self.assertIn("Reconstruct the EXACT cup/container shown in Image 1", reconstructed.prompt)
        self.assertIn("remove visible authorized source branding", reconstructed.prompt)
        self.assertIn("If no branding is visible in Image 1, add none", reconstructed.prompt)
        self.assertNotIn("Keep the adopted preset vessel unbranded", reconstructed.prompt)
        self.assertIn("treat that source container as excluded evidence", adopted.prompt)
        self.assertIn("Keep the adopted preset vessel unbranded", adopted.prompt)
        self.assertIn("No earlier prompt phrase authorizes branding", adopted.prompt)
        self.assertNotIn("Preserve every real source-visible logo", adopted.prompt)

    def test_wood_handheld_reconstruct_source_declares_geometry_state_contract(self):
        contract = resolve_preset_contract(
            "wood__handheld_lifestyle",
            container_mode="reconstruct_source",
            serving_temperature="hot",
            registry_path=REGISTRY,
        )
        self.assertIn("strict direct-evidence geometry rule", contract.prompt)
        self.assertIn("smooth, uninterrupted rotational wall", contract.prompt)
        self.assertIn("addition of an unevidenced side protrusion", contract.prompt)
        self.assertIn("board deliberately contains no target-container attachment evidence", contract.prompt)
        self.assertIn("STATE VISIBLE LOOP", contract.prompt)
        self.assertIn("STATE CONTINUOUS WALL", contract.prompt)
        self.assertIn("closed or C-shaped side loop", contract.prompt)
        self.assertIn("image-right loop remains unobstructed", contract.prompt)
        self.assertEqual(contract.prompt.lower().count("handle"), 2)
        self.assertIn("carry ZERO target-container identity", contract.prompt)
        self.assertIn("empty-air grip is an anatomy guide, not a missing mug", contract.prompt)
        self.assertNotIn("Reject board replication, source pixel reuse, missing handle,", contract.prompt)

        bundle = json.loads(
            (REGISTRY.parent / "wood__handheld_lifestyle" / "preset.json").read_text(
                encoding="utf-8"
            )
        )
        hint = next(
            item
            for item in bundle["hint_images"]
            if item["role"] == "source_cup_pose_light_and_scene_evidence"
        )
        self.assertTrue(
            any(
                "all target cup family" in rule
                for rule in hint.get("excluded_transfer", [])
            )
        )
        self.assertIn("zero target-vessel identity authority", hint["reason"])

    def test_wood_closeup_reconstruct_source_keeps_source_identity_and_companion_copy(self):
        contract = resolve_preset_contract(
            "wood__product_large",
            container_mode="reconstruct_source",
            serving_temperature="cold",
            registry_path=REGISTRY,
        )
        self.assertIn("Preserve every source-visible primary label", contract.prompt)
        self.assertIn('exact generic text "CAFE AMERICANO"', contract.prompt)
        self.assertIn("remove visible authorized source branding", contract.prompt)
        self.assertNotIn("No earlier prompt phrase authorizes branding", contract.prompt)

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
