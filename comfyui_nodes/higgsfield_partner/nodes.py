from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import urllib.request
from io import BytesIO
from pathlib import Path

import folder_paths
import numpy as np
import torch
from PIL import Image


MODEL_CONFIG = {
    "GPT Image 2": ("gpt_image_2", ["--quality", "medium"]),
    "Seedream 5.0 Pro": ("seedream_v5_pro", []),
    "Nano Banana 2": ("nano_banana_flash", []),
    "FLUX.2 Max": ("flux_2", ["--variant", "max"]),
}


class HiggsfieldImageGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (list(MODEL_CONFIG), {"default": "GPT Image 2"}),
                "image": ("IMAGE",),
                "aspect_ratio": (["3:4", "1:1", "4:3", "9:16", "16:9"], {"default": "3:4"}),
                "resolution": (["2k", "1k"], {"default": "2k"}),
            },
            "optional": {
                "image_reference_2": ("IMAGE",),
                "image_reference_3": ("IMAGE",),
                "image_reference_4": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "job_metadata")
    FUNCTION = "generate"
    CATEGORY = "api/Higgsfield"

    def generate(
        self,
        prompt: str,
        model: str,
        image: torch.Tensor,
        aspect_ratio: str,
        resolution: str,
        image_reference_2: torch.Tensor | None = None,
        image_reference_3: torch.Tensor | None = None,
        image_reference_4: torch.Tensor | None = None,
    ):
        if not prompt.strip():
            raise ValueError("prompt must not be empty")

        node = shutil.which("node")
        cli = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@higgsfield" / "cli" / "bin" / "higgsfield.js"
        if not node or not cli.is_file():
            raise FileNotFoundError(f"Higgsfield CLI runtime not found: node={node!r}, cli={cli}")

        job_type, extra_args = MODEL_CONFIG[model]
        reference_paths = self._write_references(
            image,
            image_reference_2,
            image_reference_3,
            image_reference_4,
        )
        reference_args = [
            argument
            for reference_path in reference_paths
            for argument in ("--image-references", str(reference_path))
        ]
        try:
            created = self._run_json(
                [
                    node,
                    str(cli),
                    "generate",
                    "create",
                    job_type,
                    "--prompt",
                    prompt,
                    *reference_args,
                    "--resolution",
                    resolution,
                    "--aspect-ratio",
                    aspect_ratio,
                    *extra_args,
                    "--json",
                ]
            )
            job_id = created[0] if isinstance(created, list) else created.get("id")
            if not job_id:
                raise RuntimeError(f"Higgsfield create returned no job id: {created!r}")

            completed = self._run_json(
                [
                    node,
                    str(cli),
                    "generate",
                    "wait",
                    str(job_id),
                    "--timeout",
                    "15m",
                    "--interval",
                    "5s",
                    "--json",
                ],
                timeout=960,
            )
            if completed.get("status") != "completed":
                raise RuntimeError(f"Higgsfield job did not complete: {completed!r}")

            result_url = completed.get("result_url")
            if not result_url:
                raise RuntimeError(f"Higgsfield job returned no result_url: {completed!r}")
            with urllib.request.urlopen(result_url, timeout=120) as response:
                output = Image.open(BytesIO(response.read())).convert("RGB")
            array = np.asarray(output).astype(np.float32) / 255.0
            tensor = torch.from_numpy(array).unsqueeze(0)
            metadata = {
                "display_model": model,
                "job_type": job_type,
                "job_id": job_id,
                "result_url": result_url,
                "quality": "medium" if model == "GPT Image 2" else None,
                "resolution": completed.get("params", {}).get("resolution", resolution),
                "width": completed.get("params", {}).get("width", output.width),
                "height": completed.get("params", {}).get("height", output.height),
                "image_reference_count": len(reference_paths),
            }
            return tensor, json.dumps(metadata, ensure_ascii=False)
        finally:
            for reference_path in reference_paths:
                reference_path.unlink(missing_ok=True)

    @classmethod
    def _write_references(cls, *images: torch.Tensor | None) -> list[Path]:
        paths = []
        for image in images:
            if image is None:
                continue
            for frame in image:
                paths.append(cls._write_reference_frame(frame))
        return paths

    @staticmethod
    def _write_reference_frame(frame: torch.Tensor) -> Path:
        array = np.clip(frame.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
        handle = tempfile.NamedTemporaryFile(prefix="comfy_higgsfield_", suffix=".png", delete=False)
        handle.close()
        path = Path(handle.name)
        Image.fromarray(array, mode="RGB").save(path)
        return path

    @staticmethod
    def _run_json(command: list[str], timeout: int = 120) -> dict | list:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return json.loads(completed.stdout)


class SaveHiggsfieldMetadata:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "metadata": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "higgsfield/job"}),
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "api/Higgsfield"

    def save(self, metadata: str, filename_prefix: str):
        relative = Path(filename_prefix.strip().replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("filename_prefix must stay inside the ComfyUI output directory")
        target = Path(folder_paths.get_output_directory()) / relative
        target = target.with_suffix(".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        parsed = json.loads(metadata)
        target.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ui": {"text": [str(target)]}}


NODE_CLASS_MAPPINGS = {
    "HiggsfieldImageGenerate": HiggsfieldImageGenerate,
    "SaveHiggsfieldMetadata": SaveHiggsfieldMetadata,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HiggsfieldImageGenerate": "Higgsfield Image Generate",
    "SaveHiggsfieldMetadata": "Save Higgsfield Metadata",
}
