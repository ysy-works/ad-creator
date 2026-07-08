 

## 폴더 구조

```
product_swap_gcp/
├── configs/config.py         # 스타일/구도 정의, 모델·경로·파라미터
├── templates_lib/            # ★ 템플릿 라이브러리 (12개 카테고리)
│   ├── neutral_white_minimal/
│   │   ├── product_large/     *.jpg  
│   │   ├── product_center/    *.jpg
│   │   ├── aerial_shot/       *.jpg
│   │   └── handheld_lifestyle/*.jpg
│   ├── wood/ (동일한 4개 하위폴더)
│   └── vivid_color/ (동일한 4개 하위폴더)
├── app/
│   ├── template_library.py   # 카테고리별 템플릿 목록/선택
│   ├── prompt_builder.py     # 제품 교체 프롬프트
│   ├── generator.py          # Kontext stitch 생성기
│   ├── pipeline.py           # 코어 로직 (run_swap)
│   ├── server.py             # ★ FastAPI 서버
│   └── utils.py              # job_id, 저장
├── outputs/{job_id}/         # result.png / input.png / template.png / meta.json
└── requirements.txt
```

## 템플릿 넣는 법

`templates_lib/{스타일}/{구도}/` 폴더에 **이미 제품(컵)이 놓여있는 완성 사진**을 여러 장 넣는다. 한 폴더에 여러 장 넣으면 요청마다 랜덤으로 하나가 선택된다(seed로 고정 가능). 파일명은 자유.

- 스타일: `neutral_white_minimal`, `wood`, `vivid_color`
- 구도: `product_large`(클로즈업), `product_center`(미디엄), `aerial_shot`(항공샷), `handheld_lifestyle`(손샷)

## GCP GPU VM 세팅
 

```bash
# 1) VM에서 (Python 3.10+, CUDA 드라이버 설치 전제)
pip install -r requirements.txt

# 2) HuggingFace 로그인 (Kontext-dev 라이선스 동의 필요)
huggingface-cli login

# 3) 환경변수(선택)
export PSG_QUANT=nf4          # 또는 none (VRAM 넉넉할 때)
export PSG_STEPS=30
export PSG_GUIDANCE=2.5

# 4) 서버 실행 (부팅 시 모델 상주)
uvicorn app.server:app --host 0.0.0.0 --port 8080
```

방화벽에서 8080 열고, 외부 접근은 GCP 방화벽 규칙으로 제한 권장.

## API

```
GET  /health           # 모델 로드 상태
GET  /categories       # 스타일/구도 목록 (프론트 선택 UI)
GET  /library-status   # 12개 카테고리 템플릿 보유 수 (빈 폴더 점검)
POST /swap             # 제품 교체 실행
GET  /result/{job_id}  # 결과 PNG
```

### /swap 요청 (multipart/form-data)

| 필드 | 필수 | 설명 |
|---|---|---|
| product_image | ✓ | 사용자 제품 사진 파일 |
| style_id | ✓ | neutral_white_minimal / wood / vivid_color |
| composition_id | ✓ | product_large / product_center / aerial_shot / handheld_lifestyle |
| template_name |  | 특정 템플릿 파일명 지정(없으면 랜덤) |
| product_desc |  | 제품 짧은 설명, 예: "a plastic cup of iced yuzu smoothie" |
| seed |  | 재현용 |
| extra_instruction |  | 추가 지시 |

### 호출 예 (curl)

```bash
curl -X POST http://VM_IP:8080/swap \
  -F "product_image=@yuzu.jpg" \
  -F "style_id=wood" \
  -F "composition_id=product_center" \
  -F "product_desc=a plastic cup of iced yuzu smoothie"
# → {"job_id":"...","result_url":"/result/...","seed":...}
```

### 파이썬에서 직접 (서버 없이)

```python
from app import pipeline
meta = pipeline.run_swap(
    product_image_path="yuzu.jpg",
    style_id="wood",
    composition_id="product_center",
    product_desc="a plastic cup of iced yuzu smoothie",
)
print(meta["files"]["result"])
```

 