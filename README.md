# Ad Creator

소상공인용 SNS 이미지를 만드는 서비스입니다. 현재 `presets` 브랜치는 **ComfyUI 공용 런타임과 12개 광고 이미지 프리셋을 `deploy`에 병합하기 직전 상태로 관리하는 단일 작업선**입니다.

## 현재 실행 계약

- workflow ID: `gpt-image-2-v1`
- 모델: OpenAI `gpt-image-2`
- 기본 품질: `medium` (`low|medium|high`는 ComfyUI 내부에서만 선택)
- 컵 모드: `adopt_reference`(레퍼런스 컵), `reconstruct_source`(사용자 컵 재생성)
- 온도 기본값: `auto`
- 출력: 4:5 `1024x1280`, 1:1 `1024x1024`
- 출력 정책: 처음부터 목표 비율로 생성하며 크롭·리사이즈하지 않음
- 입력 정책: 사용자 제품 1장과 프리셋별 reference control 최대 1장

## 공개 프리셋

`comfyui/presets/registry.json`이 서비스 노출 여부와 기본 프리셋의 단일 권위입니다.

| 배경 | 클로즈업 | 미디엄 | 항공 | 손에 든 샷 |
| --- | --- | --- | --- | --- |
| 화이트 | `natural_white__product_large` | `natural_white__product_center` | `natural_white__aerial_shot` | `natural_white__handheld_lifestyle` |
| 우드 | `wood__product_large` | `wood__product_center` | `wood__aerial_shot` | `wood__handheld_lifestyle` |
| 다크그레이 | `vivid__product_large` | `vivid__product_center` | `vivid__aerial_shot` | `vivid__handheld_lifestyle` |

프리셋 파일 구성과 수정 절차는 [`comfyui/presets/README.md`](comfyui/presets/README.md)를 따릅니다.

## 실행 흐름

```text
Frontend
  -> Backend
  -> HTTPS Generation Gateway
  -> ComfyUI gpt-image-2-v1
  -> preset registry / bundle / asset hash 검증
  -> OpenAI Images API
  -> 원본 결과와 audit sidecar 저장
  -> 선택한 비율의 무크롭 결과 반환
```

프론트와 백엔드는 내부 프롬프트를 만들지 않고 `workflow_id`, canonical `preset_id`, `container_mode`, `serving_temperature`, `aspect_ratio`만 전달합니다.

## 브랜치 흐름

```text
presets -> deploy -> main
langfuse -> deploy -> main
```

- `presets`: ComfyUI 공용 런타임, 프리셋, 힌트 이미지, 관련 검증과 문서
- `backend`, `frontend`, `serving`, `model-b`: 각 담당자 작업선
- `model-c`: 레거시 롤백 작업선
- `langfuse`: Gateway 생성 시간·세션 저장과 Langfuse 비용/성능 관측
- `deploy`: 담당 브랜치를 모아 최종 E2E 검증
- `main`: 검증 완료본

`presets` 정리에서는 다른 담당 브랜치의 코드나 이력을 수정하지 않습니다.

## 주요 폴더

```text
comfyui/
  config/providers/                 # 모델·품질·출력 계약
  presets/                          # 12개 bundle, registry, 힌트 자산
  workflows/                        # API/UI workflow와 registry
  custom_nodes/ad_creator/          # ComfyUI node, 공용 resolver, OpenAI adapter
  orchestrator/                     # workflow·preset routing
  gateway/                          # 제출·상태·결과 API
  observability/                    # Langfuse 수집기와 비용 정규화
  deploy/                           # GCP 배포와 담당자 인계 문서
  scripts/                          # 정적 validator와 smoke 도구
  tests/                            # 런타임·Gateway 회귀 테스트
```

## 로컬 검증

유료 이미지 호출 없이 구조와 런타임 계약을 검증합니다.

```bash
python comfyui/scripts/validate_workflows.py
python comfyui/scripts/validate_presets.py
python comfyui/scripts/validate_white_overhead_preset.py
python comfyui/scripts/validate_wood_closeup_preset.py
python comfyui/scripts/validate_wood_overhead_preset.py
python -m unittest discover -s comfyui/tests -v
```

## 문서

- ComfyUI 구조와 사용법: [`comfyui/README.md`](comfyui/README.md)
- 프리셋 구조와 수정 절차: [`comfyui/presets/README.md`](comfyui/presets/README.md)
- GCP 배포와 ComfyUI 접속: [`comfyui/deploy/README.md`](comfyui/deploy/README.md)
- 백엔드 계약: [`comfyui/deploy/BACKEND_HANDOFF.md`](comfyui/deploy/BACKEND_HANDOFF.md)
- 공용 런타임 검증 기록: [`comfyui/deploy/OPENAI_COMMON_RUNTIME_VALIDATION_20260724_KO.md`](comfyui/deploy/OPENAI_COMMON_RUNTIME_VALIDATION_20260724_KO.md)
- Langfuse 설치·팀 전달: [`comfyui/deploy/LANGFUSE_OBSERVABILITY_HANDOFF_KO.md`](comfyui/deploy/LANGFUSE_OBSERVABILITY_HANDOFF_KO.md)
