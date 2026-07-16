import json
import os
import tempfile
from pathlib import Path

from PIL import Image

from ..adapters import model_c as model_c_adapter


def _tensor_to_pil(image) -> Image.Image:
    if getattr(image, "ndim", None) == 3:
        image = image.unsqueeze(0)
    if getattr(image, "ndim", None) != 4 or image.shape[0] != 1:
        raise ValueError("model-c-v1 accepts exactly one ComfyUI IMAGE at a time.")

    array = image[0].detach().cpu().clamp(0, 1).numpy()
    if array.shape[-1] not in (1, 3, 4):
        raise ValueError(f"Unsupported image channel count: {array.shape[-1]}")
    array = (array * 255.0).round().astype("uint8")
    if array.shape[-1] == 1:
        array = array[..., 0]
    return Image.fromarray(array).convert("RGB")


def _pil_to_tensor(image: Image.Image):
    import numpy as np
    import torch

    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


class AdCreatorModelCGenerate:
    DESCRIPTION = "Runs the existing model-c NF4 pipeline without modifying its implementation."
    CATEGORY = "Ad Creator"
    FUNCTION = "generate"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "metadata_json")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "composition": (["closeup", "medium", "aerial", "handheld"], {"default": "medium"}),
                "background_style": (["vivid", "wood", "white"], {"default": "wood"}),
                "strength": (["low", "medium", "high"], {"default": "medium"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "guidance_scale": ("FLOAT", {"default": 2.5, "min": 0.0, "max": 20.0, "step": 0.1}),
                "num_inference_steps": ("INT", {"default": 28, "min": 1, "max": 100}),
                "width": ("INT", {"default": 832, "min": 256, "max": 2048, "step": 16}),
                "height": ("INT", {"default": 1040, "min": 256, "max": 2048, "step": 16}),
            }
        }

    def generate(
        self,
        image,
        composition,
        background_style,
        strength,
        seed,
        guidance_scale,
        num_inference_steps,
        width,
        height,
    ):
        input_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix="ad_creator_", suffix=".png", delete=False) as tmp:
                input_path = Path(tmp.name)
            _tensor_to_pil(image).save(input_path, format="PNG")

            result = model_c_adapter.run_model_c(
                image_path=input_path,
                composition=composition,
                background_style=background_style,
                strength=strength,
                seed=None if seed < 0 else int(seed),
                guidance_scale=float(guidance_scale),
                num_inference_steps=int(num_inference_steps),
                width=int(width),
                height=int(height),
            )
            output_path = Path(str(result["output_path"])).resolve()
            try:
                with Image.open(output_path) as generated:
                    output_image = _pil_to_tensor(generated)
            finally:
                try:
                    output_path.unlink()
                except FileNotFoundError:
                    pass

            result["output_path"] = None
            result["output_storage"] = "comfyui_save_image"
            metadata_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
            return (output_image, metadata_json)
        finally:
            if input_path is not None:
                try:
                    os.unlink(input_path)
                except OSError:
                    pass
