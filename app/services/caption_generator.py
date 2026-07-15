import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client() -> OpenAI:
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


def generate_caption_package(
    result_image_base64: str,
    mood_label: str,
    composition_label: str,
    menu_name: str | None = None,
    purpose: str | None = None,
) -> dict:
    """
    실제로 생성된 결과 이미지를 보고, 고객에게 바로 보여줄 인스타그램
    캡션 + 해시태그 + 스토리 문구를 생성.

    입력:
      - result_image_base64: "data:image/png;base64,...." 형태의 결과 이미지
      - mood_label, composition_label: 내부 작업용 힌트 (예: "우드", "클로즈업")
        -> 절대 최종 문구에 그대로 노출되면 안 됨. 프롬프트 안에서 명시적으로 차단.
      - menu_name: 사용자가 입력한 실제 메뉴명 (선택, 예: "아이스 아메리카노")
      - purpose: 사용자가 고른 게시 목적 (선택, 예: "신메뉴 소개")

    출력 (dict):
      {
        "caption": "인스타 캡션 (2~3문장)",
        "hashtags": ["#...", ...]  (8개),
        "story": "스토리용 짧은 한 줄 문구"
      }
    """
    client = _get_client()

    user_provided_lines = []
    if menu_name:
        user_provided_lines.append(f"- 메뉴명: {menu_name}")
    if purpose:
        user_provided_lines.append(f"- 게시 목적: {purpose}")
    user_provided_block = "\n".join(user_provided_lines) if user_provided_lines else "- (제공되지 않음)"

    prompt = f"""너는 카페 사장님을 대신해 인스타그램에 바로 올릴 홍보 문구를 쓰는 SNS 카피라이터다.

먼저 첨부된 사진을 직접 보고, 사진에 실제로 보이는 요소(음료 색, 컵 모양, 배경, 손 등)를 파악해라.

아래 두 종류의 정보를 구분해서 다뤄야 한다.

[A. 내부 참고용 힌트 — 최종 문구에 절대 그대로 쓰지 말 것]
- 촬영 컨셉: {mood_label} / {composition_label}
이 힌트는 사진의 톤을 이해하는 데만 참고하고, "뉴트럴", "화이트 배경", "구도", "레퍼런스", "스타일", "컨셉" 같은
디자인 설명 단어를 최종 문구에 절대 직접 쓰지 마라. 사장님이 실제로 쓸 법한 자연스러운 말로 완전히 풀어써라.

[B. 실제로 반영해야 하는 정보]
{user_provided_block}
메뉴명이 주어졌다면 반드시 캡션에 자연스럽게 녹여서 언급해라. 게시 목적이 주어졌다면 그 목적에 맞는 톤으로 써라
(예: 세일·이벤트라면 행동을 유도하는 한 줄을 포함, 신메뉴 소개라면 처음 알리는 느낌으로).
둘 다 없다면 사진 내용만으로 무난하게 작성해라.

작성 규칙:
- 캡션 2~3문장, 담백하고 자연스러운 존댓말. 손님에게 편하게 말을 거는 톤.
- 과장된 광고 문구, "특별한 순간", "여러분의 하루에 활력을", "완벽한" 같은 상투적 표현 금지.
- 사진에 실제로 보이는 요소를 최소 1가지는 구체적으로 언급.
- 이모지는 0~1개만.
- 해시태그는 8개, #카페 관련 키워드 위주 (디자인 설명 단어는 해시태그에도 쓰지 말 것).
- 스토리 문구는 15자 내외의 짧고 임팩트 있는 한 줄 (스토리 화면에 텍스트로 얹는 용도).
- 반드시 아래 JSON 형식으로만 응답 (다른 설명 텍스트 없이):

{{"caption": "...", "hashtags": ["#...", "..."], "story": "..."}}
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

    for key in ("caption", "hashtags", "story"):
        if key not in result:
            raise ValueError(f"예상한 형식이 아닙니다: {result}")

    return result
