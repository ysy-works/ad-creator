from __future__ import annotations

import re
import unicodedata
from typing import Any

from .reference_library import derive_reference_capabilities


ENVIRONMENT_FAMILIES = {
    "white_neutral",
    "warm_wood",
    "point_color",
    "modern_mineral",
    "vintage_warm",
    "dark_moody",
    "mixed_other",
}
LIGHTING_FAMILIES = {
    "direct_sun",
    "soft_window",
    "overcast",
    "warm_ambient",
    "mixed",
}
CAMERA_ANGLES = {"eye_level", "slightly_above", "high_angle", "overhead"}
CAPTURE_STYLES = {"held_product", "tabletop", "closeup", "group", "overflow"}


def frontend_mood_for_taxonomy(taxonomy: dict[str, Any]) -> str:
    if (
        taxonomy["environment_family"] == "point_color"
        or float(taxonomy["accent_color_prominence"]) >= 0.55
    ):
        return "point_color"
    if (
        taxonomy["environment_family"] in {"warm_wood", "vintage_warm"}
        and float(taxonomy["wood_prominence"]) >= 0.55
    ):
        return "wood"
    return "white"


def _normalized_text(*values: Any) -> str:
    flattened: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            flattened.extend(str(item) for item in value)
        elif value is not None:
            flattened.append(str(value))
    return unicodedata.normalize("NFKC", " ".join(flattened)).lower()


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _camera_angle(reference: dict[str, Any]) -> str:
    composition = reference["composition"]
    height = composition["camera_height"]
    shot_type = composition["shot_type"]
    if height == "overhead" or shot_type == "overhead":
        return "overhead"
    if height in {"high"}:
        return "high_angle"
    if height == "slightly_above":
        return "slightly_above"
    return "eye_level"


def _capture_style(reference: dict[str, Any], *, multiple_products: bool) -> str:
    shot_type = reference["composition"]["shot_type"]
    interaction = reference["subject"]["interaction"]
    if shot_type == "overflow":
        return "overflow"
    if shot_type == "group" or multiple_products:
        return "group"
    if shot_type == "handheld" or interaction in {"held", "touching"}:
        return "held_product"
    if shot_type == "closeup":
        return "closeup"
    return "tabletop"


def _lighting_family(reference: dict[str, Any]) -> str:
    source = reference["lighting"]["source_type"]
    return {
        "direct_sun": "direct_sun",
        "soft_window": "soft_window",
        "overcast": "overcast",
        "artificial_warm": "warm_ambient",
        "mixed": "mixed",
        "unknown": "mixed",
    }[source]


