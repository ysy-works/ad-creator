from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


COMFYUI_DIR = Path(__file__).resolve().parents[1]
BUNDLE_DIR = COMFYUI_DIR / "presets" / "wood__aerial_shot"
BUNDLE_PATH = BUNDLE_DIR / "preset.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".json", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _asset(binding: dict, label: str) -> Path:
    path = (BUNDLE_DIR / str(binding.get("path") or "")).resolve()
    _require(path.is_file(), f"Missing {label}: {path}")
    _require(_sha256(path) == binding.get("sha256"), f"Hash mismatch: {label}")
    return path


def main() -> int:
    registry = json.loads((COMFYUI_DIR / "presets" / "registry.json").read_text(encoding="utf-8"))
    slot = registry["slots"]["wood__aerial_shot"]
    _require(slot.get("enabled") is False, "Wood overhead must remain disabled before paid visual approval.")
    _require(slot.get("status") == "visual_qa_pending", "Wood overhead review status changed.")
    _require(slot.get("bundle") == "wood__aerial_shot/preset.json", "Wood overhead bundle path changed.")

    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    _require(bundle.get("preset_id") == "instagram_wood_cane_brownie_overhead_v1", "Preset ID mismatch.")
    _require(bundle.get("status") == "visual_qa_pending", "Bundle must remain pending visual QA.")
    _asset(bundle["prompt_template"], "default prompt")
    _asset(bundle["lighting_sheet"], "lighting sheet")
    _asset(bundle["grade_profile"], "grade profile")
    for label, binding in bundle["contract_assets"].items():
        _asset(binding, label)
    preserve_prompt = bundle["container_modes"]["preserve_source"]["prompt_template"]
    preserve_path = _asset(preserve_prompt, "preserve-source prompt")

    policy = bundle["provider_reference_policy"]
    _require(policy.get("maximum_images") == 2, "Provider reference maximum must remain two.")
    _require(policy.get("required_roles") == ["user_product", "sanitized_scene_control_board"], "Provider roles changed.")
    hint = bundle["hint_images"][0]
    _require(hint.get("role") == "sanitized_wood_cane_brownie_control_board", "Sanitized control-board role changed.")
    _require("2x2 board layout" in hint.get("excluded_transfer", []), "Control-board panel-copy exclusion is missing.")
    _require("complete scene" in hint.get("excluded_transfer", []), "Complete-scene transfer exclusion is missing.")
    hint_path = _asset(hint, "sanitized control board")
    with Image.open(hint_path) as image:
        _require([image.width, image.height] == [1122, 1402], "Control-board dimensions changed.")
        image.verify()

    _require(bundle["camera_contract"]["pitch_degrees"] == [72, 80], "Camera pitch changed.")
    preserve_mode = bundle["container_modes"]["preserve_source"]
    _require(preserve_mode["camera_override"]["pitch_degrees"] == [85, 89], "Preserve-source camera override changed.")
    _require(preserve_mode["camera_override"]["rim_shape"] == "near-circular", "Preserve-source rim contract changed.")
    preserve_scale = preserve_mode["product_scale_override_4x5"]
    _require(preserve_scale["width_ratio"] == [0.16, 0.21], "Preserve-source width contract changed.")
    _require(preserve_scale["height_ratio"] == [0.17, 0.23], "Preserve-source height contract changed.")
    _require("beverage_color_integration" in preserve_mode, "Generic beverage color-integration contract is missing.")
    _require("pale_neutral_component_adaptation" in preserve_mode, "Generic pale-neutral component contract is missing.")
    _require("transparent_beverage_color_integration" not in preserve_mode, "Beverage-type-specific color contract must not be present.")
    integration = bundle["product_wood_integration_contract"]
    for key in ("contact_occlusion", "cast_shadow", "opaque_container", "transparent_container", "local_edge_response"):
        _require(key in integration, f"Missing product-to-wood integration rule: {key}")
    lighting = json.loads((BUNDLE_DIR / bundle["lighting_sheet"]["path"]).read_text(encoding="utf-8"))
    _require(lighting["screen_light_map"]["dominant_shadow_vector_degrees"] == [122, 142], "Shadow vector changed.")
    _require("transparent_container" in lighting["wood_bounce_contract"], "Transparent wood interaction is missing.")
    _require(lighting["screen_light_map"]["shadow_area_ratio"][0] >= 0.50, "Partial environmental shadow coverage is too low.")
    _require(lighting["capture_contract"]["exposure_compensation_ev"][1] <= -0.52, "Wood overhead exposure is too bright.")

    default_prompt = (BUNDLE_DIR / bundle["prompt_template"]["path"]).read_text(encoding="utf-8")
    preserve_text = preserve_path.read_text(encoding="utf-8")
    for fragment in ("sanitized non-photographic control board", "PRODUCT-TO-WOOD INTEGRATION", "upper-left window-sun", "elongated narrow oval bowl points downward", "natural depth hierarchy", "cutout halo"):
        _require(fragment in default_prompt, f"Default prompt is missing: {fragment}")
    for fragment in ("sanitized non-photographic control board", "sole beverage and source-container authority", "85-89 degrees", "0.16-0.21", "nearly circular", "broad, low-density partial shadow", "internal hue, luminance and saturation relationships", "scene-referred diffuse pale-neutral material", "source-relative hierarchy", "Do not copy an exact pixel color", "Never wash out, gray, neon-brighten", "natural depth hierarchy", "warm-brown reflected fill", "No cutout halo", "generous melting white cream"):
        _require(fragment in preserve_text, f"Preserve-source prompt is missing: {fragment}")

    delivery = bundle["aspect_ratio_contracts"]["4:5"]
    _require(delivery["status"] == "prepared_pending_visual_qa", "4:5 status changed.")
    _require(delivery.get("provider_aspect_ratio") == "3:4", "Higgsfield GPT Image 2 must use its supported 3:4 provider canvas.")
    _require(delivery["bbox_qa"].get("crop_axis") == "vertical_only", "3:4 to 4:5 crop must remove top and bottom margins only.")
    _require(delivery["bbox_qa"].get("protected_objects_must_remain_complete") is True, "4:5 crop protection changed.")
    print("Validated pending wood overhead preset, hashes, sanitized control board, light/shadow and product-to-wood integration contracts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
