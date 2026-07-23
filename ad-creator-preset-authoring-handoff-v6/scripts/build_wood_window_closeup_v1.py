#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
PRESET_ID = "instagram_wood_calm_window_closeup_v1"
ASSET_ID = "ref_95fa7947818ce496"
REFERENCE_SOURCE = (
    WORKSPACE
    / "assets"
    / "references"
    / "wood"
    / "wood_closeup_cafe_latte_reference-v2.png"
)
REFERENCE_RUNTIME_NAME = "ad_creator_reference_wood_window_closeup_v1.png"
REFERENCE_RUNTIME_PATH = ROOT / "comfyui-inputs" / REFERENCE_RUNTIME_NAME
REFERENCE_RELATIVE_PATH = f"comfyui-inputs/{REFERENCE_RUNTIME_NAME}"
PIXEL_SHA256 = "fdcf3f83e673d7ed06cecb376eb7b94386bb2c1657f942136017aeeadc919523"
FILE_SHA256 = "4e17067c6696a71699e989bfc0fcb47d096a9626441698bec4b773904efd73c7"
CONTROL_DIR = ROOT / "data/reference-library/control-boards/wood-window-closeup-v1"
CONTROL_RELATIVE_PATH = (
    "data/reference-library/control-boards/wood-window-closeup-v1/scene-hint.png"
)
CONTROL_MANIFEST_RELATIVE_PATH = (
    "data/reference-library/control-boards/wood-window-closeup-v1/scene-hint-manifest.json"
)
SCENE_GRAPH_RELATIVE_PATH = (
    "data/reference-library/scene-graphs-v2/"
    "ref_95fa7947818ce496_wood_window_closeup_v1.json"
)
MOOD_ROOT = f"presets/moods/{PRESET_ID}"
EDITORIAL_ROOT = f"presets/editorial/{PRESET_ID}"
PALETTE = ["#BBAB9A", "#8B7761", "#504131", "#F1EFEE", "#E3DCD5"]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixel_sha256(path: Path) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"RGB:{image.width}x{image.height}:".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_reference_preset() -> dict[str, Any]:
    return {
        "$schema": "../../../schemas/reference-preset.schema.json",
        "schema_version": "2.0.0",
        "preset_id": PRESET_ID,
        "display_name": "인스타그램 우드 저채도 창가 클로즈업 v1",
        "concept": "quiet_closeup_pair_on_pale_live_edge_wood_by_a_soft_window",
        "source": {
            "reference_image": REFERENCE_RELATIVE_PATH,
            "width_px": 1254,
            "height_px": 1254,
            "supporting_group": "user_approved/wood/soft_window_closeup/v1",
        },
        "runtime_input_policy": {
            "default_generation_mode": "user_image_plus_abstracted_preset",
            "generation_inputs": ["user_product_identity"],
            "reference_usage": "offline_feature_extraction_only",
            "copyright_rule": "Use only measured camera, spacing, pale-wood material, soft-window light and restrained tone. Rebuild every scene pixel and never transfer reference drinks, labels, copy, plant identity or exact table grain.",
        },
        "style_abstraction": {
            "runtime_reference_image": False,
            "novel_scene_required": True,
            "allowed_style_features": [
                "one exact user beverage in the front-left primary slot",
                "one smaller generic double-paper-cup iced Americano behind-right",
                "one round pale live-edge wood table",
                "soft diffused upper-left window light",
                "restrained warm-neutral low-saturation palette",
                "subtle plant mass behind the beverage pair",
            ],
            "forbidden_copy_features": [
                "reference cafe latte recipe, milk diffusion or ice layout",
                "reference Americano recipe or exact crema pattern",
                "cafe latte, CAFE AMERICANO or any other reference text",
                "exact plant, window frame, street geometry or table grain",
                "exact crop, reflection, highlight or shadow silhouette",
            ],
        },
        "sampling_ranges": {
            "pov_modes": ["slightly-above close cafe tabletop observation"],
            "subject_center_x": [0.43, 0.50],
            "subject_center_y": [0.62, 0.68],
            "subject_width_ratio": [0.27, 0.34],
            "subject_height_ratio": [0.42, 0.52],
            "negative_space_ratio": [0.20, 0.32],
            "focal_length_mm": [45, 55],
            "camera_pitch_degrees": [18, 28],
            "light_softness": [0.78, 0.92],
            "prop_count": [1, 2],
            "asymmetry_probability": 1.0,
            "asymmetry_sources": [
                "front-left exact product and smaller behind-right companion",
                "partial window context and irregular live-edge table crop",
            ],
            "micro_moments": [
                "a quiet cafe order resting naturally beside a softly lit window"
            ],
        },
        "tone_contract": {
            "background_plane": "soft gray exterior and pale sill separated from the warmer wood foreground",
            "background_lightness": [0.56, 0.76],
            "background_saturation": [0.04, 0.14],
            "global_contrast": [0.34, 0.50],
            "shadow_density": [0.16, 0.30],
            "color_bias": "local beige-brown wood warmth with neutral white cups and cool gray window context",
            "highlight_behavior": "broad rolled highlights on cup rims, ice and condensation with no clipped plastic or paper",
            "forbidden_surface_reading": [
                "orange or yellow filter",
                "glossy synthetic wood",
                "gray lifeless beverage",
                "plastic AI ice",
                "milky airbrushed gradients",
                "flat shadowless tabletop",
            ],
        },
        "output": {
            "preferred_aspect_ratio": "3:4",
            "compatible_aspect_ratios": ["3:4", "4:5"],
        },
        "subject_layout": {
            "main_subject": {
                "role": "one_exact_user_beverage_preserving_its_source_container_and_serving_state",
                "center": {"x_ratio": 0.46, "y_ratio": 0.65},
                "bbox": {
                    "x_ratio": 0.29,
                    "y_ratio": 0.39,
                    "width_ratio": 0.34,
                    "height_ratio": 0.51,
                },
                "area_ratio": 0.1734,
                "height_ratio": 0.51,
            },
            "secondary_subjects": [
                {
                    "role": "one_generic_unbranded_double_nested_white_paper_cup_iced_Americano_with_natural_crema",
                    "center": {"x_ratio": 0.705, "y_ratio": 0.545},
                    "bbox": {
                        "x_ratio": 0.58,
                        "y_ratio": 0.31,
                        "width_ratio": 0.25,
                        "height_ratio": 0.47,
                    },
                    "area_ratio": 0.1175,
                    "height_ratio": 0.47,
                }
            ],
            "negative_space": {
                "top_ratio": 0.13,
                "left_ratio": 0.12,
                "right_ratio": 0.10,
                "bottom_ratio": 0.08,
            },
        },
        "composition": {
            "shot_type": "close environmental tabletop pair",
            "camera_angle": "slightly above and nearly level with the drink rims",
            "camera_height": "approximately one hundred five to one hundred thirty-five centimeters",
            "focal_length_equivalent_mm": 50,
            "horizon_visibility": "only a soft window and exterior band behind the table",
            "depth_of_field": "both beverages and table contact remain readable; the exterior and plant lose fine detail",
            "alignment": "primary product front-left, companion behind-right, irregular wood edge below",
        },
        "lighting": {
            "type": "single large diffused window source with quiet room fill",
            "direction": "upper-left and slightly behind toward lower-right",
            "azimuth_degrees": 315,
            "elevation_degrees": 38,
            "softness": 0.86,
            "intensity": "soft medium daylight exposure",
            "contrast": "low-to-moderate with readable cup, liquid and wood separation",
            "shadow": "short attached contacts with broad soft falloff to lower-right",
            "highlight_control": "protect white paper, transparent plastic, ice and condensation from clipping",
        },
        "color": {
            "temperature": "warm-neutral daylight without an amber cast",
            "white_balance_kelvin": 4900,
            "saturation": "restrained environment while the user beverage retains source-authoritative color",
            "contrast": "soft shoulder, weighted midtones and gentle open shadows",
            "palette_hex": PALETTE,
            "black_point": "soft neutral brown-black with preserved wood pore detail",
        },
        "scene": {
            "surface": "one round pale live-edge wood table with visible matte grain and natural edge irregularity",
            "background": "a new low-detail window sill and cool gray exterior with one indistinct green plant mass",
            "background_complexity": 0.24,
            "props": [
                "one generic double nested white paper cup iced Americano",
                "one small low-detail green plant accent",
            ],
            "max_prop_count": 2,
            "texture": "matte pale wood, finite paper fibers, plausible transparent-container optics, irregular ice and natural condensation",
        },
        "capture": {
            "look": "quiet natural cafe phone photograph with soft spatial depth",
            "realism": "one camera, one exposure and one diffused daylight system physically join both drinks and the table",
            "grain": "faint low-contrast luminance texture with finite social-photo acuity",
            "imperfections": [
                "irregular real ice geometry",
                "nonuniform condensation droplets",
                "small crema bubbles on the companion Americano",
                "subtle wood grain and edge variation",
            ],
        },
        "preservation_policy": {
            "hard_lock": [
                "exactly one user beverage",
                "user product container, identity, branding, recipe color and serving state",
                "primary product width 0.27-0.34 and height 0.42-0.52",
                "one smaller behind-right generic companion only",
                "companion is two naturally nested unbranded white paper cups with iced Americano and rich natural crema",
                "one pale matte live-edge wood table",
                "no reference text transfer",
            ],
            "editable": [
                "new window and exterior geometry",
                "minor pair spacing",
                "plant silhouette",
                "wood grain phase",
                "generic companion ice and crema arrangement",
            ],
            "reference_exclusions": [
                "reference latte contents, milk diffusion, ice and straw",
                "all reference labels and body copy",
                "exact reference Americano contents",
                "exact plant, window, street, table grain, crop and shadows",
            ],
        },
        "prompt_blocks": {
            "input_roles": "Image one is the sole authority for the exact user product, container, branding, recipe color and serving state. The sanitized scene hint supplies only low-frequency camera, pair spacing, wood support, soft-window light and restrained palette.",
            "composition": "One complete user product front-left at width 0.27-0.34 and height 0.42-0.52; one smaller double-paper-cup Americano behind-right on pale wood.",
            "look": "Soft upper-left window light; low saturation; warm-neutral wood; cool-gray exterior; realistic ice, condensation and attached shadows.",
            "preservation": "Image 1 controls the complete user product and authorized brand. Rebuild it in target light; keep the companion generic, unbranded and text-free.",
            "negative": "No duplicate user product, extra drink, copied cafe latte or CAFE AMERICANO text, invented lettering, pasted edge, halo, floating cup, flat crema, perfect geometric ice, airbrushed milk, glossy orange wood, amber wash, hard studio spotlight or excessive blur.",
        },
        "quality_gates": {
            "logo_text": "only source-authoritative user-product text may remain; the companion and scene contain no text or logo",
            "product_identity": "exactly one user beverage preserves source container, branding, recipe color and serving state",
            "preset_adherence": "primary bbox, behind-right companion, pale live-edge table, soft window light and restrained palette all pass together",
            "artifact_policy": "reject duplicate product, pasted boundary, invented text, synthetic ice, airbrushed liquid, detached shadow, glossy orange wood or copied reference detail",
        },
        "failure_recovery": [
            "restore the exact user product to the front-left bbox and remove every duplicate",
            "restore one smaller text-free double-paper-cup Americano behind-right",
            "remove reference text and any invented lettering",
            "rebuild realistic ice, condensation, liquid boundaries and contact shadows",
            "return the table to pale matte wood and the light to one broad diffused window source",
        ],
    }


