from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
COMFYUI_ROOT = Path(
    os.environ.get("COMFYUI_ROOT", Path.home() / "Documents" / "ComfyUI")
).resolve()
sys.path.insert(0, str(COMFYUI_ROOT))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from ad_creator.jsonio import load_json, validate_json  # noqa: E402
from comfy_nodes.ad_creator.nodes import (  # noqa: E402
    _beverage_surface_evidence_crop,
)


CASES = [
    (
        "matcha",
        ROOT / "example/inputs/01-product-source.png",
        ROOT
        / "outputs/analysis-cache/product/99/2b480703107391c481959baf61bf80cb39459e2f3deff8d5b07f44f19ad37e75.json",
    ),
    (
        "strawberry",
        ROOT / "example/white-basic-openai/inputs/white_basic_product_source.jpg",
        ROOT
        / "outputs/analysis-cache/product/3e/c0ba2986ff4c0074775ca4318f3bda347cc81233479b0d4a6af00c3e08a5b507.json",
    ),
]


def _tensor(path: Path) -> torch.Tensor:
    array = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def main() -> None:
    schema_pairs = [
        (
            "presets/editorial/instagram_white_neutral_overhead_spatial_v1/reference-preset.json",
            "reference-preset.schema.json",
        ),
        (
            "presets/editorial/instagram_white_neutral_overhead_spatial_v1/photographic-style-contract.json",
            "photographic-style-contract.schema.json",
        ),
        (
            "presets/moods/instagram_white_neutral_overhead_spatial_v1/scene-recipe.json",
            "scene-recipe.schema.json",
        ),
        (
            "presets/moods/instagram_white_neutral_overhead_spatial_v1/lighting-sheet.json",
            "lighting-sheet.schema.json",
        ),
        (
            "presets/container_designs/white_ceramic_mug_visible_handle_overhead_v1.json",
            "container-design.schema.json",
        ),
    ]
    for relative_path, schema_name in schema_pairs:
        validate_json(load_json(ROOT / relative_path), schema_name, project_root=ROOT)

    crop_results = []
    for name, image_path, analysis_path in CASES:
        source = _tensor(image_path)
        analysis = load_json(analysis_path)
        crop, bbox = _beverage_surface_evidence_crop(source, analysis)
        if crop.shape[1] >= source.shape[1]:
            raise AssertionError(f"{name}: crop did not remove lower sidewall evidence")
        if crop.shape[1] < 32 or crop.shape[2] < 32:
            raise AssertionError(f"{name}: crop is too small for provider evidence")
        if bbox["bottom"] > 0.5:
            raise AssertionError(f"{name}: crop retains too much lower-container evidence")
        crop_results.append(
            {
                "case": name,
                "source_width": int(source.shape[2]),
                "source_height": int(source.shape[1]),
                "crop_width": int(crop.shape[2]),
                "crop_height": int(crop.shape[1]),
                "crop_bbox_normalized": bbox,
            }
        )

    print(
        json.dumps(
            {
                "status": "passed",
                "schemas_validated": len(schema_pairs),
                "crop_cases": crop_results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
