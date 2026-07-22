# Ad Creator Presets

이 브랜치는 Ad Creator 서비스의 **ComfyUI 프리셋 실행 구조**를 개발·검증하기 위한 브랜치입니다. 기존 로컬 모델 설명서가 아니라, 서비스 프리셋과 OpenAI 이미지 생성 파일럿을 기준으로 관리합니다.

## 현재 범위

- 서비스 선택값 12개를 `comfyui/presets/registry.json`에서 단일 관리
- 승인된 화이트 미디엄·우드 미디엄 프리셋 2개만 활성화
- OpenAI `gpt-image-2`, `quality=low` provider profile 고정
- 프리셋별 prompt, lighting sheet, grade profile, hint asset과 SHA-256 검증
- 4:5(`1024x1280` → 무크롭 `880x1100`)와 1:1(`1024x1024`) 생성 계약
- 제품 원본은 기본 긴 변 1536px 상한, 저해상도 무확대·메타데이터 제거
- 기존 `model-c-v1`은 삭제하지 않고 롤백 경로로 유지

## 프리셋 진행 상태

프리셋은 여러 작업 환경에서 계속 수정·추가·검증되고 있습니다. 특정 시점의 공개·검증 프리셋 목록이나 개수를 README에 고정하지 않습니다. 실제 서비스 사용 가능 여부, 내부 contract와 provider 입력 정책은 항상 `comfyui/presets/registry.json` 및 각 preset bundle을 기준으로 확인합니다.

기존 `instagram_wood_45deg_relational_v3`는 삭제하지 않고 `available_not_routed` 대안으로 보존합니다. 새 서비스 옵션이 합의될 때만 별도 라우팅합니다.

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

프리셋은 현재 여러 작업 환경에서 수정·추가·시각 검증 중이며, 검증을 통과한 항목부터 registry에 순차 반영됩니다. 따라서 README에 published preset 개수를 고정하지 않으며, 현재 상태와 활성 여부는 `comfyui/presets/registry.json`을 기준으로 확인합니다. GCP ComfyUI·Gateway 전체 E2E와 CommonQA는 출시 차단 조건입니다.

## 연동 문서

- 백엔드·프론트 계약: `comfyui/deploy/OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`
- ComfyUI 재설계 계획: `comfyui/deploy/COMFYUI_REDESIGN_PLAN_KO.md`
- 실제 검증 기록: `comfyui/deploy/OPENAI_PILOT_VALIDATION_20260721_KO.md`

기본값은 검수된 4:5입니다. 1:1 계약은 전 구간에 준비했지만 실제 시각 QA가 끝날 때까지 공개 UI 선택지는 열지 않습니다. 어떤 비율도 다른 비율에서 잘라 만들지 않습니다.