def build_style_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "contract_id": "instagram_wood_calm_window_closeup_contract_v1",
        "preset_id": PRESET_ID,
        "creative_direction": {
            "audience": "a social-feed viewer looking for a calm natural cafe product moment",
            "desired_response": "the user drink feels physically present in a softly lit real cafe rather than inserted into a template",
            "art_direction": "one exact user beverage anchors the front-left while one small generic double-cupped Americano recedes behind-right on pale live-edge wood",
            "restraint": "keep the scene quiet, low-saturation and close without crowding the frame or adding decorative props",
            "forbidden_impression": [
                "AI beverage demo",
                "commercial studio spotlight",
                "orange lifestyle filter",
                "pasted product cutout",
                "overdecorated cafe set",
            ],
        },
        "reference_binding": {
            "asset_id": ASSET_ID,
            "pixel_sha256": PIXEL_SHA256,
            "relative_path": REFERENCE_RELATIVE_PATH,
            "width_px": 1254,
            "height_px": 1254,
            "runtime_role": "offline authority for camera, pair geometry, pale live-edge wood, soft-window light and restrained warm-neutral tone",
            "provider_submission": "never",
        },
        "camera_geometry": {
            "projection": "rectilinear normal-to-mild-tele close environmental projection",
            "focal_length_equivalent_mm": [45, 55],
            "working_distance_cm": [85, 130],
            "camera_height_cm": [105, 135],
            "pitch_degrees": [18, 28],
            "yaw_degrees": [-5, 5],
            "roll_degrees": [-1.2, 1.2],
            "distortion": "natural cup taper and table ellipse with no wide-phone looming or stretched frame edges",
            "depth_of_field": "both drink bodies, rims and contacts resolve; plant and exterior lose microdetail without synthetic portrait blur",
        },
        "composition_geometry": {
            "primary_subject_bbox": {
                "left": 0.29,
                "top": 0.39,
                "right": 0.63,
                "bottom": 0.90,
            },
            "bbox_semantics": "complete exact user product body occupies 0.27-0.34 frame width and 0.42-0.52 frame height; source-only straws or tall accessories may extend above without changing body scale",
            "primary_subject_area_ratio": [0.1134, 0.1768],
            "negative_space": "0.20-0.32 meaningful release through the window band, table edge and restrained pair spacing",
            "support_plane": {
                "kind": "one pale matte round live-edge wood table",
                "occupancy_ratio": [0.38, 0.58],
                "dominant_edge_angles_degrees": [-12, 8, 90],
                "perspective": "a broad near wood plane with a rounded irregular edge and mild ellipse supports both drink contacts",
            },
            "frame_rhythm": "large front-left exact product, smaller behind-right paper-cup companion, then soft plant and window context",
            "crop_policy": "retain the full product base and companion rim while allowing the round table edge to leave the frame naturally",
            "forbidden": [
                "primary product outside target bbox",
                "companion larger than the exact product",
                "side-by-side equal lineup",
                "cropped product base",
                "centered studio symmetry",
                "copied reference pixel layout",
            ],
        },
        "composition_variation": {
            "selection": "derive only minor pair offsets, plant mass, wood-grain phase and exterior blur from the request seed",
            "invariants": [
                "one exact front-left user product",
                "one smaller behind-right generic double-paper-cup Americano",
                "one pale round live-edge wood table",
                "45-55mm camera at 18-28 degree pitch",
                "one broad upper-left diffused window source",
            ],
            "allowed_variations": [
                "minor product-to-companion spacing",
                "generic crema and ice arrangement",
                "plant silhouette",
                "wood grain direction",
                "new low-detail exterior geometry",
            ],
            "repeat_guard": "never recreate reference drink contents, labels, exact plant, table grain, window geometry, reflections or shadows",
            "scene_similarity_limit": 0.62,
            "reference_scene_copy_forbidden": True,
        },
        "lighting_geometry": {
            "source_topology": "one very large diffused upper-left window source plus quiet room bounce",
            "azimuth_degrees": [300, 330],
            "elevation_degrees": [32, 46],
            "angular_size_degrees": [38, 62],
            "key_to_fill_ratio": [1.25, 1.70],
            "lit_area_ratio": [0.58, 0.76],
            "shadow_area_ratio": [0.16, 0.30],
            "shadow_vector_degrees": [118, 150],
            "penumbra_ratio": [0.42, 0.72],
            "highlight_behavior": "broad rolled paper and transparent-container highlights with small broken ice and condensation responses",
            "optical_effects": "subtle bounded liquid transmission, real rim thickness and nonuniform condensation under one light direction",
            "forbidden": [
                "hard studio spotlight",
                "multiple conflicting catchlights",
                "shadowless cups",
                "clipped paper white",
                "glowing ice",
                "orange ambient wash",
            ],
        },
        "tone_signature": {
            "working_color_space": "sRGB display-referred natural social-photo finish",
            "white_balance_kelvin": [4750, 5100],
            "luma_percentiles": {
                "p05": [0.06, 0.12],
                "p25": [0.28, 0.40],
                "p50": [0.50, 0.63],
                "p75": [0.70, 0.82],
                "p95": [0.88, 0.96],
            },
            "black_point": "soft neutral brown-black with visible wood pore and beverage separation",
            "white_point": "neutral paper and window whites roll below clipping",
            "contrast_curve": "gentle toe, separated midtones and soft highlight shoulder",
            "saturation": "restrained environment with the exact user beverage color protected",
            "shadow_color": "neutral brown-gray with slight cool exterior influence",
            "highlight_color": "warm-neutral diffused daylight",
            "palette_hex": PALETTE,
            "material_separation": "pale wood, white paper, transparent container, liquid, ice, plant and gray exterior remain independently colored",
            "local_contrast": "moderate only at product edges, liquid boundaries, crema, condensation and wood contact",
            "forbidden": [
                "full-frame brown grade",
                "yellow wood wash",
                "teal-orange split",
                "HDR halos",
                "crushed dark beverage",
                "uniform saturation",
            ],
        },
        "finish_signature": {
            "acuity": "finite twelve-to-sixteen-megapixel-like detail with no uniform hyper-sharpness",
            "microcontrast": "selective on product, ice, crema, condensation and wood contacts; reduced in plant and exterior",
            "grain": "faint shared low-contrast luminance texture rather than a visible filter",
            "depth_rendering": "normal-lens scale, overlap, table ellipse, contacts and soft window falloff establish depth",
            "retouching": "retain irregular ice, small bubbles, condensation variation and wood pores while integrating the exact product into new light",
            "forbidden": [
                "AI-clean liquid gradients",
                "perfect geometric ice",
                "airbrushed milk",
                "sharpening halo",
                "pasted edge",
                "synthetic portrait blur",
            ],
        },
        "qa_contract": {
            "hard_fail": [
                "exact user product count differs from one",
                "source product container, branding, recipe color or serving state changes",
                "primary product leaves the target bbox range",
                "behind-right double-paper-cup companion is missing, duplicated, branded or text-bearing",
                "reference cafe latte or CAFE AMERICANO text appears",
                "container reads as pasted or detached from the table",
                "ice, liquid diffusion, crema or condensation reads as synthetic",
                "pale matte wood or one-source soft-window lighting contract fails",
            ],
            "weights": {
                "camera_geometry": 0.18,
                "composition_rhythm": 0.20,
                "color_and_tone": 0.15,
                "lighting_space": 0.17,
                "product_identity": 0.25,
                "brand_integrity": 0.05,
            },
        },
    }


