"""Build the four common-runtime dark-grey preset bundles.

The teammate-authored preset remains the source contract. This builder only
adapts its four shot variants and two cup modes to the service slot schema.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from build_prompt import build_prompt


HERE = Path(__file__).resolve().parent
PRESET_ROOT = HERE.parent
SOURCE_PRESET_PATH = HERE / "preset.json"
SOURCE_PROMPT_ARCHIVE_PATH = HERE / "prompt.md"
HINT_ROOT = HERE / "source-hints"

SLOTS = {
    "vivid__product_large": {
        "shot_variant": "close_up",
        "composition": "closeup",
        "preset_id": "instagram_dark_grey_closeup_v1",
        "hint": "ice_glass.png",
        "hint_role": "raw_dark_grey_closeup_reference",
        "companion_policy": "reference_relational",
        "aspect_4x5": (
            "Generate the exact final 4:5 canvas at 1024x1280. Keep the complete "
            "beverage dominant but uncropped at 0.55-0.70 frame width, with only "
            "narrow soft-focus dark-grey wall and counter context at the edges."
        ),
        "aspect_1x1": (
            "Generate the exact final 1:1 canvas at 1024x1024 from the start. "
            "Recompose the complete beverage at 0.50-0.64 frame width with no crop "
            "and retain restrained dark-grey counter context around it."
        ),
    },
    "vivid__product_center": {
        "shot_variant": "medium",
        "composition": "medium",
        "preset_id": "instagram_dark_grey_medium_v1",
        "hint": "glass_background.jpg",
        "hint_role": "raw_dark_grey_glass_wall_reference",
        "companion_policy": "reference_relational",
        "aspect_4x5": (
            "Generate the exact final 4:5 canvas at 1024x1280. Keep the complete "
            "beverage in the lower-right at 0.30-0.40 frame width. Preserve the "
            "black counter in the lower 35-45 percent and the daylight glass-wall "
            "context as the larger quiet upper field."
        ),
        "aspect_1x1": (
            "Generate the exact final 1:1 canvas at 1024x1024 from the start. Keep "
            "the complete beverage in the lower-right at 0.30-0.40 frame width, "
            "with a balanced black counter and daylight glass-wall field."
        ),
    },
    "vivid__aerial_shot": {
        "shot_variant": "aerial",
        "composition": "aerial",
        "preset_id": "instagram_dark_grey_aerial_v1",
        "hint": "layout.webp",
        "hint_role": "raw_dark_grey_aerial_layout_reference",
        "companion_policy": "reference_relational",
        "aspect_4x5": (
            "Generate the exact final 4:5 canvas at 1024x1280 from a strict "
            "90-degree vertical camera. Show only top surfaces. Keep the plant and "
            "covered candle as the upper pair and beverage and pastry plate as the "
            "lower pair in a loose diamond occupying 35-45 percent of the frame."
        ),
        "aspect_1x1": (
            "Generate the exact final 1:1 canvas at 1024x1024 from a strict "
            "90-degree vertical camera. Preserve the four-part diamond layout and "
            "generous bare black round-table area; show no vessel sidewalls."
        ),
    },
    "vivid__handheld_lifestyle": {
        "shot_variant": "handheld",
        "composition": "handheld",
        "preset_id": "instagram_dark_grey_handheld_v1",
        "hint": "ice_handheld.jpg",
        "hint_role": "raw_dark_grey_handheld_pose_reference",
        "companion_policy": "none",
        "aspect_4x5": (
            "Generate the exact final 4:5 canvas at 1024x1280. Keep one complete "
            "hand-beverage unit uncropped. For an iced source, hold the upright cup "
            "against the dark-grey wall; for a hot source, keep the mug base on the "
            "black table with the hand resting on or beside it."
        ),
        "aspect_1x1": (
            "Generate the exact final 1:1 canvas at 1024x1024 from the start. Keep "
            "one complete hand-beverage unit and preserve the source-temperature "
            "branch without cropping the hand, wrist, cup rim or base."
        ),
    },
}


def sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".json", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, value: dict) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def prompt_template(source: dict, shot_variant: str, cup_mode: str) -> str:
    hot = build_prompt(
        source,
        shot_variant,
        beverage_temp="hot",
        container_mode=cup_mode,
        product_note="사용자가 업로드한 음료 사진의 색·온도·얼음·거품·레이어 상태를 그대로 유지",
    )
    ice = build_prompt(
        source,
        shot_variant,
        beverage_temp="ice",
        container_mode=cup_mode,
        product_note="사용자가 업로드한 음료 사진의 색·온도·얼음·거품·레이어 상태를 그대로 유지",
    )
    return f"""{{{{INPUT_ROLES}}}}

