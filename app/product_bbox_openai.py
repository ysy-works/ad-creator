import base64
import json
import mimetypes
import os
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _image_data_url(image: Image.Image) -> str:
    buf = BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=90)
    data = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{data}"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def detect_product_bbox(image: Image.Image, expand: float = 0.08) -> tuple[int, int, int, int] | None:
    """
    Return product bbox as pixel coords (x1, y1, x2, y2).
    Uses OpenAI Vision to find the single main product.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.environ.get("OPENAI_BBOX_MODEL", os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"))
    client = OpenAI(api_key=api_key)

    w, h = image.size

    prompt = """
Find the single main product object in this image.

Return ONLY valid JSON, no markdown:
{"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "confidence": 0.0, "object": "short name"}

Coordinates must be normalized 0 to 1 relative to the full image.

The main product is the cup, mug, bottle, can, beverage container, packaged drink, or object the user likely wants to preserve.
Include attached parts of the product such as handle, lid, straw, sleeve, label, cap, or logo.
Do NOT include table, books, bags, shelves, background clutter, shadows, hands, or unrelated objects.
Return the tightest box that contains the whole product.
If uncertain, choose the most central product-like object.
"""

    resp = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": _image_data_url(image)},
            ],
        }],
    )

    text = resp.output_text.strip()
    try:
        data = json.loads(text)
    except Exception:
        print(f"[bbox] OpenAI JSON parse failed: {text}", flush=True)
        return None

    try:
        x = float(data["x"])
        y = float(data["y"])
        bw = float(data["w"])
        bh = float(data["h"])
    except Exception:
        print(f"[bbox] OpenAI bbox fields missing: {data}", flush=True)
        return None

    x1 = int(x * w)
    y1 = int(y * h)
    x2 = int((x + bw) * w)
    y2 = int((y + bh) * h)

    # Expand a little so handles/lids do not get clipped.
    pad_x = int((x2 - x1) * expand)
    pad_y = int((y2 - y1) * expand)

    x1 = _clamp(x1 - pad_x, 0, w - 1)
    y1 = _clamp(y1 - pad_y, 0, h - 1)
    x2 = _clamp(x2 + pad_x, x1 + 1, w)
    y2 = _clamp(y2 + pad_y, y1 + 1, h)

    print(f"[bbox] object={data.get('object')} conf={data.get('confidence')} bbox={(x1, y1, x2, y2)}", flush=True)
    return x1, y1, x2, y2
