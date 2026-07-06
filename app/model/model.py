from PIL import Image


def generate_styled_image(product_image: Image.Image, reference: dict) -> Image.Image:
    """
    모델 팀이 이 함수를 채워줄 예정.

    입력:
      - product_image: 사용자가 업로드한 (엉성한) 원본 사진
      - reference: 선택한 레퍼런스 정보. 예)
          {
            "id": "warm_cafe__top_view",
            "mood_id": "warm_cafe",
            "mood_label": "따뜻한 카페 감성",
            "composition_id": "top_view",
            "composition_label": "위에서 내려다본 구도",
            "thumbnail_url": "..."
          }

    실제로는 reference가 가리키는 분위기/구도를 참고해서
    product_image를 같은 스타일로 재생성하는 모델(img2img, ControlNet 등)이
    이 자리에 들어갈 예정.

    지금은 모델팀 코드가 아직 없어서, 입력 이미지를 그대로 반환하는 더미로 채운다.
    """
    return product_image