### RUNTIME SOURCE-STATE ROUTER
Image 1 is authoritative for the beverage and serving state. First inspect only
Image 1 and classify the visible serving state as HOT or ICE/COLD. Apply exactly
one matching branch below and ignore every scene, cup, prop and temperature rule
from the unused branch. The published reference image supplies visual guidance
only; despite any text inside the archived authoring prompt, it never supplies
the beverage recipe, serving state, logo or user-product identity.

## HOT BRANCH — use only when Image 1 visibly represents a hot beverage
{hot}

## ICE/COLD BRANCH — use only when Image 1 visibly represents an iced or cold beverage
{ice}

{{{{LIGHTING_CONTRACT}}}}

{{{{ASPECT_CONTRACT}}}}
"""


def lighting_sheet(slot_id: str, shot_variant: str) -> dict:
    return {
        "schema_version": 1,
        "lighting_sheet_id": f"{slot_id}_dark_grey_shared_light_v1",
        "mood": (
            "restrained dark-grey editorial cafe realism with protected product "
            "detail and one physically coherent natural-light field"
        ),
        "shot_variant": shot_variant,
        "key_light": {
            "source": "one broad daylight source from the declared window or upper side",
            "direction": "upper-right or upper-left according to the selected shot branch",
            "relative_size": "large and soft with finite directional structure",
        },
        "ambient_fill": "low neutral room bounce; preserve charcoal separation without gray haze",
        "shadow_contract": {
            "edge": "soft attached contact shadow with no floating gap or pasted halo",
            "attachment": "every cup, hand and declared prop remains physically attached to its support",
        },
        "capture_contract": {
            "white_balance": "neutral 5000-5750K with restrained cool-grey surfaces",
            "texture": "finite phone or compact-camera acuity, natural grain and real material microtexture",
        },
        "forbidden": [
            "night-time neon grading",
            "crushed black product detail",
            "HDR or CGI gloss",
            "detached or conflicting shadows",
            "copied reference text, logo or beverage identity",
            "sticker-like product edges",
        ],
    }


def grade_profile(slot_id: str) -> dict:
    return {
        "schema_version": 1,
        "grade_profile_id": f"{slot_id}_dark_grey_grade_v1",
        "apply_in_pilot": False,
        "policy": "Review-only metadata; the prompt remains the grade authority.",
        "palette": ["charcoal", "cool dark grey", "muted neutral daylight", "restrained green"],
    }


def bbox_contract(shot_variant: str, square: bool) -> dict:
    ranges = {
        "medium": ([0.28, 0.42], [0.22, 0.50]),
        "close_up": ([0.48, 0.72], [0.38, 0.72]),
        "aerial": ([0.12, 0.28], [0.12, 0.28]),
        "handheld": ([0.18, 0.38], [0.20, 0.58]),
    }
    width, height = ranges[shot_variant]
    if square:
        width = [max(0.1, width[0] - 0.02), min(0.8, width[1] + 0.02)]
    return {
        "product_width_ratio": width,
        "product_height_ratio": height,
        "expected_primary_count": 1,
        "crop_allowed": False,
        "protected_objects_must_remain_complete": True,
    }


def hint_manifest() -> dict:
    runtime_hints = {value["hint"] for value in SLOTS.values()}
    assets = []
    for path in sorted(HINT_ROOT.iterdir()):
        if not path.is_file():
            continue
        with Image.open(path) as image:
            width, height = image.size
        assets.append(
            {
                "path": f"source-hints/{path.name}",
                "sha256": sha256(path),
                "width": width,
                "height": height,
                "runtime_provider_input": path.name in runtime_hints,
            }
        )
    return {
        "schema_version": 1,
        "artifact_type": "team_supplied_raw_hint_manifest",
        "risk_acceptance": (
            "Raw references may transfer cup, logo, text or exact composition. "
            "They are intentionally sent for this release and require later sanitization."
        ),
        "assets": assets,
    }


def build_bundle(slot_id: str, config: dict, source: dict) -> None:
    bundle_dir = PRESET_ROOT / slot_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    user_prompt = bundle_dir / "prompt-template-reconstruct-source.txt"
    reference_prompt = bundle_dir / "prompt-template-adopt-reference.txt"
    lighting_path = bundle_dir / "lighting-sheet.json"
    grade_path = bundle_dir / "grade-profile.json"
    write_text(
        user_prompt,
        prompt_template(source, config["shot_variant"], "user_cup"),
    )
    write_text(
        reference_prompt,
        prompt_template(source, config["shot_variant"], "reference_cup"),
    )
    write_json(lighting_path, lighting_sheet(slot_id, config["shot_variant"]))
    write_json(grade_path, grade_profile(slot_id))

    hint_path = HINT_ROOT / config["hint"]
    with Image.open(hint_path) as image:
        hint_width, hint_height = image.size

    bundle = {
        "schema_version": 1,
        "slot_id": slot_id,
        "preset_id": config["preset_id"],
        "family": "vivid",
        "composition": config["composition"],
        "status": "published",
        "source_review_status": "passed_by_user_review",
        "runtime_policy": {
            "schema_version": 1,
            "compiler_version": "preset-runtime-v1",
            "maximum_prompt_characters": 50000,
            "maximum_provider_inputs": 4,
            "maximum_product_sources": 3,
            "maximum_reference_controls": 1,
            "default_container_mode": "reconstruct_source",
            "supported_container_modes": ["adopt_reference", "reconstruct_source"],
            "companion_policy": config["companion_policy"],
            "brand_input_policy": {
                "enabled": False,
                "default_mode": "none",
                "activation_requirement": "frontend_and_api_brand_asset_flow",
            },
            "temperature_policy": {
                "mode": "preset_primary",
                "container_mode_rules": {
                    "adopt_reference": {
                        "allowed_product_states": ["iced", "cold", "ambient", "hot"],
                        "auto_action": "preserve_source_state",
                    },
                    "reconstruct_source": {
                        "allowed_product_states": ["iced", "cold", "ambient", "hot"],
                        "auto_action": "preserve_source_state",
                    },
                },
                "emergency_fallback": {
                    "enabled_when_policy_missing": True,
                    "minimum_confidence": 0.85,
                    "unknown_action": "needs_review",
                    "conflict_action": "needs_review",
                },
            },
        },
        "prompt_template": {
            "path": user_prompt.name,
            "sha256": sha256(user_prompt),
        },
        "lighting_sheet": {
            "path": lighting_path.name,
            "sha256": sha256(lighting_path),
        },
        "grade_profile": {
            "path": grade_path.name,
            "sha256": sha256(grade_path),
            "apply_in_pilot": False,
        },
        "contract_assets": {
            "team_source_contract": {
                "path": "../dark_grey/preset.json",
                "sha256": sha256(SOURCE_PRESET_PATH),
            },
            "team_prompt_archive": {
                "path": "../dark_grey/prompt.md",
                "sha256": sha256(SOURCE_PROMPT_ARCHIVE_PATH),
            },
            "team_hint_manifest": {
                "path": "../dark_grey/source-hints-manifest.json",
                "sha256": sha256(HERE / "source-hints-manifest.json"),
            },
        },
        "provider_reference_policy": {
            "maximum_images": 2,
            "required_roles": ["user_product", config["hint_role"]],
            "risk_acceptance": "Raw team hint is sent by explicit product-owner decision; sanitize in a later revision.",
        },
        "hint_images": [
            {
                "role": config["hint_role"],
                "path": f"../dark_grey/source-hints/{hint_path.name}",
                "sha256": sha256(hint_path),
                "width": hint_width,
                "height": hint_height,
                "send_to_provider": True,
                "container_mode_scope": ["adopt_reference", "reconstruct_source"],
                "allowed_transfer": [
                    "declared shot topology",
                    "camera relationship",
                    "broad dark-grey material family",
                    "broad light distribution",
                ],
                "forbidden_transfer": [
                    "reference beverage identity",
                    "reference serving state",
                    "reference logo or text",
                    "exact person identity",
                ],
            }
        ],
        "transforms": [
            {"type": "normalize_product_source"},
            {"type": "select_hint_by_container_mode"},
            {"type": "sanitize_reference_control"},
        ],
        "default_container_mode": "reconstruct_source",
        "container_modes": {
            "reconstruct_source": {
                "container_identity_scope": "source_container_class_material_silhouette_handle_lid_and_visible_branding",
                "prompt_template": {
                    "path": user_prompt.name,
                    "sha256": sha256(user_prompt),
                },
                "preserve": [
                    "source beverage identity and serving state",
                    "source cup material, silhouette, handle and lid",
                    "authorized visible source branding",
                ],
                "discard": ["source camera pose", "source background", "source lighting and shadows"],
            },
            "adopt_reference": {
                "container_identity_scope": "published_dark_grey_temperature_compatible_container",
                "prompt_template": {
                    "path": reference_prompt.name,
                    "sha256": sha256(reference_prompt),
                },
                "preserve": [
                    "source beverage identity and serving state",
                    "source liquid color, opacity, ice, foam, layers and garnish",
                ],
                "discard": [
                    "source container geometry and material",
                    "source container branding",
                    "reference beverage identity and serving state",
                ],
            },
        },
        "aspect_ratio_contracts": {
            "4:5": {
                "status": "published",
                "visual_review_status": "representative_matrix_pending",
                "prompt_addendum": config["aspect_4x5"],
                "generation_size": "1024x1280",
                "safe_crop": "none_exact_4x5",
                "width": 1024,
                "height": 1280,
                "format": "png",
                "bbox_qa": bbox_contract(config["shot_variant"], square=False),
            },
            "1:1": {
                "status": "published",
                "visual_review_status": "representative_matrix_pending",
                "prompt_addendum": config["aspect_1x1"],
                "generation_size": "1024x1024",
                "safe_crop": "none_exact_1x1",
                "width": 1024,
                "height": 1024,
                "format": "png",
                "bbox_qa": bbox_contract(config["shot_variant"], square=True),
            },
        },
        "qa_contract": {
            "phase": "representative_paid_visual_review_pending",
            "hard_gates": [
                "beverage_identity",
                "container_mode",
                "serving_state",
                "camera_geometry",
                "product_environment_integration",
                "hint_copy_contamination",
                "brand_ocr",
                "crop",
            ],
            "known_release_risk": "Raw provider hints are not sanitized in this revision.",
            "comparative_scores": [
                "naturalness",
                "mood_adherence",
                "product_preservation",
                "light_shadow_fidelity",
            ],
        },
    }
    write_json(bundle_dir / "preset.json", bundle)


def main() -> int:
    source = json.loads(SOURCE_PRESET_PATH.read_text(encoding="utf-8"))
    write_json(HERE / "source-hints-manifest.json", hint_manifest())
    for slot_id, config in SLOTS.items():
        build_bundle(slot_id, config, source)
    for slot_id in SLOTS:
        bundle = json.loads((PRESET_ROOT / slot_id / "preset.json").read_text(encoding="utf-8"))
        for mode in ("reconstruct_source", "adopt_reference"):
            prompt_path = PRESET_ROOT / slot_id / bundle["container_modes"][mode]["prompt_template"]["path"]
            print(f"{slot_id} {mode}: {len(prompt_path.read_text(encoding='utf-8'))} template chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
