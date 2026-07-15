import io
import os

import requests
from PIL import Image

MODEL_API_URL = os.environ.get("MODEL_API_URL", "http://136.65.68.28:8001")

# references.json의 mood_id/composition_id -> 모델 API가 요구하는 값으로 변환
MOOD_TO_BACKGROUND_STYLE = {
    "natural_white": "white",
    "wood": "wood",
    "vivid": "vivid",
}

COMPOSITION_MAP = {
    "product_large": "closeup",
    "product_center": "medium",
    "aerial_shot": "aerial",
    "handheld_lifestyle": "handheld",
}


def generate_styled_image(product_image: Image.Image, reference: dict) -> Image.Image:
    """
    기현님 GCP 서버(Flux)에 이미지를 보내서 스타일이 입혀진 결과를 받아온다.
    1) POST /generate 로 이미지+스타일 정보 전송 -> image_url 받음
    2) 그 image_url을 GET으로 다시 요청해서 실제 이미지 바이트를 받음
    """
    background_style = MOOD_TO_BACKGROUND_STYLE[reference["mood_id"]]
    composition = COMPOSITION_MAP[reference["composition_id"]]

    buffer = io.BytesIO()
    product_image.save(buffer, format="PNG")
    buffer.seek(0)

    files = {"image": ("product.png", buffer, "image/png")}
    data = {
        "composition": composition,
        "background_style": background_style,
        "strength": "medium",  # 기현님 요청대로 우선 medium 고정
    }

    # 생성에 최대 2분 넘게 걸릴 수 있어서 넉넉하게 잡음
    response = requests.post(
        f"{MODEL_API_URL}/generate",
        files=files,
        data=data,
        timeout=300,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("success"):
        raise RuntimeError(f"모델 서버 생성 실패: {result}")

    image_url = f"{MODEL_API_URL}{result['image_url']}"
    image_response = requests.get(image_url, timeout=30)
    image_response.raise_for_status()

    return Image.open(io.BytesIO(image_response.content)).convert("RGB")