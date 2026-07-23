import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from comfyui.orchestrator import (
    UnknownWorkflowError,
    WorkflowRouterError,
    build_prompt,
    submit_prompt,
    workflow_input_names,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return b'{"prompt_id":"prompt-123","number":1}'


class WorkflowRouterTest(unittest.TestCase):
    def test_openai_workflow_applies_preset(self):
        resolved = build_prompt(
            workflow_id="openai-gpt-image-2-low-v1",
            values={
                "source_image": "uploads/request.png",
                "preset_id": "wood__product_center",
                "aspect_ratio": "1:1",
                "request_id": "job-123",
            }
        )
        self.assertEqual(resolved["workflow_id"], "openai-gpt-image-2-low-v1")
        self.assertEqual(resolved["prompt"]["1"]["inputs"], {"image": "uploads/request.png"})
        self.assertEqual(
            resolved["prompt"]["2"]["inputs"]["preset_id"], "wood__product_center"
        )
        self.assertEqual(resolved["prompt"]["2"]["inputs"]["request_id"], "job-123")
        self.assertEqual(resolved["prompt"]["2"]["inputs"]["aspect_ratio"], "1:1")

    def test_default_model_c_workflow_remains_available_for_rollback(self):
        resolved = build_prompt(
            values={
                "source_image": "uploads/request.png",
                "composition": "aerial",
                "background_style": "white",
                "strength": "low",
                "seed": 42,
            }
        )
        self.assertEqual(resolved["workflow_id"], "model-c-v1")
        self.assertEqual(resolved["prompt"]["1"]["inputs"], {"image": "uploads/request.png"})
        self.assertEqual(resolved["prompt"]["2"]["inputs"]["composition"], "aerial")
        self.assertEqual(resolved["prompt"]["2"]["inputs"]["seed"], 42)

    def test_rejects_unknown_workflow(self):
        with self.assertRaises(UnknownWorkflowError):
            build_prompt(workflow_id="missing-v1", values={"source_image": "request.png"})

    def test_requires_uploaded_source_filename(self):
        with self.assertRaises(WorkflowRouterError):
            build_prompt(values={})

    def test_openai_workflow_requires_explicit_preset(self):
        with self.assertRaisesRegex(WorkflowRouterError, "preset_id"):
            build_prompt(
                workflow_id="openai-gpt-image-2-low-v1",
                values={"source_image": "request.png", "request_id": "job-123"},
            )

    def test_rejects_unregistered_input(self):
        with self.assertRaises(WorkflowRouterError):
            build_prompt(values={"source_image": "request.png", "prompt": "ignored"})

    def test_submits_resolved_prompt_to_comfyui(self):
        resolved = build_prompt(
            workflow_id="openai-gpt-image-2-low-v1",
            values={
                "source_image": "request.png",
                "preset_id": "natural_white__product_center",
                "aspect_ratio": "4:5",
                "request_id": "job-123",
            }
        )
        with patch("comfyui.orchestrator.workflow_router.urllib.request.urlopen", return_value=_Response()) as urlopen:
            result = submit_prompt(
                server_url="http://127.0.0.1:8188/",
                resolved_workflow=resolved,
                client_id="backend-test",
            )

        self.assertEqual(result["prompt_id"], "prompt-123")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8188/prompt")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["client_id"], "backend-test")
        self.assertIn("prompt", payload)

    def test_reports_workflow_input_names(self):
        self.assertEqual(
            workflow_input_names(workflow_id="openai-gpt-image-2-low-v1"),
            {
                "source_image",
                "preset_id",
                "container_mode",
                "serving_temperature",
                "aspect_ratio",
                "request_id",
            },
        )


if __name__ == "__main__":
    unittest.main()
