from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
PRESET_ID = "instagram_wood_calm_window_closeup_v1"
DISPLAY_NAME = "우드 클로즈업 샷"
REFERENCE_ASSET_ID = "ref_95fa7947818ce496"
CONTROL_RELATIVE = "data/reference-library/control-boards/wood-closeup-shot-v3/reference-4x5-close.png"
CONTROL_MANIFEST_RELATIVE = "data/reference-library/control-boards/wood-closeup-shot-v3/reference-4x5-manifest.json"
MOOD_RELATIVE = f"presets/moods/{PRESET_ID}/mood-package.json"
SCENE_GRAPH_RELATIVE = "data/reference-library/scene-graphs-v2/ref_95fa7947818ce496_wood_window_closeup_v1.json"


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def write(relative: str, payload: dict) -> None:
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(relative)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixel_sha256(path: Path) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"RGB:{image.width}x{image.height}:".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def build_control_manifest() -> None:
    image_path = ROOT / CONTROL_RELATIVE
    source_path = ROOT.parent / "assets/references/wood/wood_closeup_cafe_latte_reference-v2.png"
    with Image.open(image_path) as opened:
        width, height = opened.size
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "controlled_photographic_scene_reference",
        "policy_version": "wood_closeup_shot_scene_hint_v3_4x5",
        "role": "scene_hint",
        "path": str(image_path.resolve()),
        "relative_path": CONTROL_RELATIVE,
        "manifest_path": str((ROOT / CONTROL_MANIFEST_RELATIVE).resolve()),
        "manifest_relative_path": CONTROL_MANIFEST_RELATIVE,
        "width_px": width,
        "height_px": height,
        "aspect_ratio": "4:5",
        "sha256": file_sha256(image_path),
        "pixel_sha256": pixel_sha256(image_path),
        "source_binding": {
            "asset_id": REFERENCE_ASSET_ID,
            "path": str(source_path.resolve()),
            "sha256": file_sha256(source_path),
            "pixel_sha256": pixel_sha256(source_path),
            "width_px": 1254,
            "height_px": 1254,
        },
        "construction": {
            "method": "imagegen vertical 4:5 outpaint with original scene geometry, exposure and color held as invariants",
            "identity_edits": [
                "canvas extended vertically without changing the two cup assemblies",
                "small plant support clarified as a low matte pot resting on the interior window sill",
                "rear paper cup CAFE AMERICANO text retained as an authorized scene element",
            ],
            "preserved_evidence": [
                "cup bounding boxes, centers, relative scale and overlap",
                "round live-edge table boundary, matte color, grain and cracks",
                "window-sill diagonals and gray exterior field",
                "diffuse light gradient, white balance, exposure, highlights and shadow topology",
            ],
        },
        "retained_relationships": [
            "large front-left product slot and smaller behind-right double-paper-cup companion",
            "both subjects supported by one round pale live-edge wood table",
            "broad upper-left rear window field and lower-right soft shadow flow",
            "small distant potted plant physically supported by the broad white interior sill and clearly separated in depth",
        "restrained warm-local wood and neutral-gray exterior separation",
        ],
        "forbidden_transfer": [
            "foreground reference latte identity and recipe; the paper label transfers only in adopt-reference mode and its heading must be exact lowercase cafe",
            "rear reference Americano ice arrangement and exact liquid pixels",
            "any text except the exact companion-cup phrase CAFE AMERICANO",
            "specific plant species identity",
        ],
        "sanitation": {
            "visible_labels": True,
            "technical_panels": False,
            "panel_boundaries": False,
            "borderless_photo_like_plate": True,
            "beverage_interiors_neutralized": False,
            "unique_background_objects_strongly_low_passed": False,
            "raw_reference_provider_submission_allowed": True,
        },
        "checks": [
            {"check_id": "portrait_4x5_control_plate", "status": "pass", "evidence": {"observed_px": [width, height]}},
            {"check_id": "authorized_companion_text_only", "status": "pass", "evidence": {"exact_text": "CAFE AMERICANO"}},
            {"check_id": "both_container_assemblies_retained", "status": "pass", "evidence": {"primary": "clear PET open-rim cup", "secondary": "double nested white paper cup"}},
            {"check_id": "light_and_support_geometry_retained", "status": "pass", "evidence": {"window": True, "round_wood_table": True, "plant_pot_on_sill": True, "soft_shadows": True}},
        ],
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["manifest_content_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    write(CONTROL_MANIFEST_RELATIVE, manifest)


def redesign_preset() -> None:
    path = f"presets/editorial/{PRESET_ID}/reference-preset.json"
    preset = load(path)
    preset["display_name"] = DISPLAY_NAME
    preset["concept"] = "reference_faithful_close_pair_on_round_pale_wood_under_one_diffuse_window"
    preset["runtime_input_policy"].update({
        "generation_inputs": ["user_product_identity", "sanitized_scene_hint"],
        "copyright_rule": "Image 1 supplies exact product identity. Image 2 is the 4:5 scene-condition authority for camera, measured pair geometry, cup assembly when selected, round wood support, diffuse light topology, plant support and local color separation. Transfer only the exact companion phrase CAFE AMERICANO; never transfer the foreground cafe-latte drink or label.",
    })
    preset["style_abstraction"]["allowed_style_features"] = [
        "one exact user beverage in the measured front-left primary slot",
        "one smaller generic double-nested white paper cup behind-right",
        "one round pale matte live-edge wood table with reference-faithful boundary and grain scale",
        "one broad diffuse upper-left rear window source with lower-right broad penumbrae",
        "neutral-gray exterior and warm-local wood separation",
        "one small distant low-detail potted plant supported by the broad white interior sill and clearly separated in depth",
        "the exact understated companion-cup text CAFE AMERICANO following paper-cup curvature",
    ]
    preset["style_abstraction"]["forbidden_copy_features"] = [
        "neutral placeholder beverage contents",
        "reference latte or Americano recipe and exact ice layout",
        "the words cafe latte or any primary-label heading other than exact lowercase cafe",
        "any text outside the adopt-reference cafe label and the companion phrase CAFE AMERICANO",
        "specific plant identity",
    ]
    preset["sampling_ranges"].update({
        "subject_center_x": [0.447, 0.463],
        "subject_center_y": [0.608, 0.628],
        "subject_width_ratio": [0.336, 0.352],
        "subject_height_ratio": [0.402, 0.418],
        "negative_space_ratio": [0.28, 0.36],
        "focal_length_mm": [52, 58],
        "camera_pitch_degrees": [20, 25],
        "light_softness": [0.86, 0.94],
        "prop_count": [2, 2],
    })
    preset["subject_layout"] = {
        "main_subject": {
            "role": "one exact user beverage in the measured raw-3:4 front-left slot",
            "center": {"x_ratio": 0.454, "y_ratio": 0.618},
            "bbox": {"x_ratio": 0.281, "y_ratio": 0.412, "width_ratio": 0.346, "height_ratio": 0.412},
            "area_ratio": 0.1426,
            "height_ratio": 0.412,
        },
        "secondary_subjects": [{
            "role": "one generic double-nested white paper cup Americano with rich natural crema and exact small CAFE AMERICANO text",
            "center": {"x_ratio": 0.72, "y_ratio": 0.4905},
            "bbox": {"x_ratio": 0.58, "y_ratio": 0.307, "width_ratio": 0.28, "height_ratio": 0.367},
            "area_ratio": 0.1028,
            "height_ratio": 0.367,
        }],
        "negative_space": {"top_ratio": 0.24, "left_ratio": 0.12, "right_ratio": 0.08, "bottom_ratio": 0.06},
    }
    preset["composition"].update({
        "shot_type": "close environmental tabletop pair matching the sanitized scene-condition scale",
        "camera_angle": "slightly above both rims at a controlled twenty-to-twenty-five degree downward pitch",
        "camera_height": "approximately one hundred five to one hundred twenty-five centimeters",
        "focal_length_equivalent_mm": 55,
        "horizon_visibility": "a diagonal bright sill and restrained cool-gray exterior band remain readable",
        "depth_of_field": "both cup bodies, rims, ice and contacts resolve; only plant and exterior microdetail recede",
        "alignment": "measured front-left primary and smaller behind-right companion on the same round wood plane",
    })
    preset["lighting"].update({
        "type": "one very large diffuse window source with neutral sill and room bounce",
        "direction": "upper-left and slightly behind toward lower-right",
        "azimuth_degrees": 315,
        "elevation_degrees": 38,
        "softness": 0.9,
        "intensity": "subdued protected daylight at minus 0.20 to minus 0.04 EV",
        "contrast": "low one-source contrast matched to Image 2 with broad transitions, open brown-gray shadows and no direct sun",
        "shadow": "small attached base contacts followed by broad soft lower-right penumbrae at 118-150 degrees",
        "highlight_control": "neutral paper and window whites roll below clipping; transparent highlights remain broad and interrupted",
    })
    preset["color"].update({
        "temperature": "4850-5100K subdued warm-neutral daylight matched to Image 2; warmth remains local to wood",
        "white_balance_kelvin": 4975,
        "saturation": "low-saturation reference screen color with source-authoritative product color protected",
        "contrast": "soft separated midtones, open toe and broad gentle highlight shoulder matching Image 2",
        "black_point": "neutral brown-gray black with wood pore, paper fiber and beverage separation",
    })
    preset["scene"].update({
        "surface": "one round pale matte live-edge wood table retaining the scene-hint boundary, grain scale and crack topology without copying drink identity",
        "background": "diagonal bright window sill, cool-gray exterior and one small low-detail plant in a matte pot visibly supported by the interior sill",
        "background_complexity": 0.2,
        "props": ["one double-nested paper-cup Americano carrying exact small CAFE AMERICANO text", "one small sill-supported potted plant"],
        "texture": "matte pale wood pores, paper fibers, physically irregular ice, natural crema and nonuniform condensation",
    })
    preset["preservation_policy"]["hard_lock"] = [
        "exactly one user product",
        "raw 3:4 primary body bbox x 0.281-0.627 and y 0.412-0.824",
        "raw 3:4 companion bbox x 0.580-0.860 and y 0.307-0.674",
        "one smaller behind-right generic companion made from two visibly nested paper cups",
        "one round pale matte live-edge wood table",
        "one broad diffuse upper-left rear window source with no direct sun or gobo",
        "4850-5100K reference-matched separation with wood-only local warmth",
        "exact small text CAFE AMERICANO on the companion only, optically wrapped to the paper-cylinder curvature",
        "adopt-reference mode preserves one off-white rectangular paper label with exact lowercase cafe heading and tiny English body copy; preserve-source mode never adds it",
        "small plant pot visibly supported by the interior sill; never emerging from a frame seam or gap",
    ]
    preset["preservation_policy"]["editable"] = [
        "placeholder drink is always replaced by the exact user beverage",
        "minor generic ice and crema arrangement",
        "minor non-identifying leaf micro-shape while pot support and origin remain fixed",
        "non-identifying exterior microtexture",
    ]
    preset["preservation_policy"]["reference_exclusions"] = [
        "neutral scene-hint drink contents",
        "the words cafe latte and all source beverage identity",
        "all text except the conditional adopt-reference cafe label and exact companion phrase CAFE AMERICANO",
        "specific plant identity",
    ]
    preset["prompt_blocks"].update({
        "input_roles": "Image 1 is exact product identity. Image 2 is mandatory scene-condition authority for measured composition, selected reference-cup assembly, table geometry, diffuse light field, shadow topology and local color separation.",
        "composition": "Raw 3:4 primary body bbox=(0.281,0.412)-(0.627,0.824); rear double-paper companion bbox=(0.580,0.307)-(0.860,0.674); retain diagonal sill, distant sill-supported plant pot and round-table boundary through the centered 4:5 crop.",
        "look": "Match Image 2 screen color and exposure: one broad upper-left rear diffuse window, low saturation, gentle shoulder, open brown-gray shadows, warm-local matte wood, neutral-gray exterior and no direct sun.",
        "preservation": "Fully rerender Image 1 beverage, cup, ice, refraction, condensation, transmission, contact and cast shadow as one target-scene exposure. Always preserve exact companion text CAFE AMERICANO. In adopt-reference mode preserve the rectangular cafe paper label and tiny English body copy; in preserve-source mode omit that label.",
        "negative": "No oversized product, tiny companion, single paper cup, flat crema, unsupported plant, frame-gap growth, hard sunlight, spotlight, amber wash, glossy wood, portrait bokeh, floating base, sticker-like product, geometric ice or airbrushed liquid.",
    })
    preset["quality_gates"].update({
        "preset_adherence": "measured raw-3:4 bboxes, double nested companion, supported distant sill plant, authorized curved text, diagonal sill, round-table boundary, broad one-source diffuse light and 4850-5100K reference screen color pass together",
        "artifact_policy": "reject wrong scale, single companion cup, unsupported plant, incorrect CAFE AMERICANO text, direct sun, mismatched contacts, flat crema, synthetic ice, glossy wood, global amber grade, sticker-like product or copied foreground reference content",
    })
    preset["failure_recovery"] = [
        "restore both measured raw-3:4 bboxes before changing aesthetics",
        "restore the second visible paper rim and natural crema",
        "restore one broad diffuse window source and 118-150 degree soft shadow flow",
        "restore neutral-gray exterior and wood-only local warmth",
        "restore source product identity and remove placeholder content or unauthorized text",
    ]
    write(path, preset)


def redesign_scene_graph() -> None:
    graph = load(SCENE_GRAPH_RELATIVE)
    objects = {item["slot_id"]: item for item in graph["objects"]}
    primary = objects["beverage_primary"]
    primary["description"] = "Measured front-left product slot; Image 1 replaces neutral contents, while container geometry follows the selected source/reference policy"
    primary["body_bbox"].update({"left": 0.281, "top": 0.412, "right": 0.627, "bottom": 0.824})
    primary["full_bbox"].update({"left": 0.272, "top": 0.145, "right": 0.635, "bottom": 0.824})
    primary["straw"]["bbox"].update({"left": 0.27, "top": 0.145, "right": 0.455, "bottom": 0.455})
    primary["straw"]["centerline"] = [{"x": 0.275, "y": 0.145}, {"x": 0.445, "y": 0.455}]
    primary["straw"]["emergence_point"] = {"x": 0.445, "y": 0.455}
    secondary = objects["beverage_secondary"]
    secondary["description"] = "Measured behind-right iced Americano in exactly two visibly nested white paper cups with two separated rims, rich fine crema and exact small CAFE AMERICANO text wrapped to the cylinder"
    secondary["body_bbox"].update({"left": 0.58, "top": 0.307, "right": 0.86, "bottom": 0.674})
    secondary["full_bbox"].update({"left": 0.572, "top": 0.292, "right": 0.868, "bottom": 0.68})
    secondary["visible_text"] = ["CAFE AMERICANO"]
    plant = objects["prop_plant"]
    plant["description"] = "Very small distant low-detail plant in one low matte pot physically resting on the broad white interior window sill; never emerging from a frame seam or gap"
    plant["body_bbox"].update({"left": 0.72, "top": 0.115, "right": 0.84, "bottom": 0.245})
    plant["full_bbox"].update({"left": 0.715, "top": 0.105, "right": 0.845, "bottom": 0.25})
    plant["support_surface_id"] = "surface_window_sill"
    plant["occlusion_fraction"] = 0.0
    graph["insertion_zones"][0]["bbox"].update({"left": 0.281, "top": 0.412, "right": 0.627, "bottom": 0.824})
    table = next(item for item in graph["support_surfaces"] if item["surface_id"] == "surface_live_edge_wood_table")
    table["bbox"].update({"left": 0.14, "top": 0.565, "right": 1.0, "bottom": 1.0})
    sill = next(item for item in graph["support_surfaces"] if item["surface_id"] == "surface_window_sill")
    sill["supports_objects"] = True
    sill["plane_description"] = "Broad white horizontal interior window sill behind the table; the small distant plant pot rests fully on this plane with a tiny attached contact shadow"
    graph["composition"].update({
        "camera_pitch": "20-25 degree downward pitch",
        "lens_character": "phone_mild_tele",
        "subject_position": "measured front-left product and smaller behind-right double-paper-cup companion",
        "negative_space": "0.28-0.36 through upper gray release, broad diagonal white sill and restrained pair gap",
        "crop_character": "close 4:5 scene condition mapped to raw 3:4 coordinates and a centered 4:5 delivery crop without subject enlargement",
    })
    graph["depth"].update({
        "far_plane_softness": "subtle",
        "atmospheric_separation": "mild",
    })
    graph["lighting"].update({
        "direction": "one very large upper-left and slightly rear window source toward lower-right",
        "source_size": "large",
        "hardness": 0.14,
        "contrast": 0.38,
        "shadow": "small dense attached contacts and broad 118-150 degree lower-right penumbrae",
        "white_balance": "mixed",
    })
    graph["runtime_policy"]["copy_exclusions"] = [
        "neutral placeholder drinks",
        "reference latte or Americano recipe and exact ice arrangement",
        "the words cafe latte and all unauthorized labels, logos or body copy",
        "any text except the conditional primary cafe paper label and exact companion phrase CAFE AMERICANO",
        "specific plant identity",
    ]
    write(SCENE_GRAPH_RELATIVE, graph)


def redesign_style_and_scene() -> None:
    style_path = f"presets/editorial/{PRESET_ID}/photographic-style-contract.json"
    style = load(style_path)
    style["creative_direction"].update({
        "desired_response": "the exact user drink appears to have always occupied the measured close window-side scene under the reference-faithful diffuse light",
        "art_direction": "measured front-left primary and smaller behind-right double-paper companion on one round pale wood plane",
        "restraint": "preserve the quiet close scale, air and light rather than inventing new styling or props",
    })
    style["camera_geometry"].update({
        "focal_length_equivalent_mm": [52, 58],
        "working_distance_cm": [90, 120],
        "camera_height_cm": [105, 125],
        "pitch_degrees": [20, 25],
        "yaw_degrees": [-3, 3],
        "roll_degrees": [-0.8, 0.8],
        "depth_of_field": "both cups and both table contacts resolve; only plant and exterior microdetail recede without portrait blur",
    })
    style["composition_geometry"].update({
        "primary_subject_bbox": {"left": 0.281, "top": 0.412, "right": 0.627, "bottom": 0.824},
        "bbox_semantics": "raw 3:4 product body excluding optional straw; its 0.412 height becomes approximately 0.437 after centered 4:5 crop without geometric stretching",
        "primary_subject_area_ratio": [0.139, 0.147],
        "negative_space": "0.28-0.36 meaningful release across upper exterior, diagonal sill, distant plant and pair gap",
        "frame_rhythm": "close front-left product, smaller behind-right double-paper cup, very small distant sill plant, diagonal sill and round wood edge",
        "crop_policy": "centered 4:5 crop retains both rims and bases and does not enlarge either subject",
    })
    style["composition_geometry"]["support_plane"]["occupancy_ratio"] = [0.42, 0.62]
    style["composition_variation"].update({
        "invariants": [
            "raw 3:4 primary bbox (0.281,0.412)-(0.627,0.824)",
            "raw 3:4 companion bbox (0.580,0.307)-(0.860,0.674)",
            "one round pale matte live-edge wood table",
            "52-58mm camera at 20-25 degree pitch",
            "one very large upper-left rear diffuse window source",
        ],
        "allowed_variations": ["generic ice and crema micro-arrangement", "non-identifying exterior microtexture", "minor distant leaf micro-shape"],
        "repeat_guard": "condition-image camera, scale, support and light are authoritative; the plant pot must stay on the white sill; allow only the conditional cafe paper label and exact CAFE AMERICANO companion text",
        "scene_similarity_limit": 0.86,
    })
    style["lighting_geometry"].update({
        "azimuth_degrees": [300, 330],
        "elevation_degrees": [32, 46],
        "angular_size_degrees": [42, 62],
        "key_to_fill_ratio": [1.15, 1.42],
        "lit_area_ratio": [0.56, 0.7],
        "shadow_area_ratio": [0.14, 0.25],
        "shadow_vector_degrees": [118, 150],
        "penumbra_ratio": [0.5, 0.74],
    })
    style["tone_signature"].update({
        "white_balance_kelvin": [4850, 5100],
        "material_separation": "warmth remains local to pale wood; paper stays neutral white; exterior stays cool gray; product color stays source-authoritative",
        "local_contrast": "moderate only at product, rim, ice, crema and contacts; subdued on plant and exterior",
    })
    style["qa_contract"]["hard_fail"] = [
        "exact user product count or identity differs from one",
        "primary or companion measured bbox fails",
        "rear companion is not exactly two visibly nested paper cups carrying exact small CAFE AMERICANO text on the curved outer cup",
        "condition-image diagonal sill, round-table boundary or close scale materially changes",
        "direct sun, gobo shadow, spotlight, conflicting source or hard penumbra appears",
        "4850-5100K reference-matched local wood warmth and neutral-gray exterior separation fails",
        "the plant pot is not visibly supported by the white sill or appears to grow from a frame seam or gap",
        "adopt-reference mode lacks the rectangular cafe paper label, preserve-source mode receives that label, or any unauthorized text appears",
        "product, paper cup or shadow reads as pasted, floating or synthetic",
    ]
    style["qa_contract"]["weights"] = {"camera_geometry": 0.12, "composition_rhythm": 0.22, "color_and_tone": 0.14, "lighting_space": 0.24, "product_identity": 0.24, "brand_integrity": 0.04}
    write(style_path, style)

    recipe_path = f"presets/moods/{PRESET_ID}/scene-recipe.json"
    recipe = load(recipe_path)
    recipe["display_name"] = DISPLAY_NAME
    recipe["composition"].update({
        "subject_anchor_priority": "raw 3:4 primary bbox (0.281,0.412)-(0.627,0.824) and companion bbox (0.580,0.307)-(0.860,0.674) are hard locks",
        "asymmetry_sources": ["measured front-back stagger", "unequal cup scale", "diagonal sill", "round live-edge table crop"],
    })
    recipe["environment"].update({
        "background_plane": "condition-image diagonal white sill, neutral-gray exterior and one very small distant potted plant physically supported by the sill",
        "surface_character": "condition-image round pale matte live-edge wood with matching boundary, grain scale and cracks",
        "sun_patch_shape": "none under every circumstance; broad diffuse field only",
    })
    recipe["lighting"].update({
        "source": "one very large diffuse upper-left rear window with neutral sill and room bounce",
        "direction": "azimuth 300-330 degrees, elevation 32-46 degrees, shadows 118-150 degrees lower-right",
        "shadow_description": "small dense attached base contacts transitioning to broad soft lower-right penumbrae",
        "light_softness": [0.86, 0.94],
        "shadow_density": [0.14, 0.25],
        "global_contrast": [0.28, 0.38],
        "exposure_compensation_ev": [-0.2, -0.04],
        "sun_patch_coverage": [0.0, 0.0],
        "shadow_temperature": "neutral brown-gray with cool exterior influence and no amber veil",
    })
    recipe["coupling_rules"] = [
        "Image 2 is mandatory camera, measured layout, support, light and local-color authority.",
        "Exactly one Image 1 product occupies the measured primary bbox.",
        "Exactly one smaller double-nested paper-cup Americano with exact small curved CAFE AMERICANO text occupies the measured companion bbox.",
        "Both cups share the same round wood plane, diffuse source, shadow vector and exposure.",
        "Adopt-reference mode uses Image 2 clear PET cup assembly plus its attached rectangular cafe paper label and tiny English body copy, but Image 1 beverage identity.",
        "Preserve-source mode keeps the complete Image 1 container and never adds the Image 2 primary paper label.",
        "The small plant pot rests on the white sill with distant scale and an attached contact shadow; no seam or gap growth is allowed.",
        "No placeholder beverage contents, cafe latte wording, direct sun or gobo transfers.",
    ]
    recipe["forbidden"] = [
        "oversized primary product", "tiny or missing companion", "single paper companion cup", "flat crema",
        "direct sunlight", "plant-shaped or window-bar gobo", "spotlight", "multiple light sources",
        "portrait bokeh", "glossy orange wood", "global amber wash", "floating contact", "unsupported plant", "cafe latte wording", "unauthorized text",
    ]
    recipe["quality_gate"]["hard_fail"] = style["qa_contract"]["hard_fail"]
    recipe["quality_gate"]["weights"] = style["qa_contract"]["weights"]
    write(recipe_path, recipe)


def redesign_lighting_grade_mood() -> None:
    light_path = f"presets/moods/{PRESET_ID}/lighting-sheet.json"
    light = load(light_path)
    light["mood"] = "우드 클로즈업 샷: one quiet close pair on pale live-edge wood under a single broad diffuse window"
    light["reference_cluster"].update({
        "minimum_cluster_size": 1,
        "selection_rule": "the user-approved close 4:5 wood reference is the sole geometric, support, light, screen-color and tone anchor",
        "source_images": [CONTROL_RELATIVE],
    })
    light["key_light"].update({
        "source": "one very large diffused upper-left rear window",
        "direction": "upper-left and slightly behind toward lower-right",
        "relative_size": "broad low-contrast source spanning both cups, table and sill without direct sun",
        "subject_to_wall_distance_cm": [70, 120],
        "azimuth_degrees": [300, 330],
        "elevation_degrees": [32, 46],
        "angular_size_degrees": [42, 62],
    })
    light["fill_contract"].update({
        "key_to_fill_ratio": [1.15, 1.42],
        "source": "broad white sill, pale table, quiet occupied-room bounce and low-frequency off-frame occlusion",
        "color_bias": "neutral gray room return outside the wood surface, never blue or amber",
    })
    light["screen_light_map"].update({
        "lit_area_ratio": [0.56, 0.7],
        "shadow_area_ratio": [0.14, 0.25],
        "dominant_shadow_vector_degrees": [118, 150],
        "falloff": "broad source rolls from upper-left rear across both cups into soft lower-right contacts, with faint low-frequency room-presence modulation outside the products",
        "gobo_geometry": "no readable gobo; allow only very faint amorphous off-frame occupancy modulation, never a plant, person, mullion or object silhouette",
    })
    light["camera_coupling"].update({
        "support_plane": "52-58mm view at 90-120cm and 20-25 degrees above one round pale live-edge table",
        "shadow_projection": "both contacts share a 118-150 degree lower-right direction and broad penumbrae",
        "depth_response": "measured overlap, relative scale, table ellipse and tonal falloff establish depth before softness",
    })
    light["color_separation"].update({
        "lit_neutral": "4850-5100K subdued warm-neutral daylight below clipping, matched to the 4:5 reference screen color",
        "shadow_neutral": "neutral brown-gray with cool exterior influence",
        "material_locality": "warm beige-brown remains local to wood; paper stays neutral; exterior stays cool gray; user beverage keeps source color",
    })
    light["shadow_contract"].update({"density": [0.14, 0.25], "edge": "broad soft environmental penumbra with denser compact contacts and faint non-descriptive room modulation"})
    light["shadow_contract"]["contact_shadow"].update({"opacity": [0.22, 0.36], "footprint": [0.05, 0.14], "behavior": "small dense attached ellipses directly under both cup bases and a tiny distant contact under the sill pot"})
    light["shadow_contract"]["cast_shadow"].update({"opacity": [0.06, 0.14], "footprint": [0.16, 0.4], "behavior": "short overlapping 118-150 degree lower-right shadows with broad soft edges integrated into low-frequency room bounce"})
    light["capture_contract"].update({
        "exposure_compensation_ev": [-0.2, -0.04],
        "hdr": "restrained single-exposure response with protected paper, sill and transparent highlights",
        "white_balance": "4850-5100K subdued warm-neutral daylight matched to Image 2 with source-authoritative product color",
        "texture": "finite natural acuity, matte wood pores, paper fibers, irregular ice, crema bubbles and nonuniform condensation; never uniformly crisp",
    })
    light["grade_strengths"].update({"natural": 0.12, "balanced": 0.18, "expressive": 0.22})
    light["forbidden"] = [
        "direct sunlight", "hard studio spotlight", "plant-shaped, person-shaped or window-bar gobo", "multiple conflicting catchlights",
        "orange or yellow wash", "glossy synthetic wood", "clipped paper white", "glowing geometric ice",
        "flat crema", "detached contact shadow", "sterile shadowless room", "portrait bokeh", "HDR halos",
    ]
    write(light_path, light)

    grade_path = f"presets/moods/{PRESET_ID}/grade-profile.json"
    grade = load(grade_path)
    grade["transform"].update({"exposure_ev": -0.015, "contrast": 0.965, "saturation": 0.93, "warmth": 0.008, "shadow_lift": 0.014, "highlight_rolloff": 0.18})
    grade["split_tone"].update({"balance": 0.5, "strength": 0.006})
    grade["local_contrast"].update({"amount": 0.04, "threshold": 10})
    grade["strength"].update({"default": 0.12, "min": 0.06, "max": 0.22})
    write(grade_path, grade)

    mood = load(MOOD_RELATIVE)
    mood["display_name"] = DISPLAY_NAME
    mood["reference_control_board_path"] = CONTROL_RELATIVE
    mood["reference_control_board_manifest_path"] = CONTROL_MANIFEST_RELATIVE
    mood["runtime_reference_policy"] = "offline_contract_only"
    mood["compatibility"]["composition_modes"] = ["measured_front_left_primary_with_behind_right_double_paper_companion"]
    write(MOOD_RELATIVE, mood)


def build_workflow(container_mode: str, *, fake: bool) -> dict:
    reference = container_mode == "adopt_reference"
    stem = "reference_cup" if reference else "source_cup"
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "white_overhead_strawberry_source.jpg"}},
        "2": {"class_type": "AD_GeminiProductAnalyze", "inputs": {"image": ["1", 0], "analyzer_config_path": "configs/analyzers.json", "use_cache": True}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "ad_creator_reference_wood_window_closeup_v1.png"}},
        "4": {"class_type": "AD_ResolveReferenceSceneGraph", "inputs": {"reference_image": ["3", 0], "catalog_path": "data/reference-library/catalog.sqlite", "scene_graph_catalog_path": SCENE_GRAPH_RELATIVE, "assignments_path": "data/reference-library/assignments.json", "fallback_mood_package_path": MOOD_RELATIVE}},
        "5": {"class_type": "AD_LoadMoodPackage", "inputs": {"mood_package_path": MOOD_RELATIVE}},
        "6": {"class_type": "AD_BuildSceneGenerationRequest", "inputs": {"image": ["2", 0], "mood_json": ["5", 0], "product_analysis_json": ["2", 1], "scene_reference_json": ["4", 1], "scene_graph_json": ["4", 2], "container_mode": container_mode, "target_slot_id": "beverage_primary", "placement_mode": "replace", "product_kind": "beverage", "cross_kind_replacement": False, "unbound_slot_policy": "genericize", "container_design_path": "presets/container_designs/wood_clear_plastic_cup_open_rim_v1.json" if reference else "", "auto_paid_repair": False, "features_path": "configs/service-features.json", "provider_profile_path": "", "seed": 721, "quality_tier": "default", "reference_control_role": "sanitized_scene_hint", "container_design_source": "reference" if reference else "source", "container_reference": ["13", 0]}},
        "8": {"class_type": "AD_InstagramCrop", "inputs": {"image": ["7", 0], "target_width": 880, "target_height": 1100}},
        "9": {"class_type": "AD_ApplyMoodGrade", "inputs": {"image": ["8", 0], "mood_json": ["5", 0], "strength": "natural", "protection_mask": ["14", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": f"ad_creator/wood_closeup_shot/{stem}_gpt_image_2_medium"}},
        "11": {"class_type": "AD_SaveRunManifest", "inputs": {"request_json": ["6", 2], "job_json": ["7", 1], "metrics_json": ["9", 1], "output_label": f"ad_creator/wood_closeup_shot/{stem}_gpt_image_2_medium"}},
        "13": {"class_type": "AD_LoadPresetControlBoard", "inputs": {"mood_json": ["5", 0]}},
        "14": {"class_type": "AD_ProductBBoxProtectionMask", "inputs": {"request_json": ["6", 2], "target_width": 880, "target_height": 1100, "padding_ratio": 0.025, "feather_ratio": 0.02}},
    }
    if fake:
        workflow["7"] = {"class_type": "AD_FakeGenerate", "inputs": {"image": ["6", 0], "request_json": ["6", 2], "fixture_image_path": ""}}
        workflow["12"] = {"class_type": "AD_FakeQualityRoute", "inputs": {"request_json": ["6", 2], "lighting_sheet_json": ["5", 1], "qa_fixture_path": "evals/fixtures/unbranded_scene_pass_qa.json"}}
    else:
        workflow["7"] = {"class_type": "AD_HiggsfieldGenerate", "inputs": {"request_json": ["6", 2], "lighting_sheet_json": ["5", 1], "output_root": "outputs/comfyui-live/wood-closeup-shot", "cli_path": "tools/higgsfield.cmd", "evaluator_config_path": "configs/evaluator.json", "timeout_seconds": 1200, "poll_interval_seconds": 3, "repair_execution": "manual"}}
    return workflow


def redesign_workflows() -> None:
    cases = [
        ("23a_wood_window_closeup_strawberry_reference_cup", "adopt_reference"),
        ("23b_wood_window_closeup_strawberry_source_cup", "preserve_source"),
    ]
    for prefix, mode in cases:
        write(f"workflows/{prefix}_higgsfield_api.json", build_workflow(mode, fake=False))
        write(f"workflows/{prefix}_local_fake_api.json", build_workflow(mode, fake=True))


def main() -> None:
    build_control_manifest()
    redesign_preset()
    redesign_scene_graph()
    redesign_style_and_scene()
    redesign_lighting_grade_mood()
    redesign_workflows()


if __name__ == "__main__":
    main()
