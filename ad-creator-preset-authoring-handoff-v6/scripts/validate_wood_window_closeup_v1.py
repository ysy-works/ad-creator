#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ad_creator.jsonio import load_json, validate_json


ASSET_ID = "ref_95fa7947818ce496"
PIXEL_SHA256 = "fdcf3f83e673d7ed06cecb376eb7b94386bb2c1657f942136017aeeadc919523"
FILE_SHA256 = "4e17067c6696a71699e989bfc0fcb47d096a9626441698bec4b773904efd73c7"
PRESET_ID = "instagram_wood_calm_window_closeup_v1"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixel_sha256(path: Path) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"RGB:{image.width}x{image.height}:".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def assert_equal(observed: Any, expected: Any, label: str) -> None:
    if observed != expected:
        raise AssertionError(f"{label}: expected {expected!r}, observed {observed!r}")


def validate_contracts() -> list[str]:
    contracts = [
        (f"presets/editorial/{PRESET_ID}/reference-preset.json", "reference-preset.schema.json"),
        (f"presets/editorial/{PRESET_ID}/photographic-style-contract.json", "photographic-style-contract.schema.json"),
        (f"presets/moods/{PRESET_ID}/mood-package.json", "mood-package.schema.json"),
        (f"presets/moods/{PRESET_ID}/lighting-sheet.json", "lighting-sheet.schema.json"),
        (f"presets/moods/{PRESET_ID}/scene-recipe.json", "scene-recipe.schema.json"),
        (f"presets/moods/{PRESET_ID}/grade-profile.json", "grade-profile.schema.json"),
        ("data/reference-library/scene-graphs-v2/ref_95fa7947818ce496_wood_window_closeup_v1.json", "reference-scene-graph.schema.json"),
        ("data/reference-library/materials/wood_window_closeup_live_edge_v1.json", "wood-material-profile.schema.json"),
        ("presets/container_designs/wood_clear_plastic_cup_open_rim_v1.json", "container-design.schema.json"),
    ]
    passed: list[str] = []
    for relative_path, schema_name in contracts:
        payload = load_json(ROOT / relative_path)
        validate_json(payload, schema_name, project_root=ROOT)
        passed.append(relative_path)
    return passed


def validate_reference_binding() -> list[str]:
    runtime_reference = ROOT / "comfyui-inputs/ad_creator_reference_wood_window_closeup_v1.png"
    assert_equal(file_sha256(runtime_reference), FILE_SHA256, "runtime reference file sha256")
    assert_equal(pixel_sha256(runtime_reference), PIXEL_SHA256, "runtime reference pixel sha256")

    graph_path = ROOT / "data/reference-library/scene-graphs-v2/ref_95fa7947818ce496_wood_window_closeup_v1.json"
    graph = load_json(graph_path)
    assert_equal(graph["asset"]["asset_id"], ASSET_ID, "scene graph asset id")
    assert_equal(graph["asset"]["pixel_sha256"], PIXEL_SHA256, "scene graph pixel sha256")
    assert_equal(graph["runtime_policy"]["scene_pixels_allowed"], False, "raw scene pixel policy")
    assert_equal(graph["runtime_policy"]["maximum_exact_products"], 1, "maximum exact products")
    replaceable = [item for item in graph["objects"] if item["replaceable"]]
    assert_equal([item["slot_id"] for item in replaceable], ["beverage_primary"], "replaceable slots")

    database_path = ROOT / "data/reference-library/catalog.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM reference_assets WHERE asset_id = ?", (ASSET_ID,)
        ).fetchone()
    if row is None:
        raise AssertionError("catalog row is missing")
    assert_equal(row["relative_path"], "comfyui-inputs/ad_creator_reference_wood_window_closeup_v1.png", "catalog relative path")
    assert_equal(row["pixel_sha256"], PIXEL_SHA256, "catalog pixel sha256")
    assert_equal(row["analysis_status"], "analyzed", "catalog analysis status")

    assignments = load_json(ROOT / "data/reference-library/assignments.json")
    assignment = assignments["assignments"].get(ASSET_ID)
    if assignment is None:
        raise AssertionError("reference assignment is missing")
    assert_equal(assignment["mood_package_path"], f"presets/moods/{PRESET_ID}/mood-package.json", "assignment mood path")
    return ["runtime_reference", "scene_graph_binding", "catalog_row", "assignment"]