def build_scene_graph() -> dict[str, Any]:
    def bbox(left: float, top: float, right: float, bottom: float, confidence: float = 0.98) -> dict[str, Any]:
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "confidence": confidence,
        }

    empty_straw = {
        "present": False,
        "bbox": None,
        "centerline": None,
        "emergence_point": None,
        "angle_degrees": None,
    }
    return {
        "schema_version": "2.0.0",
        "analysis_metadata": {
            "provider": "manual_visual_review",
            "model": "human_approved_reference_contract",
            "prompt_version": "reference_scene_graph_v2",
            "analyzed_at": "2026-07-21T00:00:00+09:00",
            "confidence": 0.98,
        },
        "asset": {
            "asset_id": ASSET_ID,
            "relative_path": REFERENCE_RELATIVE_PATH,
            "file_sha256": FILE_SHA256,
            "pixel_sha256": PIXEL_SHA256,
            "width_px": 1254,
            "height_px": 1254,
            "format": "PNG",
            "source_folder_tags": ["user_approved", "wood", "soft_window", "closeup"],
            "dhash": "5b42293fe5b43470",
            "duplicate_of": None,
        },
        "scene_mode": "pair",
        "observed_major_subject_count": 2,
        "object_inventory_complete": True,
        "objects": [
            {
                "slot_id": "beverage_primary",
                "kind": "beverage",
                "role": "primary",
                "description": "Foreground-left transparent iced cafe latte placeholder; all drink contents, label text and straw are excluded from transfer and the complete slot is replaced by the exact user product",
                "body_bbox": bbox(0.30, 0.39, 0.63, 0.90),
                "full_bbox": bbox(0.27, 0.10, 0.64, 0.91),
                "straw": {
                    "present": True,
                    "bbox": bbox(0.28, 0.10, 0.42, 0.47),
                    "centerline": [{"x": 0.29, "y": 0.10}, {"x": 0.40, "y": 0.47}],
                    "emergence_point": {"x": 0.40, "y": 0.47},
                    "angle_degrees": -17.0,
                },
                "container": {
                    "class": "tall transparent cold beverage cup",
                    "material": "clear plastic",
                    "silhouette": "gently tapered cylinder",
                    "components": [
                        "open transparent rim",
                        "tall clear tapered body",
                        "visible ice and layered latte contents excluded from transfer",
                        "paper label and straw excluded from transfer",
                    ],
                },
                "interaction": "resting",
                "support_surface_id": "surface_live_edge_wood_table",
                "depth_order": 2,
                "occlusion_fraction": 0.0,
                "replaceable": True,
                "allowed_kinds": ["beverage", "dessert"],
                "visible_text": ["cafe latte", "body copy"],
                "brand_or_watermark_state": "present",
                "crop_safe": True,
            },
            {
                "slot_id": "beverage_secondary",
                "kind": "beverage",
                "role": "secondary",
                "description": "Behind-right iced Americano in two naturally nested white paper cups with rich crema; runtime companion is generic, unbranded and text-free",
                "body_bbox": bbox(0.59, 0.36, 0.82, 0.77),
                "full_bbox": bbox(0.57, 0.31, 0.84, 0.78),
                "straw": empty_straw,
                "container": {
                    "class": "double nested open paper cup",
                    "material": "white paper",
                    "silhouette": "two slightly offset tapered cylinders with a double rim",
                    "components": [
                        "two visibly nested white paper cup rims",
                        "matte white tapered outer walls",
                        "dark iced Americano surface",
                        "irregular ice and rich fine crema bubbles",
                    ],
                },
                "interaction": "resting",
                "support_surface_id": "surface_live_edge_wood_table",
                "depth_order": 1,
                "occlusion_fraction": 0.0,
                "replaceable": False,
                "allowed_kinds": ["beverage"],
                "visible_text": ["CAFE AMERICANO"],
                "brand_or_watermark_state": "present",
                "crop_safe": True,
            },
            {
                "slot_id": "prop_plant",
                "kind": "prop",
                "role": "accent",
                "description": "Small low-detail green plant mass behind the drinks; only its broad position and color weight may transfer",
                "body_bbox": bbox(0.45, 0.24, 0.73, 0.52, 0.90),
                "full_bbox": bbox(0.45, 0.24, 0.73, 0.52, 0.90),
                "straw": empty_straw,
                "container": {
                    "class": "small background plant accent",
                    "material": "organic foliage",
                    "silhouette": "irregular low-detail leaves",
                    "components": ["soft green leaf masses", "partly hidden stem or pot"],
                },
                "interaction": "resting",
                "support_surface_id": "surface_live_edge_wood_table",
                "depth_order": 0,
                "occlusion_fraction": 0.35,
                "replaceable": False,
                "allowed_kinds": ["prop"],
                "visible_text": [],
                "brand_or_watermark_state": "absent",
                "crop_safe": True,
            },
        ],
        "relations": [
            {"from_slot_id": "beverage_primary", "predicate": "left_of", "to_slot_id": "beverage_secondary", "confidence": 0.98},
            {"from_slot_id": "beverage_primary", "predicate": "in_front_of", "to_slot_id": "beverage_secondary", "confidence": 0.98},
            {"from_slot_id": "beverage_primary", "predicate": "paired_with", "to_slot_id": "beverage_secondary", "confidence": 0.96},
            {"from_slot_id": "prop_plant", "predicate": "behind", "to_slot_id": "beverage_primary", "confidence": 0.90},
            {"from_slot_id": "prop_plant", "predicate": "behind", "to_slot_id": "beverage_secondary", "confidence": 0.90},
        ],
        "support_surfaces": [
            {
                "surface_id": "surface_live_edge_wood_table",
                "kind": "table",
                "bbox": bbox(0.12, 0.53, 1.0, 1.0),
                "plane_description": "Round pale matte live-edge wood tabletop with natural irregular edge, subtle growth rings and low-saturation warm beige-brown tone",
                "supports_objects": True,
                "perspective_scale": [0.92, 1.08],
            },
            {
                "surface_id": "surface_window_sill",
                "kind": "shelf",
                "bbox": bbox(0.0, 0.13, 1.0, 0.43, 0.92),
                "plane_description": "Broad pale window sill behind the table with cool gray exterior beyond",
                "supports_objects": False,
                "perspective_scale": [0.88, 1.12],
            },
        ],
        "protected_regions": [
            {
                "region_id": "region_window_release",
                "kind": "negative_space",
                "bbox": bbox(0.0, 0.0, 1.0, 0.33, 0.94),
                "reason": "retain soft window depth and cool-gray release without copying exact exterior geometry",
            }
        ],
        "insertion_zones": [
            {
                "zone_id": "zone_beverage_primary",
                "bbox": bbox(0.29, 0.39, 0.63, 0.90),
                "support_surface_id": "surface_live_edge_wood_table",
                "allowed_kinds": ["beverage", "dessert"],
                "scale_range": [0.90, 1.10],
                "confidence": 0.98,
                "reason": "complete foreground-left product slot with stable table contact, separation from the companion and safe 4:5 crop margin",
            }
        ],
        "composition": {
            "shot_type": "tabletop",
            "camera_height": "slightly_above",
            "camera_pitch": "18-28 degree downward pitch",
            "lens_character": "phone_mild_tele",
            "subject_position": "large foreground-left product paired with one smaller behind-right companion",
            "negative_space": "0.20-0.32 through the upper window band, pair gap and table edge",
            "asymmetry_source": "front-back stagger, unequal cup scales and irregular live edge",
            "crop_character": "close environmental square source designed for a 3:4 generation and centered 4:5 social crop",
        },
        "depth": {
            "plane_count": 3,
            "foreground": "pale live-edge wood table and exact user product slot",
            "product_plane": "front-left primary slot on the wood table",
            "midground": "behind-right paper-cup companion and low-detail plant",
            "background": "window sill and cool gray exterior",
            "perspective_cues": [
                "normal-lens size falloff",
                "primary overlap in front of companion",
                "elliptical cup rims",
                "attached table contacts",
                "soft window falloff",
            ],
            "far_plane_softness": "moderate",
            "atmospheric_separation": "mild",
        },
        "lighting": {
            "source_type": "soft_window",
            "direction": "large upper-left and slightly back window source toward lower-right",
            "source_size": "large",
            "hardness": 0.18,
            "contrast": 0.40,
            "shadow": "short attached contacts with broad lower-right penumbra",
            "highlight": "rolled paper white, broad transparent rim lift and small irregular ice responses",
            "transmitted_light": "subtle and physically bounded inside transparent user-product paths only",
            "white_balance": "slightly_warm",
        },
        "color": {
            "exposure": "balanced",
            "saturation": "restrained",
            "contrast": "soft",
            "black_point": "natural",
            "palette_hex": PALETTE,
            "mean_luminance": 0.5843,
            "luminance_stddev": 0.4934,
            "mean_saturation": 0.2105,
            "edge_energy": 0.0453,
        },
        "facets": {
            "mood_tags": ["quiet", "low-saturation", "warm-neutral", "natural-cafe"],
            "environment_tags": ["window", "cafe", "gray-exterior"],
            "material_tags": ["pale-live-edge-wood", "paper", "transparent-container"],
            "shot_tags": ["tabletop", "closeup", "relational-pair"],
        },
        "taxonomy": {
            "environment_family": "warm_wood",
            "lighting_family": "soft_window",
            "camera_angle": "slightly_above",
            "capture_style": "group",
            "scene_complexity": "pair",
            "dominant_surface": "pale matte live-edge wood table",
            "wood_prominence": 0.72,
            "accent_color_prominence": 0.16,
            "frontend_mood": "wood",
            "frontend_angle": "slightly_above",
            "confidence": 0.98,
        },
        "runtime_policy": {
            "scene_pixels_allowed": False,
            "container_pixels_allowed": True,
            "copy_exclusions": [
                "reference latte recipe, milk diffusion, ice and straw",
                "reference Americano recipe and exact crema pattern",
                "all reference text, labels, logos and body copy",
                "exact plant, window, street and table-grain geometry",
                "exact crop, shadow, reflection and highlight shapes",
            ],
            "maximum_exact_products": 1,
            "maximum_generic_companions": 1,
            "maximum_major_subjects": 3,
            "maximum_props": 2,
        },
        "quality_flags": [],
    }


