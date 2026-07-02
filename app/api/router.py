import base64
import io

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

from app.model.model import generate_ad_image, TextLayerItem

router = APIRouter()


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


class GenerateResponse(BaseModel):
    image_layer: str
    text_layers: list[TextLayerItem]
    canvas_width: int = 1080
    canvas_height: int = 1080


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    product_image: UploadFile = File(...),
    prompt: str = Form(...)
):
    # 업로드된 이미지 파일 → PIL Image로 변환
    image_data = await product_image.read()
    pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")

    # 모델 호출 (model.py) - 이제 이미지 + 텍스트 레이어를 함께 반환
    result = generate_ad_image(pil_image, prompt)

    # 인스타그램 피드 비율로 변환 (텍스트가 없는 순수 이미지 레이어에만 적용)
    result_image = resize_to_instagram(result.image)

    return JSONResponse(content={
        "image_layer": image_to_base64(result_image),
        "text_layers": [layer.model_dump() for layer in result.text_layers],
        "canvas_width": 1080,
        "canvas_height": 1080,
    })