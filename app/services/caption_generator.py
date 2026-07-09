import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client() -> OpenAI:
    """
    OpenAI 클라이언트를 첫 호출 시점에 생성(lazy init).
    -> 모듈을 import하는 시점에 API 키가 없어도 에러가 안 나고,
       실제로 함수를 호출할 때만 키를 확인하게 됨.
    """
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY가 설정되지 않았습니다. "
                "app/.env 파일에 OPENAI_API_KEY=sk-... 형태로 넣어주세요."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def generate_caption_package(result_image_base64: str, mood_label: str, composition_label: str) -> dict:
    """
    실제로 생성된 결과 이미지를 직접 보고 인스타그램 캡션 + 해시태그를 생성.

    입력:
      - result_image_base64: "data:image/png;base64,...." 형태의 결과 이미지
        (router.py의 image_to_base64()가 만들어주는 형식 그대로 넣으면 됨)
      - mood_label: 예) "우드"          (참고용 힌트, 이미지만으로 애매한 뉘앙스를 보완)
      - composition_label: 예) "클로즈업"  (참고용 힌트)

    출력 (dict):
      {
        "caption": "카페 사장님이 바로 게시할 수 있는 한글 캡션 (2~3문장)",
        "hashtags": ["#카페", "#콜드브루", ...]  (8~12개)
      }
    """
    client = _get_client()

    prompt = f"""당신은 소규모 카페 사장님을 대신해 인스타그램 게시물 문구를 작성하는 카피라이터입니다.

첨부된 사진을 실제로 보고, 사진에 담긴 내용(음료 색·컵 모양·배경·분위기 등)을 반영해서
인스타그램 캡션과 해시태그를 만들어주세요.

참고 정보(사진 촬영 컨셉):
- 분위기: {mood_label}
- 구도: {composition_label}

작성 규칙:
- 캡션은 2~3문장, 친근하고 자연스러운 한글 존댓말 사장님 톤
- 사진에 실제로 보이는 요소(색감, 소품, 배경 등)를 최소 1가지 이상 구체적으로 언급할 것
- 이모지는 1~2개까지만 사용
- 메뉴명·가격 등 사진만으로 확인 안 되는 사실은 지어내지 말 것
- 해시태그는 8~12개, #카페 및 사진 분위기 관련 키워드 위주
- 반드시 아래 JSON 형식으로만 응답 (다른 설명 텍스트 없이)

{{"caption": "...", "hashtags": ["#...", "#..."]}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": result_image_base64}},
                ],
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
    )

    content = response.choices[0].message.content
    result = json.loads(content)

    if "caption" not in result or "hashtags" not in result:
        raise ValueError(f"예상한 형식이 아닙니다: {result}")

    return result