def build_mood_package() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "mood_package_id": PRESET_ID,
        "display_name": "인스타그램 우드 저채도 창가 클로즈업 v1",
        "preset_path": f"{EDITORIAL_ROOT}/reference-preset.json",
        "runtime_profile_path": "presets/editorial/runtime-profile-v1.json",
        "scene_recipe_path": f"{MOOD_ROOT}/scene-recipe.json",
        "lighting_sheet_path": f"{MOOD_ROOT}/lighting-sheet.json",
        "grade_profile_path": f"{MOOD_ROOT}/grade-profile.json",
        "photographic_style_contract_path": f"{EDITORIAL_ROOT}/photographic-style-contract.json",
        "product_integration_contract_path": "presets/editorial/product-integration-contract-v1.json",
        "reference_control_board_path": CONTROL_RELATIVE_PATH,
        "reference_control_board_manifest_path": CONTROL_MANIFEST_RELATIVE_PATH,
        "runtime_reference_policy": "offline_contract_only",
        "compatibility": {
            "composition_modes": ["front_left_exact_product_with_one_behind_right_companion"],
            "materials": ["glass", "plastic", "paper", "ceramic"],
        },
    }


def build_lighting_sheet() -> dict[str, Any]:
    baseline = read_json(
        ROOT / "presets/moods/tokyo_a6_relational_scene_hint_v4/lighting-sheet.json"
    )
    baseline.update(
        {
            "lighting_sheet_id": "instagram_wood_calm_window_closeup_sheet_v1",
            "mood": "quiet low-saturation cafe closeup on pale live-edge wood under one large diffused window",
            "reference_cluster": {
                "anchor_preset_id": PRESET_ID,
                "minimum_cluster_size": 4,
                "runtime_pixels_allowed": False,
                "selection_rule": "the user-approved reference is the sole geometric anchor; broad warm-wood cluster evidence only bounds plausible material and window-light behavior",
                "source_images": [
                    REFERENCE_RELATIVE_PATH,
                    "../assets/references/wood/wood_closeup_cafe_latte_reference.png",
                    "comfyui-inputs/ad_creator_reference_a6.jpg",
                    "comfyui-inputs/ad_creator_original_input_01.jpg",
                ],
            },
            "key_light": {
                "source": "one large diffused upper-left window",
                "direction": "upper-left and slightly behind toward lower-right",
                "relative_size": "very large apparent source producing broad low-contrast transitions",
                "subject_to_wall_distance_cm": [70, 130],
                "azimuth_degrees": [300, 330],
                "elevation_degrees": [32, 46],
                "angular_size_degrees": [38, 62],
                "distance_class": "near-window diffuse daylight",
            },
            "ambient_fill": "quiet neutral room and pale-sill bounce opens paper, ice and wood without flattening contacts",
            "reference_anchor": {
                "asset_id": ASSET_ID,
                "pixel_sha256": PIXEL_SHA256,
                "role": "offline camera, pair geometry, pale-wood, diffused-light and restrained-tone evidence; only the sanitized scene hint may carry low-frequency relationships",
            },
            "fill_contract": {
                "key_to_fill_ratio": [1.25, 1.70],
                "source": "window sill, pale table and quiet neutral room bounce",
                "color_bias": "neutral to faintly cool outside the local warm wood",
            },
            "screen_light_map": {
                "lit_area_ratio": [0.58, 0.76],
                "shadow_area_ratio": [0.16, 0.30],
                "dominant_shadow_vector_degrees": [118, 150],
                "falloff": "broad upper-left window illumination rolls gently through both drinks to soft lower-right contacts",
                "gobo_geometry": "none; keep the source large and avoid copied window-frame or plant-shadow silhouettes",
            },
            "specular_contract": {
                "highlight_shape": "broad interrupted transparent edges, rolled paper white, tiny irregular ice responses and sparse condensation sparkle",
                "highlight_width_ratio": [0.10, 0.28],
                "rim_continuity": "readable but naturally interrupted by viewing angle, paper fibers, ice and condensation",
                "transparent_caustic": "subtle, local and bounded to real transparent paths",
            },
            "camera_coupling": {
                "support_plane": "45-55mm view at 85-130cm and 18-28 degrees above one round pale live-edge table",
                "shadow_projection": "both drink contacts share a 118-150 degree lower-right direction with broad penumbrae",
                "depth_response": "primary overlap, companion scale, table ellipse and soft window falloff establish depth before background blur",
            },
            "color_separation": {
                "lit_neutral": "warm-neutral daylight below clipping",
                "shadow_neutral": "neutral brown-gray with slight cool exterior influence",
                "material_locality": "warm beige-brown stays local to wood; paper remains neutral white, exterior remains cool gray and the exact user beverage retains source color",
            },
            "qa_geometry": {
                "shadow_vector_tolerance_degrees": 18,
                "lit_area_tolerance": 0.12,
                "penumbra_ratio_tolerance": 0.12,
            },
            "shadow_contract": {
                "density": [0.16, 0.30],
                "edge": "broad soft environmental falloff with denser compact contacts under both drinks",
                "attachment": "each drink base intersects the same wood plane with no floating gap or pasted halo",
                "transparent_material": "bounded drink-colored transmission only where the exact user product is physically transparent",
                "contact_shadow": {
                    "opacity": [0.20, 0.36],
                    "footprint": [0.05, 0.15],
                    "behavior": "small dense attached ellipses under both drink bases",
                },
                "cast_shadow": {
                    "opacity": [0.08, 0.18],
                    "footprint": [0.16, 0.44],
                    "behavior": "short overlapping lower-right shadows with broad soft edges",
                },
                "transmitted_light": {
                    "opacity": [0.04, 0.14],
                    "footprint": [0.08, 0.28],
                    "behavior": "subtle bounded lift inside physically transparent product paths only",
                },
                "qa_ratios": {
                    "cast_area_to_cup_bbox": [0.16, 0.56],
                    "wrist_length_to_cup_height": [0.0, 0.01],
                    "transparent_lift_inside_shadow": [0.03, 0.18],
                },
            },
            "capture_contract": {
                "exposure_compensation_ev": [-0.16, 0.08],
                "hdr": "restrained single-exposure response with protected paper and window highlights",
                "white_balance": "4750-5100K warm-neutral daylight with source-authoritative product color",
                "texture": "finite social-photo acuity, matte wood pores, paper fibers, irregular ice, crema bubbles and nonuniform condensation",
            },
            "grade_strengths": {"natural": 0.24, "balanced": 0.34, "expressive": 0.30},
            "forbidden": [
                "hard studio spotlight",
                "multiple conflicting catchlights",
                "orange or yellow wash",
                "glossy synthetic wood",
                "clipped paper white",
                "glowing geometric ice",
                "flat crema",
                "detached contact shadow",
                "phone HDR",
            ],
        }
    )
    return baseline


