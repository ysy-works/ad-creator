from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[2]
NODE_PATH = ROOT / "comfyui_nodes" / "higgsfield_partner" / "nodes.py"


def _load_nodes():
    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_output_directory = lambda: str(ROOT / "review")
    sys.modules.setdefault("folder_paths", folder_paths)
    spec = importlib.util.spec_from_file_location("higgsfield_partner_nodes", NODE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_optional_reference_inputs_are_declared():
    module = _load_nodes()

    optional = module.HiggsfieldImageGenerate.INPUT_TYPES()["optional"]

    assert list(optional) == ["image_reference_2", "image_reference_3", "image_reference_4"]


def test_preset_node_uses_registry_and_a6_default():
    module = _load_nodes()

    required = module.HiggsfieldPresetGenerate.INPUT_TYPES()["required"]

    assert required["preset_id"][1]["default"] == "wood__product_center"
    assert "natural_white__aerial_shot" in required["preset_id"][0]
    assert "natural_white__handheld_lifestyle" in required["preset_id"][0]
    assert "wood__product_large" in required["preset_id"][0]
    assert module.NODE_CLASS_MAPPINGS["HiggsfieldPresetGenerate"] is module.HiggsfieldPresetGenerate


def test_write_references_flattens_batches_and_skips_missing_inputs():
    module = _load_nodes()
    node = module.HiggsfieldImageGenerate()
    first_batch = torch.zeros((2, 4, 5, 3), dtype=torch.float32)
    second_batch = torch.ones((1, 4, 5, 3), dtype=torch.float32)

    paths = node._write_references(first_batch, None, second_batch)
    try:
        assert len(paths) == 3
        assert all(path.is_file() for path in paths)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def test_generate_repeats_cli_flag_for_every_reference(monkeypatch):
    module = _load_nodes()
    node = module.HiggsfieldImageGenerate()
    commands = []
    reference_paths = [Path("first.png"), Path("second.png")]

    monkeypatch.setattr(module.shutil, "which", lambda _: "node")
    monkeypatch.setattr(module.Path, "home", classmethod(lambda cls: ROOT))
    cli = ROOT / "AppData" / "Roaming" / "npm" / "node_modules" / "@higgsfield" / "cli" / "bin" / "higgsfield.js"
    monkeypatch.setattr(module.Path, "is_file", lambda self: self == cli)
    monkeypatch.setattr(node, "_write_references", lambda *images: reference_paths)

    def fake_run_json(command, timeout=120):
        commands.append(command)
        if "create" in command:
            return {"id": "job-1"}
        return {
            "status": "completed",
            "result_url": "https://example.invalid/result.png",
            "params": {"resolution": "1k", "width": 1, "height": 1},
        }

    monkeypatch.setattr(node, "_run_json", fake_run_json)
    output = module.Image.new("RGB", (1, 1), "white")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            from io import BytesIO

            buffer = BytesIO()
            output.save(buffer, format="PNG")
            return buffer.getvalue()

    observed_download = {}

    def fake_urlopen(*args, **kwargs):
        observed_download.update(kwargs)
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.Path, "unlink", lambda *args, **kwargs: None)

    _, metadata_json = node.generate(
        "prompt",
        "GPT Image 2",
        torch.zeros((1, 1, 1, 3)),
        "3:4",
        "1k",
        image_reference_2=torch.ones((1, 1, 1, 3)),
    )

    create_command = commands[0]
    indexes = [index for index, value in enumerate(create_command) if value == "--image-references"]
    assert [create_command[index + 1] for index in indexes] == ["first.png", "second.png"]
    assert observed_download["context"].verify_mode == module.ssl.CERT_REQUIRED
    assert observed_download["context"].check_hostname is True
    assert module.json.loads(metadata_json)["image_reference_count"] == 2


def test_preset_node_executes_declared_transforms_and_records_policy(monkeypatch):
    module = _load_nodes()
    observed = {}

    def fake_generate(self, **kwargs):
        observed.update(kwargs)
        return torch.zeros((1, 8, 6, 3), dtype=torch.float32), module.json.dumps(
            {
                "display_model": kwargs["model"],
                "job_id": "job-preset-test",
                "image_reference_count": 2,
            }
        )

    monkeypatch.setattr(module.HiggsfieldImageGenerate, "generate", fake_generate)
    _, metadata_json = module.HiggsfieldPresetGenerate().generate(
        image=torch.zeros((1, 24, 20, 3), dtype=torch.float32),
        preset_id="natural_white__aerial_shot",
        container_mode="adopt_reference",
        serving_temperature="auto",
        model="GPT Image 2",
        resolution="1k",
    )

    metadata = module.json.loads(metadata_json)
    assert observed["image"].shape[0] == 1
    assert observed["image_reference_2"] is not None
    assert metadata["compiler_version"] == "preset-runtime-v1"
    assert metadata["brand_default_mode"] == "none"
    assert metadata["declared_transform_audit"][0]["status"] == "fallback"
    assert metadata["validation_class"].startswith("higgsfield_3x4_visual_smoke")


def test_direct_higgsfield_node_rejects_more_than_four_frames_before_submit(monkeypatch):
    module = _load_nodes()
    node = module.HiggsfieldImageGenerate()
    monkeypatch.setattr(module, "_higgsfield_cli_command", lambda: ["higgsfield"])
    monkeypatch.setattr(
        node,
        "_run_json",
        lambda *args, **kwargs: pytest.fail("provider submission must not run"),
    )

    with pytest.raises(ValueError, match="at most four"):
        node.generate(
            prompt="prompt",
            model="GPT Image 2",
            image=torch.zeros((5, 2, 2, 3), dtype=torch.float32),
            aspect_ratio="3:4",
            resolution="1k",
        )
