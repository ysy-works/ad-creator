# Ad Creator Presets

이 브랜치는 Ad Creator 서비스의 **ComfyUI 프리셋 실행 구조**를 개발·검증하기 위한 브랜치입니다. 기존 로컬 모델 설명서가 아니라, 서비스 프리셋과 OpenAI 이미지 생성 파일럿을 기준으로 관리합니다.

## 현재 범위

- 서비스 선택값 12개를 `comfyui/presets/registry.json`에서 단일 관리
- 승인된 화이트 미디엄·우드 미디엄 프리셋 2개만 활성화
- OpenAI `gpt-image-2`, `quality=low` provider profile 고정
- 프리셋별 prompt, lighting sheet, grade profile, hint asset과 SHA-256 검증
- provider 원본 `1024x1280`과 무크롭 전달 이미지 `880x1100`을 독립 저장
- 기존 `model-c-v1`은 삭제하지 않고 롤백 경로로 유지

## 활성 프리셋

| 서비스 preset ID | 내부 contract | 런타임 provider 입력 |
| --- | --- | --- |
| `natural_white__product_center` | `instagram_white_diffuse_wall_table_v1` | 사용자 제품 원본 |
| `wood__product_center` | `instagram_wood_45deg_relational_v3` | 사용자 제품 원본 + 검수된 scene hint |

나머지 10개 선택값은 아직 비활성화되어 있으며 provider 호출 전에 거부됩니다. Vivid 계열은 교체 예정이므로 신규 계약으로 확정하지 않습니다.

> 제품 입력의 기본값을 사용자 원본으로 유지할지, 레퍼런스 컵을 기본값 또는 선택 옵션으로 제공할지는 회의 결정 전입니다. 결정 전에는 현재 입력 정책을 변경하지 않습니다.

## 실행 흐름

```text
Frontend reference_id
  -> Backend
  -> Generation Gateway
  -> openai-gpt-image-2-low-v1
  -> preset registry / bundle 검증
  -> OpenAI Images API
  -> provider 원본 + audit sidecar 저장
  -> crop 없는 4:5 결과 반환
```

프론트와 백엔드는 내부 prompt나 contract ID를 추론하지 않고 canonical 서비스 preset ID만 전달합니다.

## 주요 디렉터리

```text
comfyui/
  config/providers/                 # provider model·quality·출력 계약
  presets/                          # 12-slot registry와 프리셋 bundle·자산
  workflows/                        # API/UI workflow와 workflow registry
  custom_nodes/ad_creator/          # ComfyUI node와 provider adapter
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

현재 기준은 workflow 2개, preset slot 12개, published preset 2개와 단위 테스트 55개입니다. 실제 OpenAI adapter-level `low` 화이트·우드 smoke도 각각 1회 성공했지만, GCP ComfyUI·Gateway 전체 E2E와 CommonQA는 아직 출시 차단 조건입니다.

## 연동 문서

- 백엔드·프론트 계약: `comfyui/deploy/OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`
- ComfyUI 재설계 계획: `comfyui/deploy/COMFYUI_REDESIGN_PLAN_KO.md`
- 실제 검증 기록: `comfyui/deploy/OPENAI_PILOT_VALIDATION_20260721_KO.md`

백엔드의 정사각형 중앙 crop 제거와 프론트의 4:5 결과 표시가 완료되기 전에는 신규 workflow를 서비스 기본값으로 전환하지 않습니다.
