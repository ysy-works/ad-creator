import base64
import io
import json
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
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
    같은 분위기/구도의 이미지를 생성하고, 그 결과 이미지를 바로 이어서
    캡션·해시태그 생성에도 사용한다.

    -> "결과 이미지를 실제로 보고 캡션을 쓴다"는 원칙을 지키기 위해,
       이미지 생성 직후 같은 요청 안에서 캡션까지 만들어 한 번에 응답한다.
       (나중에 진짜 모델이 붙어도 이 순서는 그대로 유지하면 됨:
        모델 결과물 → 그 결과물을 그대로 캡션 생성기에 전달)
    """
    references = _load_references()
    reference = next((r for r in references if r["id"] == reference_id), None)
    if reference is None:
        return JSONResponse(status_code=400, content={"error": "존재하지 않는 reference_id입니다."})

    image_data = await product_image.read()
    pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")

    # 1) 이미지 생성 (지금은 더미: 업로드 이미지를 그대로 반환.
    #    모델팀 연동 후에도 이 함수의 반환값이 "최종 결과 이미지"라는 계약은 동일)
    result_image = generate_styled_image(pil_image, reference)
    result_image = resize_to_instagram(result_image)
    result_base64 = image_to_base64(result_image)

    # 2) 캡션/해시태그 생성 — 방금 만든 결과 이미지를 그대로 보고 작성
    caption_package = {"caption": None, "hashtags": []}
    caption_error = None
    try:
        caption_package = generate_caption_package(
            result_image_base64=result_base64,
            mood_label=reference["mood_label"],
            composition_label=reference["composition_label"],
        )
    except Exception as e:
        # 캡션 생성이 실패해도 이미지 생성 자체는 이미 성공했으니
        # 전체 요청을 실패시키지 않고, 이미지는 정상 반환 + 에러 사유만 같이 알려준다.
        caption_error = str(e)

    return JSONResponse(content={
        "result_image": result_base64,
        "caption": caption_package.get("caption"),
        "hashtags": caption_package.get("hashtags", []),
        "caption_error": caption_error,
    })
