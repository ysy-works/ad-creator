from __future__ import annotations

import copy
import random
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from .features import DEFAULT_FEATURES, resolve_auto_paid_repair, resolve_container_mode
from .image_contracts import (
    canonical_image_binding,
    require_generation_ready_brand_contract,
    resolve_target_brand_contract,
    validate_brand_contract,
)
from .reference_library import derive_reference_capabilities
from .scene_graph import (
    adapt_scene_graph_to_reference_v1,
    derive_scene_graph_capabilities,
    resolve_slot_plan,
)
from .prompt_limits import resolve_prompt_limit_policy
from .serving_contracts import (
    require_serving_compatibility_ready,
    resolve_product_serving_state,
    resolve_serving_compatibility,
    serving_prompt_summary,
)


PROMPT_COMPILER_VERSION = "natural_compact_v4_5"
MULTI_PROMPT_COMPILER_VERSION = "natural_compact_v5_multi"
PRODUCT_SPEC_SCHEMA_VERSION = "3.0.0"
GENERATION_REQUEST_V3_SCHEMA_VERSION = "3.0.0"


class ProductSpec(TypedDict):
    schema_version: str
    product_id: str
    product_kind: str
    source_image: str
    description: str
    target_slot_id: str
    placement_mode: str
    cross_kind_replacement: bool
    container_policy: str | dict[str, Any]
    product_analysis: NotRequired[dict[str, Any] | None]
    brand_transfer_resolution: NotRequired[dict[str, Any] | None]
    target_brand_contract: NotRequired[dict[str, Any] | None]
    serving_compatibility_resolution: NotRequired[dict[str, Any] | None]


class ImageInputV3(TypedDict):
    role: str
    path: str
    product_id: NotRequired[str]


def _target_brand_state(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict):
        return "verified_absent"
    state = str(contract.get("state") or "").lower()
    if state:
        return state
    # Early v3 callers placed the final action on the target contract. Accept
    # that spelling without ever consulting sibling compatibility evidence.
    action = str(contract.get("action") or contract.get("final_action") or "").lower()
    if action in {
        "preserve_source_exact",
        "transfer_source_exact",
        "preserve_exact",
    }:
        return "verified_present"
    if action in {"omit_branding", "render_unbranded"}:
        return "verified_absent"
    return "verified_absent"


def _container_policy_mode(value: Any) -> str:
    if isinstance(value, str):
        mode = value
    elif isinstance(value, dict):
        mode = value.get("container") or value.get("mode")
    else:
        mode = None
    if mode not in {"preserve_source", "adopt_reference"}:
        raise ValueError(f"Unsupported product container policy: {mode!r}")
    return mode


def _runtime_appearance_clause(slot: dict[str, Any]) -> str:
    """Compile broad semantic appearance without turning a reference into a copy target."""
    appearance = slot.get("runtime_appearance")
    if not isinstance(appearance, dict):
        return ""
    category = str(appearance.get("category") or "").strip()
    color_family = str(appearance.get("color_family") or "").strip()
    contents = [
        str(item).strip()
        for item in appearance.get("contents", [])
        if str(item).strip()
    ]
    parts = [item for item in (category, color_family) if item]
    if contents:
        parts.append("contents=" + ", ".join(contents[:4]))
    if not parts:
        return ""
    return "; appearance=" + "; ".join(parts) + "; generic semantics only"


def validate_product_spec(product: dict[str, Any]) -> None:
    """Validate the transport-independent portion of a v3 product specification."""
    if not isinstance(product, dict):
        raise ValueError("ProductSpec must be an object")
    if product.get("schema_version") != PRODUCT_SPEC_SCHEMA_VERSION:
        raise ValueError("ProductSpec must use schema version 3.0.0")
    product_id = product.get("product_id")
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("ProductSpec product_id must be a non-empty string")
    if product.get("product_kind") not in {"beverage", "dessert"}:
        raise ValueError("ProductSpec product_kind must be beverage or dessert")
    source_image = product.get("source_image")
    if not isinstance(source_image, str) or not source_image.strip():
        raise ValueError("ProductSpec source_image must be a non-empty path")
    description = product.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("ProductSpec description must be non-empty")
    target_slot_id = product.get("target_slot_id", "auto")
    if not isinstance(target_slot_id, str) or not target_slot_id.strip():
        raise ValueError("ProductSpec target_slot_id must be a non-empty string")
    if product.get("placement_mode", "replace") not in {"replace", "add"}:
        raise ValueError("ProductSpec placement_mode must be replace or add")
    if not isinstance(product.get("cross_kind_replacement", False), bool):
        raise ValueError("ProductSpec cross_kind_replacement must be boolean")
    _container_policy_mode(product.get("container_policy", "preserve_source"))
    for field in (
        "brand_transfer_resolution",
        "target_brand_contract",
        "serving_compatibility_resolution",
    ):
        value = product.get(field)
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"ProductSpec {field} must be an object when supplied")
    analysis = product.get("product_analysis")
    if analysis is not None and not isinstance(analysis, dict):
        raise ValueError("ProductSpec product_analysis must be an object when supplied")
    if (
        isinstance(analysis, dict)
        and analysis.get("schema_version") == "3.0.0"
        and analysis.get("product_kind") != product["product_kind"]
    ):
        raise ValueError("ProductSpec product_kind conflicts with ProductAnalysisV3")
    resolution = product.get("brand_transfer_resolution")
    if isinstance(resolution, dict) and resolution.get("action") not in {
        None,
        "preserve_source_exact",
        "transfer_source_exact",
        "omit_branding",
        "block_uncertain",
    }:
        raise ValueError("ProductSpec has an unsupported brand transfer action")
    serving_resolution = product.get("serving_compatibility_resolution")
    if isinstance(serving_resolution, dict) and serving_resolution.get("action") not in {
        None,
        "allow",
        "block",
        "review",
    }:
        raise ValueError("ProductSpec has an unsupported serving compatibility action")
    target = product.get("target_brand_contract")
    if isinstance(target, dict):
        state = target.get("state")
        if state is not None and state not in {
            "verified_present",
            "verified_absent",
            "uncertain",
        }:
            raise ValueError("ProductSpec has an unsupported target brand state")
        allowed_text = target.get("allowed_main_text")
        if allowed_text is not None and (
            not isinstance(allowed_text, str) or not allowed_text.strip()
        ):
            raise ValueError("target_brand_contract allowed_main_text must be non-empty or null")
        if state == "verified_absent" and allowed_text is not None:
            raise ValueError("verified_absent target branding cannot allow main text")


