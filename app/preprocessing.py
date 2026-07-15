import os
import sys

from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config

MAX_INPUT_SIDE = 2048   # 너무 큰 입력은 축소


def load_and_prepare(image_path: str,
                     target_w: int = None,
                     target_h: int = None,
                     pad_color=(255, 255, 255)) -> Image.Image:
    """
    입력 사진을 모델에 넣기 좋은 형태로 정리.

    - EXIF 방향 보정
    - RGB 변환 (투명 배경은 흰색으로 합성)
    - 과대 이미지 축소
    - 비율 유지 리사이즈 + 패딩으로 target 크기에 맞춤 (찌그러짐 방지)

    Raises:
        PipelineError(INVALID_IMAGE)
    """
    target_w = target_w or config.DEFAULT_WIDTH
    target_h = target_h or config.DEFAULT_HEIGHT

    if not os.path.exists(image_path):
        raise config.PipelineError(
            config.ErrorCode.INVALID_IMAGE, f"file not found: {image_path}"
        )

    try:
        img = Image.open(image_path)
        img.verify()                      # 손상 파일 검사
        img = Image.open(image_path)      # verify 후 재오픈 필요
    except Exception as e:
        raise config.PipelineError(
            config.ErrorCode.INVALID_IMAGE, f"cannot open image: {e}"
        )

    # EXIF 방향 보정
    img = ImageOps.exif_transpose(img)

    # 투명 이미지 → 흰 배경 합성
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (*pad_color, 255))
        img = Image.alpha_composite(bg, img).convert("RGB")
    else:
        img = img.convert("RGB")

    # 과대 이미지 축소
    if max(img.size) > MAX_INPUT_SIDE:
        img.thumbnail((MAX_INPUT_SIDE, MAX_INPUT_SIDE), Image.LANCZOS)

    # 비율 유지 리사이즈 + 패딩 (찌그러짐 방지)
    fitted = ImageOps.contain(img, (target_w, target_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), pad_color)
    ox = (target_w - fitted.width) // 2
    oy = (target_h - fitted.height) // 2
    canvas.paste(fitted, (ox, oy))
    return canvas


def to_multiple_of_16(w: int, h: int) -> tuple[int, int]:
    """FLUX는 16의 배수 해상도를 요구."""
    return (max(16, w // 16 * 16), max(16, h // 16 * 16))