def build_scene_recipe() -> dict[str, Any]:
    return {
        "$schema": "../../../schemas/scene-recipe.schema.json",
        "schema_version": "1.0.0",
        "recipe_id": PRESET_ID,
        "display_name": "우드 저채도 창가 음료 페어 장면 v1",
        "compatible_presets": [PRESET_ID],
        "generation_policy": {
            "normal_paid_generations": 1,
            "runtime_reference_image": False,
            "traditional_compositing": False,
        },
        "composition": {
            "inherit_preset_bbox": True,
            "subject_anchor_priority": "exact user product front-left at 0.27-0.34 frame width and 0.42-0.52 frame height; one smaller generic companion remains behind-right",
            "asymmetry_sources": [
                "front-back stagger",
                "unequal beverage scale",
                "irregular round live-edge table crop",
                "soft plant and window release",
            ],
        },
        "environment": {
            "background_plane": "a new low-detail window sill and cool gray exterior with one indistinct green plant mass",
            "surface_character": "one round pale matte live-edge wood table with subdued growth rings and a naturally irregular edge",
            "sun_patch_shape": "none; broad diffuse window illumination only",
        },
        "lighting": {
            "source": "one very large diffused upper-left window plus quiet room bounce",
            "direction": "azimuth 300-330 degrees and elevation 32-46 degrees",
            "shadow_description": "dense attached base contacts transitioning to broad soft lower-right falloff",
            "light_softness": [0.78, 0.92],
            "subject_to_wall_distance_cm": [70, 130],
            "shadow_density": [0.16, 0.30],
            "global_contrast": [0.34, 0.50],
            "background_lightness": [0.56, 0.76],
            "ambient_fill": "neutral sill and room bounce keeps paper, ice, beverage and wood independently readable",
            "exposure_compensation_ev": [-0.16, 0.08],
            "sun_patch_coverage": [0.0, 0.04],
            "highlight_behavior": "rolled paper white, broad transparent edges, irregular ice and sparse condensation sparkle",
            "shadow_temperature": "neutral brown-gray with slight cool exterior influence",
        },
        "capture": {
            "rendering_pipeline": "natural social capture with finite handheld acuity and one coherent exposure",
            "shadow_processing": "keep attached contacts and soft penumbrae without HDR lifting or product spotlighting",
            "local_texture": "preserve exact user-product evidence while rebuilding realistic rim thickness, ice, liquid boundaries, condensation and table contact under target light",
            "forbidden_processing": [
                "phone HDR",
                "uniform hyper-sharpness",
                "orange filter",
                "AI-clean smoothing",
                "synthetic portrait blur",
                "cutout edge enhancement",
            ],
        },
        "human_rendering": {
            "skin_texture": "no hand unless a separate user contract explicitly requires one",
            "light_response": "any separately authorized skin must share the same upper-left diffuse window light",
            "forbidden": ["invented hand", "extra fingers", "decorative sleeve", "unrelated warm skin cast"],
        },
        "material_rules": {
            "glass": "transparent containers show finite rim and base thickness, plausible refraction, irregular ice, local condensation and attached contact",
            "plastic": "thin realistic highlights and plausible condensation remain distinct from glass thickness, paper fibers and liquid boundaries",
        },
        "coupling_rules": [
            "Exactly one source-authoritative user product occupies the front-left primary slot.",
            "One smaller generic unbranded text-free double-paper-cup iced Americano remains behind-right with irregular ice and rich fine crema.",
            "Both drinks rest physically on one round pale matte live-edge wood table.",
            "The user product preserves its source container, branding, recipe color and serving state while its optics and shadow are rebuilt under target light.",
            "Reference latte contents, labels, Americano text, exact plant, window and table grain never transfer.",
            "One broad diffused upper-left window source controls the full scene without an amber grade.",
        ],
        "forbidden": [
            "duplicate user product",
            "extra drink",
            "missing or oversized companion",
            "reference or invented text on the companion",
            "pasted container boundary",
            "floating drink",
            "perfect geometric ice",
            "airbrushed milk or liquid",
            "flat crema",
            "glossy orange wood",
        ],
        "quality_gate": {
            "hard_fail": [
                "exact product count, identity, container, branding or serving state fails",
                "primary bbox or front-left placement fails",
                "one behind-right text-free double-paper-cup companion fails",
                "reference text appears",
                "container integration, ice, liquid, crema, condensation or contact shadow reads as synthetic",
                "pale matte wood or one-source soft-window contract fails",
            ],
            "weights": {
                "camera_geometry": 0.18,
                "composition_rhythm": 0.20,
                "color_and_tone": 0.15,
                "lighting_space": 0.17,
                "product_identity": 0.25,
                "brand_integrity": 0.05,
            },
        },
    }


