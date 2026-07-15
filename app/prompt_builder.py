"""
공통 기본 프롬프트(제품 레퍼런스) + 구도 + 배경 + 강도 + 품질/금지를
순서대로 동적 결합. 12조합을 하드코딩x
"""
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config
from presets.compositions import COMPOSITION_PROMPTS
from presets.backgrounds import BACKGROUND_PROMPTS
from presets.quality_rules import PRESERVATION_RULES, QUALITY_RULES, STRENGTH_RULES
from presets.category_prompts import CATEGORY_PROMPTS


def _load_style_sheet(background_style: str, composition: str) -> str:
    path = os.path.join(config.BASE_DIR, "presets", "style_sheets.json")
    if not os.path.exists(path):
        return ""

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sheet = data.get(background_style, {}).get(composition)
        if not sheet:
            return ""

        parts = [
            "Use this category mood and lighting sheet as the dominant visual direction.",
            sheet.get("one_sentence_direction", ""),
            sheet.get("composition_force_prompt", ""),
            sheet.get("instagram_style_prompt", ""),
        ]

        camera = sheet.get("camera", {})
        lighting = sheet.get("lighting", {})
        background = sheet.get("background", {})
        color = sheet.get("color_grade", {})

        parts.append("Camera: " + "; ".join(str(v) for v in camera.values() if v))
        parts.append("Lighting: " + "; ".join(str(v) for v in lighting.values() if v))
        parts.append("Background: " + "; ".join(str(v) for v in background.values() if v))
        parts.append("Color grade: " + "; ".join(str(v) for v in color.values() if v and not isinstance(v, list)))

        palette = color.get("palette")
        if palette:
            parts.append("Palette: " + ", ".join(palette))

        avoid = sheet.get("avoid")
        if avoid:
            parts.append("Avoid these reference-style failures: " + ", ".join(avoid))

        return " ".join(x for x in parts if x)
    except Exception:
        return ""


def _medium_background_override(background_style: str, composition: str) -> str:
    if composition != "medium":
        return ""

    if background_style == "vivid":
        return (
            "MEDIUM BACKGROUND OVERRIDE FOR VIVID: This must be a colorful studio set, not a cafe. "
            "Use bold saturated paper backdrops, colorful geometric blocks, acrylic props, graphic surfaces, "
            "clean hard-edged shadows, and playful editorial Instagram styling. "
            "Dominant colors should include coral, teal, yellow, orange, pink, or cobalt. "
            "Do not use wood table, cafe window, brown wall, warm cafe interior, marble white studio, or plain white background."
        )

    if background_style == "wood":
        return (
            "MEDIUM BACKGROUND OVERRIDE FOR WOOD: This must be a warm cafe/wood lifestyle scene. "
            "Use natural wooden table, warm brown tones, cafe interior depth, soft window light, linen, ceramic dish, "
            "coffee beans, spoon, tray, or subtle cafe props. "
            "Do not use colorful paper blocks, vivid studio set, blank white studio, acrylic geometric props, or minimal white background."
        )

    if background_style == "white":
        return (
            "MEDIUM BACKGROUND OVERRIDE FOR WHITE: This must be a bright minimal white studio scene, not a cafe. "
            "Use white, ivory, pale gray, marble or matte acrylic surfaces, soft fabric, delicate props, clean negative space, "
            "soft diffused editorial lighting and gentle gray shadows. "
            "Do not use wood table, brown cafe interior, colorful blocks, saturated vivid backdrop, or warm cafe window scene."
        )

    return ""

def build_prompt(composition: str, background_style: str,
                 strength: str = "medium") -> str:
    """
    Args:
        composition: closeup / medium / aerial / handheld
        background_style: vivid / wood / white
        strength: low / medium / high

    Returns:
        결합된 편집 프롬프트(영어)
    """
    if composition not in COMPOSITION_PROMPTS:
        raise config.PipelineError(
            config.ErrorCode.UNSUPPORTED_COMPOSITION,
            f"composition '{composition}' not in {list(COMPOSITION_PROMPTS)}",
        )
    if background_style not in BACKGROUND_PROMPTS:
        raise config.PipelineError(
            config.ErrorCode.UNSUPPORTED_BACKGROUND_STYLE,
            f"background_style '{background_style}' not in {list(BACKGROUND_PROMPTS)}",
        )
    if strength not in STRENGTH_RULES:
        raise config.PipelineError(
            config.ErrorCode.UNSUPPORTED_STRENGTH,
            f"strength '{strength}' not in {list(STRENGTH_RULES)}",
        )

    style_sheet = _load_style_sheet(background_style, composition)
    category_prompt = CATEGORY_PROMPTS.get((composition, background_style), "")

    parts = [
        "The category-specific prompt has the highest priority. The output must clearly match BOTH the selected composition and selected background style.",
        category_prompt,
        PRESERVATION_RULES,
        "HARD PRODUCT RULE: The beverage is in an open transparent glass. Never add a plastic lid, dome lid, takeaway lid, sealed cap, cover, rim band, or disposable cup top. Keep the open glass rim and exposed topping visible.",
        "Preserve the user's beverage identity, but do not weaken the category composition or background style.",
        style_sheet,
        STRENGTH_RULES[strength],
        QUALITY_RULES,
        "FINAL CHECK: the result must be immediately distinguishable from the other 11 categories.",
        category_prompt,
    ]
    return " ".join(parts)


def build_background_only_prompt(background_style: str, composition: str) -> str:
    bg = BACKGROUND_PROMPTS[background_style]
    comp = COMPOSITION_PROMPTS[composition]
    return (
        "Create a clean, empty professional product-photography scene with no product in it, "
        "ready for a beverage to be placed later. " + bg + " " + comp +
        " Leave a natural empty spot on the surface where a single drink would stand. "
        "Photorealistic, no product, no cup, no glass."
    )
