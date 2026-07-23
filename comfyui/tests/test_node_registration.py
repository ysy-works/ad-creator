import json
import sys
import unittest
from pathlib import Path


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

import ad_creator


class NodeRegistrationTest(unittest.TestCase):
    def test_workflow_custom_nodes_are_registered(self):
        registry = json.loads((COMFYUI_DIR / "workflows" / "registry.json").read_text(encoding="utf-8"))
        workflow = registry["workflows"][registry["default_workflow_id"]]
        for class_type in workflow["custom_node_types"]:
            self.assertIn(class_type, ad_creator.NODE_CLASS_MAPPINGS)

    def test_registered_node_has_legacy_comfyui_contract(self):
        for node_name in (
            "AdCreatorModelCGenerate",
            "AdCreatorOpenAIImageGenerate",
        ):
            node = ad_creator.NODE_CLASS_MAPPINGS[node_name]
            self.assertTrue(callable(node.INPUT_TYPES))
            self.assertEqual(node.FUNCTION, "generate")
            self.assertEqual(node.RETURN_TYPES, ("IMAGE", "STRING"))
            self.assertEqual(node.CATEGORY, "Ad Creator")

    def test_openai_node_ui_metadata_resolves_all_published_presets(self):
        node = ad_creator.NODE_CLASS_MAPPINGS["AdCreatorOpenAIImageGenerate"]
        inputs = node.INPUT_TYPES()
        self.assertEqual(
            tuple(inputs["required"]["preset_id"][0]),
            (
                "natural_white__product_large",
                "natural_white__product_center",
                "natural_white__aerial_shot",
                "natural_white__handheld_lifestyle",
                "wood__product_large",
                "wood__product_center",
                "wood__aerial_shot",
            ),
        )


if __name__ == "__main__":
    unittest.main()
