import json
import os
import tempfile
import uuid
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from ..adapters.openai_image import (
    default_published_preset_slot,
    load_published_preset,
    published_preset_slots,
    run_openai_image,
)


SUPPORTED_ASPECT_RATIOS = ["4:5", "1:1"]
SUPPORTED_CONTAINER_MODES = ["default", "adopt_reference", "reconstruct_source"]
SUPPORTED_SERVING_TEMPERATURES = ["auto", "iced", "cold", "ambient", "hot"]


def _tensor_to_pil(image) -> Image.Image:
    if getattr(image, "ndim", None) == 3:
        image = image.unsqueeze(0)
    if getattr(image, "ndim", None) != 4 or image.shape[0] != 1:
        raise ValueError("OpenAI preset workflow accepts exactly one IMAGE at a time.")
    array = image[0].detach().cpu().clamp(0, 1).numpy()
    if array.shape[-1] not in (1, 3, 4):
        raise ValueError(f"Unsupported image channel count: {array.shape[-1]}")
    array = (array * 255.0).round().astype("uint8")
    if array.shape[-1] == 1:
        array = array[..., 0]
    return Image.fromarray(array).convert("RGB")


def _pil_to_tensor(image: Image.Image):
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _normalized_product_source(image) -> Image.Image:
    """Convert a ComfyUI tensor losslessly; adapter owns metadata stripping and resizing."""
    return _tensor_to_pil(image)


def _audit_directory() -> Path:
    configured = os.environ.get("AD_CREATOR_OPENAI_AUDIT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        import folder_paths
    except ImportError as exc:
        raise ValueError(
            "AD_CREATOR_OPENAI_AUDIT_DIR is required outside a ComfyUI runtime."
        ) from exc
    return Path(folder_paths.get_output_directory()).resolve() / "ad_creator" / "audit"


def _resolved_run_id(request_id: str) -> str:
    value = str(request_id or "").strip()
    return str(uuid.uuid4()) if value in {"", "__AUTO__"} else value


def _timeout_seconds() -> float:
    try:
        value = float(os.environ.get("OPENAI_IMAGE_TIMEOUT_SECONDS", "1200"))
    except ValueError as exc:
        raise ValueError("OPENAI_IMAGE_TIMEOUT_SECONDS must be numeric.") from exc
    if not 30 <= value <= 3600:
        raise ValueError("OPENAI_IMAGE_TIMEOUT_SECONDS must be between 30 and 3600.")
    return value


class AdCreatorOpenAIImageGenerate:
    DESCRIPTION = (
        "Runs a published Ad Creator preset with OpenAI GPT Image 2. "
        "Quality is fixed to low by the checked-in provider profile."
    )
    CATEGORY = "Ad Creator"
    FUNCTION = "generate"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "metadata_json")

    @classmethod
    def INPUT_TYPES(cls):
        preset_slots = list(published_preset_slots())
        for preset_slot in preset_slots:
            load_published_preset(preset_slot)
        return {
            "required": {
                "image": ("IMAGE",),
                "preset_id": (
                    preset_slots,
                    {"default": default_published_preset_slot()},
                ),
                "container_mode": (
                    SUPPORTED_CONTAINER_MODES,
                    {"default": "default"},
                ),
                "serving_temperature": (
                    SUPPORTED_SERVING_TEMPERATURES,
                    {"default": "auto"},
                ),
                "aspect_ratio": (SUPPORTED_ASPECT_RATIOS, {"default": "4:5"}),
                "request_id": (
                    "STRING",
                    {"default": "__AUTO__", "multiline": False},
                ),
            }
        }

    @classmethod
    def IS_CHANGED(
        cls,
        image,
        preset_id,
        container_mode,
        serving_temperature,
        aspect_ratio,
        request_id,
    ):
        # A new queued user action is an explicit new paid generation. Gateway
        # idempotency prevents network retries from creating a second prompt.
        return float("nan")

    def generate(
        self,
        image,
        preset_id,
        container_mode,
        serving_temperature,
        aspect_ratio,
        request_id,
    ):
        input_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="ad_creator_openai_", suffix=".png", delete=False
            ) as temporary:
                input_path = Path(temporary.name)
            _normalized_product_source(image).save(
                input_path,
                format="PNG",
                optimize=True,
            )
            generated, metadata = run_openai_image(
                image_path=input_path,
                preset_slot_id=preset_id,
                container_mode=container_mode,
                serving_temperature=serving_temperature,
                aspect_ratio=aspect_ratio,
                timeout_seconds=_timeout_seconds(),
                run_id=_resolved_run_id(request_id),
                audit_dir=_audit_directory(),
            )
            return (
                _pil_to_tensor(generated),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            )
        finally:
            if input_path is not None:
                try:
                    os.unlink(input_path)
                except OSError:
                    pass
