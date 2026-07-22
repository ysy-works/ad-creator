from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

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

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: Response())
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
    assert module.json.loads(metadata_json)["image_reference_count"] == 2
