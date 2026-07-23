from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SCENE_IMAGE = "ad_creator_reference_white_closeup_cylindrical_v2.png"
REFERENCE_GEOMETRY_HINT_IMAGE = "white_closeup_reference_cup_saucer_cylindrical_geometry_v2.png"


def build(source_name: str, target_name: str, mode_label: str) -> None:
    workflow = json.loads((ROOT / "workflows" / source_name).read_text(encoding="utf-8"))
    workflow["1"]["inputs"]["image"] = "white_closeup_strawberry_source.jpg"
    workflow["2"]["inputs"]["product_analysis_path"] = "configs/reviewed-product-analysis-white-closeup-strawberry-v1.json"
    workflow["13"]["inputs"]["image"] = (
        REFERENCE_GEOMETRY_HINT_IMAGE
        if mode_label == "reference_cup"
        else REFERENCE_SCENE_IMAGE
    )
    prefix = f"ad_creator/white_closeup/strawberry_{mode_label}_gpt_image_2_medium"
    workflow["10"]["inputs"]["filename_prefix"] = prefix
    workflow["11"]["inputs"]["output_label"] = prefix
    (ROOT / "workflows" / target_name).write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(target_name)


if __name__ == "__main__":
    build(
        "24a_white_closeup_matcha_reference_cup_local_fake_api.json",
        "25a_white_closeup_strawberry_reference_cup_local_fake_api.json",
        "reference_cup",
    )
    build(
        "24a_white_closeup_matcha_reference_cup_higgsfield_api.json",
        "25a_white_closeup_strawberry_reference_cup_higgsfield_api.json",
        "reference_cup",
    )
    build(
        "24b_white_closeup_matcha_source_cup_local_fake_api.json",
        "25b_white_closeup_strawberry_source_cup_local_fake_api.json",
        "source_cup",
    )
    build(
        "24b_white_closeup_matcha_source_cup_higgsfield_api.json",
        "25b_white_closeup_strawberry_source_cup_higgsfield_api.json",
        "source_cup",
    )
