from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.adapters.openai_image import load_published_preset


SLOT_ID = "natural_white__aerial_shot"
PRESET_ID = "instagram_white_neutral_overhead_spatial_v1"


def _sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".json", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    registry_path = COMFYUI_DIR / "presets" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    slot = registry["slots"][SLOT_ID]
    _require(slot.get("enabled") is True, "White overhead review slot must be enabled.")
    _require(slot.get("status") == "published", "White overhead review slot must be published after visual QA.")
    _require(slot.get("preset_id") == PRESET_ID, "Registry preset ID mismatch.")

    bundle_path = registry_path.parent / slot["bundle"]
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    _require(bundle.get("preset_id") == PRESET_ID, "Bundle preset ID mismatch.")
    _require(bundle.get("default_container_mode") == "adopt_reference", "Review must use the adopted white mug.")

    runtime = bundle.get("runtime_input_policy")
    _require(isinstance(runtime, dict), "runtime_input_policy is required.")
    _require(runtime.get("analysis_source") == "full_user_image", "Full-image analysis policy is missing.")
    _require(runtime.get("provider_source") == "beverage_surface_crop", "Surface crop policy is missing.")
    _require(runtime.get("camera_pose_authority") == "preset", "Preset camera authority is missing.")
    crop = runtime.get("crop_contract")
    _require(isinstance(crop, dict), "crop_contract is required.")
    expected_crop = {
        "horizontal_margin_container_width_ratio": 0.08,
        "top_container_height_offset_ratio": -0.03,
        "bottom_container_height_ratio": 0.34,
        "clamp_to_image": True,
        "minimum_crop_pixels": 2,
    }
    for key, value in expected_crop.items():
        _require(crop.get(key) == value, f"Crop contract mismatch: {key}")

    camera = bundle.get("camera_contract")
    _require(camera.get("pitch_degrees") == [84, 89], "Camera pitch contract changed.")
    _require(camera.get("discard_source_pose") is True, "Source-pose override is required.")
    _require(camera.get("forbid_tilt_for_branding_or_vertical_layers") is True, "Branding tilt guard is required.")

    modes = bundle.get("container_modes")
    _require(set(modes) == {"reconstruct_source", "adopt_reference"}, "Both container modes are required.")
    _require(modes["reconstruct_source"]["container_identity_scope"] == "source_family_and_material_only", "Source-family scope changed.")
    _require(modes["adopt_reference"]["container_identity_scope"] == "discard_source_container", "Adopt-reference scope changed.")
    _require("strictly inside the inner rim" in modes["adopt_reference"]["prompt_addendum"], "Opaque exterior guard is missing.")

    for name, binding in bundle["contract_assets"].items():
        path = bundle_path.parent / binding["path"]
        _require(path.is_file(), f"Contract asset missing: {name}")
        _require(_sha256(path) == binding["sha256"], f"Contract asset hash mismatch: {name}")

    hints = bundle.get("hint_images")
    _require(len(hints) == 2, "Exactly two mode-specific provider evidence boards are required.")
    expected_hint_roles = {
        "reference_cup_geometry_and_companion_scene_evidence": ["adopt_reference"],
        "user_cup_placement_and_companion_scene_evidence": ["reconstruct_source"],
    }
    _require({item.get("role") for item in hints} == set(expected_hint_roles), "Evidence-board roles changed.")
    for hint in hints:
        _require(hint.get("send_to_provider") is True, "Evidence board must be sent to the provider.")
        _require(hint.get("container_mode_scope") == expected_hint_roles[hint["role"]], "Evidence-board mode scope changed.")
        hint_path = bundle_path.parent / hint["path"]
        _require(hint_path.is_file(), "Provider evidence board is missing.")
        _require(_sha256(hint_path) == hint["sha256"], "Provider evidence-board hash mismatch.")
        _require(hint.get("width") == 1024, "Provider evidence-board width changed.")
        _require(hint.get("height") == 1536, "Provider evidence-board height changed.")

    provider_policy = bundle.get("provider_reference_policy")
    _require(isinstance(provider_policy, dict), "Provider-reference policy is missing.")
    _require(provider_policy.get("maximum_images") == 2, "Provider-reference limit must remain two images.")
    _require(provider_policy.get("required_roles") == ["user_product", "container_mode_scene_hint"], "Provider-reference roles changed.")

    preserve_prompt = modes["reconstruct_source"].get("prompt_template")
    _require(isinstance(preserve_prompt, dict), "Preserve-source prompt template is missing.")
    preserve_prompt_path = bundle_path.parent / preserve_prompt["path"]
    _require(preserve_prompt_path.is_file(), "Preserve-source prompt file is missing.")
    _require(_sha256(preserve_prompt_path) == preserve_prompt["sha256"], "Preserve-source prompt hash mismatch.")
    preserve_prompt_text = preserve_prompt_path.read_text(encoding="utf-8")
    for fragment in ("sole authority", "white mug", "Preserve a source cup saucer", "source spoon"):
        _require(fragment in preserve_prompt_text, f"Preserve-source prompt is missing: {fragment}")

    props = bundle.get("scene_props_contract")
    _require(isinstance(props, dict), "Scene-props contract is missing.")
    _require(props.get("enabled_container_modes") == ["reconstruct_source", "adopt_reference"], "Scene props must support both container modes.")
    _require(props.get("reference_image_role_by_container_mode") == {
        "reconstruct_source": "user_cup_placement_and_companion_scene_evidence",
        "adopt_reference": "reference_cup_geometry_and_companion_scene_evidence",
    }, "Scene-props role routing changed.")
    _require(props.get("declared_companion_groups") == 2, "Declared companion-group count changed.")
    _require("tines point left" in props["dessert_group"]["fork"], "Fork direction contract is missing.")
    _require("BAUHAUS" in props["magazine_group"]["appearance"], "Magazine identity contract is missing.")

    resolved = load_published_preset(
        SLOT_ID,
        aspect_ratio="4:5",
        container_mode="adopt_reference",
        registry_path=registry_path,
        allowed_statuses=("published",),
    )
    resolved_source = load_published_preset(
        SLOT_ID,
        aspect_ratio="4:5",
        container_mode="reconstruct_source",
        registry_path=registry_path,
        allowed_statuses=("published",),
    )
    _require(len(resolved.provider_image_paths) == 1, "Exactly one reference-cup evidence board must be submitted.")
    _require(resolved.provider_image_roles == ("reference_cup_geometry_and_companion_scene_evidence",), "Reference-cup evidence role changed.")
    _require(len(resolved_source.provider_image_paths) == 1, "Exactly one user-cup evidence board must be submitted.")
    _require(resolved_source.provider_image_roles == ("user_cup_placement_and_companion_scene_evidence",), "User-cup evidence role changed.")
    _require(resolved.provider_profile["model"] == "gpt-image-2", "Model profile changed.")
    _require(resolved.provider_profile["quality"] == "medium", "Default quality changed.")
    required_prompt_fragments = (
        "84-89 degrees",
        "nearly circular",
        "strictly inside the inner rim",
        "clean plain white ceramic",
        "narrow gray tiled-floor wedge",
        "broad low-density environmental shadow",
        "Basque burnt cheesecake",
        "four tines point left",
        "BAUHAUS magazine",
        "Prohibit marble veins",
        "never airbrushed, plastic, seamless, CGI, 3D-rendered or AI-smoothed",
    )
    for fragment in required_prompt_fragments:
        _require(fragment in resolved.prompt, f"Resolved prompt is missing: {fragment}")

    print(
        json.dumps(
            {
                "status": "passed",
                "slot_id": resolved.slot_id,
                "preset_id": resolved.preset_id,
                "model": resolved.provider_profile["model"],
                "quality": resolved.provider_profile["quality"],
                "prompt_sha256": resolved.prompt_sha256,
                "bundle_sha256": resolved.bundle_sha256,
                "provider_reference_images": len(resolved.provider_image_paths),
                "delivery": [resolved.delivery_width, resolved.delivery_height],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
