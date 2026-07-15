import base64
import io
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from PIL import Image

from app.model.model import generate_styled_image
from app.services.caption_generator import generate_caption_package

router = APIRouter()

REFERENCES_PATH = Path(__file__).resolve().parent.parent / "config" / "references.json"


def resize_to_instagram(image: Image.Image) -> Image.Image:
    """
    인스타그램 피드 비율(1:1 정사각형)로 이미지를 크롭/리사이즈.
    1080x1080 픽셀로 고정.
    """
    target_size = (1080, 1080)

    width, height = image.size
    min_side = min(width, height)
    left = (width - min_side) // 2
    top = (height - min_side) // 2
    right = left + min_side
    bottom = top + min_side
    image = image.crop((left, top, right, bottom))

    image = image.resize(target_size, Image.LANCZOS)
    return image


def image_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _load_references():
    with open(REFERENCES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_reference(reference_id: str):
    references = _load_references()
    return next((r for r in references if r["id"] == reference_id), None)


@router.get("/references")
async def get_references():
    """
    무드/구도별 레퍼런스 목록을 그대로 반환.
    무드 개수, 구도 개수는 이 파일(references.json) 내용에 따라 자유롭게 바뀔 수 있음.
    프론트엔드는 이 배열을 mood_id 기준으로 그루핑해서 화면에 그린다.
    """
    return _load_references()


@router.post("/generate")
async def generate(
    product_image: UploadFile = File(...),
    reference_id: str = Form(...)
):
    """
    사용자가 올린 사진 + 고른 레퍼런스(reference_id)를 기반으로
    같은 분위기/구도의 이미지를 생성해서 반환.

    캡션 생성은 여기서 하지 않는다 (사용자가 이미지 결과를 먼저 확인한 뒤,
    별도 버튼을 눌러야 /caption이 호출되는 2단계 구조).
    """
    reference = _find_reference(reference_id)
    if reference is None:
        return JSONResponse(status_code=400, content={"error": "존재하지 않는 reference_id입니다."})

    image_data = await product_image.read()
    pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")

    result_image = generate_styled_image(pil_image, reference)
    result_image = resize_to_instagram(result_image)

    return JSONResponse(content={
        "result_image": image_to_base64(result_image),
    })


class CaptionRequest(BaseModel):
    reference_id: str
    result_image_base64: str
    menu_name: Optional[str] = None
    purpose: Optional[str] = None


@router.post("/caption")
async def caption(payload: CaptionRequest):
    """
    이미 생성된 결과 이미지(result_image_base64)를 보고
    캡션 + 해시태그 + 스토리 문구를 생성.

    /generate와 분리된 이유: 사용자가 이미지 결과부터 먼저 확인하고,
    "캡션·해시태그 만들기" 버튼을 눌렀을 때만 (선택적으로) 호출되는 구조이기 때문.
    """
    reference = _find_reference(payload.reference_id)
    if reference is None:
        return JSONResponse(status_code=400, content={"error": "존재하지 않는 reference_id입니다."})

    try:
        result = generate_caption_package(
            result_image_base64=payload.result_image_base64,
            mood_label=reference["mood_label"],
            composition_label=reference["composition_label"],
            menu_name=payload.menu_name,
            purpose=payload.purpose,
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"캡션 생성 실패: {e}"})

    return JSONResponse(content=result)
