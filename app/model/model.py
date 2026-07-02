from PIL import Image
from pydantic import BaseModel


class TextLayerItem(BaseModel):
    id: str
    content: str
    x: float          # 0~1 비율 좌표 (캔버스 기준)
    y: float
    font_size: int
    font_family: str = "Pretendard"
    color: str = "#FFFFFF"
    rotation: float = 0.0


class AdResult(BaseModel):
    image: Image.Image
    text_layers: list[TextLayerItem]

    class Config:
        arbitrary_types_allowed = True


def generate_ad_image(product_image: Image.Image, prompt: str) -> AdResult:
    """
    모델 팀이 이 함수를 채워줄 예정.

    실제로는 다음 파이프라인이 들어갈 자리:
      1) 배경 제거
      2) 프롬프트 기반 광고 배경 생성
      3) 원본 제품 합성
      4) 캡션/가격 문구 생성 (텍스트 레이어)

    지금은 모델팀 코드가 아직 없어서, 아래 두 가지를 더미로 채운다:
      - image: 입력 이미지 그대로 반환 (배경 제거/생성 전)
      - text_layers: 그럴듯한 위치의 더미 캡션 텍스트
    """
    dummy_text_layers = [
        TextLayerItem(
            id="caption",
            content=f"({prompt}) 스타일 문구 - 더미",
            x=0.1,
            y=0.75,
            font_size=48,
        ),
        TextLayerItem(
            id="price",
            content="9,900원",
            x=0.1,
            y=0.85,
            font_size=36,
            color="#FFD700",
        ),
    ]

    return AdResult(image=product_image, text_layers=dummy_text_layers)