def validate_control_board() -> list[str]:
    image_path = ROOT / "data/reference-library/control-boards/wood-closeup-shot-v3/reference-4x5-close.png"
    manifest_path = ROOT / "data/reference-library/control-boards/wood-closeup-shot-v3/reference-4x5-manifest.json"
    manifest = load_json(manifest_path)
    with Image.open(image_path) as opened:
        assert_equal(opened.size, (manifest["width_px"], manifest["height_px"]), "scene hint dimensions")
        if abs((opened.width / opened.height) - 0.8) > 0.001:
            raise AssertionError(f"scene hint must be 4:5, observed {opened.width}x{opened.height}")
    assert_equal(manifest["pixel_sha256"], pixel_sha256(image_path), "scene hint pixel sha256")
    assert_equal(manifest["sha256"], file_sha256(image_path), "scene hint file sha256")
    assert_equal(manifest["source_binding"]["pixel_sha256"], PIXEL_SHA256, "scene hint source binding")
    assert_equal(manifest["sanitation"]["raw_reference_provider_submission_allowed"], True, "controlled provider submission")
    assert_equal(manifest["sanitation"]["visible_labels"], True, "authorized visible label policy")
    assert_equal(manifest["checks"][1]["evidence"]["exact_text"], "CAFE AMERICANO", "authorized companion text")
    assert_equal(manifest["pixel_sha256"] == PIXEL_SHA256, False, "scene hint differs from raw reference")
    assert_equal({check["status"] for check in manifest["checks"]}, {"pass"}, "scene hint checks")
    return ["scene_hint_4x5_dimensions", "scene_hint_hashes", "scene_hint_authorized_text_and_support"]


