from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PRESET_ID = "instagram_white_diffuse_closeup_v1"
DISPLAY_NAME = "화이트계열 클로즈업"
SOURCE = ROOT.parent / "data" / "프리셋초안" / "화이트계열_클로즈업_레퍼런스_v6.png"
INPUT_IMAGE = ROOT / "comfyui-inputs" / "ad_creator_reference_white_closeup_cylindrical_v2.png"
REFERENCE_GEOMETRY_HINT_IMAGE = "white_closeup_reference_cup_saucer_cylindrical_geometry_v2.png"
GRAPH_REL = "data/reference-library/scene-graphs-v2/ref_white_closeup_v1.json"


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def write(relative: str, payload: dict) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(relative)


def copy_reference() -> tuple[int, int, str]:
    INPUT_IMAGE.parent.mkdir(parents=True, exist_ok=True)
    if not INPUT_IMAGE.exists():
        shutil.copy2(SOURCE, INPUT_IMAGE)
    elif hashlib.sha256(INPUT_IMAGE.read_bytes()).digest() != hashlib.sha256(SOURCE.read_bytes()).digest():
        raise RuntimeError(
            "Existing approved white close-up reference differs from the source; "
            "refusing to overwrite it implicitly"
        )
    with Image.open(INPUT_IMAGE) as image:
        width, height = image.size
    digest = hashlib.sha256(INPUT_IMAGE.read_bytes()).hexdigest()
    print(INPUT_IMAGE.relative_to(ROOT))
    return width, height, digest


def pixel_sha256(path: Path) -> str:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"RGB:{rgb.width}x{rgb.height}:".encode("ascii"))
    digest.update(rgb.tobytes())
    return digest.hexdigest()