def create_product_spec(
    *,
    product_id: str,
    product_kind: str,
    source_image: str,
    description: str | None = None,
    target_slot_id: str = "auto",
    placement_mode: str = "replace",
    cross_kind_replacement: bool = False,
    container_policy: str | dict[str, Any] = "preserve_source",
    product_analysis: dict[str, Any] | None = None,
    brand_transfer_resolution: dict[str, Any] | None = None,
    target_brand_contract: dict[str, Any] | None = None,
    serving_compatibility_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one canonical ProductSpec while preserving resolved brand contracts."""
    if not isinstance(source_image, str) or not source_image.strip():
        raise ValueError("ProductSpec source_image must be a non-empty path")
    resolved_description = description
    if resolved_description is None and isinstance(product_analysis, dict):
        resolved_description = product_analysis.get("product_summary")
    product = {
        "schema_version": PRODUCT_SPEC_SCHEMA_VERSION,
        "product_id": product_id,
        "product_kind": product_kind,
        "source_image": str(Path(source_image)),
        "description": resolved_description,
        "target_slot_id": target_slot_id,
        "placement_mode": placement_mode,
        "cross_kind_replacement": cross_kind_replacement,
        "container_policy": copy.deepcopy(container_policy),
        "product_analysis": copy.deepcopy(product_analysis),
        "brand_transfer_resolution": copy.deepcopy(brand_transfer_resolution),
        "target_brand_contract": copy.deepcopy(target_brand_contract),
        "serving_compatibility_resolution": copy.deepcopy(
            serving_compatibility_resolution
        ),
    }
    validate_product_spec(product)
    return product


def assemble_product_set(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and freeze an ordered set of one to three exact user products."""
    if not isinstance(products, list) or not 1 <= len(products) <= 3:
        raise ValueError("Product set must contain between one and three products")
    values = [copy.deepcopy(item) for item in products]
    for item in values:
        validate_product_spec(item)
    product_ids = [item["product_id"] for item in values]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("ProductSpec product_id values must be unique")
    return {
        "schema_version": PRODUCT_SPEC_SCHEMA_VERSION,
        "products": values,
    }


def require_product_spec_generation_ready(product: dict[str, Any]) -> None:
    """Block unresolved or internally inconsistent final brand decisions."""
    validate_product_spec(product)
    resolution = product.get("brand_transfer_resolution")
    target = product.get("target_brand_contract")
    action = (
        str(resolution.get("action") or "").lower()
        if isinstance(resolution, dict)
        else ""
    )
    target_state = _target_brand_state(target)
    if action == "block_uncertain" or target_state in {
        "uncertain",
        "unknown",
        "unresolved",
    }:
        raise ValueError(
            f"Product {product['product_id']} branding is unresolved; generation is blocked"
        )
    branded_actions = {"preserve_source_exact", "transfer_source_exact"}
    if action in branded_actions and target_state != "verified_present":
        raise ValueError(
            f"Product {product['product_id']} branded transfer action conflicts with "
            "target_brand_contract"
        )
    if action == "omit_branding" and target_state == "verified_present":
        raise ValueError(
            f"Product {product['product_id']} omit_branding action conflicts with "
            "target_brand_contract"
        )
    serving_resolution = product.get("serving_compatibility_resolution")
    if serving_resolution is not None:
        require_serving_compatibility_ready(
            product["product_id"], serving_resolution
        )


def _sample_number(rng: random.Random, values: list[float]) -> float:
    return round(rng.uniform(values[0], values[1]), 3)


def _sample_integer(rng: random.Random, values: list[int]) -> int:
    return rng.randint(values[0], values[1])


def _intersect_ranges(
    first: list[float],
    second: list[float],
    *,
    label: str,
) -> list[float]:
    intersection = [max(first[0], second[0]), min(first[1], second[1])]
    if intersection[0] > intersection[1]:
        raise ValueError(
            f"Scene recipe and lighting sheet have incompatible {label} ranges: "
            f"{first} vs {second}"
        )
    return intersection


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def _clip(value: str, maximum: int = 180) -> str:
    compact = " ".join(value.split())
    if len(compact) <= maximum:
        return compact
    candidate = compact[: maximum + 1]
    boundaries = [
        candidate.rfind(". "),
        candidate.rfind("; "),
        candidate.rfind(": "),
        candidate.rfind(", "),
    ]
    boundary = max(boundaries)
    if boundary >= int(maximum * 0.55):
        shortened = candidate[: boundary + 1].rstrip(" ,;:")
    else:
        words = candidate.rsplit(" ", 1)[0].rstrip(" ,;:").split()
        trailing_fillers = {
            "a",
            "an",
            "and",
            "at",
            "by",
            "for",
            "from",
            "in",
            "of",
            "on",
            "the",
            "to",
            "toward",
            "with",
        }
        while words and words[-1].lower().rstrip(".,;:") in trailing_fillers:
            words.pop()
        shortened = " ".join(words)
    return shortened


def _wood_closeup_master_contract(
    *,
    preset: dict[str, Any],
    scene_graph: dict[str, Any] | None,
    lighting_sheet: dict[str, Any] | None,
    photographic_style_contract: dict[str, Any] | None,
    container_mode: str,
    reference_control_role: str,
) -> str:
    """Compile Wood Close-up Shot controls without lossy summaries."""
    if (
        preset.get("preset_id") != "instagram_wood_calm_window_closeup_v1"
        or scene_graph is None
        or lighting_sheet is None
        or photographic_style_contract is None
    ):
        return ""

    objects = {item["slot_id"]: item for item in scene_graph["objects"]}
    primary = objects["beverage_primary"]["body_bbox"]
    companion = objects["beverage_secondary"]["body_bbox"]
    plant = objects["prop_plant"]["body_bbox"]
    table = next(
        item for item in scene_graph["support_surfaces"]
        if item["surface_id"] == "surface_live_edge_wood_table"
    )["bbox"]
    camera = photographic_style_contract["camera_geometry"]
    composition = photographic_style_contract["composition_geometry"]
    tone = photographic_style_contract["tone_signature"]
    finish = photographic_style_contract["finish_signature"]
    key = lighting_sheet["key_light"]
    light_map = lighting_sheet["screen_light_map"]
    shadow = lighting_sheet["shadow_contract"]
    capture = lighting_sheet["capture_contract"]
    fill = lighting_sheet["fill_contract"]

    def box(value: dict[str, Any]) -> str:
        return (
            f"({value['left']:.3f},{value['top']:.3f})-"
            f"({value['right']:.3f},{value['bottom']:.3f})"
        )

    if container_mode == "adopt_reference":
        input_authority = (
            "Image 1 supplies beverage contents only; panel boundaries and any partial source rim "
            "have zero container authority."
        )
        container_authority = (
            "Image 1 controls only beverage identity, color, layers, ice, toppings and authorized "
            "branding; Image 2 lower-left hard-locks the clear PET silhouette: rolled open rim, H:W 1.47-1.55, taper and narrow base ring. Straw exposed rise=1.05-1.12x bottom diameter (0.52-0.58x body height); keep its diameter, lean and cut end; plus one off-white paper "
            "label with exact lowercase heading cafe and tiny English body copy. Rotate the whole cup only 3-5 degrees so the label shifts barely toward viewer-right curvature and foreshortens slightly while readable; never skew the label alone. The label is "
            "non-brand editorial design; never write cafe latte."
        )
    else:
        input_authority = "Image 1 alone fixes the complete product identity."
        container_authority = (
            "Image 1 controls the complete beverage and complete source container, including "
            "material, rim, wall, base, accessories and authorized branding. Image 2 must not "
            "replace or redesign that container or add the primary cafe paper label."
        )

    return f"""
[WOOD CLOSE-UP SHOT MASTER CONTRACT - FULL FIDELITY]
INPUT AUTHORITY: {input_authority} Image 2 is a non-contiguous evidence board, not a layout. Sample only real wood/color, window light, crema and conditional cup design; structured geometry controls scale and hierarchy. {container_authority} REAR TEXT HARD LOCK: exact small CAFE AMERICANO must remain readable and curve with the outer paper cup; blank cup fails.

FRAME MAP RAW 3:4: bboxes {box(primary)} and {box(companion)} are placement anchors, never shape references. Drift primary center 0.015-0.025/scale 2-4%; companion independently 0.02-0.035/3-5%. Lock both silhouettes, bases and overlap. Plant bbox={box(plant)} is only a distant upper-right sill zone: vary pot/leaves/position; keep supported, never seam-grown. Table bbox={box(table)} sets coverage only.

CAMERA: rectilinear {camera['focal_length_equivalent_mm'][0]}-{camera['focal_length_equivalent_mm'][1]}mm-equivalent optics; working distance {camera['working_distance_cm'][0]}-{camera['working_distance_cm'][1]}cm; pitch {camera['pitch_degrees'][0]}-{camera['pitch_degrees'][1]} degrees; yaw {camera['yaw_degrees'][0]}..{camera['yaw_degrees'][1]} degrees; roll {camera['roll_degrees'][0]}..{camera['roll_degrees'][1]} degrees. Both cup rims, bodies and table contacts remain readable. Depth comes from overlap, table perspective, relative scale, tonal falloff and reduced far-plane microcontrast. Reject wide-angle looming, compressed flattening, portrait cutout blur, large bokeh, uniform blur and a centered catalog lineup. Negative space follows: {composition['negative_space']}.

LIGHT SOURCE - HARD LOCK: exactly one {key['source']}, direction {key['direction']}, azimuth {key['azimuth_degrees'][0]}-{key['azimuth_degrees'][1]} degrees, elevation {key['elevation_degrees'][0]}-{key['elevation_degrees'][1]} degrees, apparent angular size {key['angular_size_degrees'][0]}-{key['angular_size_degrees'][1]} degrees. It produces {key['relative_size']}. Key-to-fill ratio={fill['key_to_fill_ratio'][0]}-{fill['key_to_fill_ratio'][1]}; lit-area ratio={light_map['lit_area_ratio'][0]}-{light_map['lit_area_ratio'][1]}; shadow-area ratio={light_map['shadow_area_ratio'][0]}-{light_map['shadow_area_ratio'][1]}. Dominant shadow vector={light_map['dominant_shadow_vector_degrees'][0]}-{light_map['dominant_shadow_vector_degrees'][1]} degrees toward lower-right. No direct sun patch, window-bar shadow, plant-shaped gobo, spotlight, second key, conflicting catchlight or isolated product lighting.

SHADOW AND AIR: each base has {shadow['contact_shadow']['behavior']} at opacity {shadow['contact_shadow']['opacity'][0]}-{shadow['contact_shadow']['opacity'][1]}. Cast shadows are {shadow['cast_shadow']['behavior']} at opacity {shadow['cast_shadow']['opacity'][0]}-{shadow['cast_shadow']['opacity'][1]}. Transparent paths receive only {shadow['transmitted_light']['behavior']}. The same broad source connects window, cups, liquid, ice, paper and wood. Add faint low-frequency neutral bounce and amorphous off-frame occupancy modulation suggesting nearby furniture or people outside the crop, but no readable person/object silhouette. Reject sterile shadowless emptiness, global blur, gray fog and amber veil.

COLOR AND EXPOSURE: Image 2's subdued screen color and luminance distribution outrank generic cafe grading. White balance={capture['white_balance']}; exposure={capture['exposure_compensation_ev'][0]}..{capture['exposure_compensation_ev'][1]}EV. Exterior remains neutral gray, paper neutral, warmth local to wood, and Image 1 product color authoritative. Tone curve={tone['contrast_curve']}; black={tone['black_point']}; white={tone['white_point']}; shadow={tone['shadow_color']}; highlight={tone['highlight_color']}. Reject brighter/cooler commercial polish, orange wash, clipped paper, crushed drink, teal-orange and HDR halos.

MATERIAL PHYSICS: keep pale matte wood/pore scale but invent grain, rings, cracks and live edge; no traced stain or dark mark above 30% reference contrast/1% frame. Image 2 right-middle hard-locks the rear assembly: H:W 1.60-1.68, two offset tapered cups/two rims, full base, iced Americano, irregular ice, fine crema and curved CAFE AMERICANO. Never widen, shorten, simplify or blank it. Image 1 drink is volumetric: one window light traverses wall, ice and liquid; scattering, bleed, refraction, condensation, table bounce and attached shadows stay physical. Finish={finish['acuity']} {finish['microcontrast']} Reject flat crema, geometric ice, airbrushed liquid, pasted/floating product, unauthorized text and synthetic wood.

FINAL AUDIT: require identity, close-scale hierarchy, double rims, curved CAFE AMERICANO, mode-correct primary label with cup-driven mild cylindrical foreshortening, supported distant pot, matched color/diffuse light, broad penumbrae, transmission and contacts. Reject a scene clone unless at least three differ: wood grain/cracks/edge, plant form/position, exterior texture, sill crop/angle, pair offsets.
""".strip()


def _white_closeup_master_contract(
    *,
    preset: dict[str, Any],
    product_analysis: dict[str, Any],
    container_mode: str,
) -> str:
    """Compile the source-dependent serving contract for White Close-up."""
    if preset.get("preset_id") != "instagram_white_diffuse_closeup_v1":
        return ""

    if container_mode == "adopt_reference":
        serving_rule = (
            "Image 2 is a dedicated high-detail geometry evidence crop embedded within a sanitized static "
            "scene-and-serving hint. It hard-locks one complete serving assembly: its one-piece low straight "
            "cylindrical clear reference glass (one constant outside diameter from rim to base), moderately wider "
            "warm-white ceramic saucer and wood-handled teaspoon. Preserve their outer contours, low "
            "height-to-width ratio, constant sidewall diameter, base thickness, cup-to-saucer footprint ratio, "
            "overlap, support contacts and left-side spoon orientation. Its warm ivory table texture, narrow "
            "waffle sliver and small magazine corner only set material, depth and peripheral-scale ceilings. "
            "Replace the deliberately empty hint glass with Image 1 beverage and rebuild every material under one "
            "exposure. Image 2 is not an output crop, reference beverage or exact scene template; never copy "
            "input boundaries or exact pixels."
        )
        scene_authority = (
            "The structured scene graph owns final composition and subject scale; Image 2 limits only table "
            "material and peripheral-prop visibility, while the lighting sheet owns source direction, temperature, "
            "exposure, shadows and room air."
        )
    else:
        serving_rule = (
            "Image 1 hard-locks the complete user cup and beverage geometry. Rebuild that cup without "
            "pixel tracing, centered naturally on Image 2's warm-white ceramic saucer, while retaining "
            "Image 2's wood-handled teaspoon, its left-side orientation and its physical contact with "
            "the saucer. Never average, shorten, widen or cosmetically redesign the user cup."
        )
        scene_authority = (
            "Image 2 owns composition, saucer-and-spoon placement, tabletop perspective, peripheral depth "
            "and photometric topology."
        )
    cup_silhouette_rule = (
        "REFERENCE CUP SILHOUETTE - ADOPT MODE HARD LOCK: one compact low clear-glass cylinder, never a "
        "highball or a stepped vessel. Exterior height-to-outside-diameter ratio is 0.95-1.05. From the thin "
        "open rim to the subtly thick weighted base, the sidewall remains one continuous near-vertical constant "
        "diameter. No inward shoulder, waist, taper, horizontal band, crack, seam, sleeve, facets, stacked second "
        "glass or detached base. Keep refraction and highlights continuous across the single cylindrical wall."
        if container_mode == "adopt_reference"
        else "SOURCE CUP SILHOUETTE: retain Image 1 cup geometry and regenerate its optics under Image 2 light; "
        "do not average it with the reference cup or paste its pixel boundary."
    )

    return f"""
[WHITE CLOSE-UP MASTER CONTRACT - FULL PHOTOMETRIC FIDELITY]
INPUT AUTHORITY: Image 1 owns beverage identity, opacity, layer boundaries, ice and toppings. {serving_rule} {scene_authority} Reconstruct the whole frame as one photograph; never average drinks, paste a cutout or reuse input boundaries.

CORE COMPOSITION: one complete, restrained assembly at bbox x=0.26-0.76, y=0.25-0.83, centered near (0.51,0.55). The beverage, cup, saucer and teaspoon assembly occupies about 46-52 percent of frame width and 54-60 percent of frame height: prominent but never hero-scale, with real tabletop air on every side. Retain the complete saucer and teaspoon inside frame. Use rectilinear 54-56mm, 68-86cm distance, 44-47 degree pitch, near-zero yaw/roll; show sidewall and open top. No overhead view, table edge, floor or tile grout; one continuous warm ivory-white tabletop.

{cup_silhouette_rule}

DEPTH: upper-left reveals only a narrow off-frame sliver of a normal-size waffle plate, with its visible portion limited to roughly 8-10% of frame width and no more than 13% of frame height; upper-right reveals only a small off-frame corner of a normal-size Barton Springs magazine, limited to roughly 11-13% of frame width and no more than 17% of frame height. Both are physically normal-size but sit farther outside the crop than before, so they read as distant peripheral depth cues rather than subjects. Use overlap, scale, tonal falloff and light attenuation before softness; never miniatures, centered props or competing subjects.

LIGHT AND CONTACT: exactly one broad upper-left/left-front diffuse window, azimuth 305-325 degrees, elevation 42-54 degrees, 5050-5250K, exposure -0.12 to -0.02EV, key:fill 1.55-2.25. One soft lower-right cast direction (118-142 degrees); weak camera-right/below-table neutral bounce only. Cup-to-saucer, saucer-to-table and spoon-to-saucer each need compact neutral contact then a broad coherent penumbra. Add only 2-3 faint amorphous off-frame occupancy shadows; no direct sun, second key, pattern, spotlight, void or uniform blur.

TRANSPARENT PHYSICS: finite rim, paired edge highlights, curved-wall displacement, Fresnel lift, meniscus and heavy-base refraction. Window light passes through glass, liquid and irregular partly submerged ice, then produces restrained connected transmitted lift inside the physical shadow. No plastic ice, uniform condensation, broken shoulder line or independent product lighting.

RELATIONAL BEVERAGE COLOR: rebuild Image 1 volumetrically. Preserve within-drink color ordering and contrast (strawberry red/milk white or matcha green/milk white), opacity, layers, topping category and garnish count--not its source RGB or source white point. Image 1 is light-conditioned: re-illuminate it under this window. Bright low-chroma milk, foam or cream joins the target preset's ivory ceramic/table exposure by gently reducing isolated highlight brightness, saturation and source-temperature bias enough to share one protected highlight shoulder, neutral-gray shadow and reflected-table fill. Reference pale milk/cream is not paper white: it carries subdued ivory/olive room reflection and sidewall shading. Keep fresh ingredient color and recognizable layers; do not tint the whole drink.

WHITE FINISH: table white #DEDAD2..#E8E5DE and shadows #AAA49C..#C4BEB4; retain texture and soft tonal shoulder. Pale milk shares that white point, reflection family and falloff. Soften glass-to-milk contrast only through 8-12 percent physical refraction/shared reflection, never blur; rim, layers and topping stay resolved. Reject yellow veil, blue cast, lifted blacks, HDR halo, CGI gloss, pasted edges and copied reference pixels.

FINAL AUDIT: one exposure, correct light direction, attached contacts, connected transmission/refraction and meaningful room depth. Invent new table microtexture, broad occupancy-shadow shape, waffle detail and magazine alignment.
""".strip()


def _join_limited(
    values: list[str],
    *,
    maximum_items: int = 5,
    item_characters: int = 110,
) -> str:
    return "; ".join(_clip(value, item_characters) for value in values[:maximum_items])


def _position_phrase(x: float, y: float) -> str:
    horizontal = "slightly left of center" if x < 0.47 else "slightly right of center" if x > 0.53 else "near the horizontal center"
    vertical = "in the lower half" if y > 0.58 else "near the vertical middle"
    return f"{horizontal}, {vertical}"


def _analysis_or_default(
    product_analysis: dict[str, Any] | None,
    *,
    product_description: str,
    logo_text: str | None,
    source_context_exclusions: list[str],
) -> dict[str, Any]:
    if product_analysis is not None:
        if product_analysis.get("schema_version") != "2.0.0":
            raise ValueError("Product analysis must use schema version 2.0.0")
        validate_brand_contract(product_analysis)
        return product_analysis

    return {
        "schema_version": "2.0.0",
        "analysis_metadata": {
            "provider": "manual_unbound",
            "model": "none",
            "prompt_version": "product_analysis_v2_brand_crosscheck",
            "analyzed_at": "1970-01-01T00:00:00+00:00",
            "confidence": 0,
            "brand_crosscheck": "not_needed",
        },
        "product_summary": product_description,
        "identity": {
            "beverage": product_description,
            "container": {
                "class": "the container visible in image 1",
                "material": "the original visible material",
                "geometry": "the original physical container geometry",
                "components": ["all visible original container components"],
            },
            "branding": {
                "state": "verified_present" if logo_text else "verified_absent",
                "main_text": logo_text,
                "visible_text": [logo_text] if logo_text else [],
                "non_text_mark": None,
                "placement": "the original visible brand surface",
                "colors": ["the original visible label and logo colors"],
                "confidence": 1 if logo_text else 0.5,
            },
            "must_preserve": [
                "beverage category",
                "container material and construction",
                "main logo spelling",
                "visible liquid layers",
                "visible toppings",
            ],
        },
        "visual_anchor": {
            "feature": "the product's most distinctive visible color, layer, texture, or silhouette",
            "emphasis_method": "make it clearly visible with believable light and an unobstructed view",
            "do_not_exaggerate": ["size", "color saturation", "topping quantity", "condensation"],
        },
        "geometry": {
            "container_bbox": {"left": 0.25, "top": 0.2, "right": 0.75, "bottom": 0.9, "confidence": 0},
            "subject_bbox": {"left": 0.25, "top": 0.1, "right": 0.75, "bottom": 0.9, "confidence": 0},
            "beverage_bbox": None,
            "straw": {
                "present": False,
                "bbox": None,
                "centerline": None,
                "emergence_point": None,
                "angle_degrees": None,
            },
            "interaction_bbox": None,
        },
        "adaptable": ["viewpoint", "hand interaction", "minor condensation", "background", "lighting"],
        "discarded_source_context": source_context_exclusions,
        "source_capture_assessment": {"issues": [], "evidence": []},
        "presentation_correction": {
            "enabled": False,
            "intent": "show the same physical product without redesigning it",
            "preferred_capture": {
                "focal_length_mm": [24, 35],
                "camera_distance": "a plausible ordinary smartphone distance",
                "camera_height": "near the product label or visual center",
                "rotation": "small natural rotation only",
            },
            "allowed": ["small perspective change"],
            "forbidden": ["container redesign", "material substitution", "invented packaging"],
        },
    }


def build_generation_request(
    *,
    preset: dict[str, Any],
    runtime_profile: dict[str, Any],
    input_image: str,
    product_description: str,
    logo_text: str | None,
    seed: int,
    tier: str = "default",
    source_context_exclusions: list[str] | None = None,
    product_analysis: dict[str, Any] | None = None,
    scene_reference: dict[str, Any] | None = None,
    scene_graph: dict[str, Any] | None = None,
    slot_bindings: list[dict[str, Any]] | None = None,
    unbound_slot_policy: str = "genericize",
    scene_recipe: dict[str, Any] | None = None,
    lighting_sheet: dict[str, Any] | None = None,
    photographic_style_contract: dict[str, Any] | None = None,
    container_mode: str = "preserve_source",
    container_reference_image: str | None = None,
    container_design: dict[str, Any] | None = None,
    reference_control_role: str = "container_design_only",
    container_design_source: str = "reference",
    brand_asset_image: str | None = None,
    service_features: dict[str, Any] | None = None,
    auto_paid_repair: bool | None = None,
) -> dict[str, Any]:
    if preset["runtime_input_policy"]["reference_usage"] != "offline_feature_extraction_only":
        raise ValueError("Preset must prohibit runtime reference-image use")
    if runtime_profile["reference_policy"]["send_reference_image"] is not False:
        raise ValueError("Runtime profile must prohibit reference-image submission")

    features = copy.deepcopy(service_features or DEFAULT_FEATURES)
    effective_container_mode = resolve_container_mode(container_mode, features)
    effective_auto_repair = resolve_auto_paid_repair(auto_paid_repair, features)
    if reference_control_role not in {
        "container_design_only",
        "structured_only",
        "sanitized_scene_hint",
    }:
        raise ValueError(f"Unsupported reference control role: {reference_control_role}")
    if container_design_source not in {"reference", "source"}:
        raise ValueError(f"Unsupported container design source: {container_design_source}")
    if effective_container_mode == "adopt_reference":
        if not container_design:
            raise ValueError("adopt_reference requires a container design contract")
        if container_design.get("schema_version") != "1.0.0":
            raise ValueError("Container design must use schema version 1.0.0")
        if reference_control_role == "structured_only":
            if container_reference_image:
                raise ValueError(
                    "structured_only must not submit a reference control image"
                )
        elif not container_reference_image:
            raise ValueError(
                f"{reference_control_role} requires a container reference control image"
            )
    else:
        if container_design:
            raise ValueError("preserve_source must not submit a container design")
        if reference_control_role == "sanitized_scene_hint":
            if not container_reference_image:
                raise ValueError(
                    "sanitized_scene_hint requires a reference control image"
                )
            if container_design_source != "source":
                raise ValueError(
                    "preserve_source scene hints require container_design_source=source"
                )
        elif container_reference_image:
            raise ValueError("preserve_source must not submit a container reference")

    costs = runtime_profile["cost_profiles"]
    if tier not in costs:
        raise ValueError(f"Unknown cost tier: {tier}")

    rng = random.Random(seed)
    ranges = preset["sampling_ranges"]
    discarded_context = source_context_exclusions or [
        "the original background",
        "the original hand",
        "the original clothing",
        "the original lighting",
    ]
    analysis = _analysis_or_default(
        product_analysis,
        product_description=product_description,
        logo_text=logo_text,
        source_context_exclusions=discarded_context,
    )
    require_generation_ready_brand_contract(analysis)
    if effective_container_mode == "adopt_reference":
        compatibility = container_design.get("compatibility", {})
        allowed_temperatures = compatibility.get("beverage_temperatures", [])
        product_kind = str(analysis.get("product_kind") or "beverage")
        state = resolve_product_serving_state(
            analysis,
            product_kind=product_kind,
            description=product_description,
        )
        requested_temperature = (
            "cold" if state["temperature"] == "iced" else state["temperature"]
        )
        failures: list[str] = []
        if product_kind == "dessert":
            requested_temperature = "not_applicable"
        elif requested_temperature == "unknown":
            failures.append("product_serving_temperature_unknown")
        elif requested_temperature not in allowed_temperatures:
            failures.append("product_temperature_not_supported_by_adopted_container")
        if (
            state["straw_requirement"] == "required"
            and compatibility.get("supports_straw") is not True
        ):
            failures.append("required_straw_not_supported")
        if (
            state["topping_requirement"] == "required"
            and compatibility.get("supports_toppings") is not True
        ):
            failures.append("required_toppings_not_supported")
        target_design = container_design.get("design", {})
        target_surface_text = " ".join(
            str(target_design.get(key) or "").casefold()
            for key in ("class", "material", "geometry")
        )
        target_is_transparent = any(
            token in target_surface_text
            for token in ("glass", "clear", "transparent", "translucent", "pet")
        ) and not any(
            token in target_surface_text
            for token in ("ceramic", "porcelain", "paper", "metal", "opaque")
        )
        if (
            state["side_visibility_requirement"] == "required"
            and not target_is_transparent
        ):
            failures.append(
                "identity_requires_side_visibility_but_container_is_opaque"
            )
        if failures:
            raise ValueError(
                "Legacy adopt_reference serving/container compatibility is blocked: "
                + ", ".join(failures)
            )
    if (
        brand_asset_image
        and analysis["identity"]["branding"]["state"] != "verified_present"
    ):
        raise ValueError(
            "A brand asset is allowed only when the source analysis verifies branding"
        )
    if scene_recipe is not None:
        if scene_recipe.get("schema_version") != "1.0.0":
            raise ValueError("Scene recipe must use schema version 1.0.0")
        if preset["preset_id"] not in scene_recipe["compatible_presets"]:
            raise ValueError(f"Scene recipe is not compatible with preset {preset['preset_id']}")
        if scene_recipe["generation_policy"]["runtime_reference_image"] is not False:
            raise ValueError("Scene recipe must prohibit runtime reference-image use")
        if scene_recipe["generation_policy"]["traditional_compositing"] is not False:
            raise ValueError("Scene recipe must prohibit default traditional compositing")
    if lighting_sheet is not None:
        if lighting_sheet.get("schema_version") not in {"1.0.0", "2.0.0"}:
            raise ValueError("Lighting sheet must use schema version 1.0.0 or 2.0.0")
        reference_cluster = lighting_sheet["reference_cluster"]
        if reference_cluster["runtime_pixels_allowed"] is not False:
            raise ValueError("Lighting-sheet reference pixels must remain offline")
        if reference_cluster["anchor_preset_id"] != preset["preset_id"]:
            raise ValueError(
                "Lighting sheet is not compatible with preset "
                f"{preset['preset_id']}"
            )
    if photographic_style_contract is not None:
        if photographic_style_contract.get("schema_version") != "1.0.0":
            raise ValueError("Photographic style contract must use schema version 1.0.0")
        if photographic_style_contract.get("preset_id") != preset["preset_id"]:
            raise ValueError(
                "Photographic style contract is not compatible with preset "
                f"{preset['preset_id']}"
            )
    reference_capabilities = None
    scene_graph_capabilities = None
    slot_plan = None
    target_object = None
    if scene_graph is not None:
        scene_graph_capabilities = derive_scene_graph_capabilities(scene_graph)
        if not scene_graph_capabilities["scene_generation_eligible"]:
            reasons = ", ".join(scene_graph_capabilities["reason_codes"])
            raise ValueError(f"Scene graph is not eligible for generation: {reasons}")
        slot_plan = resolve_slot_plan(
            scene_graph,
            slot_bindings or [],
            unbound_slot_policy=unbound_slot_policy,
        )
        first_binding = slot_plan["bindings"][0]
        if (
            first_binding["placement_mode"] == "add"
            and effective_container_mode == "adopt_reference"
        ):
            raise ValueError("Container adoption is unavailable for an empty insertion zone")
        target_slot_id = (
            first_binding["target_slot_id"]
            if first_binding["placement_mode"] == "replace"
            else None
        )
        graph_reference = adapt_scene_graph_to_reference_v1(
            scene_graph,
            target_slot_id=target_slot_id,
        )
        if first_binding["placement_mode"] == "add":
            graph_reference["geometry"]["container_bbox"] = copy.deepcopy(
                first_binding["target_bbox"]
            )
            graph_reference["geometry"]["subject_bbox"] = copy.deepcopy(
                first_binding["target_bbox"]
            )
        if scene_reference is not None and (
            scene_reference["asset"]["asset_id"]
            != graph_reference["asset"]["asset_id"]
        ):
            raise ValueError("Scene reference and scene graph identify different assets")
        scene_reference = graph_reference
        target_object = next(
            (
                item
                for item in scene_graph["objects"]
                if item["slot_id"] == target_slot_id
            ),
            None,
        )
        target_is_held = bool(target_object and target_object["interaction"] == "held")
        if target_is_held:
            scene_reference["subject"]["interaction"] = "held"
        reference_capabilities = {
            "policy_version": "reference_scene_runtime_v2",
            "scene_generation_eligible": True,
            "placement_anchor": "container_bbox",
            "container_adoption_eligible": bool(
                target_object
                and target_object["kind"] == "beverage"
                and target_object["container"] is not None
            ),
            "multiple_primary_products": scene_graph["scene_mode"] != "solo",
            "handheld_required": target_is_held,
            "depth_transfer": (
                "clamp_to_moderate"
                if scene_graph["depth"]["far_plane_softness"] == "strong"
                else "as_analyzed"
            ),
            "reason_codes": copy.deepcopy(
                scene_graph_capabilities["reason_codes"]
            ),
        }
    if scene_reference is not None:
        if scene_reference.get("schema_version") != "1.0.0":
            raise ValueError("Scene reference must use schema version 1.0.0")
        if scene_reference["runtime_policy"]["scene_pixels_allowed"] is not False:
            raise ValueError("Scene reference pixels must remain offline")
        if reference_capabilities is None:
            reference_capabilities = derive_reference_capabilities(scene_reference)
        if not reference_capabilities["scene_generation_eligible"]:
            reasons = ", ".join(reference_capabilities["reason_codes"])
            raise ValueError(
                "Scene reference is not eligible for single-product generation: "
                f"{reasons}"
            )
        if (
            effective_container_mode == "adopt_reference"
            and not reference_capabilities["container_adoption_eligible"]
        ):
            reasons = ", ".join(reference_capabilities["reason_codes"])
            raise ValueError(f"Reference container cannot be adopted: {reasons}")
    reference_brand_observation = (
        target_object.get("brand_surface_observation")
        if isinstance(target_object, dict)
        else None
    )
    brand_resolution = resolve_target_brand_contract(
        analysis,
        effective_container_mode,
        reference_brand_observation,
    )
    target_brand_contract = brand_resolution["target_brand_contract"]
    brand_transfer_resolution = brand_resolution["brand_transfer_resolution"]
    if brand_transfer_resolution["action"] == "block_uncertain":
        raise ValueError("Final brand contract is uncertain; paid generation is blocked")
    if brand_asset_image and target_brand_contract["state"] != "verified_present":
        raise ValueError("Brand assets are forbidden when the final target is unbranded")
    presentation = analysis["presentation_correction"]
    focal_range = ranges["focal_length_mm"]
    if presentation["enabled"]:
        preferred_focal = presentation["preferred_capture"]["focal_length_mm"]
        intersection = [max(focal_range[0], preferred_focal[0]), min(focal_range[1], preferred_focal[1])]
        if intersection[0] <= intersection[1]:
            focal_range = intersection
    recipe_light = scene_recipe["lighting"] if scene_recipe else None
    light_softness_range = recipe_light["light_softness"] if recipe_light else ranges["light_softness"]
    resolved_lighting_ranges: dict[str, list[float]] = {}
    if recipe_light:
        resolved_lighting_ranges = {
            "subject_to_wall_distance_cm": list(recipe_light["subject_to_wall_distance_cm"]),
            "shadow_density": list(recipe_light["shadow_density"]),
            "exposure_compensation_ev": list(recipe_light["exposure_compensation_ev"]),
        }
        if lighting_sheet:
            resolved_lighting_ranges = {
                "subject_to_wall_distance_cm": _intersect_ranges(
                    resolved_lighting_ranges["subject_to_wall_distance_cm"],
                    lighting_sheet["key_light"]["subject_to_wall_distance_cm"],
                    label="subject-to-wall distance",
                ),
                "shadow_density": _intersect_ranges(
                    resolved_lighting_ranges["shadow_density"],
                    lighting_sheet["shadow_contract"]["density"],
                    label="shadow density",
                ),
                "exposure_compensation_ev": _intersect_ranges(
                    resolved_lighting_ranges["exposure_compensation_ev"],
                    lighting_sheet["capture_contract"]["exposure_compensation_ev"],
                    label="exposure compensation",
                ),
            }
    sampled = {
        "pov_mode": rng.choice(ranges["pov_modes"]),
        "micro_moment": rng.choice(ranges["micro_moments"]),
        "subject_center_x": _sample_number(rng, ranges["subject_center_x"]),
        "subject_center_y": _sample_number(rng, ranges["subject_center_y"]),
        "subject_width_ratio": _sample_number(rng, ranges["subject_width_ratio"]),
        "subject_height_ratio": _sample_number(rng, ranges["subject_height_ratio"]),
        "negative_space_ratio": _sample_number(rng, ranges["negative_space_ratio"]),
        "focal_length_mm": _sample_number(rng, focal_range),
        "camera_pitch_degrees": _sample_number(rng, ranges["camera_pitch_degrees"]),
        "light_softness": _sample_number(rng, light_softness_range),
        "prop_count": _sample_integer(rng, ranges["prop_count"]),
        "asymmetric": rng.random() < ranges["asymmetry_probability"],
    }
    if scene_reference is not None:
        reference_box = scene_reference["geometry"][
            reference_capabilities["placement_anchor"]
        ]
        sampled["subject_center_x"] = round(
            (reference_box["left"] + reference_box["right"]) / 2, 3
        )
        sampled["subject_center_y"] = round(
            (reference_box["top"] + reference_box["bottom"]) / 2, 3
        )
        sampled["subject_height_ratio"] = round(
            reference_box["bottom"] - reference_box["top"], 3
        )
        if effective_container_mode == "adopt_reference":
            sampled["subject_width_ratio"] = round(
                reference_box["right"] - reference_box["left"], 3
            )
        else:
            source_box = analysis["geometry"]["container_bbox"]
            source_width = (
                (source_box["right"] - source_box["left"])
                * analysis["source_binding"]["width_px"]
            )
            source_height = (
                (source_box["bottom"] - source_box["top"])
                * analysis["source_binding"]["height_px"]
            )
            physical_aspect = source_width / max(source_height, 1)
            frame_aspect = 3 / 4
            sampled["subject_width_ratio"] = round(
                min(0.58, max(0.16, sampled["subject_height_ratio"] * physical_aspect / frame_aspect)),
                3,
            )
        full_box = scene_reference["geometry"]["subject_bbox"]
        visible_subject_area = (full_box["right"] - full_box["left"]) * (
            full_box["bottom"] - full_box["top"]
        )
        sampled["negative_space_ratio"] = round(
            min(ranges["negative_space_ratio"][1], max(ranges["negative_space_ratio"][0], 1 - visible_subject_area)),
            3,
        )
        reference_interaction = scene_reference["subject"]["interaction"]
        sampled["reference_interaction"] = reference_interaction
        if reference_interaction == "held":
            sampled["pov_mode"] = "one-handed product hold matching the abstract reference interaction"
            sampled["micro_moment"] = "briefly checking the drink at a natural arm distance"
        else:
            sampled["pov_mode"] = "first-person smartphone view of the product resting in the scene"
            sampled["micro_moment"] = "noticing the drink where it naturally rests"
        # A versioned photographic style contract is the higher-fidelity camera
        # authority.  Scene Graph lens_character is only a coarse fallback and
        # must not silently collapse a measured 50-58 mm contract to 35 mm.
        if photographic_style_contract is None:
            reference_lens = scene_reference["composition"]["lens_character"]
            sampled["focal_length_mm"] = {
                "phone_wide": 26.0,
                "phone_normal": 35.0,
                "phone_mild_tele": 48.0,
                "unknown": sampled["focal_length_mm"],
            }[reference_lens]
    if scene_reference is not None:
        # Reference JSON owns scene composition. This also prevents a recipe-level
        # hand cue from leaking into a reference that explicitly has no hand.
        sampled["asymmetry_source"] = scene_reference["composition"][
            "asymmetry_source"
        ]
        sampled["asymmetric"] = sampled["asymmetry_source"].strip().lower() not in {
            "",
            "none",
            "symmetrical",
        }
    else:
        asymmetry_sources = (
            scene_recipe["composition"]["asymmetry_sources"]
            if scene_recipe
            else ranges.get(
                "asymmetry_sources",
                [
                    "hand entry, shadow geometry, light patch, and surrounding blank space"
                ],
            )
        )
        sampled["asymmetry_source"] = rng.choice(asymmetry_sources)
    if preset.get("preset_id") == "instagram_white_diffuse_closeup_v1":
        # White Close-up is a signature composition, not a broad sampling family.
        # Keep the complete cup/saucer/spoon assembly in one stable, restrained
        # corridor. The preset must retain real tabletop air instead of turning
        # into a hero-scale product crop.
        sampled.update(
            {
                "subject_center_x": 0.51,
                "subject_center_y": 0.55,
                "subject_width_ratio": 0.50,
                "subject_height_ratio": 0.58,
                "negative_space_ratio": 0.46,
                "focal_length_mm": 55.0,
                "camera_pitch_degrees": 45.5,
            }
        )
    if recipe_light:
        sampled.update(
            {
                "subject_to_wall_distance_cm": _sample_number(
                    rng, resolved_lighting_ranges["subject_to_wall_distance_cm"]
                ),
                "shadow_density": _sample_number(
                    rng, resolved_lighting_ranges["shadow_density"]
                ),
                "exposure_compensation_ev": _sample_number(
                    rng, resolved_lighting_ranges["exposure_compensation_ev"]
                ),
                "sun_patch_coverage": _sample_number(rng, recipe_light["sun_patch_coverage"]),
            }
        )

    scene = preset["scene"]
    lighting = preset["lighting"]
    tone = preset["tone_contract"]
    human = preset.get("human_presence")
    phone = runtime_profile.get("capture_signature") or runtime_profile[
        "smartphone_capture_signature"
    ]
    composition_control = runtime_profile["composition_control"]
    forbidden_copy = "; ".join(preset["style_abstraction"]["forbidden_copy_features"])
    identity = analysis["identity"]
    overhead_surface_evidence = (
        preset.get("preset_id") == "instagram_white_neutral_overhead_spatial_v1"
    )
    branding = identity["branding"]
    brand_state = target_brand_contract["state"]
    resolved_logo_text = (
        target_brand_contract.get("allowed_main_text")
        if brand_state == "verified_present"
        else None
    )
    source_container = identity["container"]
    container = container_design["design"] if effective_container_mode == "adopt_reference" else source_container
    visual_anchor = analysis["visual_anchor"]
    discarded_context_text = "; ".join(analysis["discarded_source_context"])
    must_preserve_text = (
        _join_limited(
            [
                identity["beverage"],
                "the source beverage's top-surface color, opacity, ice, foam, fruit, garnish and approximate arrangement from image 1",
                f"only the source container family {source_container['class']} and material {source_container['material']}",
            ],
            maximum_items=5,
        )
        if overhead_surface_evidence and effective_container_mode == "preserve_source"
        else _join_limited(identity["must_preserve"], maximum_items=7)
        if effective_container_mode == "preserve_source"
        else _join_limited(
            [
                identity["beverage"],
                (
                    "the source beverage's top-surface color, opacity, ice, foam, fruit, garnish and approximate arrangement from image 1; discard source sidewall liquid-layer patterns"
                    if overhead_surface_evidence
                    else "all visible liquid layers and toppings from image 1"
                ),
                (
                    "the verified source brand spelling, mark, colors and visual hierarchy"
                    if brand_state == "verified_present"
                    else "the verified absence of every logo, label, wordmark and decorative brand-like symbol"
                ),
            ]
        )
    )
    adaptable_text = _join_limited(analysis["adaptable"])
    visual_anchor_limits = _join_limited(visual_anchor["do_not_exaggerate"])
    forbidden_surface = _join_limited(tone["forbidden_surface_reading"])
    background_lightness = recipe_light["background_lightness"] if recipe_light else tone["background_lightness"]
    global_contrast = recipe_light["global_contrast"] if recipe_light else tone["global_contrast"]
    shadow_density = recipe_light["shadow_density"] if recipe_light else tone["shadow_density"]
    light_type = recipe_light["source"] if recipe_light else lighting["type"]
    light_direction = recipe_light["direction"] if recipe_light else lighting["direction"]
    shadow_description = recipe_light["shadow_description"] if recipe_light else lighting["shadow"]
    highlight_behavior = recipe_light["highlight_behavior"] if recipe_light else tone["highlight_behavior"]
    background_plane = scene_recipe["environment"]["background_plane"] if scene_recipe else tone["background_plane"]
    phone_exposure = (
        f"auto exposure with {sampled['exposure_compensation_ev']} EV compensation while protecting direct-sun highlights"
        if scene_recipe
        else phone["exposure"]
    )
    recipe_rendering = (
        scene_recipe["capture"].get("rendering_pipeline")
        or scene_recipe["capture"].get("phone_hdr")
        if scene_recipe
        else None
    )
    phone_rendering = (
        f"{recipe_rendering}; {scene_recipe['capture']['shadow_processing']}"
        if scene_recipe
        else phone["rendering"]
    )
    bbox_left = round(sampled["subject_center_x"] - sampled["subject_width_ratio"] / 2, 3)
    bbox_right = round(sampled["subject_center_x"] + sampled["subject_width_ratio"] / 2, 3)
    bbox_top = round(sampled["subject_center_y"] - sampled["subject_height_ratio"] / 2, 3)
    bbox_bottom = round(sampled["subject_center_y"] + sampled["subject_height_ratio"] / 2, 3)
    sampled["subject_bbox"] = {
        "left": bbox_left,
        "top": bbox_top,
        "right": bbox_right,
        "bottom": bbox_bottom,
        "measurement": composition_control["measurement_subject"],
    }
    if scene["surface"].lower().startswith("none"):
        environment = f"{scene['background']}; the product is naturally held in the air"
    else:
        environment = f"{scene['background']} with {scene['surface']}"
    prop_phrase = (
        "No incidental props are present."
        if sampled["prop_count"] == 0
        else f"Include no more than {sampled['prop_count']} incidental prop(s)."
    )
    logo_directive = (
        f'The main visible brand text is exactly "{resolved_logo_text}". Preserve its letter order and punctuation; '
        "do not invent or autocomplete smaller text."
        if resolved_logo_text
        else (
            "Branding in Image 1 is uncertain. Do not invent, infer or render any readable text, logo, label, symbol or pseudo-branding."
            if brand_state == "uncertain"
            else (
                "The final target is verified unbranded by the brand-transfer contract. Image 1 contains source branding, but it is not authorized for this selected container; omit it completely and add no label, logo, lettering, symbol, watermark, or decorative brand-like mark."
                if branding.get("state") == "verified_present"
                else "Image 1 is verified unbranded. Keep the target container plain and add no label, logo, lettering, symbol, watermark, or decorative brand-like mark."
            )
        )
    )
    if overhead_surface_evidence and effective_container_mode == "preserve_source":
        logo_directive = (
            "Source sidewall branding is outside this overhead container-family contract. "
            "Never tilt or rotate the cup to reveal it; omit it when it is not naturally visible "
            "from the target overhead camera and invent no replacement text or mark."
        )
    if preset.get("preset_id") == "instagram_wood_calm_window_closeup_v1" and not resolved_logo_text:
        if effective_container_mode == "adopt_reference":
            logo_directive = (
                "Keep the primary cup unbranded. Its design nevertheless requires one non-brand "
                "off-white rectangular paper label with exact lowercase cafe heading and tiny "
                "English editorial body copy; add no other label, logo or readable phrase."
            )
        else:
            logo_directive = (
                "Preserve Image 1's verified brand state and complete source container. Do not add "
                "the Image 2 cafe paper label, any replacement text, logo or decorative mark."
            )
    human_contract = ""
    reference_interaction = (
        scene_reference["subject"]["interaction"] if scene_reference else None
    )
    if scene_reference and reference_interaction != "held":
        human_contract = (
            "Hand=none. The product rests naturally on its reference-derived support plane; "
            "do not add fingers, wrist, sleeve, arm, or a floating hand."
        )
    elif human and human["required"]:
        grip = human["grip"]
        if not resolved_logo_text:
            grip = grip.replace("no fingers covering the logo", "no fingers hiding the liquid layers")
        human_contract = (
            f"Hand={_clip(human['hand_style'], 90)}; grip={_clip(grip, 100)}; "
            f"wrist={_clip(human['wrist_and_clothing'], 120)}; nails={_clip(human['nails'], 75)}. "
            f"Discard source hand/clothing. Exclude {_join_limited(human['forbidden'], maximum_items=6, item_characters=35)}."
        )
    presentation_contract = ""
    if presentation["enabled"] and effective_container_mode == "preserve_source":
        preferred_capture = presentation["preferred_capture"]
        if scene_reference:
            presentation_contract = (
                "Presentation=correct source-camera distortion only; preserve the same physical "
                "product and let the reference-derived camera contract set the new viewpoint."
            )
        else:
            presentation_contract = (
                "Presentation=correct source-camera distortion only while preserving the same physical product. "
                f"Intent={_clip(presentation['intent'], 180)} Use about "
                f"{sampled['focal_length_mm']}mm-equivalent at {preferred_capture['camera_distance']}, "
                f"camera {preferred_capture['camera_height']}, {preferred_capture['rotation']}. "
                f"Never {_join_limited(presentation['forbidden'], maximum_items=4)}."
            )
    if overhead_surface_evidence and effective_container_mode == "preserve_source":
        presentation_contract = (
            "Presentation=discard the source camera pose and reconstruct the beverage plus a simple "
            "same-family container under the preset overhead camera; exact source sidewall geometry "
            "and branding are not required."
        )
    container_contract = (
        "PRESERVE_SOURCE: keep Image 1's real container class, material, geometry and existing "
        "components. A better camera relationship may correct lens distortion but never redesign packaging."
    )
    if overhead_surface_evidence and effective_container_mode == "preserve_source":
        container_contract = (
            "SOURCE_CONTAINER_FAMILY_OVERHEAD: Image 1 is a beverage-surface evidence crop derived "
            "from the fully analyzed source. Preserve the real beverage appearance, but rebuild a "
            "simple container in the same broad family and material only. Exact source height, taper, "
            "sidewall geometry, decoration and branding are not invariants. The preset camera is the "
            "sole pose authority: never inherit the source camera angle, rim ellipse, background, "
            "perspective, lighting or shadow."
        )
    if (
        effective_container_mode == "preserve_source"
        and reference_control_role == "sanitized_scene_hint"
    ):
        if preset.get("preset_id") == "instagram_white_diffuse_closeup_v1":
            container_contract = (
                "WHITE_CLOSEUP_USER_CUP: Image 1 exclusively owns the beverage and complete user-cup "
                "construction. Image 2 is the approved scene, saucer, teaspoon and photometric anchor. "
                "Rebuild the user cup at the reference cup position, seated on the warm-white saucer with "
                "the wood-handled teaspoon retained at left. Preserve the user's height, width, rim, base and "
                "material proportions while regenerating all refraction, reflection, contact and shadow under "
                "Image 2 light. Reconstruct one coherent exposure; never paste, mask-blend or trace the source."
            )
        else:
            container_contract = (
                "PRESERVE_SOURCE_WITH_SANITIZED_SCENE_HINT: Image 2 is a photographic evidence board "
                "of separate light, wood, crema and atmosphere crops, never a scene layout or product template. "
                "Keep Image 1's complete beverage, container, components, serving state and authorized branding. "
                "Use the board only for material response, broad photometric distribution and Instagram tone; "
                "use structured camera scale, active-slot relations and support geometry. Never render panel seams, "
                "crop coordinates, an Image 2 foreground container, or an exact source grain/shadow arrangement. "
                "Re-render Image 1 under the target camera and light with new optics, contact and shadow; "
                "never paste a cutout."
            )
    if effective_container_mode == "adopt_reference":
        target = container_design["design"]
        if brand_state == "verified_present":
            adopted_brand_clause = "Apply only the exact source branding authorized by target_brand_contract."
        elif preset.get("preset_id") == "instagram_wood_calm_window_closeup_v1":
            adopted_brand_clause = (
                "Keep the adopted cup unbranded, but preserve its authorized non-brand off-white "
                "paper label with exact lowercase cafe heading and tiny English body copy."
            )
        else:
            adopted_brand_clause = "The adopted container and every immediate support must remain completely unbranded even when Image 1 is branded."
        if reference_control_role == "structured_only":
            container_contract = (
                "STRUCTURED_REFERENCE_DESIGN: no reference image is submitted. Reconstruct a new "
                "container from the versioned design contract: material, silhouette, rim and every "
                "declared immediate support component such as a saucer, coaster or pedestal; "
                f"keep their physical support relationship at H:W={target['height_to_width_ratio'][0]}.."
                f"{target['height_to_width_ratio'][1]}. Preserve Image 1 beverage. "
                f"{adopted_brand_clause} Invent no text or brand-like decoration."
            )
        elif reference_control_role == "sanitized_scene_hint":
            wood_scene_hint = preset.get("preset_id") == "instagram_wood_calm_window_closeup_v1"
            white_scene_hint = preset.get("preset_id") == "instagram_white_diffuse_closeup_v1"
            design_authority = (
                "Regenerate the target cup design from Image 1 and the source-derived design contract; "
                "do not preserve or paste its pixel boundary, source reflections, source lighting or source perspective."
                if container_design_source == "source"
                else (
                    "Regenerate the declared reference cup assembly, including every immediate support "
                    "such as its saucer, coaster or pedestal, from the design contract."
                )
            )
            if white_scene_hint:
                container_contract = (
                    "WHITE_CLOSEUP_REFERENCE_ASSEMBLY: Image 2 is the dedicated high-detail geometry evidence "
                    "crop embedded in a sanitized static scene-and-serving hint, not an output crop or scene-layout "
                    "template. Keep its "
                    "one-piece low straight cylindrical clear-glass silhouette, constant sidewall diameter, subtly "
                    "thick base, complete warm-white saucer, wood-handled teaspoon and physical support relations. The "
                    "structured scene graph and lighting sheet—not Image 2's pixels—control final framing, scale, "
                    "light direction, exposure and shadow topology. Use the hint table only for real matte texture and "
                    "a strict peripheral ceiling: narrow waffle sliver and small magazine corner, never large props. "
                    "Replace only its deliberately empty glass with Image 1 beverage and copy no reference drink, "
                    "topping, boundary or exact pixel. "
                    "Rebuild glass, liquid, ceramic, metal, wood handle, reflections, refraction, contacts and "
                    "shadows together under one exposure; do not paste or trace pixels. "
                    f"Target cup H:W={target['height_to_width_ratio'][0]}..{target['height_to_width_ratio'][1]}. "
                    f"{adopted_brand_clause}"
                )
            else:
                container_contract = (
                    "SANITIZED_SCENE_HINT: Image 2 is a non-contiguous evidence board, not a scene layout. "
                    "Sample cup construction, real wood, crema, light, color and air; structured contracts control "
                    "camera, scale, relations and contacts. Render no panels or seams. "
                    + (
                        "Transfer the distant sill-supported plant topology and only the authorized text from the design contracts; do not copy foreground beverage contents or the words cafe latte. "
                        if wood_scene_hint
                        else "Do not copy exact pixels, beverage contents, text, branding, heater, plants, "
                    )
                    + f"furniture or exact shadow silhouettes. {design_authority} Preserve Image 1 beverage. "
                    + f"Target H:W={target['height_to_width_ratio'][0]}..{target['height_to_width_ratio'][1]}. "
                    + f"{adopted_brand_clause} Re-render cup, liquid, reflections, transmission, contact and shadow "
                    + "together under the target scene light; never paste a source cutout."
                )
        else:
            container_contract = (
                "ADOPT_REFERENCE: Image 2 is container-assembly-design-only. Adopt its material, silhouette, "
                "rim and every declared immediate support component such as a saucer, coaster or pedestal; "
                f"keep their physical support relationship at H:W={target['height_to_width_ratio'][0]}.."
                f"{target['height_to_width_ratio'][1]}. Source cup geometry is not an identity "
                f"invariant. Preserve Image 1 beverage. {adopted_brand_clause} Copy no Image 2 "
                "beverage, garnish, brand/text, unrelated prop, scene, crop, hand or shadow; invent no text."
            )
        if overhead_surface_evidence and any(
            token in str(target.get("material", "")).lower()
            for token in ("ceramic", "opaque")
        ):
            container_contract += (
                " OPAQUE_OVERHEAD_SURFACE_LOCK: all beverage color, syrup, fruit, ice and foam must "
                "remain strictly inside the inner rim. Keep the complete exterior and base clean plain "
                "white ceramic. Never transfer source sidewall streaks or render red, green or brown "
                "stains, bands, transparency or beverage layers on the mug exterior."
            )
    recipe_contract = ""
    material_rule = ""
    lighting_sheet_contract = ""
    if lighting_sheet:
        sheet_key = lighting_sheet["key_light"]
        sheet_shadow = lighting_sheet["shadow_contract"]
        sheet_capture = lighting_sheet["capture_contract"]
        lighting_sheet_contract = (
            f"Sheet={lighting_sheet['lighting_sheet_id']} is authoritative: "
            f"key={_clip(sheet_key['source'], 44)}; "
            f"direction={_clip(sheet_key['direction'], 48)}; "
            f"size={_clip(sheet_key['relative_size'], 44)}; "
            f"contact={_clip(sheet_shadow['contact_shadow']['behavior'], 35)}; "
            f"cast={_clip(sheet_shadow['cast_shadow']['behavior'], 40)}; "
            f"transmission={_clip(sheet_shadow['transmitted_light']['behavior'], 40)}; "
            f"WB={_clip(sheet_capture['white_balance'], 40)}."
        )
    if scene_recipe:
        recipe_capture = scene_recipe["capture"]
        recipe_environment = scene_recipe["environment"]
        recipe_human = scene_recipe["human_rendering"]
        material_key = "glass" if "glass" in container["material"].lower() else "plastic"
        material_rule = scene_recipe["material_rules"][material_key]
        if scene_reference:
            if lighting_sheet:
                recipe_contract = (
                    "Ref JSON controls composition, object geometry and spatial planes only. "
                    "Lighting Sheet controls source type, direction, size, hardness, shadow "
                    "density and white balance. "
                    f"Use {_clip(recipe_rendering, 65)}; protect transparent highlights; "
                    "shadow edge and highlights agree with the sheet's single source."
                )
            else:
                reference_light = scene_reference["lighting"]
                reference_direction = _clip(reference_light["direction"], 75)
                direction_phrase = (
                    reference_direction
                    if reference_direction.lower().startswith("from ")
                    else f"from {reference_direction}"
                )
                recipe_contract = (
                    f"Ref light: one {reference_light['source_type']} {direction_phrase}; "
                    f"size={reference_light['source_size']}, hardness={reference_light['hardness']}, "
                    f"contrast={reference_light['contrast']}, WB={reference_light['white_balance']}. "
                    f"Use {_clip(recipe_rendering, 65)}; protect transparent highlights; "
                    "shadow edge and highlights agree with this source."
                )
        else:
            recipe_contract = (
                f"Recipe={scene_recipe['recipe_id']}; one exposure and one source size for highlights/shadows. "
                f"Capture={_clip(recipe_rendering, 65)}. "
                f"Background={_clip(recipe_environment['background_plane'], 105)}; "
                f"surface={_clip(recipe_environment['surface_character'], 75)}. "
                f"Light={_clip(recipe_light['source'], 75)} "
                f"from {_clip(recipe_light['direction'], 55)}; distance={sampled['subject_to_wall_distance_cm']}cm; "
                f"shadow={_clip(recipe_light['shadow_description'], 105)} at density {sampled['shadow_density']}; "
                f"fill={_clip(recipe_light['ambient_fill'], 75)}; EV={sampled['exposure_compensation_ev']}; "
                f"highlight={_clip(recipe_light['highlight_behavior'], 80)}. "
                f"Skin={_clip(recipe_human['skin_texture'], 65)}; "
                f"material={_clip(material_rule, 110)}. Highlight and shadow edge imply one source size."
            )

    scene_reference_contract = ""
    if scene_reference:
        reference_composition = scene_reference["composition"]
        reference_depth = scene_reference["depth"]
        reference_softness = reference_depth["far_plane_softness"]
        if reference_capabilities["depth_transfer"] == "clamp_to_moderate":
            reference_softness = "moderate maximum"
        scene_reference_contract = (
            f"Ref JSON: shot={reference_composition['shot_type']}; "
            f"camera={reference_composition['camera_height']}/{_clip(reference_composition['camera_pitch'], 35)}/"
            f"{reference_composition['lens_character']}; interaction={scene_reference['subject']['interaction']}; "
            f"planes={_clip(reference_depth['product_plane'], 45)} > "
            f"{_clip(reference_depth['foreground'], 40)} > {_clip(reference_depth['midground'], 40)} > "
            f"{_clip(reference_depth['background'], 45)}; "
            f"subject={_clip(reference_composition['subject_position'], 50)}; "
            f"space={_clip(reference_composition['negative_space'], 55)}; "
            f"asymmetry={_clip(reference_composition['asymmetry_source'], 50)}; cue="
            f"{_join_limited(reference_depth['perspective_cues'], maximum_items=1, item_characters=45)}; "
            f"far-softness={reference_softness}; atmosphere={reference_depth['atmospheric_separation']}; "
            "rebuild relationships, not pixels."
        )

    scene_layout_contract = ""
    if slot_plan is not None and scene_graph is not None:
        binding_by_target = {
            item["target_slot_id"]: item for item in slot_plan["bindings"]
        }
        active_slot_ids = {
            item["slot_id"]
            for item in slot_plan["slots"]
            if item["action"] != "remove"
        }
        clauses = []
        for slot in slot_plan["slots"]:
            if slot["action"] == "remove":
                continue
            box = slot["target_bbox"]
            target = (
                f"@({box['left']:.2f},{box['top']:.2f},"
                f"{box['right']:.2f},{box['bottom']:.2f})"
            )
            if slot["action"] == "bind_product":
                binding = binding_by_target[slot["slot_id"]]
                clauses.append(
                    f"{binding['input_product_id']}->{slot['slot_id']}{target}"
                )
            elif slot["action"] == "genericize":
                clauses.append(
                    f"{slot['slot_id']}=new unbranded generic {slot['kind']}{target}"
                    f"{_runtime_appearance_clause(slot)}"
                )
            else:
                clauses.append(
                    f"{slot['slot_id']}=abstract-{slot['kind']}{target}"
                    f"{_runtime_appearance_clause(slot)}"
                )
        for binding in slot_plan["bindings"]:
            if binding["placement_mode"] == "add":
                box = binding["target_bbox"]
                clauses.append(
                    f"{binding['input_product_id']}->{binding['target_slot_id']}"
                    f"@({box['left']:.2f},{box['top']:.2f},"
                    f"{box['right']:.2f},{box['bottom']:.2f})"
                )
        relation_text = [
            f"{relation['from_slot_id']}>{relation['predicate']}>"
            f"{relation['to_slot_id']}"
            for relation in scene_graph["relations"]
            if relation["from_slot_id"] in active_slot_ids
            and relation["to_slot_id"] in active_slot_ids
        ]
        removed_count = sum(
            item["action"] == "remove" for item in slot_plan["slots"]
        )
        inactive_clause = f" Inactive={removed_count}." if removed_count else ""
        scene_layout_contract = (
            "Slots constrain layout, not pixels: "
            f"{'; '.join(clauses)}. Relations={'; '.join(relation_text[:3]) or 'none'}."
            f"{inactive_clause} Regenerate products, contacts, occlusion and shadows together; "
            "copy no reference product or brand."
        )

    style_contract_summary = ""
    if photographic_style_contract:
        direction = photographic_style_contract["creative_direction"]
        camera_geometry = photographic_style_contract["camera_geometry"]
        composition_geometry = photographic_style_contract["composition_geometry"]
        tone_signature = photographic_style_contract["tone_signature"]
        finish_signature = photographic_style_contract["finish_signature"]
        style_contract_summary = (
            f"Response={_clip(direction['desired_response'], 115)}; "
            f"restraint={_clip(direction['restraint'], 120)}. "
            f"Projection={_clip(camera_geometry['projection'], 70)}; working-distance="
            f"{camera_geometry['working_distance_cm'][0]}..{camera_geometry['working_distance_cm'][1]}cm; "
            f"rhythm={_clip(composition_geometry['frame_rhythm'], 120)}. "
            f"Tone={_clip(tone_signature['contrast_curve'], 90)}; material-separation="
            f"{_clip(tone_signature['material_separation'], 110)}; finish={_clip(finish_signature['acuity'], 100)}."
        )
    wood_closeup_master_contract = _wood_closeup_master_contract(
        preset=preset,
        scene_graph=scene_graph,
        lighting_sheet=lighting_sheet,
        photographic_style_contract=photographic_style_contract,
        container_mode=effective_container_mode,
        reference_control_role=reference_control_role,
    )
    white_closeup_master_contract = _white_closeup_master_contract(
        preset=preset,
        product_analysis=analysis,
        container_mode=effective_container_mode,
    )

    asymmetry_instruction = (
        f"Keep the product inside its center contract and create asymmetry through {sampled['asymmetry_source']}, not by pushing the product away from its target center."
        if sampled["asymmetric"]
        else "Keep the composition quietly balanced but naturally imperfect."
    )
    if scene_recipe:
        if scene_reference:
            reference_color = scene_reference["color"]
            environment_light_summary = (
                f"Ref tone: exposure={reference_color['exposure']}, saturation={reference_color['saturation']}, "
                f"contrast={reference_color['contrast']}, blacks={reference_color['black_point']}, "
                f"palette="
                f"{','.join(reference_color['palette_hex'][:4])}. Grade lightly without changing product colors."
            )
        else:
            environment_light_summary = (
                f"Tone: lightness {background_lightness[0]}..{background_lightness[1]}, saturation "
                f"{tone['background_saturation'][0]}..{tone['background_saturation'][1]}, contrast "
                f"{global_contrast[0]}..{global_contrast[1]}, shadow {shadow_density[0]}..{shadow_density[1]}; "
                f"{_clip(tone['color_bias'], 85)}. Reject {_clip(forbidden_surface, 140)}."
            )
        smartphone_summary = (
            f"Lens={_clip(phone['lens'], 100)}; focus={_clip(phone['depth'], 75)}; "
            f"framing={_clip(phone['framing'], 90)}."
        )
    else:
        environment_light_summary = (
            f"Use {background_plane}, a vertical indoor wall, never ground. Scene: {environment}. {prop_phrase} "
            f"Use {light_type} from {light_direction}, softness={sampled['light_softness']}, producing "
            f"{shadow_description}. Background lightness={background_lightness[0]}..{background_lightness[1]}, "
            f"saturation={tone['background_saturation'][0]}..{tone['background_saturation'][1]}, "
            f"contrast={global_contrast[0]}..{global_contrast[1]}, shadow density="
            f"{shadow_density[0]}..{shadow_density[1]}. {tone['color_bias']} {highlight_behavior} Reject {forbidden_surface}."
        )
        smartphone_summary = (
            f"Lens: {phone['lens']}. Focus: {phone['depth']}. Exposure: {phone_exposure}. "
            f"Rendering: {phone_rendering}. Framing: {phone['framing']}."
        )

    spatial_depth_contract = ""
    spatial_depth = phone.get("spatial_depth")
    if spatial_depth:
        if scene_reference:
            interaction_detail = (
                "the touching fingers"
                if reference_interaction == "held"
                else "the support contact edge"
            )
            spatial_depth_contract = (
                "Use distinct Ref foreground, product, midground and far planes. Establish "
                "recession through overlap, diminishing scale, converging lines and light falloff "
                "before softness. Keep the cup, rim, ice, liquid layers, "
                f"{interaction_detail}{' and authorized branding' if brand_state == 'verified_present' and not (overhead_surface_evidence and effective_container_mode == 'preserve_source') else ''} sharp. With real distance, reduce only "
                "far-background microcontrast, edge acuity and fine texture; atmosphere only in "
                "the farthest plane. Reject "
                f"{_join_limited(spatial_depth['forbidden'], maximum_items=6, item_characters=60)}. "
                "Softness confirms distance, never creates it."
            )
        else:
            subject_sharpness = spatial_depth["subject_sharpness"].replace(
                "verified branding",
                (
                    "authorized branding"
                    if brand_state == "verified_present" and not (
                        overhead_surface_evidence
                        and effective_container_mode == "preserve_source"
                    )
                    else "plain unbranded surfaces"
                ),
            )
            spatial_depth_contract = (
                f"{spatial_depth['scene_geometry']} {spatial_depth['focus_behavior']} Keep "
                f"{subject_sharpness}. Never use "
                f"{'; '.join(spatial_depth['forbidden'])}. Preserve readable planes; softness "
                "confirms distance but never replaces geometry."
            )

    image_roles = ["product_source"]
    image_paths = [str(Path(input_image))]
    if container_reference_image and (
        effective_container_mode == "adopt_reference"
        or reference_control_role == "sanitized_scene_hint"
    ):
        image_roles.append(
            "scene_hint"
            if reference_control_role == "sanitized_scene_hint"
            else "container_reference"
        )
        image_paths.append(str(Path(container_reference_image)))
    if (
        preset.get("preset_id") == "instagram_white_diffuse_closeup_v1"
        and container_reference_image
    ):
        source_pixels = canonical_image_binding(input_image)["pixel_sha256"]
        scene_pixels = canonical_image_binding(container_reference_image)["pixel_sha256"]
        if source_pixels == scene_pixels:
            raise ValueError(
                "White close-up requires a distinct scene/light anchor; "
                "product_source and scene_hint contain identical pixels"
            )
    if brand_asset_image:
        image_roles.append("brand_asset")
        image_paths.append(str(Path(brand_asset_image)))
    role_description = "; ".join(
        f"Image {index + 1}={role.replace('_', ' ')}" for index, role in enumerate(image_roles)
    )
    if (
        preset.get("preset_id") == "instagram_white_diffuse_closeup_v1"
        and "scene_hint" in image_roles
    ):
        if effective_container_mode == "adopt_reference":
            role_description = (
                "Image 1=product identity and beverage authority; "
                "Image 2=sanitized static scene-and-serving hint with an empty reference cup, saucer, spoon, "
                "table material and only tiny peripheral props; structured contracts own final composition and light"
            )
        else:
            role_description = (
                "Image 1=product identity and complete user-cup authority; "
                "Image 2=approved white-closeup scene, saucer, spoon and photometric anchor"
            )
    if (
        preset.get("preset_id") == "instagram_wood_calm_window_closeup_v1"
        and effective_container_mode == "adopt_reference"
    ):
        role_description = role_description.replace(
            "Image 1=product source",
            "Image 1=beverage-only evidence; source cup has zero authority",
        )
    if overhead_surface_evidence:
        role_description = role_description.replace(
            "Image 1=product source",
            "Image 1=beverage-surface evidence crop from the analyzed product source",
        )
    brand_asset_instruction = (
        f" Image {image_roles.index('brand_asset') + 1} is a source-brand asset; use it only to preserve exact branding."
        if "brand_asset" in image_roles
        else ""
    )
    measurement_components = (
        "only the lid or sleeve that actually exists in image 1"
        if effective_container_mode == "preserve_source"
        else "the adopted container plus every declared immediate support component"
    )
    camera_clause = (
        (
            f"Use the photographic style contract at {sampled['focal_length_mm']}mm-equivalent "
            f"and {sampled['camera_pitch_degrees']} degrees; the coarse Ref lens label is fallback-only."
        )
        if scene_reference and photographic_style_contract
        else "Follow the Ref JSON camera height, pitch and phone-lens character."
        if scene_reference
        else (
            f"Use {sampled['focal_length_mm']}mm-equivalent phone perspective at "
            f"{sampled['camera_pitch_degrees']} degrees."
        )
    )
    overhead_camera_contract = (
        " SOURCE-POSE OVERRIDE: regenerate the complete product at the preset's near-vertical "
        "overhead camera. The optical axis points down toward the table; the outer and inner rim "
        "read nearly circular, with only a slight physically plausible sidewall. Do not copy Image "
        "1's rim ellipse, sidewall exposure, viewpoint or perspective. Never lower or tilt the "
        "camera to reveal source-container branding or vertical beverage layers."
        if overhead_surface_evidence
        else ""
    )
    negative_space_location = (
        "in the reference-described regions"
        if scene_reference
        else "mainly above/beside the cup"
    )
    phone_prompt_summary = (
        f"Use an ordinary {sampled['focal_length_mm']}mm-equivalent smartphone main camera with "
        "mostly deep real-world focus."
        if scene_reference
        else _clip(smartphone_summary, 190)
    )
    container_summary = (
        f"source-family {container['class']}; {container['material']}; exact source sidewall geometry is not required"
        if overhead_surface_evidence and effective_container_mode == "preserve_source"
        else f"{container['class']}; {container['material']}; {_clip(container['geometry'], 110)}; components={_join_limited(container['components'], maximum_items=5, item_characters=42)}"
    )
    final_brand_gate = (
        "no invented branding and no camera tilt for branding"
        if overhead_surface_evidence and effective_container_mode == "preserve_source"
        else "verified brand state"
    )

    prompt = f"""[NATURAL SMARTPHONE CAFE PHOTO - PRIORITY]
Create one new original first-person Instagram cafe photo with an ordinary smartphone. It must feel casually captured in one attempt, not staged advertising, studio photography, CGI, a pasted cutout or copied reference. Inputs: {role_description}.{brand_asset_instruction}

[IDENTITY - HARD LOCK]
Beverage={_clip(identity['beverage'], 180)}. Container={container_summary}. Preserve {_clip(must_preserve_text, 430)}. Anchor={_clip(visual_anchor['feature'], 120)} via {_clip(visual_anchor['emphasis_method'], 105)}; do not exaggerate {_clip(visual_anchor_limits, 150)}. {_clip(container_contract, 1500)} {_clip(presentation_contract, 240)} {_clip(logo_directive, 260)}

[COMPOSITION - MEASURED]
Moment={_humanize(sampled['micro_moment'])}; setup={_humanize(sampled['pov_mode'])}; phone stays in the other unseen hand. Product body is the container plus {measurement_components}, excluding straw and hand. Target body bbox=({bbox_left},{bbox_top})-({bbox_right},{bbox_bottom}), center=({sampled['subject_center_x']},{sampled['subject_center_y']}), size=({sampled['subject_width_ratio']},{sampled['subject_height_ratio']}); tolerance center {composition_control['center_tolerance']}, size {composition_control['size_tolerance']}. Negative space={sampled['negative_space_ratio']} +/-{composition_control['negative_space_tolerance']} {negative_space_location}. {camera_clause}{overhead_camera_contract} {asymmetry_instruction} Keep 4:5 crop safety. {scene_reference_contract} {scene_layout_contract}

[LIGHT, TONE, HAND]
{_clip(recipe_contract, 430 if scene_reference else 500)} {_clip(lighting_sheet_contract, 400)} {_clip(environment_light_summary, 210)} {_clip(human_contract, 430)}

[SMARTPHONE DEPTH - GEOMETRY BEFORE SOFTNESS]
{spatial_depth_contract or 'Use overlap, scale and perspective lines to separate near, middle and far planes. Keep the complete product sharp; reduce only far-background fine detail slightly. Reject uniform blur, portrait cutout blur and DSLR bokeh.'} {phone_prompt_summary}

[PHYSICS AND SAFETY]
Product, {('hand, ' if not scene_reference or reference_interaction == 'held' else '')}environment, highlights, reflections, transmission and shadows share one source/camera. Render {container['material']} physically: glass keeps rim/base thickness and refraction; plastic keeps thin reflections. Preserve contact; reject floating edges or conflicting shadows. Scene pixels are not submitted; extra images obey declared roles. Invent details; never copy {_clip(forbidden_copy, 150)}. Discard {_clip(discarded_context_text, 100)}. Add no unverified text, logo, watermark or pseudo-branding. Reject malformed hands, extra fingers, uniform blur, studio/catalog/CGI appearance, HDR halos and movie-like grading. {_clip('Also reject ' + '; '.join(scene_recipe['forbidden']), 170) if scene_recipe else ''}

[FINAL GATE]
The beverage, selected container policy, {final_brand_gate}, visual anchor, bbox, negative space, physical depth, {('hand contact' if not scene_reference or reference_interaction == 'held' else 'support-plane contact')} and single-source light must all agree. {'Every active slot, relation and exact product count must also match the scene plan.' if slot_plan else ''} Correct any violation before returning the image.
"""

    if "capture_signature" in runtime_profile:
        preset_composition = preset["composition"]
        preset_color = preset["color"]
        observational_social = preset.get("generation_voice") == "observational_social"
        style_summary_limit = 620
        preset_block_limit = 190
        scene_reference_limit = 430
        scene_layout_limit = 700
        recipe_limit = 430
        lighting_limit = 430
        container_contract_limit = 1500
        if preset.get("preset_id") == "instagram_wood_calm_window_closeup_v1":
            # The full-fidelity wood master block carries the non-lossy geometry,
            # light, atmosphere, label and material rules. Trim only duplicate summaries.
            style_summary_limit = 400
            preset_block_limit = 120
            scene_reference_limit = 260
            scene_layout_limit = 450
            recipe_limit = 280
            lighting_limit = 320
            container_contract_limit = 900
        elif preset.get("preset_id") == "instagram_white_diffuse_closeup_v1":
            # The non-lossy White Close-up master block below owns the signature
            # geometry and photometry. Compact only duplicated generic summaries.
            style_summary_limit = 360
            preset_block_limit = 105
            scene_reference_limit = 220
            scene_layout_limit = 360
            recipe_limit = 250
            lighting_limit = 300
            container_contract_limit = 850
        editorial_heading = (
            "[QUIET OBSERVATIONAL SOCIAL CAFE PHOTOGRAPH - HARD LOCK]"
            if observational_social
            else "[ART-DIRECTED EDITORIAL CAFE PHOTOGRAPH - HARD LOCK]"
        )
        editorial_opening = (
            "Create one new original cafe photograph that feels like a perceptive person noticed and captured a real moment. The precision must stay invisible: quiet, lived-in, lightly imperfect and socially natural, never promotional, showroom-clean or deliberately 'Instagram styled'."
            if observational_social
            else "Create one new original professionally art-directed editorial cafe photograph with quiet material intelligence and precise visual restraint. It must not read as a casual smartphone image, generic cafe stock, ecommerce catalog, CGI or a copied reference."
        )
        prompt = f"""{editorial_heading}
{editorial_opening} Inputs: {role_description}.{brand_asset_instruction}

[EXACT PRODUCT]
Beverage={_clip(identity['beverage'], 180)}. Container={container_summary}. Preserve {_clip(must_preserve_text, 430)}. {_clip(container_contract, container_contract_limit)} {_clip(logo_directive, 260)}

[PRESET, REFERENCE AND ACTIVE SCENE]
{_clip(style_contract_summary, style_summary_limit)} Preset={_clip(preset['prompt_blocks']['look'], preset_block_limit)} {_clip(preset['prompt_blocks']['composition'], preset_block_limit)} {_clip(preset['prompt_blocks']['preservation'], preset_block_limit)} {_clip(scene_reference_contract, scene_reference_limit)} {_clip(scene_layout_contract, scene_layout_limit)} Only active slots and relations are authoritative; removed reference objects have no authority.

[CAMERA AND COMPOSITION]
Capture={_clip(preset_composition['shot_type'], 80)}; angle={_clip(preset_composition['camera_angle'], 110)}; height={_clip(preset_composition['camera_height'], 100)}; focal={sampled['focal_length_mm']}mm-equivalent; pitch={sampled['camera_pitch_degrees']}deg; horizon={_clip(preset_composition['horizon_visibility'], 70)}; focus={_clip(preset_composition['depth_of_field'], 110)}.{overhead_camera_contract} Product bbox=({bbox_left},{bbox_top})-({bbox_right},{bbox_bottom}); center=({sampled['subject_center_x']},{sampled['subject_center_y']}); negative-space={sampled['negative_space_ratio']}. Alignment={_clip(preset_composition['alignment'], 135)}. Preserve support-plane perspective and designed asymmetry.

[LIGHT, COLOR AND MATERIAL]
{_clip(recipe_contract, recipe_limit)} {_clip(lighting_sheet_contract, lighting_limit)} Environment={_clip(environment, 170)}. WB={preset_color['white_balance_kelvin']}K; palette={','.join(preset_color['palette_hex'])}; contrast={_clip(preset_color['contrast'], 80)}; saturation={_clip(preset_color['saturation'], 80)}; black={_clip(preset_color['black_point'], 90)}. {_clip(material_rule, 150)} Product, support, reflections, transmission and shadows share one physical light system.

[EDITORIAL FINISH]
{_clip(preset['capture']['look'], 160)}. {_clip(preset['capture']['realism'], 150)}. Create depth through camera geometry, plane overlap, scale and light falloff before softness. Keep the complete product sharp without wide-angle looming, computational halos, generic bokeh or plastic retouching. Add no unverified text, logo or watermark. Reject floating contact, invented props, malformed hands and conflicting shadows.

{wood_closeup_master_contract}
{white_closeup_master_contract}

[FINAL GATE]
Return the image only when exact beverage identity, selected container policy, {final_brand_gate}, approved scale/position corridors, camera geometry, negative-space topology, support contact, palette, material hierarchy and single-source light all agree.
"""

    if preset.get("preset_id") == "instagram_white_diffuse_closeup_v1":
        required_white_terms = [
            "complete saucer and teaspoon",
            "cup-to-saucer",
            "Reconstruct the whole frame as one photograph",
        ]
        required_white_terms.extend(
            ["dedicated high-detail geometry evidence crop", "not an output crop"]
            if effective_container_mode == "adopt_reference"
            else ["approved white-closeup"]
        )
        prompt_casefold = prompt.casefold()
        missing_white_terms = [
            term for term in required_white_terms if term.casefold() not in prompt_casefold
        ]
        if missing_white_terms:
            raise ValueError(
                "White close-up prompt lost core composition terms: "
                + ", ".join(missing_white_terms)
            )
        contradictory_white_terms = (
            "do not invent a saucer",
            "contains no spoon",
            "reference spoon excluded",
        )
        found_contradictions = [
            term for term in contradictory_white_terms if term.casefold() in prompt.casefold()
        ]
        if found_contradictions:
            raise ValueError(
                "White close-up prompt contains a serving-assembly contradiction: "
                + ", ".join(found_contradictions)
            )

    forbidden_language = runtime_profile["language_policy"]["forbidden"]
    found = [term for term in forbidden_language if term.lower() in prompt.lower()]
    if found:
        raise ValueError(f"Forbidden prompt language present: {found}")
    prompt_limit_policy = resolve_prompt_limit_policy(
        provider=runtime_profile.get("provider"),
        model=runtime_profile.get("model"),
    )
    if len(prompt.strip()) > prompt_limit_policy.maximum_characters:
        raise ValueError(
            f"Compiled prompt has {len(prompt.strip())} characters; "
            f"limit is {prompt_limit_policy.maximum_characters} "
            f"({prompt_limit_policy.policy_id})"
        )

    cost = costs[tier]
    quality_gate = copy.deepcopy(runtime_profile["quality_gate"])
    if scene_recipe:
        for failure in scene_recipe["quality_gate"]["hard_fail"]:
            if failure not in quality_gate["hard_fail"]:
                quality_gate["hard_fail"].append(failure)
        quality_gate["weights"] = scene_recipe["quality_gate"]["weights"]
    if preset.get("preset_id") == "instagram_white_diffuse_closeup_v1":
        for failure in (
            "white close-up serving assembly exceeds the restrained scale corridor or loses surrounding tabletop air",
            "saucer or wood-handled teaspoon is missing, cropped, floating or malformed",
            "adopted reference cup is a tall highball, stepped vessel, decorative band, crack, seam, sleeve or stacked vessel instead of one compact low straight cylinder",
            "product_source and scene_hint are identical or the scene/light anchor is absent",
            "glass, liquid, ceramic and spoon do not share one coherent exposure and reflection system",
            "bright low-chroma milk, foam or cream retains an isolated source-white point instead of sharing the saucer and table exposure",
            "white-room depth lacks peripheral scale falloff, off-frame occupancy shadow or table-plane air",
        ):
            if failure not in quality_gate["hard_fail"]:
                quality_gate["hard_fail"].append(failure)
    if effective_container_mode == "adopt_reference":
        quality_gate["hard_fail"] = [
            failure
            for failure in quality_gate["hard_fail"]
            if failure
            not in {
                "changed container material or construction",
                "presentation correction became container redesign",
            }
        ]
        quality_gate["hard_fail"].append(
            "declared container design or its required immediate support was not reconstructed"
        )
        if preset.get("preset_id") == "instagram_wood_calm_window_closeup_v1":
            quality_gate["hard_fail"].append(
                "primary retained the source glass cylinder, thick rim or flat glass base instead of the thin tapered clear PET cup, rolled open rim, narrow base ring and reference straw"
            )
        if reference_control_role == "sanitized_scene_hint":
            quality_gate["hard_fail"].append(
                "scene-hint text, branding, beverage identity, exact pixels or identifiable background object leaked into the output"
            )
        elif reference_control_role == "container_design_only":
            quality_gate["hard_fail"].append(
                "reference beverage, brand, unrelated props, background or exact arrangement leaked into the output"
            )
    if overhead_surface_evidence:
        for failure in (
            "output inherited the oblique source camera instead of the target overhead camera",
            "cup rim is strongly elliptical or the sidewall is too exposed for the target overhead camera",
        ):
            if failure not in quality_gate["hard_fail"]:
                quality_gate["hard_fail"].append(failure)
        if effective_container_mode == "adopt_reference":
            failure = (
                "beverage color, syrup or fruit appears on the opaque container exterior or base"
            )
            if failure not in quality_gate["hard_fail"]:
                quality_gate["hard_fail"].append(failure)
    if slot_plan is not None:
        for failure in (
            "bound user product is missing or placed in the wrong scene slot",
            "active beverage and dessert count differs from the resolved slot plan",
            "one product intrudes into another protected slot or negative-space region",
            "generic companion copies reference branding or product identity",
            "support contact, depth order, occlusion or shadow contradicts the slot plan",
        ):
            if failure not in quality_gate["hard_fail"]:
                quality_gate["hard_fail"].append(failure)
    return {
        "schema_version": "2.0.0",
        "preset_id": preset["preset_id"],
        "scene_recipe_id": scene_recipe["recipe_id"] if scene_recipe else None,
        "photographic_style_contract_id": (
            photographic_style_contract["contract_id"]
            if photographic_style_contract
            else None
        ),
        "lighting_sheet_contract": (
            {
                "lighting_sheet_id": lighting_sheet["lighting_sheet_id"],
                "authority": [
                    "source_type",
                    "direction",
                    "source_size",
                    "hardness",
                    "shadow_density",
                    "white_balance",
                ],
                "resolved_ranges": copy.deepcopy(resolved_lighting_ranges),
                "runtime_reference_pixels_submitted": False,
            }
            if lighting_sheet
            else None
        ),
        "scene_reference_contract": (
            {
                "asset_id": scene_reference["asset"]["asset_id"],
                "pixel_sha256": scene_reference["asset"]["pixel_sha256"],
                "composition": copy.deepcopy(scene_reference["composition"]),
                "depth": copy.deepcopy(scene_reference["depth"]),
                "facets": copy.deepcopy(scene_reference["facets"]),
                "runtime_capabilities": copy.deepcopy(reference_capabilities),
            }
            if scene_reference
            else None
        ),
        "scene_graph_contract": (
            {
                "asset_id": scene_graph["asset"]["asset_id"],
                "schema_version": scene_graph["schema_version"],
                "taxonomy": copy.deepcopy(scene_graph["taxonomy"]),
                "slot_plan": copy.deepcopy(slot_plan),
                "relations": copy.deepcopy(scene_graph["relations"]),
                "runtime_capabilities": copy.deepcopy(scene_graph_capabilities),
                "runtime_reference_pixels_submitted": False,
            }
            if scene_graph is not None
            else None
        ),
        "seed": seed,
        "sampled_parameters": sampled,
        "product_analysis": analysis,
        "brand_contract": {
            "state": brand_state,
            "allowed_main_text": resolved_logo_text,
            "visible_text": (
                copy.deepcopy(branding["visible_text"])
                if brand_state == "verified_present"
                else []
            ),
            "non_text_mark": (
                branding["non_text_mark"]
                if brand_state == "verified_present"
                else None
            ),
        },
        "brand_transfer_resolution": copy.deepcopy(brand_transfer_resolution),
        "identity_policy": {
            "beverage": "preserve_source",
            "container": effective_container_mode,
            "branding": brand_transfer_resolution["action"],
        },
        "reference_control": {
            "role": reference_control_role,
            "submitted": bool(container_reference_image),
            "container_design_source": container_design_source,
        },
        "container_design": copy.deepcopy(container_design),
        "service_features": copy.deepcopy(features),
        "repair_policy": {
            "auto_paid_repair": effective_auto_repair,
            "minimum_trigger_confidence": features["features"]["auto_paid_repair"][
                "minimum_trigger_confidence"
            ],
            "maximum_attempts": features["features"]["auto_paid_repair"]["maximum_attempts"],
            "maximum_additional_credits": features["features"]["auto_paid_repair"][
                "maximum_additional_credits"
            ],
        },
        "source_context_exclusions": analysis["discarded_source_context"],
        "capture_contract": {
            "spatial_depth": copy.deepcopy(phone.get("spatial_depth")),
        },
        "generation": {
            "provider": runtime_profile["provider"],
            "job_type": runtime_profile["model"],
            "submission_path": runtime_profile["submission_path"],
            "image_paths": image_paths,
            "image_roles": image_roles,
            "prompt": prompt.strip(),
            "prompt_character_limit": prompt_limit_policy.maximum_characters,
            "prompt_limit_policy_id": prompt_limit_policy.policy_id,
            "prompt_limit_verification_state": (
                prompt_limit_policy.verification_state
            ),
            "aspect_ratio": runtime_profile["format"]["generation_aspect_ratio"],
            "resolution": cost["resolution"],
            "quality": cost["quality"],
            "estimated_credits": cost["credits_per_image"],
        },
        "postprocess": {
            "delivery_aspect_ratio": runtime_profile["format"]["delivery_aspect_ratio"],
            "crop_mode": runtime_profile["format"]["crop_mode"],
            "safe_zone": runtime_profile["format"]["safe_zone"],
            "target_delivery_pixels": runtime_profile["format"]["target_delivery_pixels"],
        },
        "quality_gate": quality_gate,
    }


def _structured_product_identity(
    product: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    """Read only fields whose schema semantics are product identity.

    ``ProductSpec.description`` is deliberately excluded. It is a transport/UI
    summary and may contain the source photo's table, hand, coaster or other
    capture context. Free-form ``must_preserve`` values are excluded for the
    same reason: they do not distinguish product features from source-scene
    features. If an analysis is supplied but has no usable identity, fail
    closed instead of attempting keyword removal from prose.
    """

    analysis = product.get("product_analysis")
    if analysis is None:
        return None, None
    if not isinstance(analysis, dict):
        raise ValueError(
            f"Product {product['product_id']} product_analysis must be an object"
        )
    identity = analysis.get("identity")
    if not isinstance(identity, dict):
        raise ValueError(
            f"Product {product['product_id']} has no structured identity for prompt compilation"
        )
    for field in ("product", "beverage"):
        value = identity.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip(), identity
    # Some pre-analysis compatibility callers carry only brand evidence. They
    # have no identity prose to leak, so use the source-image-only directive.
    # A partially populated identity (for example container without product)
    # is internally inconsistent and must not be guessed around.
    if identity.get("container") is None:
        return None, None
    raise ValueError(
        f"Product {product['product_id']} has no structured product content identity"
    )


def _structured_source_container_summary(
    product: dict[str, Any],
    identity: dict[str, Any] | None,
) -> str:
    if identity is None:
        return (
            "source-form=read only the exact product container form and material from "
            "the product source"
        )
    container = identity.get("container")
    if not isinstance(container, dict):
        raise ValueError(
            f"Product {product['product_id']} has no structured source container identity"
        )
    values: dict[str, str] = {}
    for field in ("class", "material", "geometry"):
        value = container.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Product {product['product_id']} source container {field} is missing"
            )
        values[field] = _clip(value.strip(), 75)
    raw_components = container.get("components")
    if not isinstance(raw_components, list):
        raise ValueError(
            f"Product {product['product_id']} source container components are missing"
        )
    components = [
        value.strip()
        for value in raw_components
        if isinstance(value, str) and value.strip()
    ]
    component_clause = (
        "; components="
        + _join_limited(components, maximum_items=6, item_characters=50)
        if components
        else ""
    )
    return (
        "source-form={"
        f"class={values['class']}; material={values['material']}; "
        f"geometry={values['geometry']}{component_clause}"
        "}"
    )


def _adopted_container_consumable_summary(product: dict[str, Any]) -> str:
    """Return only content identity when the source vessel must be discarded.

    ProductAnalysis remains intact in the request for audit and QA.  This helper
    narrows only the provider-facing card so source packaging, interaction and
    branding cannot compete with the resolved adopted-container contract.
    """

    primary, _identity = _structured_product_identity(product)
    if primary is None:
        return (
            f"consumable=read only the exact {product['product_kind']} contents from "
            "the product source"
        )
    return f"consumable={_clip(primary, 190)}"


def _product_identity_summary(
    product: dict[str, Any],
    *,
    container_mode: str = "preserve_source",
) -> str:
    if container_mode == "adopt_reference":
        return _adopted_container_consumable_summary(product)

    primary, identity = _structured_product_identity(product)
    if primary is None:
        content = (
            f"content=read only the exact {product['product_kind']} identity from "
            "the product source"
        )
    else:
        content = f"content={_clip(primary, 190)}"
    return f"{content}; {_structured_source_container_summary(product, identity)}"


_UNKNOWN_TARGET_CONTAINER_VALUES = {
    "indeterminate",
    "none",
    "not applicable",
    "not visible",
    "n/a",
    "uncertain",
    "unknown",
    "unresolved",
    "unspecified",
}


def _target_container_structure_value(value: Any, *, field: str) -> str:
    """Return a prompt-safe structural value or fail closed.

    The adopted-container card is deliberately compiled only from the four
    structural container fields in SceneGraphV2. Reference descriptions,
    visible text and brand observations never enter this path.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Adopted target container has no usable {field}")
    normalized = " ".join(value.replace("_", " ").split())
    if normalized.casefold() in _UNKNOWN_TARGET_CONTAINER_VALUES:
        raise ValueError(f"Adopted target container {field} is unknown")
    return _clip(normalized, 70)


def _adopted_target_container_summary(
    scene_graph: dict[str, Any],
    binding: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Resolve the exact target-slot vessel without exposing reference identity."""

    if binding.get("placement_mode") != "replace":
        raise ValueError(
            "adopt_reference requires a replace binding with an observed target container"
        )
    target_slot_id = binding["target_slot_id"]
    target = next(
        (
            item
            for item in scene_graph.get("objects", [])
            if item.get("slot_id") == target_slot_id
        ),
        None,
    )
    if not isinstance(target, dict):
        raise ValueError(
            f"adopt_reference target slot has no observed scene object: {target_slot_id}"
        )
    container = target.get("container")
    if not isinstance(container, dict):
        raise ValueError(
            f"adopt_reference target slot has no compatible container: {target_slot_id}"
        )

    container_class = _target_container_structure_value(
        container.get("class"), field="class"
    )
    material = _target_container_structure_value(
        container.get("material"), field="material"
    )
    silhouette = _target_container_structure_value(
        container.get("silhouette"), field="silhouette"
    )
    raw_components = container.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise ValueError("Adopted target container has no usable components")
    components = [
        _target_container_structure_value(value, field="component")
        for value in raw_components
    ]
    return (
        (
            "adopted-target-container={"
            f"class={container_class}, material={material}, silhouette={silhouette}, "
            f"components={_join_limited(components, maximum_items=6, item_characters=50)}"
            "}"
        ),
        container,
    )


def _authorized_surface_style_contract(product: dict[str, Any]) -> bool:
    """Recognize only an explicit, permission-bearing exterior style contract."""

    policy = product.get("container_policy")
    if not isinstance(policy, dict):
        return False
    contract = policy.get("surface_style_contract")
    if not isinstance(contract, dict):
        return False
    permissions = contract.get("transfer_permissions")
    return (
        contract.get("authorization_state") == "authorized"
        and isinstance(permissions, list)
        and any(isinstance(value, str) and value.strip() for value in permissions)
    )


def _opaque_adopted_container_boundary(
    product: dict[str, Any],
    container: dict[str, Any],
) -> str:
    material = str(container.get("material") or "").casefold()
    ceramic_markers = ("ceramic", "porcelain", "stoneware", "earthenware")
    transparency_markers = ("clear", "transparent", "translucent")
    if not any(value in material for value in ceramic_markers) or any(
        value in material for value in transparency_markers
    ):
        return ""
    common = (
        "content-boundary=confine all liquid, toppings, drink color, layers and "
        "marbling to the inner cavity; only physically protruding contents may rise "
        "above the rim; keep the target container exterior fully opaque"
    )
    if _authorized_surface_style_contract(product):
        return (
            common
            + "; exterior styling may use only attributes explicitly permitted by the "
            "authorized surface-style contract, with no inferred drink texture or drips"
        )
    return (
        common
        + "; no drink texture, color gradient, marbling, translucency or drips may appear "
        "on the exterior; no authorized surface-style contract is active"
    )


def _target_support_surface_summary(
    scene_graph: dict[str, Any],
    support_surface_id: Any,
) -> str:
    if not isinstance(support_surface_id, str) or not support_surface_id.strip():
        raise ValueError("An active target slot has no support_surface_id")
    support = next(
        (
            item
            for item in scene_graph.get("support_surfaces", [])
            if item.get("surface_id") == support_surface_id
        ),
        None,
    )
    if not isinstance(support, dict):
        raise ValueError(
            f"Active target support surface is missing from the scene graph: {support_surface_id}"
        )
    kind = support.get("kind")
    description = support.get("plane_description") or support.get("description")
    details = []
    if isinstance(kind, str) and kind.strip():
        details.append(f"kind={_clip(kind.strip(), 45)}")
    if isinstance(description, str) and description.strip():
        details.append(f"surface={_clip(description.strip(), 100)}")
    suffix = f"({', '.join(details)})" if details else ""
    return f"{support_surface_id}{suffix}"


def _target_brand_directive(product: dict[str, Any]) -> str:
    contract = product.get("target_brand_contract")
    if not isinstance(contract, dict):
        return "target is unbranded; render no text, logo, label, symbol or pseudo-brand"

    # The sibling brand_transfer_resolution records why a decision was made, but
    # it is never prompt authority. Only these final target fields are read.
    state = _target_brand_state(contract)
    if state in {"uncertain", "unknown", "unresolved"}:
        raise ValueError(
            f"Product {product['product_id']} target brand contract is unresolved"
        )
    main_text = contract.get("allowed_main_text")
    allowed_text = [
        value.strip()
        for value in [main_text]
        if isinstance(value, str) and value.strip()
    ]
    if state != "verified_present":
        return "target is unbranded; render no text, logo, label, symbol or pseudo-brand"
    if not allowed_text:
        return (
            "target has a verified non-text brand state but no allowed text; preserve only "
            "the resolved target mark and invent no readable or decorative text"
        )
    rendered = f'"{_clip(allowed_text[0], 70)}"'
    return (
        f"render only exact target text {rendered}; preserve spelling and punctuation; "
        "add no other brand-like mark"
    )


def _format_bbox(box: dict[str, Any]) -> str:
    return (
        f"({box['left']:.2f},{box['top']:.2f},"
        f"{box['right']:.2f},{box['bottom']:.2f})"
    )


def _multi_scene_summary(
    scene_graph: dict[str, Any],
    *,
    include_camera: bool = True,
) -> str:
    composition = scene_graph["composition"]
    depth = scene_graph["depth"]
    taxonomy = scene_graph["taxonomy"]
    camera_clause = (
        f"shot={composition['shot_type']}; camera={composition['camera_height']}/"
        f"{_clip(composition['camera_pitch'], 45)}/{composition['lens_character']}; "
        if include_camera
        else "topology-only; camera comes exclusively from the photographic style contract; "
    )
    return (
        camera_clause
        + f"subject={_clip(composition['subject_position'], 80)}; "
        f"negative-space={_clip(composition['negative_space'], 90)}; "
        f"depth={_clip(depth['foreground'], 55)} > {_clip(depth['product_plane'], 70)} > "
        f"{_clip(depth['midground'], 55)} > {_clip(depth['background'], 65)}; "
        f"environment={taxonomy['environment_family']}."
    )


def _multi_lighting_summary(
    scene_graph: dict[str, Any],
    lighting_sheet: dict[str, Any] | None,
    resolved_lighting_contract: dict[str, Any] | None = None,
) -> str:
    if resolved_lighting_contract is not None:
        signature = resolved_lighting_contract.get("signature", {})
        return (
            f"effective={resolved_lighting_contract.get('effective_lighting_id', 'resolved')}; "
            f"family={resolved_lighting_contract.get('family', 'resolved')}; "
            f"direction={signature.get('direction_degrees', 'resolved')}deg; "
            f"elevation={signature.get('elevation_degrees', 'resolved')}deg; "
            f"hardness={signature.get('hardness', 'resolved')}; "
            f"shadow-density={signature.get('shadow_density', 'resolved')}; "
            f"EV={signature.get('exposure_ev', 'resolved')}; "
            f"WB={signature.get('white_balance_mired', 'resolved')}mired."
        )
    if lighting_sheet is not None:
        key = lighting_sheet.get("key_light", {})
        shadow = lighting_sheet.get("shadow_contract", {})
        capture = lighting_sheet.get("capture_contract", {})
        source_size = (
            key.get("source_size")
            or key.get("relative_size")
            or key.get("angular_size_degrees")
            or "resolved"
        )
        hardness = (
            key.get("hardness")
            or shadow.get("edge")
            or "resolved"
        )
        return (
            f"sheet={lighting_sheet.get('lighting_sheet_id', 'resolved')}; "
            f"source={_clip(str(key.get('source_type', key.get('source', 'resolved'))), 55)}; "
            f"direction={_clip(str(key.get('direction', 'resolved')), 65)}; "
            f"size={_clip(str(source_size), 55)}; "
            f"hardness={_clip(str(hardness), 55)}; "
            f"shadow-density={_clip(str(shadow.get('density', 'resolved')), 45)}; "
            f"WB={_clip(str(capture.get('white_balance', 'resolved')), 45)}."
        )
    lighting = scene_graph["lighting"]
    return (
        f"source={lighting['source_type']}; direction={_clip(lighting['direction'], 70)}; "
        f"size={lighting['source_size']}; hardness={lighting['hardness']}; "
        f"shadow={_clip(lighting['shadow'], 100)}; WB={lighting['white_balance']}."
    )


def _wood_material_summary(wood_material_profile: dict[str, Any] | None) -> str:
    if not isinstance(wood_material_profile, dict):
        return "No wood material contract is active."
    axes = wood_material_profile.get("family_axes")
    axes = axes if isinstance(axes, dict) else wood_material_profile
    appearance = wood_material_profile.get("appearance")
    appearance = appearance if isinstance(appearance, dict) else wood_material_profile
    axis_fields = ("lightness", "color_family", "grain_pattern", "finish")
    appearance_fields = (
        "chroma",
        "grain_direction_degrees",
        "grain_frequency",
        "grain_contrast",
        "surface_occupancy",
    )
    parts = [
        f"{field.replace('_', '-')}={_clip(str(axes[field]), 60)}"
        for field in axis_fields
        if axes.get(field) is not None
    ]
    parts.extend(
        f"{field.replace('_', '-')}={_clip(str(appearance[field]), 60)}"
        for field in appearance_fields
        if appearance.get(field) is not None
    )
    lab_contract = appearance.get("lab")
    lab = (
        lab_contract.get("median")
        if isinstance(lab_contract, dict)
        else wood_material_profile.get("lab_median")
    )
    if lab is not None:
        parts.insert(0, f"Lab={_clip(str(lab), 85)}")
    return (
        "; ".join(parts[:10])
        + ". Material authority covers color, chroma, grain and finish only; it cannot "
        "supply objects, layout, text, branding, shadows or lighting."
    )


def _contract_range(value: Any, unit: str = "") -> str:
    if not isinstance(value, list) or len(value) != 2:
        return "resolved"
    return f"{value[0]}-{value[1]}{unit}"


def _editorial_style_sections(contract: dict[str, Any]) -> str:
    creative = contract["creative_direction"]
    camera = contract["camera_geometry"]
    composition = contract["composition_geometry"]
    variation = contract["composition_variation"]
    support = composition["support_plane"]
    lighting = contract["lighting_geometry"]
    tone = contract["tone_signature"]
    finish = contract["finish_signature"]
    bbox = composition["primary_subject_bbox"]
    luma = tone["luma_percentiles"]
    return f"""[PHOTOGRAPHIC STYLE CONTRACT - PRIMARY AUTHORITY]
Audience={_clip(creative['audience'], 48)}; response={_clip(creative['desired_response'], 55)}; direction={_clip(creative['art_direction'], 58)}; restraint={_clip(creative['restraint'], 42)}.

[CAMERA GEOMETRY - HARD LOCK]
Projection={_clip(camera['projection'], 42)}; focal={_contract_range(camera['focal_length_equivalent_mm'], 'mm-equivalent')}; distance={_contract_range(camera['working_distance_cm'], 'cm')}; height={_contract_range(camera['camera_height_cm'], 'cm')}; pitch={_contract_range(camera['pitch_degrees'], 'deg')}; yaw={_contract_range(camera['yaw_degrees'], 'deg')}; roll={_contract_range(camera['roll_degrees'], 'deg')}; distortion={_clip(camera['distortion'], 43)}; focus={_clip(camera['depth_of_field'], 48)}.

[COMPOSITION GEOMETRY - HARD LOCK]
Slot={_format_bbox(bbox)} adaptive to product aspect; area={_contract_range(composition['primary_subject_area_ratio'])}; negative={_clip(composition['negative_space'], 54)}; support={_clip(support['kind'], 42)}@{_contract_range(support['occupancy_ratio'])}; edges={_clip(str(support['dominant_edge_angles_degrees']), 30)}; perspective={_clip(support['perspective'], 45)}; rhythm={_clip(composition['frame_rhythm'], 48)}; crop={_clip(composition['crop_policy'], 38)}.

[CONTROLLED VARIATION - ANTI-TEMPLATE]
Preserve={_join_limited(variation['invariants'], maximum_items=4, item_characters=25)}; vary={_join_limited(variation['allowed_variations'], maximum_items=4, item_characters=23)}; guard={_clip(variation['repeat_guard'], 65)}. Reference-scene copy is forbidden; similarity<={variation['scene_similarity_limit']}.

[LIGHT ON SCREEN - HARD LOCK]
Source={_clip(lighting['source_topology'], 50)}; az={_contract_range(lighting['azimuth_degrees'], 'deg')}; el={_contract_range(lighting['elevation_degrees'], 'deg')}; size={_contract_range(lighting['angular_size_degrees'], 'deg')}; key:fill={_contract_range(lighting['key_to_fill_ratio'])}; lit={_contract_range(lighting['lit_area_ratio'])}; shadow={_contract_range(lighting['shadow_area_ratio'])}@{_contract_range(lighting['shadow_vector_degrees'], 'deg')}; penumbra={_contract_range(lighting['penumbra_ratio'])}; highlight={_clip(lighting['highlight_behavior'], 52)}; optics={_clip(lighting['optical_effects'], 48)}.

[COLOR, TONE AND FINISH - HARD LOCK]
WB={_contract_range(tone['white_balance_kelvin'], 'K')}; luma05/50/95={_contract_range(luma['p05'])}/{_contract_range(luma['p50'])}/{_contract_range(luma['p95'])}; black={_clip(tone['black_point'], 36)}; white={_clip(tone['white_point'], 36)}; curve={_clip(tone['contrast_curve'], 42)}; saturation={_clip(tone['saturation'], 50)}; shadow={_clip(tone['shadow_color'], 32)}; highlight={_clip(tone['highlight_color'], 32)}; palette={','.join(tone['palette_hex'])}; materials={_clip(tone['material_separation'], 58)}; acuity={_clip(finish['acuity'], 40)}; micro={_clip(finish['microcontrast'], 40)}; depth={_clip(finish['depth_rendering'], 42)}.
""".strip()


def _product_integration_sections(contract: dict[str, Any]) -> str:
    source = contract["source_interpretation"]
    camera = contract["camera_reconciliation"]
    lighting = contract["lighting_reconstruction"]
    contact = contract["support_contact"]
    frequency = contract["image_frequency_match"]
    return f"""[PRODUCT-SCENE INTEGRATION - HARD LOCK]
Inputs are identity evidence, never foreground plates. Preserve={_join_limited(source['preserve'], maximum_items=4, item_characters=23)}. Fully rerender all pixels, boundary, rim/base optics, highlights, refraction, condensation, sharpness and WB; never reuse source boundary or shading.
Camera={_join_limited(camera['required_cues'], maximum_items=3, item_characters=30)}. Light={_join_limited(lighting['required_cues'], maximum_items=3, item_characters=30)}. Contact={_clip(contact['placement'], 48)}; shadow={_clip(contact['contact_shadow'], 45)}; {_clip(contact['accessory_policy'], 55)}. Match edge acuity {_contract_range(frequency['edge_acuity_ratio'])}, contrast {_contract_range(frequency['local_contrast_ratio'])}, halo<={frequency['maximum_halo_px']}px. Brand after geometry/light; glyphs follow curvature. Reject any sticker, pasted cutout, white fringe, floating base or detached shadow.
""".strip()


def validate_control_board_manifest_for_products(
    manifest: dict[str, Any],
    products: list[dict[str, Any]],
) -> None:
    if manifest.get("artifact_type") == "sanitized_photographic_scene_hint":
        # The core binding validator already verifies its exact pixels and
        # sanitation contract. A scene hint is a single borderless artifact,
        # not a technical multi-panel control board.
        return
    panels = manifest.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 4:
        raise ValueError("Control-board manifest requires one to four panels")
    product_by_id = {item["product_id"]: item for item in products}
    container_product_ids: list[str] = []
    wood_seen = False
    wood_count = 0
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("Every control-board panel manifest entry must be an object")
        role = panel.get("role")
        if role == "wood_material":
            wood_seen = True
            wood_count += 1
            continue
        if role != "container_surface":
            raise ValueError(f"Unsupported control-board panel role: {role!r}")
        if wood_seen:
            raise ValueError("Adopted-container panels must precede the wood material panel")
        product_id = panel.get("product_id")
        if not isinstance(product_id, str) or product_id not in product_by_id:
            raise ValueError("Container panel product_id is not in the ordered product set")
        if product_id in container_product_ids:
            raise ValueError("A product may have at most one adopted-container panel")
        if _container_policy_mode(product_by_id[product_id]["container_policy"]) != "adopt_reference":
            raise ValueError("Container panels are forbidden for preserve_source products")
        container_product_ids.append(product_id)
    if wood_count > 1:
        raise ValueError("A control board may contain at most one wood material panel")
    expected_order = [
        item["product_id"]
        for item in products
        if item["product_id"] in set(container_product_ids)
    ]
    if container_product_ids != expected_order:
        raise ValueError("Container panels must follow the ordered ProductSpec sequence")


def build_multi_product_generation_request(
    *,
    preset: dict[str, Any],
    runtime_profile: dict[str, Any],
    products: list[dict[str, Any]] | dict[str, Any],
    scene_graph: dict[str, Any],
    seed: int,
    tier: str = "default",
    unbound_slot_policy: str = "genericize",
    scene_recipe: dict[str, Any] | None = None,
    lighting_sheet: dict[str, Any] | None = None,
    resolved_lighting_contract: dict[str, Any] | None = None,
    wood_material_profile: dict[str, Any] | None = None,
    control_board_image: str | None = None,
    control_board_manifest: dict[str, Any] | None = None,
    photographic_style_contract: dict[str, Any] | None = None,
    product_integration_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a GenerationRequestV3 for one to three exact user products.

    V3 intentionally uses one ordered ``image_inputs`` array. It never emits the
    parallel v2 ``image_paths``/``image_roles`` transport fields.
    """
    if isinstance(products, dict):
        if products.get("schema_version") != PRODUCT_SPEC_SCHEMA_VERSION:
            raise ValueError("Product set must use schema version 3.0.0")
        raw_products = products.get("products")
    else:
        raw_products = products
    product_set = assemble_product_set(raw_products)
    product_values = product_set["products"]
    for product in product_values:
        require_product_spec_generation_ready(product)

    if resolved_lighting_contract is not None and not isinstance(
        resolved_lighting_contract, dict
    ):
        to_dict = getattr(resolved_lighting_contract, "to_dict", None)
        if not callable(to_dict):
            raise ValueError("resolved_lighting_contract must be an object")
        resolved_lighting_contract = to_dict()
    if resolved_lighting_contract is not None:
        signature = resolved_lighting_contract.get("signature")
        required_signature = {
            "direction_degrees",
            "elevation_degrees",
            "hardness",
            "shadow_density",
            "exposure_ev",
            "white_balance_mired",
        }
        if not isinstance(signature, dict) or not required_signature.issubset(signature):
            raise ValueError("resolved_lighting_contract has an incomplete signature")

    if preset["runtime_input_policy"]["reference_usage"] != "offline_feature_extraction_only":
        raise ValueError("Preset must prohibit runtime reference-image use")
    if runtime_profile["reference_policy"]["send_reference_image"] is not False:
        raise ValueError("Runtime profile must prohibit reference-image submission")
    costs = runtime_profile["cost_profiles"]
    if tier not in costs:
        raise ValueError(f"Unknown cost tier: {tier}")
    if (control_board_manifest is None) != (control_board_image is None):
        raise ValueError("A control-board image and its separate manifest are both required")
    if control_board_manifest is not None:
        validate_control_board_manifest_for_products(
            control_board_manifest,
            product_values,
        )

    scene_graph_capabilities = derive_scene_graph_capabilities(scene_graph)
    if not scene_graph_capabilities["scene_generation_eligible"]:
        reasons = ", ".join(scene_graph_capabilities["reason_codes"])
        raise ValueError(f"Scene graph is not eligible for generation: {reasons}")
    bindings = [
        {
            "input_product_id": item["product_id"],
            "target_slot_id": item.get("target_slot_id", "auto"),
            "placement_mode": item.get("placement_mode", "replace"),
            "product_kind": item["product_kind"],
            "cross_kind_replacement": item.get("cross_kind_replacement", False),
        }
        for item in product_values
    ]
    slot_plan = resolve_slot_plan(
        scene_graph,
        bindings,
        unbound_slot_policy=unbound_slot_policy,
        maximum_exact_products=3,
    )
    binding_by_product = {
        item["input_product_id"]: item for item in slot_plan["bindings"]
    }
    object_by_id = {item["slot_id"]: item for item in scene_graph["objects"]}
    for product in product_values:
        binding = binding_by_product[product["product_id"]]
        container_mode = _container_policy_mode(product["container_policy"])
        target_object = (
            object_by_id.get(binding["target_slot_id"])
            if container_mode == "adopt_reference"
            and binding["placement_mode"] == "replace"
            else None
        )
        serving_resolution = resolve_serving_compatibility(
            product_analysis=product.get("product_analysis"),
            product_kind=product["product_kind"],
            description=product.get("description"),
            container_mode=container_mode,
            target_scene_object=target_object,
        )
        product["serving_compatibility_resolution"] = serving_resolution
        if serving_resolution["action"] == "block":
            require_serving_compatibility_ready(
                product["product_id"], serving_resolution
            )
    product_set = assemble_product_set(product_values)

    image_inputs = [
        {
            "role": "product_source",
            "product_id": item["product_id"],
            "path": str(Path(item["source_image"])),
        }
        for item in product_values
    ]
    if control_board_image is not None:
        image_inputs.append(
            {
                "role": "reference_control_board",
                "path": str(Path(control_board_image)),
            }
        )
    if len(image_inputs) > 4:
        raise ValueError("GenerationRequestV3 exceeds the four-image provider limit")

    input_descriptions = [
        f"Image {index}=product_source({item['product_id']})"
        for index, item in enumerate(image_inputs, start=1)
        if item["role"] == "product_source"
    ]
    if image_inputs[-1]["role"] == "reference_control_board":
        input_descriptions.append(
            f"Image {len(image_inputs)}=sanitized reference_control_board"
        )

    cards = []
    for index, product in enumerate(product_values, start=1):
        binding = binding_by_product[product["product_id"]]
        container_mode = _container_policy_mode(product["container_policy"])
        if container_mode == "preserve_source":
            container_directive = (
                "preserve physical container material, construction, silhouette family and real "
                "components while reconstructing every pixel for the target camera and light"
            )
        else:
            adopted_target_container, target_container = _adopted_target_container_summary(
                scene_graph,
                binding,
            )
            opaque_boundary = _opaque_adopted_container_boundary(
                product,
                target_container,
            )
            container_directive = (
                "discard the source container together with its components, accessories, "
                "interaction context and support props; use only the resolved compatible "
                f"adopted-container design; {adopted_target_container}; "
                + (f"{opaque_boundary}; " if opaque_boundary else "")
                + "target_brand_contract is the sole brand authority"
            )
        cards.append(
            f"P{index} {product['product_id']} ({product['product_kind']}, Image {index}) -> "
            f"{binding['target_slot_id']} bbox={_format_bbox(binding['target_bbox'])}: "
            f"{_product_identity_summary(product, container_mode=container_mode)}; "
            f"{serving_prompt_summary(product['serving_compatibility_resolution'])}; "
            f"container={container_directive}; "
            f"brand={_target_brand_directive(product)}."
        )

    active_slot_clauses = []
    binding_by_target = {
        item["target_slot_id"]: item for item in slot_plan["bindings"]
    }
    for slot in slot_plan["active_slots"]:
        binding = binding_by_target.get(slot["slot_id"])
        if binding is not None:
            action = f"exact {binding['input_product_id']}"
        elif slot["action"] == "genericize":
            action = (
                f"new unbranded generic {slot['kind']}"
                f"{_runtime_appearance_clause(slot)}"
            )
        else:
            action = f"abstract {slot['kind']}{_runtime_appearance_clause(slot)}"
        target_support = _target_support_surface_summary(
            scene_graph,
            slot.get("support_surface_id"),
        )
        active_slot_clauses.append(
            f"{slot['slot_id']}={action}@{_format_bbox(slot['target_bbox'])} "
            f"support={target_support}"
        )
    for binding in slot_plan["bindings"]:
        if binding["placement_mode"] == "add":
            zone = next(
                (
                    item
                    for item in scene_graph.get("insertion_zones", [])
                    if item.get("zone_id") == binding["target_slot_id"]
                ),
                None,
            )
            if not isinstance(zone, dict):
                raise ValueError(
                    f"Active insertion target is missing: {binding['target_slot_id']}"
                )
            target_support = _target_support_surface_summary(
                scene_graph,
                zone.get("support_surface_id"),
            )
            active_slot_clauses.append(
                f"{binding['target_slot_id']}=exact {binding['input_product_id']}"
                f"@{_format_bbox(binding['target_bbox'])} support={target_support}"
            )
    relation_clauses = [
        f"{item['from_slot_id']}>{item['predicate']}>{item['to_slot_id']}"
        for item in slot_plan["active_relations"]
    ]
    if control_board_image is not None and photographic_style_contract is not None:
        board_clause = (
            "The sanitized non-identifying control board may supply only abstract camera geometry, "
            "support-plane topology, light map, palette and authorized material patches. Copy no "
            "reference product, text, brand, garnish, prop identity or exact shadow silhouette."
        )
    elif control_board_image is not None:
        board_clause = (
            "The control board is sanitized and non-identifying. Read adopted-container panels only "
            "for resolved geometry and material panels only for color, chroma, grain and finish. "
            "Copy no object, arrangement, text, logo, lighting or shadow from it."
        )
    else:
        board_clause = (
            "No reference pixels are submitted; rebuild the resolved contracts from structured values."
        )
    wood_summary = _wood_material_summary(wood_material_profile)
    if (
        wood_material_profile is None
        and photographic_style_contract is not None
        and "wood" in photographic_style_contract["composition_geometry"]["support_plane"]["kind"].lower()
    ):
        wood_summary = (
            "Wood material is defined by the photographic style contract as a scene support "
            "surface; no separate material-profile override is active."
        )
    recipe_id = scene_recipe.get("recipe_id") if isinstance(scene_recipe, dict) else None
    if photographic_style_contract is not None:
        prompt_header = """[ART-DIRECTED EDITORIAL CAFE PHOTOGRAPH - REFERENCE FIDELITY HARD LOCK]
Create one original editorial cafe photograph for an experienced Tokyo concept-store buyer. Reject smartphone, stock, ecommerce, CGI and reference copying."""
        style_sections = _editorial_style_sections(photographic_style_contract)
        integration_sections = (
            _product_integration_sections(product_integration_contract)
            if product_integration_contract is not None
            else ""
        )
        capture_heading = "EDITORIAL CAPTURE AND MATERIAL SAFETY"
        capture_contract = (
            "Obey style and integration contracts. Create depth through geometry, overlap, scale and "
            "light falloff; reject computational halos, wide-angle looming, generic bokeh and plastic retouching."
        )
    else:
        prompt_header = """[NATURAL SMARTPHONE CAFE PHOTO - MULTI PRODUCT HARD LOCK]
Create one new original ordinary-smartphone cafe photo, casually captured in one exposure. It must not look like staged advertising, a catalog image, CGI, a pasted composite or a copied reference."""
        style_sections = ""
        integration_sections = ""
        capture_heading = "SMARTPHONE PHYSICS AND SAFETY"
        capture_contract = (
            "Use ordinary phone perspective and mostly deep real-world focus. Keep exact products "
            "sharp; show depth through overlap, scale, converging lines and light falloff before "
            "slight far-plane softness. Materials retain believable thickness, reflection, "
            "refraction and texture."
        )
    prompt = f"""{prompt_header} Ordered inputs: {'; '.join(input_descriptions)}.

[COMMON SCENE CONTRACT]
{_multi_scene_summary(scene_graph, include_camera=photographic_style_contract is None)} Recipe={recipe_id or 'resolved scene graph'}. Preserve support topology, depth, crop safety and negative space; the photographic style contract is sole camera authority when present. Rebuild products, contact, occlusion and shadows together; copy no reference product or brand.

    {style_sections}

    {integration_sections}

[PRODUCT CARDS - EXACT USER PRODUCTS]
{' '.join(cards)} Product cards are independent: do not exchange identity, container, topping, texture, color, text or brand between products. Exactly {len(product_values)} user products must remain recognizable.

[ACTIVE LAYOUT ONLY]
Slots={'; '.join(active_slot_clauses) or 'none'}. Relations={'; '.join(relation_clauses) or 'none'}. Generic count={slot_plan['generic_companion_count']}; every generic is newly invented and completely unbranded. Removed source slots and their relations are inactive and must not reappear. Keep frame margin at least 0.06 and generic occlusion at most 0.20.

[LIGHTING AND MATERIAL]
Lighting={_multi_lighting_summary(scene_graph, lighting_sheet, resolved_lighting_contract)} Use one physically consistent source, exposure and white balance across every subject. Wood={wood_summary} {board_clause}

[{capture_heading}]
{capture_contract} Add no unverified text, logo or watermark. Reject floating edges, malformed hands, uniform blur or conflicting shadows.

[FINAL GATE]
Return only when exact ID/count, slot, size, support, relation, brand, target-camera optics, attached contact, edge-frequency, material and single-source light agree. Pasted foreground, missing measurement or uncertainty cannot pass.
""".strip()

    forbidden_language = runtime_profile["language_policy"]["forbidden"]
    found = [term for term in forbidden_language if term.lower() in prompt.lower()]
    if found:
        raise ValueError(f"Forbidden prompt language present: {found}")
    prompt_limit_policy = resolve_prompt_limit_policy(
        provider=runtime_profile.get("provider"),
        model=runtime_profile.get("model"),
    )
    if len(prompt) > prompt_limit_policy.maximum_characters:
        raise ValueError(
            f"Compiled multi-product prompt has {len(prompt)} characters; "
            f"limit is {prompt_limit_policy.maximum_characters} "
            f"({prompt_limit_policy.policy_id})"
        )

    quality_gate = copy.deepcopy(runtime_profile["quality_gate"])
    for failure in (
        "exact product ID or count differs from the resolved product set",
        "a product is missing or placed outside its resolved target slot",
        "active support, depth, occlusion or relation contradicts the slot plan",
        "a generic companion carries branding or copied product identity",
        "output branding contradicts a target_brand_contract",
        "output serving temperature, ice, straw, toppings or vessel service style contradicts the resolved serving contract",
        "material control-board content leaked into objects, layout, text, light or shadow",
    ):
        if failure not in quality_gate["hard_fail"]:
            quality_gate["hard_fail"].append(failure)
    if product_integration_contract is not None:
        for failure in product_integration_contract["qa_contract"]["hard_fail"]:
            if failure not in quality_gate["hard_fail"]:
                quality_gate["hard_fail"].append(failure)
    cost = costs[tier]
    return {
        "schema_version": GENERATION_REQUEST_V3_SCHEMA_VERSION,
        "prompt_compiler_version": MULTI_PROMPT_COMPILER_VERSION,
        "preset_id": preset["preset_id"],
        "scene_recipe_id": recipe_id,
        "seed": seed,
        "product_set": product_set,
        "products": copy.deepcopy(product_values),
        "scene_graph_contract": {
            "asset_id": scene_graph["asset"]["asset_id"],
            "schema_version": scene_graph["schema_version"],
            "taxonomy": copy.deepcopy(scene_graph["taxonomy"]),
            "slot_plan": copy.deepcopy(slot_plan),
            "active_slots": copy.deepcopy(slot_plan["active_slots"]),
            "relations": copy.deepcopy(slot_plan["active_relations"]),
            "runtime_capabilities": {
                **copy.deepcopy(scene_graph_capabilities),
                "maximum_exact_products": 3,
            },
            # A reviewed derivative control board is not a submission of raw
            # reference pixels. This safety flag remains false by schema.
            "runtime_reference_pixels_submitted": False,
        },
        "wood_material_profile": copy.deepcopy(wood_material_profile),
        "resolved_lighting_contract": copy.deepcopy(resolved_lighting_contract),
        "photographic_style_contract": copy.deepcopy(photographic_style_contract),
        "product_integration_contract": copy.deepcopy(product_integration_contract),
        "reference_control_board_manifest": copy.deepcopy(control_board_manifest),
        "generation": {
            "provider": runtime_profile["provider"],
            "job_type": runtime_profile["model"],
            "submission_path": runtime_profile["submission_path"],
            "image_inputs": image_inputs,
            "prompt": prompt,
            "prompt_character_limit": prompt_limit_policy.maximum_characters,
            "prompt_limit_policy_id": prompt_limit_policy.policy_id,
            "prompt_limit_verification_state": (
                prompt_limit_policy.verification_state
            ),
            "aspect_ratio": runtime_profile["format"]["generation_aspect_ratio"],
            "resolution": cost["resolution"],
            "quality": cost["quality"],
            "estimated_credits": cost["credits_per_image"],
        },
        "postprocess": {
            "delivery_aspect_ratio": runtime_profile["format"]["delivery_aspect_ratio"],
            "crop_mode": runtime_profile["format"]["crop_mode"],
            "safe_zone": runtime_profile["format"]["safe_zone"],
            "target_delivery_pixels": runtime_profile["format"]["target_delivery_pixels"],
        },
        "quality_gate": quality_gate,
    }


def build_identity_repair_request(
    *,
    runtime_profile: dict[str, Any],
    generated_image: str,
    original_product_image: str,
    logo_text: str | None,
    failed_details: list[str],
    failed_checks: list[str] | None = None,
    container_mode: str = "preserve_source",
    brand_asset_image: str | None = None,
) -> dict[str, Any]:
    repair = runtime_profile["retry_policy"]["identity_repair"]
    failures = "; ".join(failed_details)
    failed_check_set = set(failed_checks or [])
    container_lock = (
        "Preserve the adopted reference-derived cup construction already visible in Image 1; do not restore the original container from Image 2."
        if container_mode == "adopt_reference"
        else "Preserve the same source container construction."
    )
    image_paths = [str(Path(generated_image)), str(Path(original_product_image))]
    image_roles = ["generated_scene", "product_source"]
    if brand_asset_image:
        image_paths.append(str(Path(brand_asset_image)))
        image_roles.append("brand_asset")
    brand_asset_instruction = (
        f" Image {len(image_paths)} is the exact source-brand asset."
        if brand_asset_image
        else ""
    )
    protected_scene_parts = ["composition", "wall", "crop", "cup position", "drink texture"]
    if "wrist_exposure" not in failed_check_set:
        protected_scene_parts.append("hand and wrist geometry")
    if not failed_check_set.intersection(
        {"contact_shadow", "cast_shadow", "transmitted_light", "lighting_physical_consistency"}
    ):
        protected_scene_parts.extend(["sunlight", "shadow", "exposure"])
    protected_text = ", ".join(protected_scene_parts)
    logo_instruction = (
        f'The main visible brand text must read exactly "{logo_text}". Preserve its lowercase letter order and punctuation character by character. Do not infer, autocomplete, or add smaller text.'
        if logo_text
        else "Preserve the source brand mark without inventing or autocompleting unreadable text."
    )
    prompt = f"""Image 1 is the newly generated target photograph. Image 2 is the original user product identity source.{brand_asset_instruction} Correct only these failed identity details: {failures}.
Keep Image 1 {protected_text}, smartphone perspective, and every unrelated detail unchanged. Any requested wrist or shadow correction is limited to the failed region and must remain physically connected.
{container_lock}
{logo_instruction}
Use Image 2 only to verify product identity. Do not copy its background, hand pose, lighting, crop, or surrounding objects. Return the same new natural first-person smartphone scene with only the failed product details corrected."""
    return {
        "schema_version": "2.0.0",
        "repair_type": "conditional_product_identity",
        "identity_policy": {
            "beverage": "preserve_source",
            "container": container_mode,
            "branding": "preserve_source_exact",
        },
        "failed_checks": sorted(failed_check_set),
        "generation": {
            "provider": runtime_profile["provider"],
            "job_type": runtime_profile["model"],
            "submission_path": runtime_profile["submission_path"],
            "image_paths": image_paths,
            "image_roles": image_roles,
            "prompt": prompt,
            "aspect_ratio": runtime_profile["format"]["generation_aspect_ratio"],
            "resolution": repair["resolution"],
            "quality": repair["quality"],
            "estimated_credits": repair["credits"],
        },
        "maximum_attempts": repair["maximum_attempts"],
    }
