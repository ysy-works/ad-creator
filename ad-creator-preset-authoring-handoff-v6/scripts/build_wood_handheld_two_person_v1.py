"""Build the static-contract bundle for the Wood Handheld Two-Person preset."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ad_creator.image_contracts import canonical_image_binding
from ad_creator.scene_graph import validate_scene_graph


PRESET_ID = "instagram_wood_handheld_two_person_v1"
ASSET_ID = "ref_c61e3c79a9b4d2ef"
REFERENCE_RELATIVE_PATH = "comfyui-inputs/ad_creator_reference_wood_handheld_two_person_v2.png"
REFERENCE_PATH = ROOT / REFERENCE_RELATIVE_PATH
SCENE_GRAPH_RELATIVE_PATH = (
    "data/reference-library/scene-graphs-v2/ref_c61e3c79a9b4d2ef_wood_handheld_two_person_v1.json"
)
MILD_TILT_SCENE_GRAPH_RELATIVE_PATH = (
    "data/reference-library/scene-graphs-v2/"
    "ref_c61e3c79a9b4d2ef_wood_handheld_two_person_tilt_mild_v1.json"
)
MODERATE_TILT_SCENE_GRAPH_RELATIVE_PATH = (
    "data/reference-library/scene-graphs-v2/"
    "ref_c61e3c79a9b4d2ef_wood_handheld_two_person_tilt_moderate_v1.json"
)
EDITORIAL_ROOT = f"presets/editorial/{PRESET_ID}"
MOOD_ROOT = f"presets/moods/{PRESET_ID}"
CONTROL_ROOT = "data/reference-library/control-boards/wood-handheld-two-person-v1"
CONTROL_RELATIVE_PATH = f"{CONTROL_ROOT}/scene-hint.png"
HINT_INPUT_RELATIVE_PATH = "comfyui-inputs/ad_creator_wood_handheld_two_person_scene_hint_v1.png"
REFERENCE_CUP_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/scene-hint-reference-cup.png"
USER_CUP_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/scene-hint-user-cup.png"
REFERENCE_CUP_HINT_INPUT_RELATIVE_PATH = (
    "comfyui-inputs/ad_creator_wood_handheld_two_person_scene_hint_reference_cup_v1.png"
)
USER_CUP_HINT_INPUT_RELATIVE_PATH = (
    "comfyui-inputs/ad_creator_wood_handheld_two_person_scene_hint_user_cup_v1.png"
)
HOT_POSE_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/pose-hint-hot-v1.png"
HOT_PHOTO_POSE_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/pose-hint-hot-photo-v2.png"
HOT_3D_POSE_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/pose-hint-hot-3d-v2.png"
# The user-approved two-panel board is pose-only for both serving states.
ICED_POSE_HINT_RELATIVE_PATH = HOT_PHOTO_POSE_HINT_RELATIVE_PATH
HOT_SCENE_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/scene-hint-user-hot-v1.png"
HOT_PHOTO_SCENE_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/scene-hint-user-hot-photo-v2.png"
HOT_3D_SCENE_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/scene-hint-user-hot-3d-v2.png"
ICED_SCENE_HINT_RELATIVE_PATH = f"{CONTROL_ROOT}/scene-hint-user-iced-v1.png"
HOT_SCENE_HINT_INPUT_RELATIVE_PATH = (
    "comfyui-inputs/ad_creator_wood_handheld_two_person_scene_hint_hot_v1.png"
)
HOT_PHOTO_SCENE_HINT_INPUT_RELATIVE_PATH = (
    "comfyui-inputs/ad_creator_wood_handheld_two_person_scene_hint_hot_photo_v2.png"
)
HOT_3D_SCENE_HINT_INPUT_RELATIVE_PATH = (
    "comfyui-inputs/ad_creator_wood_handheld_two_person_scene_hint_hot_3d_v2.png"
)
ICED_SCENE_HINT_INPUT_RELATIVE_PATH = (
    "comfyui-inputs/ad_creator_wood_handheld_two_person_scene_hint_iced_v1.png"
)
HOT_TEST_IMAGE = "wood_handheld_hot_cappuccino_saucer_source.png"
HOT_TEST_ANALYSIS = "configs/reviewed-product-analysis-wood-handheld-hot-cappuccino-v1.json"
REFERENCE_CUP_CONTAINER_DESIGN = (
    "presets/container_designs/wood_handheld_compact_ceramic_mug_v1.json"
)
TEST_IMAGE = "white_closeup_matcha_user_source.png"
TEST_ANALYSIS = "configs/reviewed-product-analysis-wood-handheld-matcha-user-v1.json"
REFERENCE_CUP_TEST_ANALYSIS = (
    "configs/reviewed-product-analysis-wood-handheld-matcha-reference-cup-v1.json"
)

BASE_PRESET = ROOT / "presets/editorial/instagram_wood_calm_window_closeup_v1/reference-preset.json"
BASE_STYLE = ROOT / "presets/editorial/instagram_wood_calm_window_closeup_v1/photographic-style-contract.json"
BASE_MOOD = ROOT / "presets/moods/instagram_wood_calm_window_closeup_v1/mood-package.json"
BASE_RECIPE = ROOT / "presets/moods/instagram_wood_calm_window_closeup_v1/scene-recipe.json"
BASE_LIGHTING = ROOT / "presets/moods/instagram_wood_calm_window_closeup_v1/lighting-sheet.json"
BASE_GRADE = ROOT / "presets/moods/instagram_wood_calm_window_closeup_v1/grade-profile.json"
BASE_ANALYSIS = ROOT / "configs/reviewed-product-analysis-white-closeup-matcha-user-v1.json"
BASE_LOCAL_WORKFLOW = ROOT / "workflows/23b_wood_window_closeup_strawberry_source_cup_local_fake_api.json"
BASE_PAID_WORKFLOW = ROOT / "workflows/23b_wood_window_closeup_strawberry_source_cup_higgsfield_api.json"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bbox(left: float, top: float, right: float, bottom: float, confidence: float = 0.98) -> dict[str, Any]:
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "confidence": confidence,
    }


def no_straw() -> dict[str, Any]:
    return {
        "present": False,
        "bbox": None,
        "centerline": None,
        "emergence_point": None,
        "angle_degrees": None,
    }


def build_scene_hint(path: Path, *, target_cup_mode: str = "reference") -> None:
    """Build a non-contiguous evidence board that cannot act as a scene template."""
    if target_cup_mode not in {"reference", "user", "hot", "hot_photo", "hot_3d", "iced"}:
        raise ValueError(f"Unsupported target cup mode: {target_cup_mode}")
    width, height = 1125, 1500
    source = Image.open(REFERENCE_PATH).convert("RGB")
    if source.size != (width, height):
        source = source.resize((width, height), Image.Resampling.LANCZOS)

    image = Image.new("RGB", (width, height), "#e6e0d5")
    panel_boxes = [
        (18, 18, 553, 741),
        (571, 18, 1107, 741),
        (18, 759, 553, 1482),
        (571, 759, 1107, 1482),
    ]
    evidence = [
        # Upper companion: leather clothing, hand anatomy, ceramic cup and drink.
        ((0, 275, 650, 900), 2.2, 0.45, 0.0),
        # Lower target carrier: bare wrist/hair tie, hand grip, cup and drink.
        ((120, 845, 730, 1500), 2.2, 0.45, 0.0),
        # Peripheral context: croissant/plate, magazine and both saucers.
        ((650, 125, 1125, 1165), 6.0, 2.0, 2.2),
        # Material/photometry: pale wood grain direction, sill and cloudy window field.
        ((100, 0, 900, 450), 2.8, 0.65, 0.0),
    ]

    for panel_index, (panel_box, (crop_box, reduction, blur_radius, post_blur)) in enumerate(
        zip(panel_boxes, evidence)
    ):
        panel_width = panel_box[2] - panel_box[0]
        panel_height = panel_box[3] - panel_box[1]
        region = source.crop(crop_box)
        if panel_index == 1 and target_cup_mode in {"hot", "hot_photo", "hot_3d", "iced"}:
            pose_path = ROOT / {
                "hot": HOT_POSE_HINT_RELATIVE_PATH,
                "hot_photo": HOT_PHOTO_POSE_HINT_RELATIVE_PATH,
                "hot_3d": HOT_3D_POSE_HINT_RELATIVE_PATH,
                "iced": ICED_POSE_HINT_RELATIVE_PATH,
            }[target_cup_mode]
            region = Image.open(pose_path).convert("RGB")
            reduction, blur_radius, post_blur = 1.7, 0.35, 0.0
        if target_cup_mode == "user" and panel_index == 1:
            # Extract only the target hand/wrist pixels around the cup. A flat
            # cup-shaped cover would itself become a geometry hint, so the
            # reference cup interior, body and handle are excluded entirely.
            neutral = Image.new("RGB", region.size, "#cbc5ba")
            _, cb, cr = region.convert("YCbCr").split()
            cb_skin = cb.point(lambda value: 255 if 72 <= value <= 142 else 0)
            cr_skin = cr.point(lambda value: 255 if 122 <= value <= 188 else 0)
            skin_mask = ImageChops.multiply(cb_skin, cr_skin)
            pose_mask = Image.new("L", region.size, 0)
            pose_draw = ImageDraw.Draw(pose_mask)
            pose_draw.polygon(
                [(105, 105), (205, 55), (300, 100), (455, 205), (455, 340),
                 (350, 390), (315, 655), (105, 655), (125, 355)],
                fill=255,
            )
            pose_draw.ellipse((155, 42, 500, 335), fill=0)
            pose_draw.rounded_rectangle((205, 150, 500, 350), radius=70, fill=0)
            skin_mask = ImageChops.multiply(skin_mask, pose_mask)
            skin_mask = skin_mask.filter(ImageFilter.GaussianBlur(1.6))
            region = Image.composite(region, neutral, skin_mask)
            draw = ImageDraw.Draw(region)
            draw.line((210, 548, 335, 554), fill="#393735", width=12)
        reduced = region.resize(
            (
                max(48, round(region.width / reduction)),
                max(48, round(region.height / reduction)),
            ),
            Image.Resampling.LANCZOS,
        )
        reduced = reduced.filter(ImageFilter.GaussianBlur(blur_radius))
        region = reduced.resize(region.size, Image.Resampling.BICUBIC)
        region = ImageEnhance.Color(region).enhance(0.82)
        region = ImageEnhance.Contrast(region).enhance(0.94)
        fitted = ImageOps.contain(
            region,
            (panel_width - 18, panel_height - 18),
            Image.Resampling.LANCZOS,
        )
        if post_blur:
            fitted = fitted.filter(ImageFilter.GaussianBlur(post_blur))
        panel = Image.new("RGB", (panel_width, panel_height), "#d7d1c7")
        panel.paste(
            fitted,
            ((panel_width - fitted.width) // 2, (panel_height - fitted.height) // 2),
        )
        image.paste(panel, panel_box[:2])

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def build_reference_preset(binding: dict[str, Any]) -> dict[str, Any]:
    preset = copy.deepcopy(read_json(BASE_PRESET))
    preset.update(
        {
            "preset_id": PRESET_ID,
            "display_name": "우드 손잡이 투컵 샷",
            "display_name": "우드 저채도 투인 핸드헬드",
            "concept": "two_seated_cafe_goers_holding_two_drinks_beneath_a_pale_wood_window_counter",
            "source": {
                "reference_image": REFERENCE_RELATIVE_PATH,
                "width_px": binding["width_px"],
                "height_px": binding["height_px"],
                "supporting_group": "user_approved/wood/handheld/two_person/v2",
            },
            "runtime_input_policy": {
                "default_generation_mode": "user_image_plus_static_relational_scene_hint",
                "generation_inputs": ["user_product_identity", "static_relational_scene_hint"],
                "reference_usage": "offline_feature_extraction_only",
                "copyright_rule": "Image 1 exclusively supplies the exact user beverage and complete user cup. Image 2 is a fixed spatial-and-hand-pose hint: it controls the crop topology, lower bare-wrist grip, upper-left leather-sleeved grip, two cup positions, counter/window/prop geometry and diffuse photometric field. Reconstruct a new photograph; do not transfer readable magazine text, a logo, source latte art, exact pixels or identities.",
            },
            "style_abstraction": {
                "runtime_reference_image": False,
                "novel_scene_required": True,
                "allowed_style_features": [
                    "one exact iced user beverage held lower-centre at 20-22 percent of frame width and 26-29 percent of frame height, with a natural tilted open-top and visible-sidewall view",
                    "one smaller generic hot ceramic companion cup held by the upper-left seated companion",
                    "two anonymous adult hands and two clothing cues only: dark leather at upper-left and a bare lower left wrist above two separately readable dark-clothed thighs",
                    "pale matte oak window counter, broad white-gray window ledge, partial pastry plate, neutral magazine and white saucer context",
                    "one cloud-filtered upper-right rear window source with soft lower-left shadow falloff and faded low-saturation afternoon-film response",
                ],
                "forbidden_copy_features": [
                    "faces, identities, nails, jewelry or fashion branding",
                    "readable magazine lettering, book title, logo or watermark",
                    "exact latte art, crema pattern or source beverage recipe",
                    "exact wood knots, exterior pixels, reflections, crop pixels or hand skin identity",
                    "a third person, additional hands, additional drinks or a cluttered tabletop",
                ],
            },
            "sampling_ranges": {
                "pov_modes": ["high-oblique seated window-side cafe observation"],
                "subject_center_x": [0.43, 0.48],
                "subject_center_y": [0.62, 0.68],
                "subject_width_ratio": [0.20, 0.22],
                "subject_height_ratio": [0.26, 0.29],
                "negative_space_ratio": [0.18, 0.25],
                "focal_length_mm": [45, 52],
                "camera_pitch_degrees": [48, 56],
                "light_softness": [0.84, 0.92],
                "prop_count": [2, 2],
                "asymmetry_probability": 1.0,
                "asymmetry_sources": [
                    "two hands at staggered heights",
                    "held primary beneath smaller held companion",
                    "window counter receding to the upper-right",
                    "cropped pastry and magazine context on the right",
                ],
                "micro_moments": ["two friends quietly holding drinks beside a pale wood cafe window"],
            },
            "tone_contract": {
                "background_plane": "pale oak counter and white-gray window ledge recede above the two held drinks",
                "background_lightness": [0.52, 0.73],
                "background_saturation": [0.04, 0.13],
                "global_contrast": [0.34, 0.46],
                "shadow_density": [0.2, 0.34],
                "color_bias": "cloudy neutral-gray afternoon daylight; pale oak is locally faded beige, while ceramics/window lean cool-neutral and clothing falls to charcoal without crushing texture",
                "highlight_behavior": "broad muted ceramic and ice highlights with a soft film shoulder; never clipped white plates, paper-white milk or glossy CGI skin",
                "forbidden_surface_reading": [
                    "orange or yellow filter",
                    "plastic wood",
                    "flat skin",
                    "black-clipped clothing",
                    "neon beverage",
                    "AI-clean global smoothing",
                ],
            },
            "output": {"preferred_aspect_ratio": "3:4", "compatible_aspect_ratios": ["3:4", "4:5"]},
            "subject_layout": {
                "main_subject": {
                    "role": "one exact user beverage held lower-centre by the 6 o'clock hand, shown with a credible visible sidewall",
                    "center": {"x_ratio": 0.455, "y_ratio": 0.605},
                    "bbox": {"x_ratio": 0.348, "y_ratio": 0.458, "width_ratio": 0.214, "height_ratio": 0.282},
                    "area_ratio": 0.060,
                    "height_ratio": 0.282,
                },
                "secondary_subjects": [
                    {
                        "role": "one generic small hot ceramic companion cup held at upper-left",
                        "center": {"x_ratio": 0.44, "y_ratio": 0.46},
                        "bbox": {"x_ratio": 0.32, "y_ratio": 0.34, "width_ratio": 0.25, "height_ratio": 0.22},
                        "area_ratio": 0.055,
                        "height_ratio": 0.22,
                    }
                ],
                "negative_space": {"top_ratio": 0.10, "left_ratio": 0.03, "right_ratio": 0.02, "bottom_ratio": 0.03},
            },
            "composition": {
                "shot_type": "high-oblique intimate two-person cafe observation, with both hands and cups visible but faces absent",
                "camera_angle": "48-56 degree downward pitch across the lower hand toward the upper-right window counter",
                "camera_height": "approximately 125-145 centimetres above the held lower drink",
                "focal_length_equivalent_mm": 49,
                "horizon_visibility": "only the pale window ledge and exterior gray band remain readable along the upper edge",
                "depth_of_field": "both held cups, hands, pastry edge and magazine/saucer cluster resolve; exterior microtexture alone may soften",
                "alignment": "lower-centre exact user cup remains hand-held below the smaller upper-left ceramic companion; right-side props remain cropped environmental evidence",
            },
            "lighting": {
                "type": "one large diffuse upper-right rear window source plus subdued room bounce",
                "direction": "upper-right window counter toward the lower-left hands and laps",
                "azimuth_degrees": 48,
                "elevation_degrees": 44,
                "softness": 0.84,
                "intensity": "cloud-filtered protected afternoon daylight at minus 0.34 to minus 0.16 EV, never a sunny or golden-hour beam",
                "contrast": "faded low-to-moderate directional contrast with dark but textured clothing, a gentle film shoulder and broad penumbrae",
                "shadow": "compact occlusion at fingers and cup bases, then broad soft lower-left falloff along the counter and laps",
                "highlight_control": "window whites, saucers, ceramic rims and ice retain finite rolloff below clipping",
            },
            "color": {
                "temperature": "5400-5750K cloudy neutral-gray afternoon daylight; warmth remains local to faded oak and coffee, never a yellow or sunset wash",
                "white_balance_kelvin": 5580,
                "saturation": "6-10 percent faded natural color density; protect user beverage layer order without neon green, golden wood or isolated milky-white lift",
                "contrast": "soft compressed highlight shoulder and a gently opened film toe, while charcoal fabric texture and attached contact shadows remain visible",
                "palette_hex": ["#B8AA92", "#938879", "#39393A", "#D9DBD9", "#AAB1B2"],
                "black_point": "soft neutral charcoal with leather grain, trouser folds and hand separation visible; no crushed void and no gray haze",
            },
            "scene": {
                "surface": "pale matte oak window counter with real long grain and small natural tonal variation; retain its diagonal recession but invent a new grain phase",
                "background": "white-gray window ledge and a restrained exterior band above the counter",
                "background_complexity": 0.28,
                "props": [
                    "one partial white pastry plate with one croissant at upper-right",
                    "one neutral magazine partly occupied by a white saucer plus one small empty saucer near the upper centre",
                ],
                "max_prop_count": 2,
                "texture": "pale oak pores, matte ceramic, leather grain, natural skin texture and credible ice/layer refraction; no plastic table or airbrushed liquid",
            },
            "capture": {
                "look": "quiet candid cafe phone photograph with natural hand-held asymmetry and finite social-photo acuity",
                "realism": "one camera, one exposure and one window system must physically join both hands, both drinks, ceramics, counter and props",
                "grain": "faint low-contrast sensor texture; preserve real materials rather than digitally sharpened edges",
                "imperfections": [
                    "imperfect crema and foam on the generic companion",
                    "irregular clear ice and layered beverage transmission on the exact user drink",
                    "small natural creases in dark leather and dark lap fabric",
                    "subtle hand skin variation without beauty retouching",
                ],
            },
            "human_presence": {
                "required": True,
                "hand_style": "two anonymous adult feminine hands only, naturally proportioned and visible from wrist to fingers; Image 2 explicitly anchors both grip silhouettes, wrist lengths, finger spacing and staggered heights; no face or full body",
                "grip": "the lower 6 o'clock person's left hand supports the smaller exact user drink from below and around its side without hiding the visible layers; the upper-left hand naturally supports the smaller companion ceramic cup",
                "wrist_and_clothing": "discard source-product hand/clothing. Rebuild Image 2's lower bare left wrist, slim black hair tie and two separately readable dark-clothed thighs: retain a shallow central V seam and natural folds so the legs never fuse into one mass. No black cuff, leather sleeve or any sleeve may enter the lower hand zone. Charcoal-black matte leather belongs exclusively to the upper-left companion arm.",
                "nails": "short natural muted nails; no distinctive manicure, rings, watch or branded accessory",
                "forbidden": ["face", "third person", "extra hand", "fused fingers", "posed catalogue grip", "beauty-smoothed skin"],
            },
            "preservation_policy": {
                "hard_lock": [
                    "exactly one user product held in the lower-centre primary hand slot with its sidewall, ice and layers physically visible",
                    "exactly one smaller generic hot ceramic companion cup held at upper-left",
                    "exactly two adult hands locked to Image 2 pose topology: upper-left black leather only, lower person's left hand with bare wrist and slim black hair tie over two distinct dark-clothed thighs and zero lower sleeve",
                    "pale oak window counter, white-gray window ledge, upper-right pastry plate, right-side neutral magazine/saucer cluster and small upper-centre saucer",
                    "one cloud-filtered upper-right rear diffuse window source at 5400-5750K with lower-left soft falloff, faded film shoulder and no sunset warmth",
                ],
                "editable": [
                    "the exact user beverage and source container under preserve-source mode",
                    "generic companion crema pattern and cup handle micro-angle",
                    "new oak grain phase, exterior microtexture and slight crop breathing",
                    "non-identifying skin microtexture and minor finger pressure",
                ],
                "reference_exclusions": [
                    "faces, identities, source hand pixels and fashion labels",
                    "readable magazine title or publisher text",
                    "exact latte art, cup mark, pastry crumbs, window reflection or source wood knots",
                    "any scene text, logo or watermark",
                ],
            },
            "prompt_blocks": {
                "input_roles": "Image 1 owns the full exact user beverage and source cup. Image 2 is a submitted spatial hand-pose reference: follow its 3:4 crop topology, both grip silhouettes, exclusive upper leather/lower bare-wrist clothing boundary, cup size hierarchy, counter/window/prop coordinates and cloudy afternoon light distribution. Never copy Image 2 pixels, text or identities.",
                "composition": "Hold the lower-centre user drink in the 6 o'clock person's bare left hand at 20-22 percent of frame width and 26-29 percent of frame height. Match approved B: the cup top leans camera-ward and toward the bottom of frame while its base shifts oppositely toward the upper-right window; use 9-12 degrees without a pouring pose. Keep the liquid surface gravity-level, the upper-left companion, and the cropped right-side context.",
                "look": "A calm low-saturation wood cafe snapshot: real 49mm-equivalent high-oblique perspective, faded beige oak, cool-neutral ceramics/window, textured charcoal clothing and a slightly faded cloudy-afternoon film response under one subdued diffuse window.",
                "preservation": "Rebuild the whole frame in one exposure. The user drink, hand occlusion, cup wall, ice, counter contact, ceramic shadows, off-frame room occlusion and room bounce must meet physically; preserve no source background, reference text or exact reference pixels.",
                "negative": "No faces, third person, extra fingers, empty hand, duplicated cup, direct sun, HDR, orange wash, plastic wood, copied magazine words, wide-angle distortion, beauty retouching, floating beverage or AI bokeh.",
            },
            "quality_gates": {
                "logo_text": "no readable magazine, cup or clothing text; preserve source branding only if the user product itself is verified branded",
                "product_identity": "one exact iced user beverage retains its layer order, ice, opacity and cup construction in a credible visible-sidewall hand-held view",
                "preset_adherence": "two hands/two cups, upper-left leather companion, lower-centre user hand, pale oak counter, window, pastry, magazine/saucer and one diffuse upper-right window light pass together",
                "artifact_policy": "reject missing hand, duplicate hand/cup, top-only primary cup, sidewall-hidden iced beverage, absent pastry/magazine/window, source clone, source text, rigid fingers, flat crema, pasted drink, inconsistent shadows or artificial skin",
            },
            "failure_recovery": [
                "restore lower-centre hand-held primary sidewall before changing color or props",
                "restore the second upper-left hand-held companion cup before adding depth blur",
                "restore the upper-right window, pastry and right-side magazine/saucer context before adding new props",
                "restore one diffuse upper-right window and lower-left penumbrae before grading",
                "remove all reference text and rejoin the user product, hand and counter into one exposure",
            ],
        }
    )
    return preset


def build_style_contract(binding: dict[str, Any]) -> dict[str, Any]:
    style = copy.deepcopy(read_json(BASE_STYLE))
    style.update(
        {
            "contract_id": "instagram_wood_handheld_two_person_contract_v1",
            "preset_id": PRESET_ID,
            "creative_direction": {
                "audience": "a social-feed viewer looking for an intimate, believable two-person cafe pause",
                "desired_response": "the exact iced user drink appears naturally held by the lower person in a real window-side conversation, never pasted into a coffee still life",
                "art_direction": "high-oblique two-hand composition: lower-centre exact user drink, upper-left ceramic companion, pale wood counter and partial right-side cafe context",
                "restraint": "preserve cropped everyday context, believable hand pressure and quiet material texture; no product-ad symmetry or styling flourish",
                "forbidden_impression": ["AI beverage demo", "fashion campaign", "commercial studio spotlight", "overdecorated cafe set", "pasted product cutout"],
            },
            "reference_binding": {
                "asset_id": ASSET_ID,
                "pixel_sha256": binding["pixel_sha256"],
                "relative_path": REFERENCE_RELATIVE_PATH,
                "width_px": binding["width_px"],
                "height_px": binding["height_px"],
                "runtime_role": "submitted spatial hand-pose hint for two grip silhouettes, exclusive clothing zones, crop topology, prop placement, pale wood counter, window direction and faded cloudy-afternoon exposure",
                "provider_submission": "scene_hint_only",
            },
            "camera_geometry": {
                "projection": "rectilinear normal high-oblique handheld observation with no phone-wide stretch",
                "focal_length_equivalent_mm": [45, 52],
                "working_distance_cm": [105, 135],
                "camera_height_cm": [125, 145],
                "pitch_degrees": [48, 56],
                "yaw_degrees": [-4, 4],
                "roll_degrees": [-1.2, 1.2],
                "distortion": "natural cup ellipses and wrist foreshortening; neither stretched edge hands nor flattened tabletop",
                "depth_of_field": "both hands, both cups, saucers and right-side prop edges remain structurally readable; only exterior microdetail recedes",
            },
            "composition_geometry": {
                "primary_subject_bbox": {"left": 0.348, "top": 0.458, "right": 0.562, "bottom": 0.740},
                "bbox_semantics": "raw 3:4 lower-centre held product body including visible sidewall but excluding any optional straw; hand is a separate occluding foreground relation",
                "primary_subject_area_ratio": [0.056, 0.064],
                "negative_space": "upper window counter remains quiet; right-side pastry and magazine/saucer crop provide context without filling the frame",
                "support_plane": {
                    "kind": "pale matte oak window counter plus two natural held-carrier hand contacts",
                    "occupancy_ratio": [0.56, 0.74],
                    "dominant_edge_angles_degrees": [-42, -4, 42],
                    "perspective": "a pale wood counter recedes toward the upper-right window; hands interrupt it at two distinct seated depths",
                },
                "frame_rhythm": "compact lower-centre iced primary at 20-22 percent frame width and 26-29 percent frame height in Image 2's bare left hand; its top leans camera-ward/bottom-of-frame while its base shifts window-ward/upper-right at the selected B angle of 9-12 degrees; smaller upper-left ceramic companion and cropped right-side context remain unchanged",
                "crop_policy": "3:4 source composition stays complete; optional 4:5 crop may trim only outer clothing and counter margins, never either hand, cup, pastry plate, magazine/saucer cluster or window ledge",
                "forbidden": ["missing primary sidewall", "equal side-by-side cup lineup", "cropped fingers", "face", "empty right-side context", "centered studio symmetry"],
            },
            "composition_variation": {
                "selection": "derive only small new grain phase, exterior microtexture, companion handle angle and natural finger pressure from request seed",
                "invariants": [
                    "lower-centre user drink held by the 6 o'clock hand",
                    "smaller upper-left companion held by the leather-sleeved hand",
                    "right-side pastry and magazine/saucer context",
                    "upper-right window counter and one diffuse daylight field",
                ],
                "allowed_variations": ["minor non-identifying skin texture", "new oak grain phase", "small companion crema variation", "unreadable neutral magazine page layout"],
                "repeat_guard": "the relational map and light field are authoritative, but do not copy magazine text, faces, exact wood knots, exact reflections, skin identity or reference pixels",
                "scene_similarity_limit": 0.82,
                "reference_scene_copy_forbidden": True,
            },
            "lighting_geometry": {
                "source_topology": "one broad upper-right rear diffused window source with quiet room return",
                "azimuth_degrees": [36, 58],
                "elevation_degrees": [38, 52],
                "angular_size_degrees": [38, 58],
                "key_to_fill_ratio": [1.28, 1.62],
                "lit_area_ratio": [0.48, 0.62],
                "shadow_area_ratio": [0.24, 0.36],
                "shadow_vector_degrees": [196, 228],
                "penumbra_ratio": [0.46, 0.68],
                "highlight_behavior": "broad rolled light on ceramics, real restrained glass/plastic edges and small irregular ice responses",
                "optical_effects": "the user drink retains finite wall thickness, ice refraction, liquid transmission and hand/counter bounce under the same light",
                "forbidden": ["hard noon sun", "window-bar gobo", "multiple catchlights", "clipped ceramic", "glowing ice", "orange ambient wash"],
            },
            "tone_signature": {
                "working_color_space": "sRGB display-referred natural social-photo finish",
                "white_balance_kelvin": [5400, 5750],
                "luma_percentiles": {"p05": [0.06, 0.12], "p25": [0.24, 0.36], "p50": [0.42, 0.54], "p75": [0.62, 0.75], "p95": [0.80, 0.89]},
                "black_point": "soft neutral charcoal with leather grain, trouser folds and hand separation visible; a gentle film toe without washed haze",
                "white_point": "cloudy gray-white window ledge and ceramic roll below clipping; never paper-white glow",
                "shadow_color": "neutral charcoal with a quiet cool-gray window influence, not brown-black or blue-teal",
                "highlight_color": "muted neutral ivory on ceramic, pale gray on window and only restrained faded beige reflection on oak",
                "contrast_curve": "slightly faded low-to-moderate overcast-afternoon film curve: compressed highlights, open but anchored shadows and separated materials",
                "material_separation": "locally faded oak, cool-neutral ceramic/window, matte leather, natural skin and source-authoritative drink layers remain separately readable within one subdued exposure",
            },
            "finish_signature": {
                "acuity": "finite ordinary phone-camera acuity softened by a mild faded-film response; keep the primary drink structurally resolved but reduce its local edge acuity about 5-7 percent relative to the nearby hand and cup rim so it belongs to the frame",
                "microcontrast": "real wood pores, leather grain, ceramic edge rolloff and skin texture remain local; primary beverage liquid and ice use slightly softer microcontrast than the hand and rim, never isolated hyper-sharpness or blur",
                "grain": "faint low-contrast sensor texture with a subtle analog-print softness only",
                "forbidden": ["beauty retouch", "plastic skin", "global blur", "HDR halo", "AI-clean smoothing", "portrait bokeh", "orange vintage filter", "teal-and-orange grade"],
            },
        }
    )
    return style


def build_scene_graph(
    binding: dict[str, Any],
    file_sha256: str,
    *,
    primary_angle_variant: str = "mild",
) -> dict[str, Any]:
    angle_variants = {
        "mild": {
            "degrees": "4-6",
            "top_ratio": "34-38",
            "label": "A, subtle",
        },
        "moderate": {
            "degrees": "9-12",
            "top_ratio": "40-45",
            "label": "B, selected moderate",
        },
    }
    if primary_angle_variant not in angle_variants:
        raise ValueError(f"Unsupported primary angle variant: {primary_angle_variant}")
    angle = angle_variants[primary_angle_variant]
    primary = bbox(0.348, 0.458, 0.562, 0.740)
    companion = bbox(0.31, 0.34, 0.57, 0.56)
    return {
        "schema_version": "2.0.0",
        "analysis_metadata": {
            "provider": "manual_visual_review",
            "model": "human_approved_reference_contract",
            "prompt_version": "reference_scene_graph_v2",
            "analyzed_at": "2026-07-23T00:00:00+09:00",
            "confidence": 0.98,
        },
        "asset": {
            "asset_id": ASSET_ID,
            "relative_path": REFERENCE_RELATIVE_PATH,
            "file_sha256": file_sha256,
            "pixel_sha256": binding["pixel_sha256"],
            "width_px": binding["width_px"],
            "height_px": binding["height_px"],
            "format": "PNG",
            "source_folder_tags": ["user_approved", "wood", "handheld", "two_person", "soft_window"],
            "dhash": binding["dhash"],
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
                "description": f"ANGLE VARIANT {angle['label']}: lower-centre source cup remains compact at 20-22 percent frame width and 26-29 percent frame height. Tilt the cup axis only {angle['degrees']} degrees: its top moves camera-ward and toward the bottom of frame, while its base moves oppositely toward the upper-right window. Show {angle['top_ratio']} percent open top and keep the liquid surface gravity-level; never reverse this direction or turn it into a pouring pose.",
                "body_bbox": primary,
                "full_bbox": bbox(0.300, 0.438, 0.610, 0.832),
                "straw": no_straw(),
                "container": {
                    "class": "user-controlled beverage container",
                    "material": "source-authoritative",
                    "silhouette": "source-authoritative sidewall under preserve-source mode",
                    "components": ["complete exact user cup", "exact beverage layers", "natural hand occlusion"],
                },
                "interaction": "held",
                "support_surface_id": "surface_primary_hand",
                "depth_order": 3,
                "occlusion_fraction": 0.16,
                "replaceable": True,
                "allowed_kinds": ["beverage"],
                "visible_text": [],
                "brand_or_watermark_state": "uncertain",
                "crop_safe": True,
            },
            {
                "slot_id": "beverage_secondary",
                "kind": "beverage",
                "role": "secondary",
                "description": "Smaller generic hot ceramic companion cup attached to Image 2's upper-left leather-sleeved hand pose. It provides natural coffee/crema scale only and remains unbranded.",
                "body_bbox": companion,
                "full_bbox": bbox(0.27, 0.31, 0.61, 0.58),
                "straw": no_straw(),
                "container": {
                    "class": "small off-white ceramic latte cup",
                    "material": "matte glazed ceramic",
                    "silhouette": "compact low cup with one simple handle and a visible irregular coffee surface",
                    "components": ["ceramic rim", "small handle", "natural foam and crema"],
                },
                "interaction": "touching",
                "support_surface_id": "surface_companion_hand",
                "depth_order": 2,
                "occlusion_fraction": 0.14,
                "replaceable": False,
                "allowed_kinds": ["beverage"],
                "visible_text": [],
                "brand_or_watermark_state": "absent",
                "crop_safe": True,
            },
            {
                "slot_id": "prop_pastry_plate",
                "kind": "prop",
                "role": "accent",
                "description": "One partial white plate with a single croissant at the upper-right counter edge; natural cafe context, never a hero food shot.",
                "body_bbox": bbox(0.82, 0.20, 1.0, 0.42, 0.94),
                "full_bbox": bbox(0.79, 0.17, 1.0, 0.45, 0.94),
                "straw": no_straw(),
                "container": {"class": "cropped white pastry plate", "material": "ceramic", "silhouette": "partial plate rim and croissant edge", "components": ["one croissant", "one white plate"]},
                "interaction": "resting",
                "support_surface_id": "surface_wood_window_counter",
                "depth_order": 0,
                "occlusion_fraction": 0.0,
                "replaceable": False,
                "allowed_kinds": ["prop"],
                "visible_text": [],
                "brand_or_watermark_state": "absent",
                "crop_safe": True,
            },
            {
                "slot_id": "prop_magazine_saucer",
                "kind": "prop",
                "role": "accent",
                "description": "Right-side neutral magazine partly covered by a plain white saucer, plus a small empty saucer near upper centre. Preserve their cropped spatial rhythm but not readable copy.",
                "body_bbox": bbox(0.65, 0.35, 1.0, 0.78, 0.94),
                "full_bbox": bbox(0.55, 0.25, 1.0, 0.80, 0.94),
                "straw": no_straw(),
                "container": {"class": "editorial paper and ceramic context cluster", "material": "unbranded matte paper and white ceramic", "silhouette": "cropped rectangular magazine with overlapping saucer circles", "components": ["one neutral magazine", "one right-side saucer", "one small empty upper-centre saucer"]},
                "interaction": "overlapping",
                "support_surface_id": "surface_wood_window_counter",
                "depth_order": 1,
                "occlusion_fraction": 0.16,
                "replaceable": False,
                "allowed_kinds": ["prop"],
                "visible_text": [],
                "brand_or_watermark_state": "uncertain",
                "crop_safe": True,
            },
        ],
        "relations": [
            {"from_slot_id": "beverage_primary", "predicate": "in_front_of", "to_slot_id": "beverage_secondary", "confidence": 0.98},
            {"from_slot_id": "beverage_primary", "predicate": "paired_with", "to_slot_id": "beverage_secondary", "confidence": 0.98},
            {"from_slot_id": "beverage_secondary", "predicate": "left_of", "to_slot_id": "prop_magazine_saucer", "confidence": 0.96},
            {"from_slot_id": "prop_pastry_plate", "predicate": "right_of", "to_slot_id": "beverage_secondary", "confidence": 0.96},
            {"from_slot_id": "prop_magazine_saucer", "predicate": "right_of", "to_slot_id": "beverage_primary", "confidence": 0.94},
        ],
        "support_surfaces": [
            {"surface_id": "surface_wood_window_counter", "kind": "counter", "bbox": bbox(0.16, 0.0, 1.0, 0.78), "plane_description": "Pale matte oak window counter with diagonal long-grain recession toward the upper-right and neutral white-gray sill beyond", "supports_objects": True, "perspective_scale": [0.88, 1.15]},
            {"surface_id": "surface_primary_hand", "kind": "held_carrier", "bbox": bbox(0.25, 0.54, 0.61, 0.93), "plane_description": "Image 2 lower person's anonymous bare left hand and slim black hair-tie wrist at 6 o'clock holding the compact primary user drink above two separately readable dark-clothed thighs; no lower sleeve enters this surface", "supports_objects": True, "perspective_scale": [0.96, 1.04]},
            {"surface_id": "surface_companion_hand", "kind": "held_carrier", "bbox": bbox(0.0, 0.24, 0.62, 0.62), "plane_description": "Upper-left anonymous hand emerging from charcoal-black leather and holding the smaller companion ceramic cup", "supports_objects": True, "perspective_scale": [0.94, 1.06]},
        ],
        "protected_regions": [
            {"region_id": "region_primary_hand", "kind": "hand", "bbox": bbox(0.25, 0.54, 0.61, 0.93), "reason": "follow Image 2 lower person's bare left-wrist angle and visible black hair tie, then adapt the fingers around the smaller user cup; prohibit any lower black cuff or leather sleeve"},
            {"region_id": "region_companion_hand", "kind": "hand", "bbox": bbox(0.0, 0.25, 0.62, 0.61), "reason": "preserve one credible upper-left leather-sleeved companion hand"},
            {"region_id": "region_primary_lower_body", "kind": "occupied", "bbox": bbox(0.05, 0.60, 0.78, 1.0), "reason": "preserve exactly two anatomically connected dark-clothed thighs and knees with a shallow central V-shaped separation and visible fabric folds; never merge them into a one-leg silhouette"},
            {"region_id": "region_window_release", "kind": "negative_space", "bbox": bbox(0.18, 0.0, 1.0, 0.26), "reason": "retain pale window ledge and exterior release without copying its exact pixels"},
            {"region_id": "region_magazine_copy", "kind": "visible_text", "bbox": bbox(0.67, 0.40, 1.0, 0.76), "reason": "preserve magazine geometry only; suppress all readable copy"},
        ],
        "insertion_zones": [
            {"zone_id": "zone_beverage_primary", "bbox": primary, "support_surface_id": "surface_primary_hand", "allowed_kinds": ["beverage"], "scale_range": [0.94, 1.06], "confidence": 0.98, "reason": "lower-centre held product slot preserves a visible source-cup sidewall, hand grip and safe 4:5 crop"},
        ],
        "composition": {
            "shot_type": "handheld",
            "camera_height": "high",
            "camera_pitch": "48-56 degree downward high-oblique seated observation",
            "lens_character": "phone_mild_tele",
            "subject_position": "lower-centre primary in one hand, smaller upper-left companion in a second hand, cropped counter props at right",
            "negative_space": "quiet upper window ledge plus partial counter strips around the right-side props",
            "asymmetry_source": "two staggered hands, unequal cup scales and cropped right-side pastry/magazine context",
            "crop_character": "3:4 reference preserves the complete two-cup relationship; optional 4:5 output may trim only outer clothing/counter margins",
        },
        "depth": {
            "plane_count": 4,
            "foreground": "lower person's anonymous bare left hand, slim black hair tie, exact smaller user product and two distinct dark-clothed thighs",
            "product_plane": f"compact lower-centre held primary using angle variant {angle['label']} at {angle['degrees']} degrees: top camera-ward/bottom-of-frame, base window-ward/upper-right, liquid gravity-level, visible sidewall and attached hand occlusion",
            "midground": "upper-left companion hand/cup plus right-side magazine/saucer cluster",
            "background": "pale oak window counter, window ledge and small exterior band",
            "perspective_cues": ["normal-lens hand scale", "two held cups at staggered depths", "diagonal counter recession", "attached finger occlusion", "two-thigh central separation", "tonal falloff toward dark clothing"],
            "far_plane_softness": "subtle",
            "atmospheric_separation": "mild",
        },
        "lighting": {
            "source_type": "soft_window",
            "direction": "one cloud-filtered upper-right rear window source toward lower-left hands and dark laps",
            "source_size": "large",
            "hardness": 0.18,
            "contrast": 0.42,
            "shadow": "compact finger/cup occlusion then broad soft lower-left counter and lap falloff",
            "highlight": "muted cloudy-gray ceramic/sill rolloff and bounded user-drink ice highlights; low-chroma milk never reaches isolated paper white",
            "transmitted_light": "subtle bounded lift through the physically transparent user drink only",
            "white_balance": "neutral",
        },
        "color": {
            "exposure": "low",
            "saturation": "restrained",
            "contrast": "soft",
            "black_point": "natural",
            "palette_hex": ["#C8B99D", "#9B8567", "#454343", "#EEF0EE", "#C7CDD0"],
            "mean_luminance": 0.43,
            "luminance_stddev": 0.33,
            "mean_saturation": 0.12,
            "edge_energy": 0.052,
        },
        "facets": {
            "mood_tags": ["quiet", "low-saturation", "candid", "two-person", "natural-cafe"],
            "environment_tags": ["window", "cafe", "pale-oak-counter"],
            "material_tags": ["oak", "ceramic", "leather", "skin", "transparent-beverage"],
            "shot_tags": ["handheld", "high-oblique", "relational-pair"],
        },
        "taxonomy": {
            "environment_family": "warm_wood",
            "lighting_family": "soft_window",
            "camera_angle": "high_angle",
            "capture_style": "held_product",
            "scene_complexity": "pair",
            "dominant_surface": "pale matte oak window counter",
            "wood_prominence": 0.64,
            "accent_color_prominence": 0.12,
            "frontend_mood": "wood",
            "frontend_angle": "high_angle",
            "confidence": 0.98,
        },
        "runtime_policy": {
            "scene_pixels_allowed": False,
            "container_pixels_allowed": True,
            "copy_exclusions": ["source latte art", "readable magazine text", "faces and identities", "exact wood knots", "reference reflections", "all non-user-product branding"],
            "maximum_exact_products": 1,
            "maximum_generic_companions": 1,
            "maximum_major_subjects": 3,
            "maximum_props": 2,
        },
        "quality_flags": [],
    }


def build_mood_package() -> dict[str, Any]:
    mood = copy.deepcopy(read_json(BASE_MOOD))
    mood.update(
        {
            "mood_package_id": PRESET_ID,
            "display_name": "우드 손잡이 투컵 샷",
            "display_name": "우드 저채도 투인 핸드헬드",
            "preset_path": f"{EDITORIAL_ROOT}/reference-preset.json",
            "scene_recipe_path": f"{MOOD_ROOT}/scene-recipe.json",
            "lighting_sheet_path": f"{MOOD_ROOT}/lighting-sheet.json",
            "grade_profile_path": f"{MOOD_ROOT}/grade-profile.json",
            "photographic_style_contract_path": f"{EDITORIAL_ROOT}/photographic-style-contract.json",
            "reference_control_board_path": CONTROL_RELATIVE_PATH,
            "reference_control_board_manifest_path": f"{CONTROL_ROOT}/scene-hint-manifest.json",
            "runtime_reference_policy": "offline_contract_only",
            "compatibility": {
                "composition_modes": ["two_held_drinks_on_window_counter"],
                "materials": ["glass", "plastic", "paper", "ceramic"],
            },
        }
    )
    return mood


def build_control_manifest(
    reference_binding: dict[str, Any],
    control_binding: dict[str, Any],
    control_file_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "static_relational_scene_hint",
        "policy_version": "wood_handheld_two_person_scene_hint_v4",
        "role": "scene_hint",
        "relative_path": CONTROL_RELATIVE_PATH,
        "width_px": control_binding["width_px"],
        "height_px": control_binding["height_px"],
        "aspect_ratio": "3:4",
        "sha256": control_file_sha256,
        "pixel_sha256": control_binding["pixel_sha256"],
        "source_binding": {
            "asset_id": ASSET_ID,
            "relative_path": REFERENCE_RELATIVE_PATH,
            "pixel_sha256": reference_binding["pixel_sha256"],
        },
        "retained_relationships": [
            "separate upper companion hand, leather clothing, cup and drink evidence",
            "separate lower bare-wrist hand, hair tie, cup and drink evidence",
            "separate croissant, magazine and saucer context evidence",
            "separate pale-oak grain direction, sill and cloudy-window photometry evidence",
        ],
        "forbidden_transfer": [
            "faces and identities",
            "readable magazine text or logos",
            "reference latte art and beverage recipe",
            "exact pixels, wood knots, reflections and hand skin identity",
        ],
        "sanitation": {
            "runtime_role": "non-contiguous pose, object, material and photometry evidence board",
            "construction": "four independently cropped and low-frequency-reduced panels; no panel preserves full-scene topology",
            "reference_product_pixels_authoritative": False,
            "reference_text_transfer_allowed": False,
            "source_product_transfer_allowed": False,
        },
    }


def build_scene_recipe() -> dict[str, Any]:
    return {
        "$schema": "../../../schemas/scene-recipe.schema.json",
        "schema_version": "1.0.0",
        "recipe_id": PRESET_ID,
        "display_name": "우드 손잡이 투컵 샷",
        "compatible_presets": [PRESET_ID],
        "generation_policy": {"normal_paid_generations": 1, "runtime_reference_image": False, "traditional_compositing": False},
        "composition": {
            "inherit_preset_bbox": True,
            "subject_anchor_priority": "lower primary held-product bbox (0.310,0.420)-(0.600,0.790), upper companion held-cup bbox (0.310,0.340)-(0.570,0.560), and right-side contextual prop clusters are hard locks",
            "asymmetry_sources": ["two staggered hands", "unequal held cup scale", "upper-right window counter", "partial pastry and magazine/saucer context"],
        },
        "environment": {
            "background_plane": "pale oak window counter, white-gray sill and restrained exterior band with cropped pastry, magazine and saucers",
            "surface_character": "matte pale oak with long natural grain, real pores and local warmth only",
            "sun_patch_shape": "none; one broad diffuse field without stripes or gobo",
        },
        "lighting": {
            "source": "one very large diffuse upper-right rear window with quiet room return",
            "direction": "azimuth 36-58 degrees, elevation 38-52 degrees, broad shadows toward lower-left",
            "shadow_description": "compact finger and cup occlusion, then broad soft lower-left counter/lap penumbrae",
            "light_softness": [0.78, 0.88],
            "subject_to_wall_distance_cm": [65, 115],
            "shadow_density": [0.20, 0.34],
            "global_contrast": [0.34, 0.46],
            "background_lightness": [0.52, 0.73],
            "ambient_fill": "neutral sill and room bounce retain ceramic, skin, leather, ice and wood separation without flattening contacts",
            "exposure_compensation_ev": [-0.28, -0.08],
            "sun_patch_coverage": [0.0, 0.0],
            "highlight_behavior": "protected window, ceramic and finite transparent drink highlights with no clipped white glow",
            "shadow_temperature": "neutral charcoal with faint cool window influence and no amber veil",
        },
        "capture": {
            "rendering_pipeline": "natural social capture with one coherent exposure and finite hand-held camera acuity",
            "shadow_processing": "keep finger occlusion and broad penumbrae; never lift dark clothing with HDR",
            "local_texture": "preserve user beverage identity, layers, sidewall, ice, cup thickness and hand contact while rebuilding them under the target window light; lower only the liquid-and-ice local edge acuity about 5-7 percent so the drink does not look separately sharpened",
            "forbidden_processing": ["phone HDR", "uniform hyper-sharpness", "orange filter", "AI-clean smoothing", "beauty retouching", "portrait blur", "cutout edge enhancement"],
        },
        "human_rendering": {
            "skin_texture": "exactly two anonymous adult hands with natural joint compression, pores and unobtrusive short nails; no faces",
            "light_response": "both hands, black leather, dark lap fabric and user drink share the same upper-right diffuse window source",
            "forbidden": ["third person", "extra fingers", "fused hand", "white shirt", "decorative sleeve", "beauty-smoothed skin", "fashion branding"],
        },
        "material_rules": {
            "glass": "transparent source cups retain finite rim/base thickness, irregular ice, refraction, liquid transmission and attached hand shadow",
            "plastic": "source-preserved clear plastic remains distinct from glass and paper through thin highlight continuity and real condensation",
            "ceramic": "generic companion cup and saucers retain matte glazed edge rolloff, not plastic white glow",
            "wood": "pale oak keeps long grain and pores with local warmth; no gloss, orange filter or copied knot topology",
        },
        "coupling_rules": [
            "Image 2 is mandatory static relational authority for two hand poses, clothing cues, cup hierarchy, prop placement, counter/window geometry and diffuse light topology.",
            "Exactly one Image 1 product replaces the lower primary hot-cup placeholder while preserving its complete user cup and visible iced sidewall.",
            "Exactly one smaller generic hot ceramic companion remains held at upper-left by the leather-sleeved hand.",
            "Exactly two hands are visible; the lower target is in the lower person's left hand. Exactly two separately readable thighs and knees connect naturally to that seated person; no fused or missing leg, face, third person, extra arm or extra drink is allowed.",
            "Pastry plate, magazine/saucer cluster and upper window remain physically on the pale oak counter, and their text is never transferred.",
            "All materials share a 5400-5750K cloudy neutral-gray upper-right window exposure, faded low-saturation film shoulder and lower-left shadow falloff.",
        ],
        "forbidden": ["top-only primary cup", "missing hand", "extra hand", "third drink", "white shirt", "direct sunlight", "window-bar gobo", "spotlight", "multiple light sources", "portrait bokeh", "glossy orange wood", "global amber wash", "floating contact", "readable magazine text", "unauthorized logo"],
        "quality_gate": {
            "hard_fail": [
                "the lower-centre exact user drink is not held by one credible 6 o'clock hand with a visible sidewall",
                "the smaller upper-left hot ceramic companion or leather-sleeved hand is missing",
                "there are not exactly two hands and two cups, or a face/third person appears",
                "the lower seated person does not have exactly two separately readable, anatomically connected thighs and knees, or the dark clothing merges into a one-leg silhouette",
                "the target drink is held by the lower person's right hand instead of the left hand",
                "the upper-right window, partial pastry plate or right-side magazine/saucer context is absent or materially rearranged",
                "direct sun, gobo, spotlight, conflicting source or hard synthetic shadow appears",
                "5000-5250K local-wood warmth and neutral ceramic/window separation fails",
                "the user drink, hand, counter and shadows read as pasted, floating, over-smoothed or physically disconnected",
                "reference magazine text, logo, watermark, face identity or exact source pixels leak into output",
            ],
            "weights": {"camera_geometry": 0.16, "composition_rhythm": 0.24, "color_and_tone": 0.12, "lighting_space": 0.20, "product_identity": 0.24, "brand_integrity": 0.04},
        },
    }


def build_lighting_sheet(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "lighting_sheet_id": "instagram_wood_handheld_two_person_sheet_v1",
        "mood": "우드 손잡이 투컵 샷: two held drinks beside a pale oak counter under one quiet window",
        "mood": "우드 저채도 투인 핸드헬드: two held drinks beside a pale oak counter under one cloudy afternoon window",
        "reference_cluster": {"anchor_preset_id": PRESET_ID, "minimum_cluster_size": 1, "runtime_pixels_allowed": False, "selection_rule": "the cropped user-approved wood handheld reference anchors submitted hand-pose/crop topology, counter/window direction and faded cloudy-afternoon tone without copying pixels", "source_images": [CONTROL_RELATIVE_PATH]},
        "key_light": {"source": "one very large cloud-filtered upper-right rear window", "direction": "upper-right window counter toward lower-left hands and laps", "relative_size": "broad low-contrast overcast source spanning hands, cups, counter and right-side props without direct sun or golden-hour beam", "subject_to_wall_distance_cm": [65, 115], "azimuth_degrees": [36, 58], "elevation_degrees": [38, 52], "angular_size_degrees": [48, 68], "distance_class": "near-window cloudy afternoon daylight"},
        "ambient_fill": "quiet cool-gray sill and room bounce keeps ceramic, leather, skin, ice and oak separate while preserving hand/cup contacts and off-frame room presence",
        "reference_anchor": {"asset_id": ASSET_ID, "pixel_sha256": binding["pixel_sha256"], "role": "submitted static scene hint for crop topology, two hand grips, exclusive clothing zones, counter/window/prop geometry and faded cloudy-afternoon photometry; never transfer pixels, text or identities"},
        "fill_contract": {"key_to_fill_ratio": [1.16, 1.42], "source": "cool-gray sill, pale counter and quiet room return, with dark lap fabric providing natural local occlusion", "color_bias": "cloudy neutral-gray outside locally faded oak warmth; never blue cast, amber wash or red sunset"},
        "screen_light_map": {"lit_area_ratio": [0.44, 0.56], "shadow_area_ratio": [0.30, 0.42], "dominant_shadow_vector_degrees": [196, 228], "falloff": "broad cloud-filtered upper-right field rolls across the counter and cups into lower-left hand/lap shadow, with real finger occlusion, quiet off-frame presence and no artificial pattern", "gobo_geometry": "no readable gobo, blind stripe, plant silhouette, mullion shadow or spotlight"},
        "specular_contract": {"highlight_shape": "muted broad ceramic/window rolloff, finite thin source-cup edges, irregular ice responses and restrained natural skin sheen; milk highlights sit below ceramic/window peak", "highlight_width_ratio": [0.10, 0.28], "rim_continuity": "finite and physically interrupted by viewing angle, ice, cup wall and hand occlusion", "transparent_caustic": "subtle, local and bounded to the actual transparent user-drink path"},
        "camera_coupling": {"support_plane": "45-52mm high-oblique view across a pale oak window counter and two hand-held carriers", "shadow_projection": "both hands and cups share upper-right illumination and lower-left broad falloff", "depth_response": "staggered hand scale, counter recession, overlap and tonal falloff establish depth before softness"},
        "color_separation": {"lit_neutral": "5400-5750K protected cloudy neutral-gray daylight with faded film density", "shadow_neutral": "soft neutral charcoal with faint cool window influence", "material_locality": "faded oak/coffee warmth remains local; ceramic and sill stay cool-neutral; charcoal clothing retains detail; user beverage retains source layer relationships while low-chroma milk shares the scene's muted highlight shoulder and reflected fill"},
        "qa_geometry": {"shadow_vector_tolerance_degrees": 18, "lit_area_tolerance": 0.12, "penumbra_ratio_tolerance": 0.14},
        "shadow_contract": {"density": [0.24, 0.38], "edge": "compact attached finger/cup occlusion transitioning to broad cloudy environmental lower-left penumbrae", "attachment": "user cup intersects the bare lower hand naturally; props rest on the same counter; no floating halo", "transparent_material": "bounded user-drink-colored transmission only through real clear material", "contact_shadow": {"opacity": [0.26, 0.42], "footprint": [0.04, 0.13], "behavior": "small dense occlusion at fingers, cup grip and counter props"}, "cast_shadow": {"opacity": [0.10, 0.21], "footprint": [0.14, 0.40], "behavior": "broad soft lower-left counter and lap falloff aligned to the cloudy window with quiet off-frame occupancy"}, "transmitted_light": {"opacity": [0.03, 0.11], "footprint": [0.05, 0.18], "behavior": "restrained colored lift inside true transparent user drink only; low-chroma milk never becomes self-luminous or paper white"}, "qa_ratios": {"cast_area_to_cup_bbox": [0.12, 0.46], "wrist_length_to_cup_height": [0.28, 1.0], "transparent_lift_inside_shadow": [0.03, 0.14]}},
        "capture_contract": {"exposure_compensation_ev": [-0.34, -0.16], "hdr": "single-exposure cloudy-afternoon response with protected gray-white ceramics/window, gently faded film shoulder and textured dark clothing", "white_balance": "5400-5750K cloudy neutral-gray daylight with source-authoritative user beverage layer relationships", "texture": "finite natural acuity, subdued oak pores, leather grain and skin texture; primary beverage liquid and ice sit about 5-7 percent below the adjacent hand/rim edge acuity, never uniformly sharp or visibly blurred"},
        "grade_strengths": {"natural": 0.14, "balanced": 0.18, "expressive": 0.20},
        "forbidden": ["direct sunlight", "hard studio spotlight", "window-bar gobo", "multiple conflicting catchlights", "orange/yellow wash", "red sunset cast", "glossy synthetic wood", "clipped ceramic", "paper-white milk", "glowing geometric ice", "flat crema", "detached hand/cup shadow", "sterile room", "portrait bokeh", "HDR halos", "teal-and-orange grade"],
    }


def build_grade_profile() -> dict[str, Any]:
    grade = copy.deepcopy(read_json(BASE_GRADE))
    grade.update(
        {
            "grade_profile_id": "instagram_wood_handheld_two_person_grade_v1",
            "transform": {"exposure_ev": -0.06, "contrast": 0.94, "saturation": 0.88, "warmth": -0.008, "shadow_lift": 0.020, "highlight_rolloff": 0.30},
            "strength": {"default": 0.14, "min": 0.08, "max": 0.20},
            "local_contrast": {"radius": 2.4, "amount": 0.020, "threshold": 13},
        }
    )
    return grade


def build_analysis() -> dict[str, Any]:
    analysis = copy.deepcopy(read_json(BASE_ANALYSIS))
    analysis["product_summary"] = "An iced matcha milk latte in a tall clear tumbler: natural deep green matcha in the upper half, pale milk below, irregular clear ice and fine surface bubbles. This Wood Handheld preset preserves the complete user cup and must show a credible visible sidewall in the lower hand."
    identity = analysis["identity"]
    identity["container"] = {
        "class": "tall clear tumbler in the source image; preserve the complete source cup in this preset",
        "material": "clear transparent glass or plastic from the source",
        "geometry": "source vessel is tall and gently tapered; preserve its rim, wall, base and sidewall under the new high-oblique window camera",
        "components": ["iced matcha milk beverage", "irregular transparent ice cubes", "thin natural surface foam"],
    }
    identity["must_preserve"] = [
        "iced matcha milk latte identity",
        "deep natural matcha green concentrated toward the upper layer",
        "pale milky lower layer with soft irregular green diffusion",
        "multiple irregular clear ice cubes and small surface bubbles",
        "complete source cup sidewall, rim and base in preserve-source mode",
        "visible side layers under one neutral wood-window exposure",
        "no invented logo, text, fruit, cream scoop, garnish or straw",
    ]
    identity["serving_state"]["side_visibility_requirement"] = "required"
    analysis["adaptable"] = ["source background", "source camera crop", "source table", "source hand", "source light and shadow"]
    analysis["discarded_source_context"] = ["source cafe wall and table", "source furniture", "source camera crop", "source hand and clothing", "source lighting and shadow"]
    analysis["presentation_correction"] = {
        "enabled": True,
        "intent": "reconstruct the exact attached iced matcha milk beverage and complete source tumbler in the lower-centre Wood Handheld two-person scene, held by the 6 o'clock hand with sidewall layers visible",
        "preferred_capture": {"focal_length_mm": [45, 52], "camera_distance": "high-oblique two-person cafe distance", "camera_height": "58-64 degree downward window-side observation", "rotation": "follow the dedicated iced pose hint: rim center left of base center, never an eye-level cup rotated in 2D"},
        "allowed": ["re-light beverage optics under target window light", "preserve source cup geometry and visible sidewall", "reconstruct natural hand grip", "adjust scale only within target held-slot corridor"],
        "forbidden": ["replace source cup with a ceramic hot cup", "flatten to a top-only cup view", "remove ice or layers", "invent straw, logo, fruit, cream or garnish", "retain source background, source hand or source shadow", "turn matcha neon or milk paper-white"],
    }
    return analysis


def build_reference_cup_analysis() -> dict[str, Any]:
    analysis = copy.deepcopy(read_json(ROOT / TEST_ANALYSIS))
    analysis["product_summary"] = (
        "An iced matcha milk latte whose beverage identity, matcha-to-milk color "
        "relationship, irregular ice and fine surface bubbles must be reconstructed "
        "inside the preset's compact off-white ceramic reference mug."
    )
    identity = analysis["identity"]
    identity["container"] = {
        "class": "compact off-white ceramic reference mug",
        "material": "matte off-white glazed ceramic",
        "geometry": "short compact cylindrical body, gently rounded lower wall, thin rim and one small loop handle",
        "components": [
            "iced matcha milk beverage",
            "irregular transparent ice cubes",
            "thin natural surface foam",
        ],
    }
    identity["must_preserve"] = [
        "iced matcha milk latte identity",
        "deep natural matcha green and pale milk color relationship",
        "multiple irregular clear ice cubes and small surface bubbles",
        "natural matcha diffusion into the milk without paper-white separation",
        "no invented logo, text, fruit, cream scoop, garnish or straw",
    ]
    identity["serving_state"]["side_visibility_requirement"] = "optional"
    analysis["presentation_correction"] = {
        "enabled": True,
        "intent": (
            "transfer only the exact iced matcha beverage identity into the compact "
            "off-white ceramic reference mug held by the lower bare hand"
        ),
        "preferred_capture": {
            "focal_length_mm": [45, 52],
            "camera_distance": "high-oblique two-person cafe distance",
            "camera_height": "48-56 degree downward window-side observation",
            "rotation": "small natural hand-driven rotation only",
        },
        "allowed": [
            "re-light beverage optics under target window light",
            "adopt the verified compact ceramic reference mug",
            "reconstruct a natural hand grip around the adopted mug",
            "adjust scale only within the target held-slot corridor",
        ],
        "forbidden": [
            "retain the source tall transparent tumbler",
            "copy reference latte art or crema",
            "remove ice or the matcha-milk color relationship",
            "invent straw, logo, fruit, cream or garnish",
            "retain source background, source hand or source shadow",
            "turn matcha neon or milk paper-white",
        ],
    }
    return analysis


def build_hot_analysis() -> dict[str, Any]:
    source_path = ROOT / "comfyui-inputs" / HOT_TEST_IMAGE
    binding = canonical_image_binding(source_path)
    analysis = copy.deepcopy(read_json(ROOT / TEST_ANALYSIS))
    analysis["source_binding"] = binding
    analysis["product_summary"] = (
        "Hot cappuccino in a compact off-white glazed ceramic cup with two thin black "
        "rim stripes, small curved black typography and one loop handle on image-right. "
        "Preserve the exact cup and coffee; discard the source saucer, hand, sleeve, "
        "wall and source lighting for this cup-body grip pose."
    )
    identity = analysis["identity"]
    identity["beverage"] = "hot cappuccino with a thin natural crema"
    identity["container"] = {
        "class": "compact off-white glazed ceramic handled cup",
        "material": "off-white glazed ceramic",
        "geometry": (
            "compact gently tapered ceramic body, thick rounded rim, stable foot and "
            "one rounded loop handle; preserve the source cup, not its saucer"
        ),
        "components": [
            "off-white ceramic cup",
            "right-side rounded loop handle",
            "two thin black rim stripes",
            "small curved black cup typography",
            "hot cappuccino",
        ],
    }
    identity["must_preserve"] = [
        "hot cappuccino identity and thin natural crema",
        "compact off-white glazed ceramic cup",
        "thick rounded rim and right-side rounded loop handle",
        "two thin parallel black stripes following the cylindrical rim curvature",
        "small black CAPPUCCINO typography naturally printed on the curved ceramic wall",
        "complete cup sidewall, handle and base",
        "no invented extra logo, text, straw, ice, garnish or latte art",
    ]
    identity["serving_state"] = {
        "schema_version": "1.0.0",
        "temperature": "hot",
        "ice_presence": "absent",
        "straw_requirement": "none",
        "topping_requirement": "none",
        "side_visibility_requirement": "required",
        "confidence": 0.98,
        "evidence": [
            "open hot coffee surface is visible",
            "thin crema follows the metal rim",
            "no ice, straw or cold-service lid is present",
        ],
    }
    analysis["geometry"] = {
        "container_bbox": bbox(0.33, 0.45, 0.75, 0.66, 0.97),
        "subject_bbox": bbox(0.23, 0.43, 0.77, 0.71, 0.96),
        "beverage_bbox": bbox(0.36, 0.46, 0.65, 0.52, 0.95),
        "straw": no_straw(),
        "interaction_bbox": None,
    }
    analysis["visual_anchor"] = {
        "feature": (
            "rounded ceramic rim, two curved black stripes, right loop handle, small "
            "curved CAPPUCCINO typography and natural crema"
        ),
        "emphasis_method": (
            "preserve cup proportions, glaze and printed design while rebuilding them under "
            "the preset's cloudy window and hand-held high-oblique camera"
        ),
        "do_not_exaggerate": [
            "ceramic gloss",
            "crema thickness",
            "handle size",
            "rim brightness",
            "cup height",
            "printed text size",
        ],
    }
    analysis["adaptable"] = [
        "source saucer",
        "source background",
        "source camera crop",
        "source hand and sleeve",
        "source light and shadow",
    ]
    analysis["discarded_source_context"] = [
        "matching striped ceramic saucer",
        "source hand and striped sleeve",
        "white wall and table",
        "source lighting and shadow",
    ]
    analysis["presentation_correction"] = {
        "enabled": True,
        "intent": (
            "reconstruct the exact hot cappuccino and striped ceramic handled cup in the "
            "lower left-hand slot without the source saucer"
        ),
        "preferred_capture": {
            "focal_length_mm": [45, 52],
            "camera_distance": "high-oblique two-person cafe distance",
            "camera_height": "58-64 degree downward window-side observation",
            "rotation": (
                "rotate the cup in real 3D so the loop handle stays fully visible on "
                "image-right; keep the axis nearly neutral with only a 4-6 degree lean "
                "toward image 7-8 o'clock"
            ),
        },
        "allowed": [
            "re-light ceramic and cappuccino under target window light",
            "remove the source saucer",
            "reconstruct a natural left-hand grip",
            "keep the source cup handle on image-right",
            "adjust scale within the held-slot corridor",
        ],
        "forbidden": [
            "replace the source ceramic cup with metal, glass or plain unprinted ceramic",
            "retain the source saucer, hand, sleeve or wall",
            "omit or straighten the two curved rim stripes and source cup typography",
            "invent ice, straw, lid, extra logo, text, garnish or latte art",
            "flatten the cup to a top-only view",
            "place the target handle on image-left or hide it behind the hand",
            "tilt the cup axis toward image-right or upper-right",
        ],
    }
    return analysis


def mutate_workflow(
    payload: dict[str, Any],
    *,
    paid: bool,
    container_mode: str = "preserve_source",
    scene_graph_path: str = SCENE_GRAPH_RELATIVE_PATH,
    output_variant: str = "",
    input_image: str = TEST_IMAGE,
    product_analysis_path: str | None = None,
    pose_hint_variant: str = "iced",
) -> dict[str, Any]:
    if container_mode not in {"preserve_source", "adopt_reference"}:
        raise ValueError(f"Unsupported container mode: {container_mode}")
    workflow = copy.deepcopy(payload)
    if pose_hint_variant not in {"iced", "hot", "hot_photo", "hot_3d", "legacy"}:
        raise ValueError(f"Unsupported pose hint variant: {pose_hint_variant}")
    workflow["1"]["inputs"]["image"] = input_image
    workflow["2"]["inputs"]["product_analysis_path"] = (
        product_analysis_path
        or (
            REFERENCE_CUP_TEST_ANALYSIS
            if container_mode == "adopt_reference"
            else TEST_ANALYSIS
        )
    )
    workflow["3"]["inputs"]["image"] = Path(REFERENCE_RELATIVE_PATH).name
    workflow["4"]["inputs"].update(
        {
            "scene_graph_catalog_path": scene_graph_path,
            "fallback_mood_package_path": f"{MOOD_ROOT}/mood-package.json",
        }
    )
    workflow["5"]["inputs"]["mood_package_path"] = f"{MOOD_ROOT}/mood-package.json"
    workflow["6"]["inputs"].update(
        {
            "container_mode": container_mode,
            "target_slot_id": "beverage_primary",
            "placement_mode": "replace",
            "product_kind": "beverage",
            "cross_kind_replacement": False,
            "unbound_slot_policy": "genericize",
            "container_design_path": (
                REFERENCE_CUP_CONTAINER_DESIGN
                if container_mode == "adopt_reference"
                else ""
            ),
            "auto_paid_repair": False,
            "seed": 903,
            "quality_tier": "default",
            "reference_control_role": "sanitized_scene_hint",
            "container_design_source": (
                "reference" if container_mode == "adopt_reference" else "source"
            ),
        }
    )
    if container_mode == "adopt_reference":
        workflow["13"]["inputs"]["image"] = Path(
            REFERENCE_CUP_HINT_INPUT_RELATIVE_PATH
        ).name
        prefix = (
            "ad_creator/wood_handheld_two_person/"
            "matcha_user_reference_cup_gpt_image_2_medium"
        )
    else:
        hint_path = {
            "iced": ICED_SCENE_HINT_INPUT_RELATIVE_PATH,
            "hot": HOT_SCENE_HINT_INPUT_RELATIVE_PATH,
            "hot_photo": HOT_PHOTO_SCENE_HINT_INPUT_RELATIVE_PATH,
            "hot_3d": HOT_3D_SCENE_HINT_INPUT_RELATIVE_PATH,
            "legacy": USER_CUP_HINT_INPUT_RELATIVE_PATH,
        }[pose_hint_variant]
        workflow["13"]["inputs"]["image"] = Path(hint_path).name
        prefix = (
            "ad_creator/wood_handheld_two_person/"
            + (
                "hot_cappuccino_source_cup_gpt_image_2_medium"
                if pose_hint_variant in {"hot", "hot_photo", "hot_3d"}
                else "matcha_user_source_cup_gpt_image_2_medium"
            )
        )
    if output_variant:
        prefix = f"{prefix}_{output_variant}"
    workflow["10"]["inputs"]["filename_prefix"] = prefix
    workflow["11"]["inputs"]["output_label"] = prefix
    if paid:
        workflow["7"]["inputs"]["output_root"] = "outputs/comfyui-live/wood-handheld-two-person-v1"
    else:
        workflow["7"]["inputs"]["fixture_image_path"] = ""
    return workflow


def mutate_openai_workflow(
    *,
    input_image: str,
    product_analysis_path: str,
    pose_hint_variant: str,
    output_variant: str,
    seed: int,
) -> dict[str, Any]:
    workflow = mutate_workflow(
        read_json(BASE_PAID_WORKFLOW),
        paid=True,
        container_mode="preserve_source",
        output_variant=output_variant,
        input_image=input_image,
        product_analysis_path=product_analysis_path,
        pose_hint_variant=pose_hint_variant,
    )
    provider_path = "configs/providers/openai-gpt-image-2.json"
    workflow["6"]["inputs"]["provider_profile_path"] = provider_path
    workflow["6"]["inputs"]["seed"] = seed
    workflow["7"] = {
        "class_type": "AD_OpenAIImageGenerate",
        "inputs": {
            "request_json": ["6", 2],
            "lighting_sheet_json": ["5", 1],
            "output_root": "outputs/comfyui-openai/wood-handheld-two-person-v1",
            "provider_config_path": provider_path,
            "evaluator_config_path": "configs/evaluator.json",
            "timeout_seconds": 1200,
            "repair_execution": "manual",
        },
    }
    return workflow


def mutate_openai_smoke_workflow(
    *,
    input_image: str,
    product_analysis_path: str,
    pose_hint_variant: str,
    output_variant: str,
    seed: int,
) -> dict[str, Any]:
    workflow = mutate_workflow(
        read_json(BASE_LOCAL_WORKFLOW),
        paid=False,
        container_mode="preserve_source",
        output_variant=output_variant,
        input_image=input_image,
        product_analysis_path=product_analysis_path,
        pose_hint_variant=pose_hint_variant,
    )
    workflow["6"]["inputs"]["provider_profile_path"] = (
        "configs/providers/openai-gpt-image-2.json"
    )
    workflow["6"]["inputs"]["seed"] = seed
    return workflow


def update_catalog_and_assignments(scene_graph: dict[str, Any], binding: dict[str, Any], file_sha256: str) -> None:
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
                binding["pixel_sha256"],
                file_sha256,
                binding["dhash"],
                binding["width_px"],
                binding["height_px"],
                "user_approved/wood/handheld/two_person/v2",
                None,
                "analyzed",
                json.dumps(scene_graph, ensure_ascii=False, sort_keys=True),
                None,
            ),
        )
        connection.commit()

    assignments_path = ROOT / "data/reference-library/assignments.json"
    assignments = read_json(assignments_path)
    assignments["assignments"][ASSET_ID] = {
        "analysis_status": "analyzed",
        "canonical_asset_id": ASSET_ID,
        "cluster_id": "wood_handheld_two_person_v1",
        "confidence": 0.98,
        "evidence": ["user-approved crop", "two hand-held beverage slots", "pale oak window counter", "soft upper-right window", "manual scene-graph review"],
        "membership": "core",
        "mood_package_path": f"{MOOD_ROOT}/mood-package.json",
        "runtime_capabilities": {"cross_kind_slot_ids": [], "default_target_slot_id": "beverage_primary", "replaceable_slot_ids": ["beverage_primary"], "supports_cross_kind_replacement": False},
        "taxonomy": {"accent_color_prominence": 0.12, "camera_angle": "high_angle", "capture_style": "held_product", "confidence": 0.98, "dominant_surface": "pale matte oak window counter", "environment_family": "warm_wood", "frontend_angle": "high_angle", "frontend_mood": "wood", "lighting_family": "soft_window", "scene_complexity": "pair", "wood_prominence": 0.64},
    }
    write_json(assignments_path, assignments)


def main() -> int:
    if not REFERENCE_PATH.is_file():
        raise FileNotFoundError(f"Reference image missing: {REFERENCE_PATH}")
    binding = canonical_image_binding(REFERENCE_PATH)
    file_sha256 = sha256_file(REFERENCE_PATH)

    control_path = ROOT / CONTROL_RELATIVE_PATH
    reference_cup_hint_path = ROOT / REFERENCE_CUP_HINT_RELATIVE_PATH
    user_cup_hint_path = ROOT / USER_CUP_HINT_RELATIVE_PATH
    hot_photo_scene_hint_path = ROOT / HOT_PHOTO_SCENE_HINT_RELATIVE_PATH
    iced_scene_hint_path = ROOT / ICED_SCENE_HINT_RELATIVE_PATH
    build_scene_hint(reference_cup_hint_path, target_cup_mode="reference")
    build_scene_hint(user_cup_hint_path, target_cup_mode="user")
    build_scene_hint(hot_photo_scene_hint_path, target_cup_mode="hot_photo")
    build_scene_hint(iced_scene_hint_path, target_cup_mode="iced")
    shutil.copy2(reference_cup_hint_path, control_path)
    shutil.copy2(reference_cup_hint_path, ROOT / REFERENCE_CUP_HINT_INPUT_RELATIVE_PATH)
    shutil.copy2(user_cup_hint_path, ROOT / USER_CUP_HINT_INPUT_RELATIVE_PATH)
    shutil.copy2(
        hot_photo_scene_hint_path,
        ROOT / HOT_PHOTO_SCENE_HINT_INPUT_RELATIVE_PATH,
    )
    shutil.copy2(iced_scene_hint_path, ROOT / ICED_SCENE_HINT_INPUT_RELATIVE_PATH)
    control_binding = canonical_image_binding(control_path)
    control_file_sha256 = sha256_file(control_path)
    shutil.copy2(control_path, ROOT / HINT_INPUT_RELATIVE_PATH)

    preset = build_reference_preset(binding)
    style = build_style_contract(binding)
    scene_graph = build_scene_graph(binding, file_sha256, primary_angle_variant="moderate")
    moderate_scene_graph = build_scene_graph(
        binding,
        file_sha256,
        primary_angle_variant="moderate",
    )
    validate_scene_graph(scene_graph, project_root=str(ROOT))
    validate_scene_graph(moderate_scene_graph, project_root=str(ROOT))
    mood = build_mood_package()
    control_manifest = build_control_manifest(binding, control_binding, control_file_sha256)
    recipe = build_scene_recipe()
    lighting = build_lighting_sheet(binding)
    grade = build_grade_profile()
    analysis = build_analysis()

    write_json(ROOT / EDITORIAL_ROOT / "reference-preset.json", preset)
    write_json(ROOT / EDITORIAL_ROOT / "photographic-style-contract.json", style)
    write_json(ROOT / MOOD_ROOT / "mood-package.json", mood)
    write_json(ROOT / CONTROL_ROOT / "scene-hint-manifest.json", control_manifest)
    write_json(ROOT / MOOD_ROOT / "scene-recipe.json", recipe)
    write_json(ROOT / MOOD_ROOT / "lighting-sheet.json", lighting)
    write_json(ROOT / MOOD_ROOT / "grade-profile.json", grade)
    write_json(ROOT / SCENE_GRAPH_RELATIVE_PATH, scene_graph)
    write_json(ROOT / MILD_TILT_SCENE_GRAPH_RELATIVE_PATH, scene_graph)
    write_json(
        ROOT / MODERATE_TILT_SCENE_GRAPH_RELATIVE_PATH,
        moderate_scene_graph,
    )
    write_json(ROOT / TEST_ANALYSIS, analysis)
    write_json(ROOT / REFERENCE_CUP_TEST_ANALYSIS, build_reference_cup_analysis())
    write_json(ROOT / HOT_TEST_ANALYSIS, build_hot_analysis())
    update_catalog_and_assignments(scene_graph, binding, file_sha256)
    write_json(
        ROOT / "workflows/26a_wood_handheld_two_person_matcha_source_cup_local_fake_api.json",
        mutate_workflow(
            read_json(BASE_LOCAL_WORKFLOW),
            paid=False,
            container_mode="preserve_source",
        ),
    )
    write_json(
        ROOT / "workflows/26a_wood_handheld_two_person_matcha_source_cup_higgsfield_api.json",
        mutate_workflow(
            read_json(BASE_PAID_WORKFLOW),
            paid=True,
            container_mode="preserve_source",
        ),
    )
    write_json(
        ROOT / "workflows/26b_wood_handheld_two_person_matcha_reference_cup_local_fake_api.json",
        mutate_workflow(
            read_json(BASE_LOCAL_WORKFLOW),
            paid=False,
            container_mode="adopt_reference",
        ),
    )
    write_json(
        ROOT / "workflows/26b_wood_handheld_two_person_matcha_reference_cup_higgsfield_api.json",
        mutate_workflow(
            read_json(BASE_PAID_WORKFLOW),
            paid=True,
            container_mode="adopt_reference",
        ),
    )
    write_json(
        ROOT / "workflows/26f_wood_handheld_hot_photo_hint_local_fake_api.json",
        mutate_workflow(
            read_json(BASE_LOCAL_WORKFLOW),
            paid=False,
            container_mode="preserve_source",
            output_variant="angle_board_v3",
            input_image=HOT_TEST_IMAGE,
            product_analysis_path=HOT_TEST_ANALYSIS,
            pose_hint_variant="hot_photo",
        ),
    )
    write_json(
        ROOT / "workflows/26f_wood_handheld_hot_photo_hint_higgsfield_api.json",
        mutate_workflow(
            read_json(BASE_PAID_WORKFLOW),
            paid=True,
            container_mode="preserve_source",
            output_variant="angle_board_v3",
            input_image=HOT_TEST_IMAGE,
            product_analysis_path=HOT_TEST_ANALYSIS,
            pose_hint_variant="hot_photo",
        ),
    )
    write_json(
        ROOT / "workflows/26h_wood_handheld_hot_cappuccino_openai_gpt_image_2_api.json",
        mutate_openai_workflow(
            input_image=HOT_TEST_IMAGE,
            product_analysis_path=HOT_TEST_ANALYSIS,
            pose_hint_variant="hot_photo",
            output_variant="angle_board_v3_openai",
            seed=904,
        ),
    )
    write_json(
        ROOT / "workflows/26h_wood_handheld_hot_cappuccino_openai_gpt_image_2_local_fake_api.json",
        mutate_openai_smoke_workflow(
            input_image=HOT_TEST_IMAGE,
            product_analysis_path=HOT_TEST_ANALYSIS,
            pose_hint_variant="hot_photo",
            output_variant="angle_board_v3_openai_smoke",
            seed=904,
        ),
    )
    write_json(
        ROOT / "workflows/26i_wood_handheld_matcha_openai_gpt_image_2_api.json",
        mutate_openai_workflow(
            input_image=TEST_IMAGE,
            product_analysis_path=TEST_ANALYSIS,
            pose_hint_variant="iced",
            output_variant="angle_board_v3_openai",
            seed=905,
        ),
    )
    write_json(
        ROOT / "workflows/26i_wood_handheld_matcha_openai_gpt_image_2_local_fake_api.json",
        mutate_openai_smoke_workflow(
            input_image=TEST_IMAGE,
            product_analysis_path=TEST_ANALYSIS,
            pose_hint_variant="iced",
            output_variant="angle_board_v3_openai_smoke",
            seed=905,
        ),
    )
    for label, scene_graph_path in (
        ("tilt_mild", MILD_TILT_SCENE_GRAPH_RELATIVE_PATH),
        ("tilt_moderate", MODERATE_TILT_SCENE_GRAPH_RELATIVE_PATH),
    ):
        write_json(
            ROOT
            / f"workflows/26c_wood_handheld_two_person_matcha_source_cup_{label}_local_fake_api.json",
            mutate_workflow(
                read_json(BASE_LOCAL_WORKFLOW),
                paid=False,
                container_mode="preserve_source",
                scene_graph_path=scene_graph_path,
                output_variant=label,
            ),
        )
        write_json(
            ROOT
            / f"workflows/26c_wood_handheld_two_person_matcha_source_cup_{label}_higgsfield_api.json",
            mutate_workflow(
                read_json(BASE_PAID_WORKFLOW),
                paid=True,
                container_mode="preserve_source",
                scene_graph_path=scene_graph_path,
                output_variant=label,
            ),
        )

    print(json.dumps({"preset_id": PRESET_ID, "asset_id": ASSET_ID, "reference_pixel_sha256": binding["pixel_sha256"], "status": "built"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
