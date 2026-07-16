import io
import os

import requests
from PIL import Image

MODEL_API_URL = os.environ.get("MODEL_API_URL", "http://136.65.68.28:8001")

DEFAULT_WORKFLOW_ID = "model-c-v1"

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


def _generate_with_model_c_v1(product_image: Image.Image, reference: dict) -> Image.Image:
    """
    model-c-v1 워크플로 (기현님 개발 모델).

    TODO: 팀장님이 inference 서비스(ComfyUI 실행 인터페이스) 스펙을 확정해서 주시면
    이 함수 내부만 그 스펙에 맞게 교체하면 됨. 지금은 기존에 연동해둔
    기현님 GCP 서버(136.65.68.28:8001) 직접 호출 로직을 그대로 사용.
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
        "strength": "medium",
    }

    response = requests.post(
        f"{MODEL_API_URL}/generate",
        files=files,
        data=data,
        timeout=420,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("success"):
        raise RuntimeError(f"모델 서버 생성 실패: {result}")

    image_url = f"{MODEL_API_URL}{result['image_url']}"
    image_response = requests.get(image_url, timeout=30)
    image_response.raise_for_status()

    return Image.open(io.BytesIO(image_response.content)).convert("RGB")


# workflow_id -> 실제 호출 함수. 새 워크플로가 추가되면 여기 한 줄만 등록하면 됨.
WORKFLOW_REGISTRY = {
    "model-c-v1": _generate_with_model_c_v1,
}


def generate_styled_image(product_image: Image.Image, reference: dict, workflow_id: str = None) -> Image.Image:
    """
    입력:
      - product_image: 사용자가 업로드한 원본 사진
      - reference: 선택한 레퍼런스 정보 (mood_id, composition_id 등 포함)
      - workflow_id: 사용할 워크플로 식별자. 없으면 DEFAULT_WORKFLOW_ID 사용.
    """
    workflow_id = workflow_id or DEFAULT_WORKFLOW_ID
    handler = WORKFLOW_REGISTRY.get(workflow_id)
    if handler is None:
        raise ValueError(f"알 수 없는 workflow_id입니다: {workflow_id}")
    return handler(product_image, reference)