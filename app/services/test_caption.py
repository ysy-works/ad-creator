"""
캡션+해시태그 생성 기능을, 실제 이미지 파일로 서버 없이 바로 테스트하는 스크립트.

사용법:
  1) 이 파일을 app/services/ 폴더에 두세요 (caption_generator.py와 같은 위치).
  2) app/.env 파일에 OPENAI_API_KEY=sk-... 가 들어있어야 합니다.
  3) 아래 TEST_IMAGE_PATH를 실제 존재하는 이미지 파일 경로로 바꾸세요.
     예: frontend/public/references/wood__product_large.png
  4) 실행: python app\\services\\test_caption.py  (프로젝트 루트에서)
"""

import base64
from pathlib import Path
from caption_generator import generate_caption_package

# 테스트용 이미지 경로 (실제 존재하는 파일로 바꿔서 사용)
# TEST_IMAGE_PATH = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "references" / "wood__product_large.png"
TEST_IMAGE_PATH = Path(r"C:\Users\송우현\Downloads\images1.jpg")

MOOD_LABEL = "우드"
COMPOSITION_LABEL = "클로즈업"


def image_file_to_base64(path: Path) -> str:
    ext = path.suffix.lstrip(".").lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/{mime};base64,{encoded}"


if __name__ == "__main__":
    if not TEST_IMAGE_PATH.exists():
        print(f"이미지를 찾을 수 없습니다: {TEST_IMAGE_PATH}")
        print("TEST_IMAGE_PATH를 실제 존재하는 이미지 경로로 바꿔주세요.")
    else:
        print(f"테스트 이미지: {TEST_IMAGE_PATH.name}")
        image_base64 = image_file_to_base64(TEST_IMAGE_PATH)

        result = generate_caption_package(image_base64, MOOD_LABEL, COMPOSITION_LABEL)
        print("\n캡션:", result["caption"])
        print("해시태그:", " ".join(result["hashtags"]))