def build_grade_profile() -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "grade_profile_id": "instagram_wood_calm_window_closeup_grade_v1",
        "input_color_space": "sRGB",
        "output_color_space": "sRGB",
        "transform": {
            "exposure_ev": 0.02,
            "contrast": 0.94,
            "saturation": 0.90,
            "warmth": 0.05,
            "shadow_lift": 0.015,
            "highlight_rolloff": 0.22,
        },
        "tone_curve": [[0.0, 0.015], [0.18, 0.19], [0.50, 0.50], [0.82, 0.80], [1.0, 0.97]],
        "split_tone": {
            "shadow_rgb": [0.49, 0.50, 0.52],
            "highlight_rgb": [0.54, 0.51, 0.47],
            "balance": 0.50,
            "strength": 0.025,
        },
        "selective_saturation": {"red": 0.96, "yellow": 0.88, "green": 0.92, "cyan": 0.94, "blue": 0.92, "magenta": 0.96},
        "local_contrast": {"radius": 2.2, "amount": 0.12, "threshold": 7},
        "strength": {"default": 0.24, "min": 0.12, "max": 0.40},
        "protection": {"regions": ["product", "logo"], "mask_strength": 0.94},
        "qa_limits": {"max_dark_clip_ratio": 0.006, "max_bright_clip_ratio": 0.010},
    }


def build_wood_material_profile() -> dict[str, Any]:
    return {
        "schema_version": "3.1.0",
        "status": "draft",
        "family_axes": {
            "lightness": "light",
            "color_family": "brown",
            "grain_pattern": "cathedral",
            "finish": "raw-matte",
        },
        "appearance": {
            "lab": {
                "median": [65.0, 6.5, 14.5],
                "p10": [42.0, 5.0, 10.0],
                "p90": [78.0, 7.5, 18.0],
            },
            "chroma": 15.9,
            "grain_direction_degrees": 7.0,
            "grain_frequency": 0.11,
            "grain_contrast": 0.22,
            "surface_occupancy": None,
            "surface_occupancy_basis": "unavailable",
            "observed_lab": None,
        },
        "confidence": 0.68,
        "species": "unknown",
        "source_pixel_sha256": PIXEL_SHA256,
        "artifact": None,
        "measurement_evidence": None,
    }


