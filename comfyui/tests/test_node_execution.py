import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from PIL import Image


CUSTOM_NODES_DIR = Path(__file__).resolve().parents[1] / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.nodes.model_c import AdCreatorModelCGenerate


class NodeExecutionTest(unittest.TestCase):
    def test_random_seed_disables_comfyui_cache(self):
        self.assertNotEqual(
            AdCreatorModelCGenerate.IS_CHANGED(None, "medium", "white", "medium", -1),
            AdCreatorModelCGenerate.IS_CHANGED(None, "medium", "white", "medium", -1),
        )
        self.assertEqual(
            AdCreatorModelCGenerate.IS_CHANGED(None, "medium", "white", "medium", 42),
            42,
        )

    def test_converts_image_calls_adapter_and_cleans_temp_input(self):
        generated = io.BytesIO()
        Image.new("RGB", (12, 10), (245, 240, 230)).save(generated, format="PNG")
        observed_input: Path | None = None

        def fake_run_model_c(**kwargs):
            nonlocal observed_input
            observed_input = Path(kwargs["image_path"])
            self.assertTrue(observed_input.is_file())
            self.assertEqual(kwargs["composition"], "medium")
            self.assertEqual(kwargs["background_style"], "white")
            self.assertEqual(kwargs["strength"], "medium")
            self.assertEqual(kwargs["seed"], 42)
            return (
                {
                    "success": True,
                    "output_path": "/remote/generated.png",
                    "image_url": "/outputs/generated.png",
                    "seed": 42,
                },
                generated.getvalue(),
            )

        source = torch.zeros((1, 8, 9, 3), dtype=torch.float32)
        with patch("ad_creator.nodes.model_c.model_c_adapter.run_model_c", side_effect=fake_run_model_c):
            image, metadata_json = AdCreatorModelCGenerate().generate(
                image=source,
                composition="medium",
                background_style="white",
                strength="medium",
                seed=42,
            )

        metadata = json.loads(metadata_json)
        self.assertEqual(tuple(image.shape), (1, 10, 12, 3))
        self.assertEqual(metadata["seed"], 42)
        self.assertNotIn("output_path", metadata)
        self.assertEqual(metadata["output_storage"], "comfyui_save_image")
        self.assertIsNotNone(observed_input)
        self.assertFalse(observed_input.exists())


if __name__ == "__main__":
    unittest.main()
