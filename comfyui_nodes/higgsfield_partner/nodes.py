from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from io import BytesIO
from pathlib import Path

import folder_paths
import certifi
import numpy as np
import torch
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
CUSTOM_NODES_DIR = ROOT / "comfyui" / "custom_nodes"
if str(CUSTOM_NODES_DIR) not in sys.path:
    sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.runtime import execute_product_transforms, resolve_preset_contract


MODEL_CONFIG = {
    "GPT Image 2": ("gpt_image_2", ["--quality", "medium"]),
    "Seedream 5.0 Pro": ("seedream_v5_pro", []),
    "Nano Banana 2": ("nano_banana_flash", []),
    "FLUX.2 Max": ("flux_2", ["--variant", "max"]),
}


def _verified_ssl_context() -> ssl.SSLContext:
    """Build a verified context independent of the host Python CA install."""
    return ssl.create_default_context(cafile=certifi.where())


def _higgsfield_cli_command() -> list[str]:
    configured = os.environ.get("HIGGSFIELD_CLI_BIN", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend(
        sorted(
            (Path.home() / "Library/pnpm/store/v11/links/@higgsfield/cli").glob(
                "*/*/node_modules/@higgsfield/cli/vendor/hf"
            ),
            reverse=True,
        )
    )
    candidates.append(
        Path.home()
        / "AppData/Roaming/npm/node_modules/@higgsfield/cli/bin/higgsfield.js"
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.suffix == ".js":
            node = shutil.which("node")
            if node:
                return [node, str(candidate)]
            continue
        if os.access(candidate, os.X_OK):
            return [str(candidate)]
    executable = shutil.which("higgsfield") or shutil.which("hf")
    if executable:
        return [executable]
    raise FileNotFoundError(
        "Higgsfield CLI runtime not found. Install @higgsfield/cli or set HIGGSFIELD_CLI_BIN."
    )


def _runtime_preset_slots() -> list[str]:
    registry = json.loads(
        (ROOT / "comfyui/presets/registry.json").read_text(encoding="utf-8")
    )
    return [
        slot_id
        for slot_id, item in registry["slots"].items()
        if item.get("enabled") and item.get("status") in {"published", "validated"}
    ]


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

        cli_command = _higgsfield_cli_command()

        job_type, extra_args = MODEL_CONFIG[model]
        reference_paths = self._write_references(
            image,
            image_reference_2,
            image_reference_3,
            image_reference_4,
        )
        if len(reference_paths) > 4:
            for reference_path in reference_paths:
                reference_path.unlink(missing_ok=True)
            raise ValueError("Higgsfield requests may contain at most four image references.")
        reference_args = [
            argument
            for reference_path in reference_paths
            for argument in ("--image-references", str(reference_path))
        ]
        try:
            created = self._run_json(
                [
                    *cli_command,
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
                    *cli_command,
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
            with urllib.request.urlopen(
                result_url,
                timeout=120,
                context=_verified_ssl_context(),
            ) as response:
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


class HiggsfieldPresetGenerate:
    """Compile preset JSON through the shared runtime, then call Higgsfield."""

    @classmethod
    def INPUT_TYPES(cls):
        slots = _runtime_preset_slots()
        registry = json.loads(
            (ROOT / "comfyui/presets/registry.json").read_text(encoding="utf-8")
        )
        default = registry.get("default_preset_slot")
        return {
            "required": {
                "image": ("IMAGE",),
                "preset_id": (slots, {"default": default if default in slots else slots[0]}),
                "container_mode": (
                    ["default", "adopt_reference", "reconstruct_source"],
                    {"default": "default"},
                ),
                "serving_temperature": (
                    ["auto", "iced", "cold", "ambient", "hot"],
                    {"default": "auto"},
                ),
                "model": (list(MODEL_CONFIG), {"default": "GPT Image 2"}),
                "resolution": (["1k", "2k"], {"default": "1k"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "job_metadata")
    FUNCTION = "generate"
    CATEGORY = "api/Higgsfield"

    def generate(
        self,
        image: torch.Tensor,
        preset_id: str,
        container_mode: str,
        serving_temperature: str,
        model: str,
        resolution: str,
    ):
        if image.ndim != 4 or image.shape[0] != 1:
            raise ValueError("Preset execution requires exactly one user-product image.")
        contract = resolve_preset_contract(
            preset_id,
            aspect_ratio="4:5",
            container_mode=container_mode,
            serving_temperature=serving_temperature,
            registry_path=ROOT / "comfyui/presets/registry.json",
            allowed_statuses=("published", "validated"),
        )
        source_path = HiggsfieldImageGenerate._write_reference_frame(image[0])
        try:
            with execute_product_transforms(
                source_path,
                contract.declared_transforms,
            ) as (transformed_source, transform_audit):
                references = [self._path_tensor(transformed_source)]
                for path in contract.provider_image_paths:
                    references.append(self._path_tensor(path))
                if len(references) > 4:
                    raise ValueError("Resolved preset exceeds the four-image input cap.")
                prompt = contract.prompt + (
                    "\n\n[HIGGSFIELD VISUAL-SMOKE CANVAS ADAPTATION]\n"
                    "The provider canvas is native 3:4 because this Higgsfield model does not expose "
                    "4:5. Recompose without cropping any required product, support or companion. This "
                    "output is visual-smoke evidence only and not exact 4:5 geometry validation."
                )
                if len(prompt) > 12_000:
                    raise ValueError(
                        f"Provider-adapted prompt exceeds 12,000 characters: {len(prompt)}"
                    )
                result, metadata_json = HiggsfieldImageGenerate().generate(
                    prompt=prompt,
                    model=model,
                    image=references[0],
                    aspect_ratio="3:4",
                    resolution=resolution,
                    image_reference_2=references[1] if len(references) > 1 else None,
                    image_reference_3=references[2] if len(references) > 2 else None,
                    image_reference_4=references[3] if len(references) > 3 else None,
                )
        finally:
            source_path.unlink(missing_ok=True)
        metadata = json.loads(metadata_json)
        metadata.update(
            {
                "preset_slot_id": contract.slot_id,
                "preset_id": contract.preset_id,
                "preset_status": contract.status,
                "compiler_version": contract.compiler_version,
                "container_mode": contract.container_mode,
                "serving_temperature": contract.serving_temperature,
                "brand_input_enabled": contract.brand_input_enabled,
                "brand_default_mode": contract.brand_default_mode,
                "brand_policy_sha256": contract.brand_policy_sha256,
                "companion_policy": contract.companion_policy,
                "base_prompt_sha256": contract.prompt_sha256,
                "declared_transform_audit": transform_audit,
                "validation_class": "higgsfield_3x4_visual_smoke_not_publishable_4x5_qa",
            }
        )
        return result, json.dumps(metadata, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _path_tensor(path: Path) -> torch.Tensor:
        with Image.open(path) as opened:
            array = np.asarray(opened.convert("RGB"), dtype=np.float32) / 255.0
        return torch.from_numpy(array).unsqueeze(0)


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
    "HiggsfieldPresetGenerate": HiggsfieldPresetGenerate,
    "SaveHiggsfieldMetadata": SaveHiggsfieldMetadata,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HiggsfieldImageGenerate": "Higgsfield Image Generate",
    "HiggsfieldPresetGenerate": "Higgsfield Preset Generate",
    "SaveHiggsfieldMetadata": "Save Higgsfield Metadata",
}