def make_scene_hint() -> dict[str, Any]:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CONTROL_DIR / "scene-hint.png"
    manifest_path = CONTROL_DIR / "scene-hint-manifest.json"
    with Image.open(REFERENCE_SOURCE) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    square = ImageOps.fit(source, (768, 768), method=Image.Resampling.LANCZOS)
    square = square.resize((192, 192), Image.Resampling.LANCZOS).resize((768, 768), Image.Resampling.BICUBIC)
    square = square.filter(ImageFilter.GaussianBlur(5.5))

    # Replace both source drink identities and all labels with neutral low-frequency
    # placeholders. Geometry remains; source beverage pixels and copy do not.
    # Remove the source-only straw against a row-matched low-frequency field so
    # the control board cannot accidentally request a straw for every product.
    straw_fill = square.crop((20, 0, 180, 768)).resize((768, 768), Image.Resampling.BICUBIC)
    straw_fill = straw_fill.filter(ImageFilter.GaussianBlur(24))
    straw_mask = Image.new("L", square.size, 0)
    ImageDraw.Draw(straw_mask).line((190, 38, 360, 440), fill=255, width=112)
    straw_mask = straw_mask.filter(ImageFilter.GaussianBlur(8))
    square.paste(straw_fill, (0, 0), straw_mask)

    overlay = Image.new("RGB", square.size, "#A99987")
    primary_mask = Image.new("L", square.size, 0)
    draw = ImageDraw.Draw(primary_mask)
    draw.rounded_rectangle((218, 286, 497, 708), radius=60, fill=255)
    primary_mask = primary_mask.filter(ImageFilter.GaussianBlur(24))
    square.paste(overlay, (0, 0), primary_mask)

    paper = Image.new("RGB", square.size, "#E4DFD8")
    companion_mask = Image.new("L", square.size, 0)
    draw = ImageDraw.Draw(companion_mask)
    draw.rounded_rectangle((438, 222, 647, 606), radius=42, fill=255)
    companion_mask = companion_mask.filter(ImageFilter.GaussianBlur(20))
    square.paste(paper, (0, 0), companion_mask)

    plant_blur = square.filter(ImageFilter.GaussianBlur(24))
    plant_mask = Image.new("L", square.size, 0)
    ImageDraw.Draw(plant_mask).ellipse((330, 142, 585, 405), fill=255)
    plant_mask = plant_mask.filter(ImageFilter.GaussianBlur(24))
    square.paste(plant_blur, (0, 0), plant_mask)

    plate = Image.new("RGB", (768, 1024), "#C3B5A7")
    top = square.crop((0, 0, 768, 1)).resize((768, 128), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(10))
    bottom = square.crop((0, 767, 768, 768)).resize((768, 128), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(8))
    plate.paste(top, (0, 0))
    plate.paste(square, (0, 128))
    plate.paste(bottom, (0, 896))
    softened = plate.filter(ImageFilter.GaussianBlur(7.0))
    seam_mask = Image.new("L", plate.size, 0)
    seam_draw = ImageDraw.Draw(seam_mask)
    seam_draw.rectangle((0, 108, 768, 148), fill=255)
    seam_draw.rectangle((0, 876, 768, 916), fill=255)
    seam_mask = seam_mask.filter(ImageFilter.GaussianBlur(18.0))
    plate.paste(softened, (0, 0), seam_mask)
    plate = plate.resize((384, 512), Image.Resampling.LANCZOS).resize((768, 1024), Image.Resampling.BICUBIC)
    plate = plate.filter(ImageFilter.GaussianBlur(0.4))
    plate.save(output_path, format="PNG", optimize=True)

    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "sanitized_photographic_scene_hint",
        "policy_version": "wood_window_closeup_scene_hint_v1",
        "role": "scene_hint",
        "path": str(output_path.resolve()),
        "relative_path": CONTROL_RELATIVE_PATH,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_relative_path": CONTROL_MANIFEST_RELATIVE_PATH,
        "width_px": 768,
        "height_px": 1024,
        "aspect_ratio": "3:4",
        "sha256": sha256_file(output_path),
        "pixel_sha256": pixel_sha256(output_path),
        "source_binding": {
            "asset_id": ASSET_ID,
            "path": str(REFERENCE_SOURCE.resolve()),
            "sha256": FILE_SHA256,
            "pixel_sha256": PIXEL_SHA256,
            "width_px": 1254,
            "height_px": 1254,
        },
        "construction": {
            "canvas_px": [768, 1024],
            "source_square_placement_px": {"left": 0, "top": 128, "right": 768, "bottom": 896},
            "background_low_pass": {"intermediate_px": [192, 192], "gaussian_blur_px": 5.5},
            "identity_masks": [
                {"mask_id": "primary_beverage_and_label", "bbox": [0.28, 0.07, 0.65, 0.92], "operation": "neutral low-frequency placeholder"},
                {"mask_id": "secondary_cup_and_text", "bbox": [0.57, 0.29, 0.85, 0.79], "operation": "unmarked paper low-frequency placeholder"},
                {"mask_id": "plant_identity", "bbox": [0.43, 0.18, 0.76, 0.53], "operation": "strong low-pass only"},
            ],
            "final_information_ceiling_px": [384, 512],
            "canvas_extension": "stretched low-frequency top and bottom fields with feathered seams and no panels or labels",
        },
        "retained_relationships": [
            "large front-left product slot and smaller behind-right companion",
            "both subjects supported by one round pale live-edge wood table",
            "soft upper-left window field and cool-gray exterior separation",
            "low-frequency plant mass behind the pair",
            "restrained warm-neutral palette and close camera scale",
        ],
        "forbidden_transfer": [
            "reference latte identity, recipe, milk diffusion, ice or straw",
            "reference Americano recipe or exact crema pattern",
            "cafe latte, CAFE AMERICANO or any reference label or body copy",
            "exact plant, window, exterior or table grain",
            "exact crop, reflections, highlights, shadows or source pixels",
        ],
        "sanitation": {
            "visible_labels": False,
            "technical_panels": False,
            "panel_boundaries": False,
            "borderless_photo_like_plate": True,
            "beverage_interiors_neutralized": True,
            "unique_background_objects_strongly_low_passed": True,
            "raw_reference_provider_submission_allowed": False,
        },
        "checks": [
            {"check_id": "dimensions_3_by_4", "status": "pass", "evidence": {"observed_px": [768, 1024]}},
            {"check_id": "no_technical_panels_or_labels_drawn", "status": "pass", "evidence": {"drawing_operations": "low-pass photo plate and identity masks only"}},
            {"check_id": "source_product_and_copy_masks_applied", "status": "pass", "evidence": {"mask_ids": ["primary_beverage_and_label", "secondary_cup_and_text", "plant_identity"]}},
            {"check_id": "output_differs_from_raw_source", "status": "pass" if pixel_sha256(output_path) != PIXEL_SHA256 else "fail", "evidence": {"output_pixel_sha256": pixel_sha256(output_path), "source_pixel_sha256": PIXEL_SHA256}},
        ],
    }
    manifest["manifest_content_sha256"] = canonical_json_sha256(manifest)
    write_json(manifest_path, manifest)
    return manifest


