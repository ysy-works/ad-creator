import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


COMFYUI_DIR = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = COMFYUI_DIR / "scripts" / "validate_workflows.py"
SPEC = importlib.util.spec_from_file_location("validate_workflows", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)


class WorkflowRegistryTest(unittest.TestCase):
    def test_default_registry_is_valid(self):
        registry_path = COMFYUI_DIR / "workflows" / "registry.json"
        self.assertEqual(
            VALIDATOR.validate_registry(registry_path),
            ["gpt-image-2-v1", "openai-gpt-image-2-low-v1", "model-c-v1"],
        )

    def test_default_workflow_is_canonical_gpt_image_2(self):
        registry = json.loads((COMFYUI_DIR / "workflows" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["default_workflow_id"], "gpt-image-2-v1")

    def test_registry_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            workflows = root / "workflows"
            workflows.mkdir()
            registry = {
                "schema_version": 1,
                "default_workflow_id": "bad",
                "workflows": {
                    "bad": {
                        "enabled": True,
                        "api_workflow": "../outside.json",
                        "ui_workflow": "../outside.json",
                    }
                },
            }
            registry_path = workflows / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaises(VALIDATOR.WorkflowValidationError):
                VALIDATOR.validate_registry(registry_path)


if __name__ == "__main__":
    unittest.main()