def derive_reference_taxonomy(
    reference: dict[str, Any],
    inventory_asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive independent discovery axes while retaining the legacy UI mapping."""
    asset = inventory_asset or {}
    path_text = _normalized_text(
        reference.get("asset", {}).get("relative_path"),
        asset.get("relative_path"),
        asset.get("source_folder_tags"),
    )
    facets = reference["facets"]
    semantic_text = _normalized_text(
        facets["environment_tags"],
        facets["material_tags"],
        facets["mood_tags"],
        facets["shot_tags"],
        reference["subject"]["primary_subject"],
    )
    combined = f"{path_text} {semantic_text}"
    color = reference["color"]

    explicit_wood_folder = _contains(path_text, "우드", "wood")
    semantic_wood = _contains(semantic_text, "wood", "timber", "oak", "walnut")
    wood_prominence = 0.0
    if semantic_wood:
        wood_prominence = 0.34
    if explicit_wood_folder and semantic_wood:
        wood_prominence = 0.68
    elif explicit_wood_folder:
        wood_prominence = 0.56
    if _contains(semantic_text, "wooden table", "wood tabletop", "wood-paneled"):
        wood_prominence = max(wood_prominence, 0.72)

    explicit_point_folder = _contains(path_text, "포인트컬러", "point color")
    accent_prominence = 0.0
    if explicit_point_folder:
        accent_prominence = 0.74
    elif color["mean_saturation"] >= 0.24:
        accent_prominence = 0.56
    elif color["mean_saturation"] >= 0.17:
        accent_prominence = 0.30

    if _contains(path_text, "빈티지", "vintage") or _contains(
        semantic_text, "vintage", "retro", "antique"
    ):
        environment_family = "vintage_warm"
    elif explicit_point_folder or accent_prominence >= 0.55:
        environment_family = "point_color"
    elif explicit_wood_folder and wood_prominence >= 0.55:
        environment_family = "warm_wood"
    elif _contains(path_text, "모던", "금속", "modern", "metal") or _contains(
        semantic_text,
        "stainless",
        "brushed steel",
        "chrome",
        "concrete",
        "stone",
        "mineral",
    ):
        environment_family = "modern_mineral"
    elif color["mean_luminance"] <= 0.34:
        environment_family = "dark_moody"
    elif _contains(path_text, "화이트", "white", "neutral") or (
        color["mean_luminance"] >= 0.50 and color["mean_saturation"] <= 0.18
    ):
        environment_family = "white_neutral"
    else:
        environment_family = "mixed_other"

    material_tags = [str(value).strip().lower() for value in facets["material_tags"]]
    surface_priority = (
        "wood",
        "concrete",
        "stone",
        "steel",
        "metal",
        "glass",
        "ceramic",
        "plaster",
        "stucco",
        "fabric",
    )
    dominant_surface = next(
        (
            material
            for token in surface_priority
            for material in material_tags
            if token in material
        ),
        material_tags[0] if material_tags else "unknown surface",
    )

    capabilities = derive_reference_capabilities(reference)
    multiple_products = capabilities["multiple_primary_products"] or bool(
        re.search(r"\b(pair|two|three|multiple|assorted|group)\b", combined)
    )
    capture_style = _capture_style(
        reference,
        multiple_products=multiple_products,
    )
    scene_complexity = "pair" if multiple_products else "solo"
    if capture_style in {"group", "overflow"} and _contains(
        combined, "three", "four", "five", "six", "seven", "assorted", "multiple"
    ):
        scene_complexity = "set"

    frontend_mood = frontend_mood_for_taxonomy(
        {
            "environment_family": environment_family,
            "wood_prominence": wood_prominence,
            "accent_color_prominence": accent_prominence,
        }
    )

    folder_evidence = any(
        _contains(path_text, token)
        for token in ("화이트", "우드", "포인트컬러", "빈티지", "모던", "white", "wood")
    )
    return {
        "environment_family": environment_family,
        "lighting_family": _lighting_family(reference),
        "camera_angle": _camera_angle(reference),
        "capture_style": capture_style,
        "scene_complexity": scene_complexity,
        "dominant_surface": dominant_surface,
        "wood_prominence": round(wood_prominence, 2),
        "accent_color_prominence": round(accent_prominence, 2),
        "frontend_mood": frontend_mood,
        "frontend_angle": _camera_angle(reference),
        "confidence": 0.84 if folder_evidence else 0.68,
    }


def derive_inventory_taxonomy(asset: dict[str, Any]) -> dict[str, Any]:
    """Provide a low-confidence local index before semantic image analysis."""
    path_text = _normalized_text(
        asset.get("relative_path"),
        asset.get("source_folder_tags"),
    )
    metrics = asset["local_color_metrics"]
    wood = 0.56 if _contains(path_text, "우드", "wood") else 0.0
    accent = 0.74 if _contains(path_text, "포인트컬러", "point color") else 0.0
    if _contains(path_text, "빈티지", "vintage"):
        environment = "vintage_warm"
    elif accent >= 0.55:
        environment = "point_color"
    elif wood >= 0.55:
        environment = "warm_wood"
    elif _contains(path_text, "모던", "금속", "modern", "metal"):
        environment = "modern_mineral"
    elif metrics["mean_luminance"] <= 0.30:
        environment = "dark_moody"
    elif _contains(path_text, "화이트", "white", "neutral") or (
        metrics["mean_luminance"] >= 0.50 and metrics["mean_saturation"] <= 0.18
    ):
        environment = "white_neutral"
    else:
        environment = "mixed_other"

    if _contains(path_text, "착샷", "held"):
        capture_style = "held_product"
        angle = "eye_level"
    elif _contains(path_text, "떼샷", "group"):
        capture_style = "group"
        angle = "slightly_above"
    elif _contains(path_text, "클로즈업", "closeup", "close-up"):
        capture_style = "closeup"
        angle = "slightly_above"
    elif _contains(path_text, "오버플로우", "overflow"):
        capture_style = "overflow"
        angle = "high_angle"
    elif _contains(path_text, "탑뷰", "top view", "overhead"):
        capture_style = "tabletop"
        angle = "overhead"
    else:
        capture_style = "tabletop"
        angle = "slightly_above"

    frontend_mood = (
        "point_color"
        if environment == "point_color"
        else "wood"
        if environment in {"warm_wood", "vintage_warm"} and wood >= 0.55
        else "white"
    )
    return {
        "environment_family": environment,
        "lighting_family": "mixed",
        "camera_angle": angle,
        "capture_style": capture_style,
        "scene_complexity": (
            "set" if capture_style == "overflow" else "pair" if capture_style == "group" else "solo"
        ),
        "dominant_surface": "wood" if wood >= 0.55 else "unknown surface",
        "wood_prominence": wood,
        "accent_color_prominence": accent,
        "frontend_mood": frontend_mood,
        "frontend_angle": angle,
        "confidence": 0.45,
    }


def validate_taxonomy_axes(taxonomy: dict[str, Any]) -> None:
    if taxonomy["environment_family"] not in ENVIRONMENT_FAMILIES:
        raise ValueError("Unknown environment family")
    if taxonomy["lighting_family"] not in LIGHTING_FAMILIES:
        raise ValueError("Unknown lighting family")
    if taxonomy["camera_angle"] not in CAMERA_ANGLES:
        raise ValueError("Unknown camera angle")
    if taxonomy["capture_style"] not in CAPTURE_STYLES:
        raise ValueError("Unknown capture style")
    if taxonomy["scene_complexity"] not in {"solo", "pair", "set"}:
        raise ValueError("Unknown scene complexity")
    for key in ("wood_prominence", "accent_color_prominence", "confidence"):
        if not 0 <= float(taxonomy[key]) <= 1:
            raise ValueError(f"Taxonomy {key} must be normalized")