def update_catalog(scene_graph: dict[str, Any]) -> None:
    database_path = ROOT / "data/reference-library/catalog.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO reference_assets (
                asset_id, relative_path, pixel_sha256, file_sha256, dhash,
                width_px, height_px, source_group, duplicate_of,
                analysis_status, analysis_json, failure
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                relative_path=excluded.relative_path,
                pixel_sha256=excluded.pixel_sha256,
                file_sha256=excluded.file_sha256,
                dhash=excluded.dhash,
                width_px=excluded.width_px,
                height_px=excluded.height_px,
                source_group=excluded.source_group,
                duplicate_of=excluded.duplicate_of,
                analysis_status=excluded.analysis_status,
                analysis_json=excluded.analysis_json,
                failure=excluded.failure
            """,
            (
                ASSET_ID,
                REFERENCE_RELATIVE_PATH,
                PIXEL_SHA256,
                FILE_SHA256,
                "5b42293fe5b43470",
                1254,
                1254,
                "user_approved/wood/soft_window_closeup",
                None,
                "analyzed",
                json.dumps(scene_graph, ensure_ascii=False, sort_keys=True),
                None,
            ),
        )
        connection.commit()


def update_assignments() -> None:
    path = ROOT / "data/reference-library/assignments.json"
    payload = read_json(path)
    payload["assignments"][ASSET_ID] = {
        "analysis_status": "analyzed",
        "canonical_asset_id": ASSET_ID,
        "cluster_id": "warm_wood_soft_window_v1",
        "confidence": 0.98,
        "evidence": [
            "user-approved generated reference",
            "manual visual curation and scene-graph review",
            "environment=warm_wood",
            "lighting=soft_window",
            "camera=slightly_above",
            "scene=pair",
            "mean_luminance=0.5843",
            "mean_saturation=0.2105",
        ],
        "membership": "core",
        "mood_package_path": f"{MOOD_ROOT}/mood-package.json",
        "runtime_capabilities": {
            "cross_kind_slot_ids": ["beverage_primary"],
            "default_target_slot_id": "beverage_primary",
            "replaceable_slot_ids": ["beverage_primary"],
            "supports_cross_kind_replacement": True,
        },
        "taxonomy": {
            "accent_color_prominence": 0.16,
            "camera_angle": "slightly_above",
            "capture_style": "group",
            "confidence": 0.98,
            "dominant_surface": "pale matte live-edge wood table",
            "environment_family": "warm_wood",
            "frontend_angle": "slightly_above",
            "frontend_mood": "wood",
            "lighting_family": "soft_window",
            "scene_complexity": "pair",
            "wood_prominence": 0.72,
        },
    }
    write_json(path, payload)


def mutate_api_workflow(payload: dict[str, Any], *, paid: bool) -> dict[str, Any]:
    workflow = copy.deepcopy(payload)
    workflow["1"]["inputs"]["image"] = "wood_window_product_source.png"
    workflow["3"]["inputs"]["image"] = REFERENCE_RUNTIME_NAME
    workflow["4"]["inputs"]["scene_graph_catalog_path"] = SCENE_GRAPH_RELATIVE_PATH
    workflow["4"]["inputs"]["fallback_mood_package_path"] = f"{MOOD_ROOT}/mood-package.json"
    workflow["5"]["inputs"]["mood_package_path"] = f"{MOOD_ROOT}/mood-package.json"
    request = workflow["6"]["inputs"]
    request.update(
        {
            "container_mode": "preserve_source",
            "container_design_path": "",
            "reference_control_role": "sanitized_scene_hint",
            "container_design_source": "source",
            "auto_paid_repair": False,
            "provider_profile_path": "configs/providers/openai-gpt-image-1-mini.json",
            "seed": 721,
            "quality_tier": "default",
            "target_slot_id": "beverage_primary",
            "placement_mode": "replace",
            "product_kind": "beverage",
            "cross_kind_replacement": True,
            "unbound_slot_policy": "genericize",
        }
    )
    if paid:
        workflow["7"] = {
            "class_type": "AD_OpenAIImageGenerate",
            "inputs": {
                "request_json": ["6", 2],
                "lighting_sheet_json": ["5", 1],
                "output_root": "outputs/comfyui-openai/wood-window-closeup-v1",
                "provider_config_path": "configs/providers/openai-gpt-image-1-mini.json",
                "evaluator_config_path": "configs/evaluator.json",
                "timeout_seconds": 1200,
                "repair_execution": "manual",
            },
        }
    else:
        workflow["7"]["inputs"]["fixture_image_path"] = ""
        workflow["12"]["inputs"]["qa_fixture_path"] = "evals/fixtures/unbranded_scene_pass_qa.json"
    workflow["10"]["inputs"]["filename_prefix"] = "ad_creator/wood_window_closeup_v1"
    workflow["11"]["inputs"]["output_label"] = "ad_creator/wood_window_closeup_v1"
    return workflow


def mutate_gui_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    workflow = copy.deepcopy(payload)
    for node in workflow["nodes"]:
        node_id = int(node["id"])
        if node_id == 1:
            node["widgets_values"] = ["wood_window_product_source.png"]
        elif node_id == 3:
            node["widgets_values"] = [REFERENCE_RUNTIME_NAME]
        elif node_id == 4:
            node["widgets_values"] = [
                "data/reference-library/catalog.sqlite",
                SCENE_GRAPH_RELATIVE_PATH,
                "data/reference-library/assignments.json",
                f"{MOOD_ROOT}/mood-package.json",
            ]
        elif node_id == 5:
            node["widgets_values"] = [f"{MOOD_ROOT}/mood-package.json"]
        elif node_id == 6:
            node["widgets_values"] = [
                "preserve_source",
                "beverage_primary",
                "replace",
                "beverage",
                True,
                "genericize",
                "",
                False,
                "configs/service-features.json",
                "configs/providers/openai-gpt-image-1-mini.json",
                721,
                "default",
                "sanitized_scene_hint",
                "source",
            ]
        elif node_id == 7:
            node["type"] = "AD_OpenAIImageGenerate"
            node["title"] = "OpenAI 이미지 생성 (유료 · 승인 후 실행)"
            node["widgets_values"] = [
                "outputs/comfyui-openai/wood-window-closeup-v1",
                "configs/providers/openai-gpt-image-1-mini.json",
                "configs/evaluator.json",
                1200,
                "manual",
            ]
        elif node_id == 10:
            node["widgets_values"] = ["ad_creator/wood_window_closeup_v1"]
        elif node_id == 11:
            node["widgets_values"] = ["ad_creator/wood_window_closeup_v1"]
    workflow.setdefault("extra", {})["preset_id"] = PRESET_ID
    workflow["extra"]["paid_execution_authorized"] = False
    return workflow


def build_workflows() -> None:
    fake_base = read_json(
        ROOT / "workflows/18_a6_relational_v4_scene_hint_reference_cup_local_fake_api.json"
    )
    paid_base = read_json(
        ROOT / "workflows/18_a6_relational_v4_scene_hint_reference_cup_higgsfield_api.json"
    )
    gui_base = read_json(
        ROOT / "workflows/18_a6_relational_v4_scene_hint_reference_cup_higgsfield.json"
    )
    write_json(
        ROOT / "workflows/22_wood_window_closeup_preserve_source_local_fake_api.json",
        mutate_api_workflow(fake_base, paid=False),
    )
    write_json(
        ROOT / "workflows/22_wood_window_closeup_preserve_source_openai_api.json",
        mutate_api_workflow(paid_base, paid=True),
    )
    write_json(
        ROOT / "workflows/22_wood_window_closeup_preserve_source_openai.json",
        mutate_gui_workflow(gui_base),
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not REFERENCE_SOURCE.is_file():
        raise FileNotFoundError(f"Reference image not found: {REFERENCE_SOURCE}")
    if pixel_sha256(REFERENCE_SOURCE) != PIXEL_SHA256:
        raise ValueError("Reference pixel hash changed; stop and review before rebuilding the preset")
    if sha256_file(REFERENCE_SOURCE) != FILE_SHA256:
        raise ValueError("Reference file hash changed; stop and review before rebuilding the preset")

    REFERENCE_RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REFERENCE_SOURCE, REFERENCE_RUNTIME_PATH)

    preset = build_reference_preset()
    style = build_style_contract()
    scene_graph = build_scene_graph()
    mood = build_mood_package()
    lighting = build_lighting_sheet()
    recipe = build_scene_recipe()
    grade = build_grade_profile()
    material = build_wood_material_profile()

    write_json(ROOT / EDITORIAL_ROOT / "reference-preset.json", preset)
    write_json(ROOT / EDITORIAL_ROOT / "photographic-style-contract.json", style)
    write_json(ROOT / MOOD_ROOT / "mood-package.json", mood)
    write_json(ROOT / MOOD_ROOT / "lighting-sheet.json", lighting)
    write_json(ROOT / MOOD_ROOT / "scene-recipe.json", recipe)
    write_json(ROOT / MOOD_ROOT / "grade-profile.json", grade)
    write_json(ROOT / SCENE_GRAPH_RELATIVE_PATH, scene_graph)
    write_json(
        ROOT / "data/reference-library/materials/wood_window_closeup_live_edge_v1.json",
        material,
    )
    manifest = make_scene_hint()
    update_catalog(scene_graph)
    update_assignments()
    build_workflows()

    print(
        json.dumps(
            {
                "preset_id": PRESET_ID,
                "reference_asset_id": ASSET_ID,
                "scene_hint_pixel_sha256": manifest["pixel_sha256"],
                "paid_execution_authorized": False,
                "status": "built",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
