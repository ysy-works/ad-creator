import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image


CUSTOM_NODES_DIR = Path(__file__).resolve().parents[1] / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.adapters import model_c


class ModelCAdapterTest(unittest.TestCase):
    def test_passes_arguments_and_returns_success_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            output = root / "output.png"
            Image.new("RGB", (8, 8), "white").save(source)
            Image.new("RGB", (8, 8), (255, 253, 240)).save(output)

            generate = Mock(
                return_value={
                    "success": True,
                    "output_path": str(output),
                    "composition": "medium",
                    "background_style": "wood",
                    "strength": "medium",
                    "seed": 42,
                }
            )
            fake_inference = SimpleNamespace(generate_beverage_image=generate)

            with patch.object(model_c, "_load_inference_module", return_value=fake_inference), patch.object(
                model_c, "_output_dir", return_value=root
            ):
                result = model_c.run_model_c(
                    image_path=source,
                    composition="medium",
                    background_style="wood",
                    strength="medium",
                    seed=42,
                    guidance_scale=2.5,
                    num_inference_steps=28,
                    width=832,
                    height=1040,
                )

            self.assertTrue(result["success"])
            generate.assert_called_once_with(
                image_path=str(source.resolve()),
                composition="medium",
                background_style="wood",
                strength="medium",
                seed=42,
                guidance_scale=2.5,
                num_inference_steps=28,
                width=832,
                height=1040,
                output_dir=str(root),
            )

    def test_preserves_model_error_code(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (8, 8), "white").save(source)
            fake_inference = SimpleNamespace(
                generate_beverage_image=Mock(
                    return_value={
                        "success": False,
                        "error_code": "CUDA_OUT_OF_MEMORY",
                        "error_message": "out of memory",
                    }
                )
            )

            with patch.object(model_c, "_load_inference_module", return_value=fake_inference), patch.object(
                model_c, "_output_dir", return_value=Path(directory)
            ):
                with self.assertRaises(model_c.ModelCExecutionError) as caught:
                    model_c.run_model_c(
                        image_path=source,
                        composition="medium",
                        background_style="wood",
                        strength="medium",
                        seed=None,
                        guidance_scale=2.5,
                        num_inference_steps=28,
                        width=832,
                        height=1040,
                    )

            self.assertEqual(caught.exception.code, "CUDA_OUT_OF_MEMORY")
            self.assertEqual(caught.exception.result["error_code"], "CUDA_OUT_OF_MEMORY")


if __name__ == "__main__":
    unittest.main()
