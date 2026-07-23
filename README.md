# Ad Creator Presets

이 브랜치는 Ad Creator 서비스의 **ComfyUI 프리셋 실행 구조**를 개발·검증하기 위한 브랜치입니다. 기존 로컬 모델 설명서가 아니라, 서비스 프리셋과 OpenAI 이미지 생성 파일럿을 기준으로 관리합니다.

## 현재 범위

- 서비스 선택값 12개를 `comfyui/presets/registry.json`에서 단일 관리
- 공개·검증 상태는 `comfyui/presets/registry.json`에서 관리
- registry가 지정한 published 프리셋 하나를 기본값으로 사용
- OpenAI `gpt-image-2`, `quality=low` provider profile 고정
- 프리셋별 prompt, lighting sheet, grade profile, hint asset과 SHA-256 검증
- 4:5(`1024x1280`)와 1:1(`1024x1024`) 생성 결과를 무크롭·무리사이즈로 전달
- 제품 원본은 기본 긴 변 1536px 상한, 저해상도 무확대·메타데이터 제거
- 기존 `model-c-v1`은 삭제하지 않고 롤백 경로로 유지

## 활성 프리셋

| 서비스 preset ID | 내부 contract | 런타임 provider 입력 |
| --- | --- | --- |
| `natural_white__product_center` | `instagram_white_diffuse_wall_table_v1` | 사용자 제품 원본 |
| `wood__product_center` | `tokyo_a6_relational_scene_hint_v4` | 사용자 제품 원본 + 검수된 A6 scene hint |

나머지 10개 선택값은 아직 비활성화되어 있으며 provider 호출 전에 거부됩니다. Vivid 계열은 교체 예정이므로 신규 계약으로 확정하지 않습니다.

기존 `instagram_wood_45deg_relational_v3`는 삭제하지 않고 `available_not_routed` 대안으로 보존합니다. 새 서비스 옵션이 합의될 때만 별도 라우팅합니다.

컵 정책, 온도, 동반 피사체, 조명, 색감, 입력 역할과 typed transform은 각 프리셋 JSON이 선언합니다. 공용 런타임은 특정 프리셋 ID별 분기를 두지 않습니다.

## 실행 흐름

```text
Frontend reference_id
  -> Backend
  -> Generation Gateway
  -> openai-gpt-image-2-low-v1
  -> preset registry / bundle 검증
  -> OpenAI Images API
  -> provider 원본 + audit sidecar 저장
  -> 선택 비율로 처음부터 생성한 crop 없는 결과 반환
```

프론트와 백엔드는 내부 prompt나 contract ID를 추론하지 않고 canonical 서비스 preset ID만 전달합니다.

## 주요 디렉터리

```text
comfyui/
  config/providers/                 # provider model·quality·출력 계약
  presets/                          # 12-slot registry와 프리셋 bundle·자산
  workflows/                        # API/UI workflow와 workflow registry
  custom_nodes/ad_creator/          # ComfyUI node와 provider adapter
    runtime/                         # provider 중립 resolver·prompt compiler·typed transform executor
  orchestrator/                     # workflow·preset routing
  gateway/                          # 업로드·큐·상태·결과 API
  deploy/                           # 담당자 인계·배포·검증 문서
  scripts/                          # registry validator와 명시적 smoke script
  tests/                            # gateway·node·adapter 회귀 테스트
```

## 검증

```bash
python comfyui/scripts/validate_workflows.py
python comfyui/scripts/validate_presets.py
python -m unittest discover -s comfyui/tests -v
```

공용 런타임의 안전 상한은 제품 최대 3장과 reference control 최대 1장을 합친 provider 입력 4장, 프롬프트 12,000자입니다. 상한 초과 시 입력이나 프롬프트를 임의 제거·절단하지 않고 제출 전에 실패합니다. 실제 published 개수와 기본값은 registry를 기준으로 확인합니다. GCP ComfyUI·Gateway 전체 E2E와 CommonQA는 출시 차단 조건입니다.

## 연동 문서

- 백엔드·프론트 계약: `comfyui/deploy/OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`
- ComfyUI 재설계 계획: `comfyui/deploy/COMFYUI_REDESIGN_PLAN_KO.md`
- 실제 검증 기록: `comfyui/deploy/OPENAI_PILOT_VALIDATION_20260721_KO.md`

기본값은 검수된 4:5입니다. 1:1 계약은 전 구간에 준비했지만 실제 시각 QA가 끝날 때까지 공개 UI 선택지는 열지 않습니다. 어떤 비율도 다른 비율에서 잘라 만들지 않습니다.
