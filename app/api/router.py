import base64
import io
import json
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
from PIL import Image

from app.model.model import generate_styled_image

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


@router.get("/references")
async def get_references():
    """
    무드/구도별 레퍼런스 목록을 그대로 반환.
    무드 개수, 구도 개수는 이 파일(references.json) 내용에 따라 자유롭게 바뀔 수 있음.
    프론트엔드는 이 배열을 mood_id 기준으로 그루핑해서 화면에 그린다.
    """
    with open(REFERENCES_PATH, "r", encoding="utf-8") as f:
        references = json.load(f)
    return references


@router.post("/generate")
async def generate(
    product_image: UploadFile = File(...),
    reference_id: str = Form(...)
):
    """
    사용자가 올린 사진 + 고른 레퍼런스(reference_id)를 기반으로
    같은 분위기/구도의 이미지를 생성해서 반환.
    """
    # 선택한 레퍼런스 정보 조회 (분위기/구도 라벨 등, 모델 호출 시 참고용)
    with open(REFERENCES_PATH, "r", encoding="utf-8") as f:
        references = json.load(f)
    reference = next((r for r in references if r["id"] == reference_id), None)
    if reference is None:
        return JSONResponse(status_code=400, content={"error": "존재하지 않는 reference_id입니다."})

    image_data = await product_image.read()
    pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")

    result_image = generate_styled_image(pil_image, reference)
    result_image = resize_to_instagram(result_image)

    return JSONResponse(content={
        "result_image": image_to_base64(result_image),
    })
