from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps
import io

from app.model.model import generate_ad_image

router = APIRouter()

def resize_to_instagram(image: Image.Image) -> Image.Image:
    """
    인스타그램 피드 비율(1:1 정사각형)로 이미지를 크롭/리사이즈.
    1080x1080 픽셀로 고정.
    """
    target_size = (1080, 1080)

    # 이미지를 정사각형으로 크롭 (중앙 기준)
    width, height = image.size
    min_side = min(width, height)
    left = (width - min_side) // 2
    top = (height - min_side) // 2
    right = left + min_side
    bottom = top + min_side
    image = image.crop((left, top, right, bottom))

    # 1080x1080으로 리사이즈
    image = image.resize(target_size, Image.LANCZOS)
    return image

@router.post("/generate")
async def generate(
    product_image: UploadFile = File(...),
    prompt: str = Form(...)
):
    # 업로드된 이미지 파일 → PIL Image로 변환
    image_data = await product_image.read()
    pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")

    # 모델 호출 (model.py의 빈 공간)
    result_image = generate_ad_image(pil_image, prompt)

    # 인스타그램 피드 비율로 변환
    result_image = resize_to_instagram(result_image)

    # 결과 PIL Image → 바이트로 변환해서 반환
    output = io.BytesIO()
    result_image.save(output, format="PNG")
    output.seek(0)

    return StreamingResponse(output, media_type="image/png")