
카페 제품 사진 1장을 입력받아, 제품의 형태와 주요 특징을 유지하면서 인스타그램 감성의 제품 사진으로 재생성하는 모델링/추론 파이프라인입니다.


## 주요 기능

- 입력 음료 사진 기반 이미지 재생성
- 4가지 구도 지원
  - `closeup`
  - `medium`
  - `aerial`
  - `handheld`
- 3가지 배경/무드 지원
  - `vivid`
  - `wood`
  - `white`
- 총 12개 조합 생성 가능
- FLUX.1-Kontext-dev 기반 로컬 추론
- 참조 이미지 분석 기반 스타일 시트 적용
- OpenAI API를 이용해 `templates_lib` 참조 이미지들의 공통 무드/조명/구도 분석

## 폴더 구조

```text
kh_v2/
  app/
    config.py
    inference.py
    model_loader.py
    preprocessing.py
    prompt_builder.py
    validation.py

  presets/
    backgrounds.py
    category_prompts.py
    compositions.py
    quality_rules.py
    style_sheets.json

  scripts/
    analyze_templates_openai.py
    generate_single.py
    generate_matrix.py

  input/
  output/
  templates_lib/

  requirements.txt
  README.md
```

## 별도 배치 파일

다음 파일과 폴더는 GitHub에 올리지 않고 서버에 별도로 배치합니다.

```text
.env
templates_lib/
input/
output/
모델 캐시
```

`templates_lib` 구조는 아래와 같아야 합니다.

```text
templates_lib/
  neutral_white_minimal/
    aerial_shot/
    handheld_lifestyle/
    product_center/
    product_large/

  vivid_color/
    aerial_shot/
    handheld_lifestyle/
    product_center/
    product_large/

  wood/
    aerial_shot/
    handheld_lifestyle/
    product_center/
    product_large/
```

각 폴더 안에는 해당 무드/구도를 대표하는 참조 이미지를 여러 장 넣습니다.

## 환경 변수

`.env` 예시:

```env
HF_TOKEN=hf_xxxxxxxxxxxxxxxxx
HF_HOME=/opt/hf_cache
HF_HUB_CACHE=/opt/hf_cache/hub
TRANSFORMERS_CACHE=/opt/hf_cache/hub

OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
OPENAI_VISION_MODEL=gpt-4.1-mini
```

주의: `.env`는 GitHub에 올리지 않습니다.

## 설치

```bash
cd /home/wina0901/kh_v2
source /opt/venv/product_swap/bin/activate

pip install -r requirements.txt
pip install openai python-dotenv
```

Hugging Face 로그인 및 FLUX.1-Kontext-dev 라이선스 동의가 필요합니다.

```bash
hf auth login
```

## 참조 이미지 분석

`templates_lib`를 서버에 배치한 뒤 실행합니다.

```bash
cd /home/wina0901/kh_v2
python scripts/analyze_templates_openai.py
```

성공하면 아래 파일이 생성됩니다.

```text
presets/style_sheets.json
```

이 파일은 각 카테고리의 공통 무드, 조명, 구도, 배경 특징을 담고 있으며 생성 프롬프트에 자동 반영됩니다.

## 단일 이미지 생성

```bash
python scripts/generate_single.py input/drink.jpg \
  --comp medium \
  --bg wood \
  --strength medium \
  --seed 42
```

옵션:

```text
--comp      closeup | medium | aerial | handheld
--bg        vivid | wood | white
--strength  low | medium | high
--seed      optional int
--steps     optional int
--guidance  optional float
```

## 12개 조합 생성

```bash
python scripts/generate_matrix.py input/drink.jpg --seed 42 --sheet
```

결과는 `output/`에 저장됩니다.

컨택트시트:

```text
output/matrix_sheet.png
```

## 백엔드 연동

백엔드는 아래 함수만 호출하면 됩니다.

```python
from app.inference import generate_beverage_image

result = generate_beverage_image(
    image_path="/home/wina0901/kh_v2/input/request_001.jpg",
    composition="medium",
    background_style="wood",
    strength="medium",
    seed=42,
    output_dir="/home/wina0901/kh_v2/output",
)
```

성공 응답 예시:

```json
{
  "success": true,
  "output_path": "/home/wina0901/kh_v2/output/20260715_123456_ab12cd.png",
  "composition": "medium",
  "background_style": "wood",
  "strength": "medium",
  "seed": 42,
  "width": 832,
  "height": 1040,
  "elapsed_seconds": 31.2,
  "model": "black-forest-labs/FLUX.1-Kontext-dev",
  "mode": "recreate"
}
```

실패 응답 예시:

```json
{
  "success": false,
  "error_code": "MODEL_LOAD_FAILED",
  "error_message": "..."
}
```

## 백엔드 담당자 전달 사항

백엔드는 업로드 이미지를 파일로 저장한 뒤 `image_path`를 모델 함수에 전달합니다.

```text
입력:
- image_path
- composition
- background_style
- seed optional

출력:
- success
- output_path
- error_code / error_message
```

`output_path`는 백엔드에서 프론트가 접근 가능한 URL로 변환하면 됩니다.

예:

```text
/home/wina0901/kh_v2/output/result.png
-> /static/results/result.png
```

## 운영 주의사항

- FLUX 모델은 매우 무겁기 때문에 첫 요청은 모델 로딩으로 오래 걸립니다.
- `model_loader.py`는 싱글톤 방식으로 파이프라인을 캐시하므로 두 번째 요청부터는 모델을 재사용합니다.
- GPU 메모리 문제를 피하려면 동시 요청은 1개로 제한하는 것을 권장합니다.
- 여러 요청은 백엔드에서 큐 처리하는 것이 안전합니다.
- `input/`, `output/`, `.env`, 모델 캐시, 참조 이미지는 Git에 올리지 않습니다.