def validate_workflows() -> list[str]:
    workflow_paths = {
        "fake": ROOT / "workflows/22_wood_window_closeup_preserve_source_local_fake_api.json",
        "paid": ROOT / "workflows/22_wood_window_closeup_preserve_source_openai_api.json",
        "gui": ROOT / "workflows/22_wood_window_closeup_preserve_source_openai.json",
    }
    fake = load_json(workflow_paths["fake"])
    paid = load_json(workflow_paths["paid"])
    gui = load_json(workflow_paths["gui"])

    for label, workflow in (("fake", fake), ("paid", paid)):
        request = workflow["6"]["inputs"]
        assert_equal(request["container_mode"], "preserve_source", f"{label} container mode")
        assert_equal(request["container_design_source"], "source", f"{label} container design source")
        assert_equal(request["reference_control_role"], "sanitized_scene_hint", f"{label} reference role")
        assert_equal(request["target_slot_id"], "beverage_primary", f"{label} target slot")
        assert_equal(request["auto_paid_repair"], False, f"{label} automatic paid repair")
        assert_equal(workflow["3"]["inputs"]["image"], "ad_creator_reference_wood_window_closeup_v1.png", f"{label} reference image")

    assert_equal(fake["7"]["class_type"], "AD_FakeGenerate", "fake provider node")
    assert_equal(paid["7"]["class_type"], "AD_OpenAIImageGenerate", "paid provider node")
    assert_equal(paid["7"]["inputs"]["provider_config_path"], "configs/providers/openai-gpt-image-1-mini.json", "paid provider config")
    paid_text = json.dumps(paid, ensure_ascii=False)
    if "AD_HiggsfieldGenerate" in paid_text:
        raise AssertionError("paid OpenAI workflow still contains a Higgsfield generator")

    gui_nodes = {int(node["id"]): node for node in gui["nodes"]}
    assert_equal(gui_nodes[7]["type"], "AD_OpenAIImageGenerate", "GUI provider node")
    assert_equal(gui_nodes[6]["widgets_values"][0], "preserve_source", "GUI container mode")
    assert_equal(gui_nodes[6]["widgets_values"][7], False, "GUI automatic paid repair")
    assert_equal(gui.get("extra", {}).get("paid_execution_authorized"), False, "GUI paid authorization flag")

    higgsfield_paths = {
        "reference_paid": ROOT / "workflows/23a_wood_window_closeup_strawberry_reference_cup_higgsfield_api.json",
        "reference_fake": ROOT / "workflows/23a_wood_window_closeup_strawberry_reference_cup_local_fake_api.json",
        "source_paid": ROOT / "workflows/23b_wood_window_closeup_strawberry_source_cup_higgsfield_api.json",
        "source_fake": ROOT / "workflows/23b_wood_window_closeup_strawberry_source_cup_local_fake_api.json",
    }
    for label, path in higgsfield_paths.items():
        workflow = load_json(path)
        request = workflow["6"]["inputs"]
        is_reference = label.startswith("reference")
        assert_equal(request["container_mode"], "adopt_reference" if is_reference else "preserve_source", f"{label} container mode")
        assert_equal(request["container_design_source"], "reference" if is_reference else "source", f"{label} container design source")
        assert_equal(request["reference_control_role"], "sanitized_scene_hint", f"{label} reference role")
        assert_equal(request["target_slot_id"], "beverage_primary", f"{label} target slot")
        assert_equal(request["quality_tier"], "default", f"{label} quality tier")
        assert_equal(request["auto_paid_repair"], False, f"{label} automatic paid repair")
        expected_design = "presets/container_designs/wood_clear_plastic_cup_open_rim_v1.json" if is_reference else ""
        assert_equal(request["container_design_path"], expected_design, f"{label} container design")
        assert_equal(request["container_reference"], ["13", 0], f"{label} scene hint connection")
        assert_equal(workflow["14"]["class_type"], "AD_ProductBBoxProtectionMask", f"{label} protection mask node")
        assert_equal(workflow["9"]["inputs"]["protection_mask"], ["14", 0], f"{label} grade protection")
        generator = workflow["7"]
        if label.endswith("paid"):
            assert_equal(generator["class_type"], "AD_HiggsfieldGenerate", f"{label} provider node")
            assert_equal(generator["inputs"]["repair_execution"], "manual", f"{label} repair execution")
            assert_equal(generator["inputs"]["lighting_sheet_json"], ["5", 1], f"{label} lighting sheet connection")
        else:
            assert_equal(generator["class_type"], "AD_FakeGenerate", f"{label} provider node")
            assert_equal(workflow["12"]["class_type"], "AD_FakeQualityRoute", f"{label} fake QA node")

    return [
        *[str(path.relative_to(ROOT)) for path in workflow_paths.values()],
        *[str(path.relative_to(ROOT)) for path in higgsfield_paths.values()],
    ]


def validate_paths() -> list[str]:
    mood = load_json(ROOT / f"presets/moods/{PRESET_ID}/mood-package.json")
    path_keys = [
        "preset_path",
        "runtime_profile_path",
        "scene_recipe_path",
        "lighting_sheet_path",
        "grade_profile_path",
        "photographic_style_contract_path",
        "product_integration_contract_path",
        "reference_control_board_path",
        "reference_control_board_manifest_path",
    ]
    passed: list[str] = []
    for key in path_keys:
        target = ROOT / mood[key]
        if not target.is_file():
            raise AssertionError(f"mood package path does not exist: {key}={mood[key]}")
        passed.append(key)
    return passed


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    report = {
        "preset_id": PRESET_ID,
        "contracts": validate_contracts(),
        "reference_binding": validate_reference_binding(),
        "control_board": validate_control_board(),
        "workflows": validate_workflows(),
        "mood_paths": validate_paths(),
        "paid_generation_executed_by_validation": False,
        "status": "pass",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
