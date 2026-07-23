from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ad_creator.jsonio import load_json, validate_json


CONTRACTS = [
    ("presets/editorial/instagram_white_diffuse_closeup_v1/reference-preset.json", "reference-preset.schema.json"),
    ("presets/editorial/instagram_white_diffuse_closeup_v1/photographic-style-contract.json", "photographic-style-contract.schema.json"),
    ("presets/moods/instagram_white_diffuse_closeup_v1/mood-package.json", "mood-package.schema.json"),
    ("presets/moods/instagram_white_diffuse_closeup_v1/lighting-sheet.json", "lighting-sheet.schema.json"),
    ("presets/moods/instagram_white_diffuse_closeup_v1/scene-recipe.json", "scene-recipe.schema.json"),
    ("presets/moods/instagram_white_diffuse_closeup_v1/grade-profile.json", "grade-profile.schema.json"),
    ("data/reference-library/scene-graphs-v2/ref_white_closeup_v1.json", "reference-scene-graph.schema.json"),
    ("presets/container_designs/white_closeup_short_glass_saucer_v1.json", "container-design.schema.json"),
]


def main() -> None:
    for relative, schema in CONTRACTS:
        validate_json(load_json(ROOT / relative), schema, project_root=ROOT)
        print("PASS", relative)

    workflow_paths = (
        "workflows/24a_white_closeup_matcha_reference_cup_local_fake_api.json",
        "workflows/24a_white_closeup_matcha_reference_cup_higgsfield_api.json",
        "workflows/24c_white_closeup_matcha_user_reference_cup_local_fake_api.json",
        "workflows/24c_white_closeup_matcha_user_reference_cup_higgsfield_api.json",
        "workflows/24b_white_closeup_matcha_source_cup_local_fake_api.json",
        "workflows/24b_white_closeup_matcha_source_cup_higgsfield_api.json",
        "workflows/25a_white_closeup_strawberry_reference_cup_local_fake_api.json",
        "workflows/25a_white_closeup_strawberry_reference_cup_higgsfield_api.json",
        "workflows/25b_white_closeup_strawberry_source_cup_local_fake_api.json",
        "workflows/25b_white_closeup_strawberry_source_cup_higgsfield_api.json",
    )
    for relative in workflow_paths:
        workflow = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        request = workflow["6"]["inputs"]
        expected_mode = "adopt_reference" if "reference_cup" in relative else "preserve_source"
        expected_hint = (
            "white_closeup_scene_cup_hint_v1.png"
            if expected_mode == "adopt_reference"
            else "ad_creator_reference_white_closeup_cylindrical_v2.png"
        )
        assert request["container_mode"] == expected_mode
        assert request["reference_control_role"] == "sanitized_scene_hint"
        assert request["auto_paid_repair"] is False
        assert request["scene_graph_json"] == ["4", 2]
        assert workflow["13"]["inputs"]["image"] == expected_hint
        assert workflow["1"]["inputs"]["image"] != workflow["13"]["inputs"]["image"]
        assert workflow["9"]["inputs"]["protection_mask"] == ["14", 0]
        print("PASS", relative)

    assert (ROOT / "comfyui-inputs/ad_creator_reference_white_closeup_cylindrical_v2.png").is_file()
    assert (ROOT / "comfyui-inputs/white_closeup_reference_cup_saucer_cylindrical_geometry_v2.png").is_file()
    assert (ROOT / "comfyui-inputs/white_closeup_scene_cup_hint_v1.png").is_file()

    source = (ROOT / "src/ad_creator/prompting.py").read_text(encoding="utf-8")
    source_folded = source.casefold()
    ast.parse(source)
    for required in (
        "White close-up requires a distinct scene/light anchor",
        "complete saucer and teaspoon",
        "cup-to-saucer",
        "WHITE_CLOSEUP_REFERENCE_ASSEMBLY",
        "WHITE_CLOSEUP_USER_CUP",
        "REFERENCE CUP SILHOUETTE - ADOPT MODE HARD LOCK",
        "dedicated high-detail geometry evidence crop",
        "not an output crop",
        "RELATIONAL BEVERAGE COLOR",
    ):
        assert required.casefold() in source_folded
    for forbidden in (
        "source_has_saucer",
        "source_has_spoon",
    ):
        assert forbidden not in source

    container = load_json(ROOT / "presets/container_designs/white_closeup_short_glass_saucer_v1.json")
    components = " ".join(container["design"]["components"]).lower()
    assert "saucer" in components
    assert "teaspoon" in components
    assert "constant outside diameter" in components
    assert container["design"]["height_to_width_ratio"] == [0.95, 1.05]
    assert "inward shoulder" not in container["design"]["geometry"].lower()
    grade = load_json(ROOT / "presets/moods/instagram_white_diffuse_closeup_v1/grade-profile.json")
    assert grade["targeted_relight"]["policy_id"] == "bright_low_chroma_relight_v2"
    assert grade["targeted_relight"]["scope"] == "protection_mask"
    assert grade["targeted_relight"]["reflected_tint_rgb"] == [0.9, 0.9, 0.84]
    assert grade["targeted_relight"]["reflected_tint_strength"] == 0.07

    reference = load_json(ROOT / "presets/editorial/instagram_white_diffuse_closeup_v1/reference-preset.json")
    assert reference["sampling_ranges"]["subject_width_ratio"] == [0.46, 0.52]
    assert reference["sampling_ranges"]["subject_height_ratio"] == [0.5, 0.6]
    assert reference["sampling_ranges"]["negative_space_ratio"] == [0.42, 0.5]

    scene_graph = load_json(ROOT / "data/reference-library/scene-graphs-v2/ref_white_closeup_v1.json")
    primary = scene_graph["objects"][0]
    assert primary["full_bbox"] == {
        "left": 0.26,
        "top": 0.25,
        "right": 0.76,
        "bottom": 0.83,
        "confidence": 0.96,
    }
    print("PASS restrained serving scale, bright low-chroma relight, relational beverage color and distinct-input guard")


if __name__ == "__main__":
    main()