def build(width: int, height: int, digest: str) -> None:
    asset_id = f"ref_{digest[:16]}"
    pixel_digest = pixel_sha256(INPUT_IMAGE)
    preset = load("presets/editorial/instagram_white_neutral_overhead_spatial_v1/reference-preset.json")
    preset.update({"preset_id": PRESET_ID, "display_name": DISPLAY_NAME, "concept": "large_white_interior_closeup_with_diffuse_room_air"})
    preset["source"].update({"reference_image": str(INPUT_IMAGE.relative_to(ROOT)).replace("\\", "/"), "width_px": width, "height_px": height, "supporting_group": "user_approved/white_closeup_v6"})
    preset["runtime_input_policy"].update({
        "generation_inputs": ["user_product_identity", "sanitized_scene_hint"],
        "reference_usage": "offline_feature_extraction_only",
        "copyright_rule": "Rebuild a new scene from the light, space and crop grammar. Never trace the exact table texture, shadow masses, waffle details or magazine alignment.",
    })
    preset["style_abstraction"].update({
        "runtime_reference_image": False,
        "novel_scene_required": True,
        "allowed_style_features": [
            "one large close product assembly on a warm ivory-white matte table",
            "broad upper-left diffuse window light and soft lower-right shadows",
            "partial normal-size waffle plate entering only at upper-left edge",
            "partial Barton Springs magazine entering at upper-right edge",
            "quiet off-frame occupancy shadows and finite depth falloff",
            "low straight cylindrical reference glass in adopt-reference mode, with the approved saucer and wood-handled teaspoon completing the serving assembly in both modes",
        ],
        "forbidden_copy_features": ["reference beverage identity", "exact reference pixels", "exact table marks", "exact shadow silhouette", "exact waffle pixels", "exact magazine placement", "watermark"],
    })
    preset["sampling_ranges"].update({
        "pov_modes": ["high three-quarter close tabletop"], "subject_center_x": [0.47, 0.53], "subject_center_y": [0.47, 0.55],
        "subject_width_ratio": [0.53, 0.62], "subject_height_ratio": [0.46, 0.57], "negative_space_ratio": [0.32, 0.42],
        "focal_length_mm": [52, 58], "camera_pitch_degrees": [42, 49], "light_softness": [0.86, 0.95], "prop_count": [2, 2],
        "asymmetry_probability": 1.0, "asymmetry_sources": ["partial waffle at upper-left and partial magazine at upper-right"],
    })
    preset["tone_contract"].update({
        "background_plane": "warm ivory-white matte tabletop inside a real white cafe room",
        "background_lightness": [0.72, 0.9], "background_saturation": [0.025, 0.075], "global_contrast": [0.3, 0.44], "shadow_density": [0.14, 0.29],
        "color_bias": "warm-neutral white with neutral gray shadows, never beige or blue",
        "highlight_behavior": "soft protected shoulder retaining table, glass, cream and paper texture",
        "forbidden_surface_reading": ["seamless studio sweep", "glossy acrylic", "fabric", "wood", "pure white void"],
    })
    preset["subject_layout"] = {
        "main_subject": {"role": "one large exact user beverage and serving assembly", "center": {"x_ratio": 0.5, "y_ratio": 0.51}, "bbox": {"x_ratio": 0.21, "y_ratio": 0.24, "width_ratio": 0.58, "height_ratio": 0.54}, "area_ratio": 0.30, "height_ratio": 0.54},
        "secondary_subjects": [
            {"role": "partial normal-size waffle plate at upper-left frame edge", "center": {"x_ratio": 0.03, "y_ratio": 0.17}, "bbox": {"x_ratio": 0.0, "y_ratio": 0.06, "width_ratio": 0.16, "height_ratio": 0.22}, "area_ratio": 0.035, "height_ratio": 0.22},
            {"role": "partial Barton Springs magazine at upper-right frame edge", "center": {"x_ratio": 0.91, "y_ratio": 0.18}, "bbox": {"x_ratio": 0.8, "y_ratio": 0.04, "width_ratio": 0.2, "height_ratio": 0.28}, "area_ratio": 0.056, "height_ratio": 0.28},
        ],
        "negative_space": {"top_ratio": 0.18, "left_ratio": 0.14, "right_ratio": 0.13, "bottom_ratio": 0.15},
    }
    preset["composition"].update({
        "shot_type": "large close environmental tabletop product", "camera_angle": "natural high three-quarter view at 42-49 degrees", "camera_height": "close above the table",
        "focal_length_equivalent_mm": 55, "horizon_visibility": "none; room depth is implied by light, overlap, edge crops and finite focus falloff",
        "depth_of_field": "complete product and spoon readable; edge props mildly and physically defocused", "alignment": "large central product balanced by peripheral edge crops",
    })
    preset["lighting"].update({
        "type": "one very large diffuse window source plus weak neutral white-room bounce", "direction": "upper-left/left-front toward lower-right", "azimuth_degrees": 315,
        "elevation_degrees": 48, "softness": 0.91, "intensity": "protected natural daylight at -0.15 to 0 EV", "contrast": "low but dimensional",
        "shadow": "compact attached contacts plus broad low-density lower-right penumbrae and faint off-frame occupancy modulation",
        "highlight_control": "retain white table, saucer, cream, glass rim, spoon and magazine paper texture without clipping",
    })
    preset["color"].update({"temperature": "5000-5300K warm-neutral daylight", "white_balance_kelvin": 5150, "saturation": "low globally; preserve beverage-internal color relationships while re-illuminating bright low-chroma milk or cream into the target warm-neutral exposure", "contrast": "soft midtone separation", "palette_hex": ["#E4E0D8", "#D7D2C8", "#C4BEB4", "#AAA39A", "#716B66"], "black_point": "open neutral gray-brown"})
    preset["scene"].update({"surface": "warm ivory-white matte cafe tabletop with subtle real texture", "background": "minimal white interior implied by diffuse light and off-frame spatial shadows", "background_complexity": 0.16, "props": ["partial waffle plate at upper-left edge", "partial Barton Springs magazine at upper-right edge"], "max_prop_count": 2, "texture": "subtle matte table variation, paper fiber, natural food texture and finite social-photo grain"})
    preset["capture"].update({"look": "natural high three-quarter Instagram cafe close-up with quiet white-room depth", "realism": "one physical exposure and one broad window source connect product, continuous tabletop and distant edge props", "grain": "faint luminance grain after ordinary social compression", "imperfections": ["minor matte table tone variation", "natural beverage, ice and garnish asymmetry", "unequal peripheral focus falloff", "broad incomplete off-frame occupancy shadows"]})
    preset["preservation_policy"] = {
        "hard_lock": ["exact user beverage identity, layers, ice and toppings", "one 110-percent large central cup-saucer-spoon serving assembly", "low straight cylindrical reference glass, complete warm-white saucer and wood-handled teaspoon together in adopt-reference mode", "exact user cup centered on the approved saucer with the approved teaspoon in preserve-source mode", "single diffuse upper-left light", "partial waffle left and magazine right"],
        "editable": ["invented table microtexture", "soft environmental shadow masses", "minor edge-prop crop and focus falloff", "container only under selected mode"],
        "reference_exclusions": ["reference beverage", "exact serving-assembly pixels", "exact table marks", "exact shadow silhouette", "watermark"],
    }
    preset["prompt_blocks"].update({
        "input_roles": "Image 1 owns beverage identity and the user cup when selected. Image 2 owns the approved white-closeup composition, diffuse light, saucer, wood-handled teaspoon and peripheral depth cues.",
        "composition": "One 110-percent large cup-saucer-spoon serving assembly fills the central-lower 4:5 frame while the saucer and spoon stay complete; only a cropped edge of a normal-size waffle plate enters upper-left and a partial Barton Springs magazine enters upper-right; preserve the approved perspective and scale hierarchy.",
        "look": "Warm-neutral white interior, one broad upper-left/left-front diffuse window at 5050-5250K, soft lower-right contacts, long feathered penumbrae, restrained transmission through glass and liquid, and faint off-frame occupancy shadows with real room air.",
        "preservation": "Preserve beverage identity and internal color relationships, not its original absolute white point. In adopt mode use the approved low straight cylindrical reference glass, complete saucer and wood-handled teaspoon; in preserve mode keep the exact user cup on that same approved saucer with that teaspoon.",
        "negative": "No overhead view, round-table edge, table leg, tiled floor, grout, flat white void, studio sweep, miniature waffle, centered magazine, hard sunlight, beige veil, missing saucer, missing or malformed spoon, floating product, CGI liquid, HDR halo or watermark.",
    })
    preset["quality_gates"].update({"product_identity": "beverage and selected cup remain authoritative", "preset_adherence": "large close cup-saucer-spoon assembly, two peripheral edge props, white-room air and one diffuse light all pass", "artifact_policy": "reject flat white, missing or malformed serving components, miniature props, hard shadows, clipped whites, pasted edges or copied scene pixels"})
    preset["failure_recovery"] = ["restore exact beverage and selected cup", "restore the complete saucer and wood-handled teaspoon", "restore large close scale", "restore partial edge props", "restore one broad diffuse source and spatial shadows"]
    write(f"presets/editorial/{PRESET_ID}/reference-preset.json", preset)

    style = load("presets/editorial/instagram_white_neutral_overhead_spatial_v1/photographic-style-contract.json")
    style.update({"contract_id": "instagram_white_diffuse_closeup_contract_v1", "preset_id": PRESET_ID})
    style["creative_direction"].update({"desired_response": "a quiet white close-up that still feels located inside a real cafe room", "art_direction": "large close serving assembly with edge-cropped waffle and magazine under one diffuse window", "restraint": "one product assembly, two peripheral crop cues and one light idea", "forbidden_impression": ["generic AI product insert", "sterile ecommerce sweep", "miniature food props", "over-propped cafe campaign"]})
    style["reference_binding"].update({"asset_id": asset_id, "pixel_sha256": pixel_digest, "relative_path": str(INPUT_IMAGE.relative_to(ROOT)).replace("\\", "/"), "width_px": width, "height_px": height, "runtime_role": "offline source for the approved white-closeup scene, photometric and cup-saucer-spoon hint", "provider_submission": "never"})
    style["camera_geometry"].update({"projection": "rectilinear high three-quarter close-up", "focal_length_equivalent_mm": [52, 58], "working_distance_cm": [55, 80], "camera_height_cm": [65, 95], "pitch_degrees": [42, 49], "yaw_degrees": [-4, 4], "roll_degrees": [-1, 1], "distortion": "no wide-angle enlargement", "depth_of_field": "product and spoon readable; edge props mildly defocused by real distance"})
    style["composition_geometry"].update({"primary_subject_bbox": {"left": 0.23, "top": 0.24, "right": 0.79, "bottom": 0.90}, "bbox_semantics": "complete cup, saucer and wood-handled teaspoon assembly", "primary_subject_area_ratio": [0.3, 0.38], "negative_space": "38-44 percent meaningful warm-white room field around the large assembly", "support_plane": {"kind": "warm ivory-white matte cafe tabletop", "occupancy_ratio": [0.88, 1.0], "dominant_edge_angles_degrees": [0, 5], "perspective": "one continuous tabletop with light and shadow falloff"}, "frame_rhythm": "large central-lower serving assembly with small partial edge cues", "crop_policy": "complete cup, saucer and spoon; waffle and magazine intentionally cropped", "forbidden": ["flat studio sweep", "tiny product", "complete waffle plate", "centered magazine", "cropped saucer", "cropped spoon"]})
    style["lighting_geometry"].update({"source_topology": "one very large upper-left diffuse window plus weak neutral room bounce", "azimuth_degrees": [305, 325], "elevation_degrees": [42, 56], "angular_size_degrees": [35, 60], "key_to_fill_ratio": [1.5, 2.5], "lit_area_ratio": [0.62, 0.82], "shadow_area_ratio": [0.14, 0.3], "shadow_vector_degrees": [112, 142], "penumbra_ratio": [0.28, 0.55], "highlight_behavior": "broad protected highlights retaining white and transparent texture", "optical_effects": "connected refraction, transmitted color and contact darkening", "forbidden": ["shadowless wrap", "hard sun", "multiple directions", "HDR halo", "clipped white"]})
    style["tone_signature"].update({"white_balance_kelvin": [5000, 5300], "black_point": "open neutral gray-brown", "white_point": "warm ivory-white with visible texture", "contrast_curve": "gentle toe, soft midtone separation and protected shoulder", "saturation": "low globally; preserve beverage-internal color relationships while re-illuminating bright low-chroma milk or cream into the target warm-neutral exposure", "shadow_color": "neutral gray", "highlight_color": "warm-neutral ivory", "palette_hex": ["#E4E0D8", "#D7D2C8", "#C4BEB4", "#AAA39A", "#716B66"], "material_separation": "glass, liquid, ceramic, metal, wood handle, waffle and paper remain distinct", "local_contrast": "moderate only on product identity", "forbidden": ["beige veil", "blue cast", "crushed black", "neon color", "flat auto-HDR", "isolated source-white milk"]})
    style["qa_contract"] = {"hard_fail": ["complete saucer or wood-handled teaspoon absent", "cup-saucer-spoon scale or overlap differs materially from the approved core composition", "reference cup rendered as a tall highball, shoulder, waist, decorative band, crack, seam, sleeve or stacked vessel instead of the approved low straight cylinder", "product too small", "waffle or magazine not peripheral", "white space flat or shadowless", "hard sunlight", "clipped whites", "pasted product", "isolated pure-white milk that does not share the ceramic and table exposure", "reference pixels traced"], "weights": {"camera_geometry": 0.15, "composition_rhythm": 0.2, "color_and_tone": 0.13, "lighting_space": 0.24, "product_identity": 0.2, "brand_integrity": 0.08}}
    write(f"presets/editorial/{PRESET_ID}/photographic-style-contract.json", style)

    mood = load("presets/moods/instagram_white_neutral_overhead_spatial_v1/mood-package.json")
    mood.update({"mood_package_id": PRESET_ID, "display_name": DISPLAY_NAME, "preset_path": f"presets/editorial/{PRESET_ID}/reference-preset.json", "scene_recipe_path": f"presets/moods/{PRESET_ID}/scene-recipe.json", "lighting_sheet_path": f"presets/moods/{PRESET_ID}/lighting-sheet.json", "grade_profile_path": f"presets/moods/{PRESET_ID}/grade-profile.json", "photographic_style_contract_path": f"presets/editorial/{PRESET_ID}/photographic-style-contract.json", "container_design_path": "presets/container_designs/white_closeup_short_glass_saucer_v1.json", "runtime_reference_policy": "offline_contract_only"})
    mood["compatibility"].update({"composition_modes": ["single_product_white_closeup"]})
    write(f"presets/moods/{PRESET_ID}/mood-package.json", mood)

    recipe = load("presets/moods/instagram_white_neutral_overhead_spatial_v1/scene-recipe.json")
    recipe.update({"recipe_id": "instagram_white_diffuse_closeup_recipe_v1", "display_name": DISPLAY_NAME, "compatible_presets": [PRESET_ID]})
    recipe["composition"].update({"subject_anchor_priority": "one large complete cup-saucer-spoon assembly; edge-cropped waffle upper-left and magazine upper-right", "asymmetry_sources": ["unequal peripheral edge crops", "soft off-frame occupancy shadows"]})
    recipe["environment"].update({"background_plane": "warm ivory-white matte cafe tabletop inside a minimal white room", "surface_character": "subtle real matte texture, never seamless", "sun_patch_shape": "no sun patch; only broad diffuse tonal modulation"})
    recipe["lighting"].update({"source": "one very large upper-left diffuse window", "direction": "upper-left/left-front toward lower-right", "shadow_description": "compact attached contacts plus broad feathered environmental shadows", "light_softness": [0.86, 0.95], "subject_to_wall_distance_cm": [70, 140], "shadow_density": [0.14, 0.29], "global_contrast": [0.3, 0.44], "background_lightness": [0.72, 0.9], "ambient_fill": "weak neutral white-room bounce", "exposure_compensation_ev": [-0.15, 0.0], "sun_patch_coverage": [0.0, 0.0], "highlight_behavior": "protected whites and transparent detail", "shadow_temperature": "neutral"})
    recipe["material_rules"].update({"glass": "preserve beverage optics; adopt mode transfers the one-piece low straight cylindrical reference glass, while the approved saucer and spoon remain scene-authoritative. Re-illuminate bright low-chroma milk or cream into the warm-neutral ceramic and table exposure while preserving beverage-internal color relationships; never preserve an isolated source-white point", "plastic": "preserve exact user-cup family in source mode while integrating it with the approved saucer and spoon"})
    recipe["coupling_rules"] = ["Cup, beverage, saucer, spoon, support and props share one diffuse exposure.", "Bright low-chroma milk or cream shares the tabletop and ceramic white balance, reflection, contact shadow and highlight shoulder while its beverage-relative color contrast remains intact.", "The approved saucer and wood-handled teaspoon remain present in both modes.", "Adopt mode uses the low straight cylindrical reference glass; preserve mode uses the exact user cup.", "Peripheral props communicate depth and never become miniature subjects."]
    recipe["forbidden"] = ["flat seamless white", "hard sun", "miniature waffle", "centered magazine", "missing saucer", "missing or malformed spoon", "watermark", "pasted product"]
    recipe["quality_gate"]["hard_fail"] = recipe["forbidden"] + ["product too small", "light and shadows do not communicate room volume"]
    write(f"presets/moods/{PRESET_ID}/scene-recipe.json", recipe)

    lighting = load("presets/moods/instagram_white_neutral_overhead_spatial_v1/lighting-sheet.json")
    lighting.update({"lighting_sheet_id": "instagram_white_diffuse_closeup_sheet_v1", "mood": "warm-white close cafe tabletop under one broad diffuse window"})
    lighting["reference_cluster"].update({"anchor_preset_id": PRESET_ID, "runtime_pixels_allowed": False, "selection_rule": "large central serving assembly, edge-cropped waffle and magazine, diffuse white-room space", "source_images": [INPUT_IMAGE.name]})
    lighting["key_light"].update({"source": "one very large upper-left diffuse window", "direction": "upper-left/left-front toward lower-right", "relative_size": "very large, producing broad highlights and long feathered penumbrae", "subject_to_wall_distance_cm": [70, 140]})
    lighting["fill_contract"].update({"key_to_fill_ratio": [1.5, 2.5], "source": "weak neutral white-room bounce", "color_bias": "neutral"})
    lighting["screen_light_map"].update({"lit_area_ratio": [0.62, 0.78], "shadow_area_ratio": [0.14, 0.28], "dominant_shadow_vector_degrees": [118, 142], "falloff": "broad directional upper-left to lower-right falloff across one continuous matte tabletop", "gobo_geometry": "two or three amorphous 3-8 percent opacity off-frame occupancy modulations only; no readable silhouette"})
    lighting["shadow_contract"].update({"density": [0.14, 0.28], "edge": "compact attached core opening into a long feathered penumbra", "attachment": "each present cup, saucer and source spoon owns a separate but directionally coherent contact", "transparent_material": "curved-wall refraction, Fresnel edge response and a restrained beverage-colored transmitted lift stay connected to the cast-shadow footprint"})
    lighting["shadow_contract"]["contact_shadow"].update({"opacity": [0.24, 0.36], "footprint": [0.04, 0.13], "behavior": "compact neutral-gray attachment directly beneath each present support contact"})
    lighting["shadow_contract"]["cast_shadow"].update({"opacity": [0.08, 0.18], "footprint": [0.38, 1.1], "behavior": "one lower-right shadow per object with a penumbra 0.28-0.52 of local caster width"})
    lighting["shadow_contract"]["transmitted_light"].update({"opacity": [0.05, 0.18], "footprint": [0.1, 0.32], "behavior": "restrained source-beverage-colored lift only inside the physically connected transparent shadow"})
    lighting["capture_contract"].update({"exposure_compensation_ev": [-0.15, 0.0], "white_balance": "5000-5300K warm-neutral white", "texture": "matte table, protected glass and cream, paper fiber and faint grain"})
    lighting["forbidden"] = ["shadowless studio sweep", "hard sunlight", "clipped white", "beige veil", "blue cast", "portrait cutout blur"]
    lighting["reference_anchor"].update({"asset_id": asset_id, "pixel_sha256": pixel_digest, "role": "user-approved scene-condition anchor with novelty requirement"})
    write(f"presets/moods/{PRESET_ID}/lighting-sheet.json", lighting)

    container = {
        "schema_version": "1.0.0", "container_design_id": "white_closeup_short_cylindrical_glass_saucer_v2", "display_name": "White close-up low cylindrical clear glass, saucer and teaspoon assembly",
        "design": {"class": "low straight cylindrical open tumbler on saucer with teaspoon", "material": "clear glass", "geometry": "one-piece low clear-glass tumbler with one continuous straight cylindrical exterior from thin circular rim to subtly thick weighted base. Exterior height-to-outside-diameter ratio is 0.95-1.05: compact, broad and low, never a tall highball. Outside diameter remains visually constant through the sidewall; no shoulder, waist, band, seam, crack, sleeve, faceting or stacked vessel. Center it on a separate moderately wider low round warm-white ceramic saucer with one wood-handled teaspoon resting along the saucer's left side", "components": ["low straight clear-glass cylindrical body", "thin open circular rim", "constant outside diameter through the clear sidewall", "subtly thick clear weighted base", "separate moderately wider low round warm-white ceramic saucer", "single metal teaspoon with a dark natural-wood handle on the saucer's left side"], "height_to_width_ratio": [0.95, 1.05]},
        "allowed_transfer": ["one-piece low straight cylindrical glass silhouette", "thin rim, constant sidewall diameter and weighted base", "complete warm-white saucer", "single wood-handled teaspoon and its left-side support relationship"],
        "forbidden_transfer": ["reference beverage", "waffle", "magazine", "table", "exact shadow pixels", "text", "logo", "watermark"],
        "compatibility": {"beverage_temperatures": ["cold", "ambient"], "supports_toppings": True, "supports_straw": False, "brand_surface": "plain unbranded glass; saucer remains plain"},
    }
    write("presets/container_designs/white_closeup_short_glass_saucer_v1.json", container)

    graph = load("data/reference-library/scene-graphs-v2/ref_499763da87e8bf0e.json")
    graph["asset"].update({"asset_id": asset_id, "relative_path": str(INPUT_IMAGE.relative_to(ROOT)).replace("\\", "/"), "file_sha256": digest, "pixel_sha256": pixel_digest, "width_px": width, "height_px": height, "format": "PNG", "source_folder_tags": ["user_approved", "white_neutral", "closeup", "soft_diffuse"], "duplicate_of": None})
    primary = graph["objects"] if isinstance(graph["objects"], dict) else graph["objects"][0]
    primary.update({"description": "large 110-percent central replaceable low cylindrical-glass beverage assembly with mandatory saucer and wood-handled teaspoon", "body_bbox": {"left": 0.30, "top": 0.25, "right": 0.72, "bottom": 0.74, "confidence": 0.96}, "full_bbox": {"left": 0.20, "top": 0.21, "right": 0.82, "bottom": 0.93, "confidence": 0.96}, "container": {"class": "low straight cylindrical open tumbler on saucer with teaspoon", "material": "clear glass", "silhouette": "one-piece compact low clear-glass cylinder with constant sidewall diameter from thin rim to subtly thick weighted base, on a separate moderately wider low round saucer with one wood-handled teaspoon at left", "components": container["design"]["components"]}, "support_surface_id": "surface_white_table"})
    graph["objects"] = [primary]
    graph["support_surfaces"] = [{"surface_id": "surface_white_table", "kind": "table", "bbox": {"left": 0, "top": 0, "right": 1, "bottom": 1, "confidence": 0.99}, "plane_description": "warm ivory-white matte cafe tabletop", "supports_objects": True, "perspective_scale": [0.9, 1.1]}]
    graph["insertion_zones"] = [{"zone_id": "zone_product_on_white_table", "bbox": {"left": 0.20, "top": 0.21, "right": 0.82, "bottom": 0.93, "confidence": 0.98}, "support_surface_id": "surface_white_table", "allowed_kinds": ["beverage", "dessert"], "scale_range": [1.08, 1.12], "confidence": 0.98, "reason": "reviewed 110-percent cup-saucer-spoon assembly with complete support contact"}]
    graph["runtime_policy"].update({"scene_pixels_allowed": False, "container_pixels_allowed": True, "copy_exclusions": ["reference beverage identity and recipe", "exact serving-assembly pixels", "exact table texture and shadow silhouette", "exact waffle pixels and magazine alignment", "watermark"], "maximum_exact_products": 1, "maximum_generic_companions": 1, "maximum_major_subjects": 3, "maximum_props": 2})
    graph["composition"].update({"shot_type": "closeup", "camera_height": "slightly_above", "camera_pitch": "42-49 degrees", "lens_character": "phone_mild_tele", "subject_position": "large near center", "negative_space": "quiet continuous warm-white tabletop with distant peripheral depth cues", "asymmetry_source": "partial waffle upper-left and magazine upper-right", "crop_character": "4:5 close social crop with no table edge or floor"})
    graph["depth"] = {"plane_count": 3, "foreground": "large complete cup-saucer-spoon assembly with physically attached contacts and coherent shadow", "product_plane": "cup, complete saucer and wood-handled teaspoon on one continuous tabletop", "midground": "warm ivory-white matte tabletop with broad directional light falloff", "background": "distant partial waffle upper-left and partial magazine upper-right on the same continuous tabletop", "perspective_cues": ["large foreground serving-assembly scale", "peripheral objects cropped by opposite frame edges", "distance-dependent microcontrast reduction", "overlapping attached shadows and broad light falloff"], "far_plane_softness": "subtle", "atmospheric_separation": "mild"}
    graph["facets"] = {"mood_tags": ["white neutral", "diffuse daylight", "quiet spatial", "natural cafe close-up"], "environment_tags": ["continuous ivory-white tabletop", "partial waffle", "partial magazine", "off-frame room shadows"], "material_tags": ["matte ivory-white table", "clear glass", "food texture", "paper", "source-authoritative accessory"], "shot_tags": ["high three-quarter close-up", "single large product", "portrait social crop"]}
    graph["protected_regions"] = [{"region_id": "region_upper_center_air", "kind": "negative_space", "bbox": {"left": 0.18, "top": 0.0, "right": 0.8, "bottom": 0.27, "confidence": 0.94}, "reason": "retain quiet white-room air between the two peripheral edge crops"}, {"region_id": "region_room_shadow_air", "kind": "shadow", "bbox": {"left": 0.0, "top": 0.18, "right": 1.0, "bottom": 1.0, "confidence": 0.9}, "reason": "retain broad low-density directional occupancy modulation while inventing its exact silhouette"}]
    graph["taxonomy"].update({"environment_family": "white_neutral", "lighting_family": "soft_window", "camera_angle": "slightly_above", "capture_style": "closeup", "scene_complexity": "solo", "dominant_surface": "continuous warm ivory-white matte tabletop", "wood_prominence": 0.0, "accent_color_prominence": 0.05, "frontend_mood": "white", "frontend_angle": "slightly_above", "confidence": 0.99})
    write(GRAPH_REL, graph)

    with sqlite3.connect(ROOT / "data/reference-library/catalog.sqlite") as connection:
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
                width_px=excluded.width_px,
                height_px=excluded.height_px,
                source_group=excluded.source_group,
                analysis_status=excluded.analysis_status,
                analysis_json=excluded.analysis_json,
                failure=excluded.failure
            """,
            (asset_id, str(INPUT_IMAGE.relative_to(ROOT)).replace("\\", "/"), pixel_digest, digest, "0000000000000000", width, height, "user_approved/white/soft_diffuse_closeup", None, "analyzed", json.dumps(graph, ensure_ascii=False, sort_keys=True), None),
        )
        connection.commit()
    print("data/reference-library/catalog.sqlite")

    assignments_path = ROOT / "data/reference-library/assignments.json"
    assignments = json.loads(assignments_path.read_text(encoding="utf-8"))
    assignments["assignments"][asset_id] = {
        "analysis_status": "analyzed", "canonical_asset_id": asset_id,
        "cluster_id": "soft_diffuse_neutral_candid_v1", "confidence": 0.99,
        "evidence": ["user-approved white close-up v6", "manual scene-graph and lighting-contract review"],
        "membership": "core", "mood_package_path": f"presets/moods/{PRESET_ID}/mood-package.json",
        "runtime_capabilities": {"cross_kind_slot_ids": ["beverage_primary"], "default_target_slot_id": "beverage_primary", "replaceable_slot_ids": ["beverage_primary"], "supports_cross_kind_replacement": True},
        "taxonomy": {"accent_color_prominence": 0.05, "camera_angle": "slightly_above", "capture_style": "closeup", "confidence": 0.99, "dominant_surface": "warm ivory-white matte table", "environment_family": "white_neutral", "frontend_angle": "slightly_above", "frontend_mood": "white", "lighting_family": "soft_window", "scene_complexity": "group", "wood_prominence": 0.0},
    }
    assignments_path.write_text(json.dumps(assignments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("data/reference-library/assignments.json")

    workflow_sources = {
        "24a_white_closeup_matcha_reference_cup_local_fake_api.json": "23a_wood_window_closeup_strawberry_reference_cup_local_fake_api.json",
        "24a_white_closeup_matcha_reference_cup_higgsfield_api.json": "23a_wood_window_closeup_strawberry_reference_cup_higgsfield_api.json",
        "24b_white_closeup_matcha_source_cup_local_fake_api.json": "23b_wood_window_closeup_strawberry_source_cup_local_fake_api.json",
        "24b_white_closeup_matcha_source_cup_higgsfield_api.json": "23b_wood_window_closeup_strawberry_source_cup_higgsfield_api.json",
    }
    replacements = {
        "ad_creator_reference_wood_window_closeup_v1.png": INPUT_IMAGE.name,
        "data/reference-library/scene-graphs-v2/ref_95fa7947818ce496_wood_window_closeup_v1.json": GRAPH_REL,
        "presets/moods/instagram_wood_calm_window_closeup_v1/mood-package.json": f"presets/moods/{PRESET_ID}/mood-package.json",
        "presets/container_designs/wood_clear_plastic_cup_open_rim_v1.json": "presets/container_designs/white_closeup_short_glass_saucer_v1.json",
        "ad_creator/wood_closeup_shot/": "ad_creator/white_closeup/",
        "strawberry_cream": "matcha_cream",
    }
    for target_name, source_name in workflow_sources.items():
        text = (ROOT / "workflows" / source_name).read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        workflow = json.loads(text)
        workflow["13"]["inputs"]["image"] = (
            REFERENCE_GEOMETRY_HINT_IMAGE
            if "_reference_cup_" in target_name
            else INPUT_IMAGE.name
        )
        workflow["7"]["inputs"]["output_root"] = "outputs/comfyui-live/white-closeup"
        path = ROOT / "workflows" / target_name
        path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    build(*copy_reference())
