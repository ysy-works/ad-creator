import base64
import json
import mimetypes
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "templates_lib"
OUT_PATH = ROOT / "presets" / "style_sheets.json"

STYLE_MAP = {
    "neutral_white_minimal": "white",
    "vivid_color": "vivid",
    "wood": "wood",
}

COMPOSITION_MAP = {
    "aerial_shot": "aerial",
    "handheld_lifestyle": "handheld",
    "product_center": "medium",
    "product_large": "closeup",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGES_PER_CATEGORY = int(os.environ.get("MAX_TEMPLATE_IMAGES", "8"))


def image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"


def category_images(folder: Path) -> list[Path]:
    imgs = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    imgs.sort()
    return imgs[:MAX_IMAGES_PER_CATEGORY]


def analyze_category(client: OpenAI, model: str, image_paths: list[Path], bg_key: str, comp_key: str) -> dict:
    prompt = f"""
You are analyzing multiple Instagram-style beverage reference photos from ONE category.

Return ONLY valid JSON. No markdown.

Your job:
- Find the visual elements that are COMMON or strongly repeated across the reference images.
- Ignore one-off details that appear in only one image.
- Build a reusable mood/lighting/composition sheet for generating new beverage product photos.
- Do NOT describe a specific drink as the target product.
- Do NOT tell the generation model to copy props exactly.
- Focus on repeatable style: camera, composition, lighting, background, surface, props density,
  color palette, shadows, depth of field, Instagram/product-photo mood.

Category:
- background_style: {bg_key}
- composition: {comp_key}

Important:
The final prompt will be used with a user's own beverage product image. The user's product must remain the subject.
The reference style sheet should only control background, lighting, camera mood, surface, props, color grade and atmosphere.

Return this JSON schema:
{{
  "background_style": "{bg_key}",
  "composition": "{comp_key}",
  "reference_count": {len(image_paths)},
  "mood_name": "short English name",
  "common_elements": ["repeated visual element", "..."],
  "discard_as_one_off": ["specific detail to avoid copying", "..."],
  "one_sentence_direction": "one concise sentence that captures the category mood",
  "camera": {{
    "angle": "common camera angle and viewpoint",
    "framing": "how large the product should appear and where it sits",
    "lens_feel": "lens/compression feel",
    "depth_of_field": "common focus/background blur behavior"
  }},
  "lighting": {{
    "quality": "soft/hard/diffused/direct etc",
    "direction": "where light usually comes from",
    "contrast": "contrast level",
    "shadow": "shadow softness and placement",
    "highlight": "highlight/reflection behavior"
  }},
  "background": {{
    "surface": "common table/surface material",
    "environment": "common setting",
    "props": "common prop style and density",
    "negative_space": "how empty or busy the scene is"
  }},
  "color_grade": {{
    "palette": ["color 1", "color 2", "color 3", "color 4"],
    "temperature": "warm/cool/neutral",
    "saturation": "low/medium/high",
    "contrast": "low/medium/high"
  }},
  "instagram_style_prompt": "detailed reusable prompt phrase based only on common category traits",
  "composition_force_prompt": "strong phrase that makes this composition visually distinct from other categories",
  "avoid": ["failure to avoid", "..."]
}}
"""

    content = [{"type": "input_text", "text": prompt}]
    for img in image_paths:
        content.append({"type": "input_image", "image_url": image_data_url(img)})

    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
    )

    text = resp.output_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print("\n[parse failed] raw response:\n", text, file=sys.stderr)
        raise


def main():
    load_dotenv(ROOT / ".env")
    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    if not TEMPLATE_ROOT.exists():
        raise SystemExit(f"templates_lib not found: {TEMPLATE_ROOT}")

    result = {}
    for style_dir in sorted(TEMPLATE_ROOT.iterdir()):
        if not style_dir.is_dir() or style_dir.name not in STYLE_MAP:
            continue

        bg_key = STYLE_MAP[style_dir.name]
        result.setdefault(bg_key, {})

        for comp_dir in sorted(style_dir.iterdir()):
            if not comp_dir.is_dir() or comp_dir.name not in COMPOSITION_MAP:
                continue

            comp_key = COMPOSITION_MAP[comp_dir.name]
            imgs = category_images(comp_dir)
            if not imgs:
                print(f"[skip] no images: {comp_dir}")
                continue

            print(f"[analyze] {bg_key}/{comp_key}: {len(imgs)} images")
            for img in imgs:
                print(f"  - {img.name}")

            result[bg_key][comp_key] = analyze_category(client, model, imgs, bg_key, comp_key)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
