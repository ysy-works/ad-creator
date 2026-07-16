import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from PIL import Image


CUSTOM_NODES_DIR = Path(__file__).resolve().parents[1] / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.nodes.model_c import AdCreatorModelCGenerate


class NodeExecutionTest(unittest.TestCase):
    def test_converts_image_calls_adapter_and_cleans_temp_input(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "generated.png"
            Image.new("RGB", (12, 10), (245, 240, 230)).save(output_path)
            observed_input: Path | None = None

            def fake_run_model_c(**kwargs):
                nonlocal observed_input
                observed_input = Path(kwargs["image_path"])
                self.assertTrue(observed_input.is_file())
                return {
                    "success": True,
                    "output_path": str(output_path),
                    "seed": 42,
                }

            source = torch.zeros((1, 8, 9, 3), dtype=torch.float32)
            with patch("ad_creator.nodes.model_c.model_c_adapter.run_model_c", side_effect=fake_run_model_c):
                image, metadata_json = AdCreatorModelCGenerate().generate(
                    image=source,
                    composition="medium",
                    background_style="white",
                    strength="medium",
                    seed=42,
                    guidance_scale=2.5,
                    num_inference_steps=28,
                    width=832,
                    height=1040,
                )

            self.assertEqual(tuple(image.shape), (1, 10, 12, 3))
            self.assertEqual(json.loads(metadata_json)["seed"], 42)
            self.assertIsNone(json.loads(metadata_json)["output_path"])
            self.assertEqual(json.loads(metadata_json)["output_storage"], "comfyui_save_image")
            self.assertFalse(output_path.exists())
            self.assertIsNotNone(observed_input)
            self.assertFalse(observed_input.exists())


if __name__ == "__main__":
    unittest.main()
