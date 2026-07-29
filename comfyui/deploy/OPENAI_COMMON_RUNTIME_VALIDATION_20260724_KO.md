# GPT Image 2 공용 런타임 검증 기록 — 2026-07-24

## 배포 상태

- Git commit: `8df290f`
- GCP repo: `/opt/ad-creator`
- Gateway health workflow: `gpt-image-2-v1`
- Gateway `/health`: 정상
- ComfyUI·Gateway systemd: `active`
- ComfyUI 품질 선택: `low`, `medium`, `high`
- 서비스 기본 품질: `medium`
- 서비스 슬롯: 12개 선언, 11개 활성
- 비활성 슬롯: `wood__handheld_lifestyle` — 별도 제작 중

## 정적 검증

- 활성 11개 × 비율 2개 × 컵 모드 2개 = 44개 계약 해석 통과
- 4:5: `1024x1280`, 1:1: `1024x1024`
- 로컬 단위 테스트 75개 통과
- GCP에서 preset/workflow validator 통과
- GCP 전체 unittest는 운영 가상환경의 기존 테스트 의존성 문제로 완주하지 못함:
  `pytest` 미설치 및 Python 3.10에서 `comfyui.gateway.app` patch target 충돌

## 실제 Gateway → ComfyUI → OpenAI 생성

성공:

1. `vivid__product_large`
   - `reconstruct_source`, 4:5, medium
   - 결과: `1024x1280`
   - 입력 역할: 제품 원본 + raw dark-grey close-up reference
   - provider elapsed: 62.704초
2. `vivid__handheld_lifestyle`
   - `adopt_reference`, 1:1, medium
   - 결과: `1024x1024`
   - 입력 역할: 제품 원본 + raw dark-grey handheld pose reference
   - provider elapsed: 64.693초

실패:

- `vivid__product_center`의 두 컵 모드에서 OpenAI `string_above_max_length`
- 같은 길이대인 `vivid__aerial_shot`은 중복 실패 호출을 피하기 위해 유료 호출 생략

컴파일 후 프롬프트 길이:

| 슬롯 | 사용자 컵 | 레퍼런스 컵 |
| --- | ---: | ---: |
| 다크그레이 클로즈업 | 약 30.1K | 약 33.2K |
| 다크그레이 미디엄 | 약 33.9K | 약 37.1K |
| 다크그레이 항공 | 약 35.2K | 약 38.3K |
| 다크그레이 손컵 | 약 26.5K | 약 29.7K |

사용자 결정에 따라 긴 프롬프트는 이번 작업에서 축약하지 않았다. 따라서 다크그레이 미디엄·항공 및 클로즈업 레퍼런스컵은 현재 서비스 통과 상태로 볼 수 없으며, 프롬프트 조정 전까지 프론트 노출 승인을 보류해야 한다.

## 백엔드 인수인계

프롬프트 상한 문제를 해결하고 재검증한 뒤 다음 값으로 전환한다.

```env
COMFYUI_WORKFLOW_ID=gpt-image-2-v1
```

백엔드는 `quality`를 전송하지 않는다. `container_mode`, `serving_temperature=auto`, `aspect_ratio`만 기존 계약대로 전달한다.
