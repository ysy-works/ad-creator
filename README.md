# Ad Creator Presets

이 브랜치는 Ad Creator 서비스의 **ComfyUI 프리셋 실행 구조**를 개발·검증하기 위한 브랜치입니다. 기존 로컬 모델 설명서가 아니라, 서비스 프리셋과 OpenAI 이미지 생성 파일럿을 기준으로 관리합니다.

## 현재 범위

- 서비스 선택값 12개를 `comfyui/presets/registry.json`에서 단일 관리
- 공개·검증 상태는 `comfyui/presets/registry.json`에서 관리
- registry의 `default_preset_slot`만 기본값으로 사용하며, A6 `tokyo_a6_relational_scene_hint_v4`는 기본값을 유지
- OpenAI `gpt-image-2`, 기본 `quality=medium`; ComfyUI 내부에서만 `low|medium|high` 선택 가능
- 프리셋별 prompt, lighting sheet, grade profile, hint asset과 SHA-256 검증
- 4:5(`1024x1280`)와 1:1(`1024x1024`) 생성 결과를 무크롭·무리사이즈로 전달
- 제품 원본은 기본 긴 변 1536px 상한, 저해상도 무확대·메타데이터 제거
- 기존 `model-c-v1`은 삭제하지 않고 롤백 경로로 유지

## 프리셋 진행 상태

프리셋은 여러 작업 환경에서 계속 수정·추가·검증되고 있습니다. 특정 시점의 공개·검증 프리셋 목록이나 개수를 README에 고정하지 않습니다. 실제 서비스 사용 가능 여부, 내부 contract와 provider 입력 정책은 항상 `comfyui/presets/registry.json` 및 각 preset bundle을 기준으로 확인합니다.

통과 프리셋의 정확한 보관 상태는 `comfyui/presets/passed-presets.json`이 권위입니다. A6만 기본값이며 보류된 프리셋은 통과 목록에서 제외합니다.

기존 `instagram_wood_45deg_relational_v3`는 삭제하지 않고 `available_not_routed` 대안으로 보존합니다. 새 서비스 옵션이 합의될 때만 별도 라우팅합니다.

컵 정책, 온도, 동반 피사체, 조명, 색감, 입력 역할과 typed transform은 각 프리셋 JSON이 선언하며 공용 런타임은 특정 프리셋 ID별 분기를 두지 않습니다. 기본 컵 정책은 `adopt_reference`이고, 사용자 컵은 픽셀 합성이 아닌 `reconstruct_source`로 재생성합니다. 사용자 로고 입력은 프론트·API 계약이 완성될 때까지 비활성화합니다. 프리셋이 선언한 기본 표면 문구(현재 우드 close-up의 `CAFE AMERICANO`)는 유지하며, 향후 per-image 로고 입력이 활성화되면 선언된 한 표면의 기본 문구만 교체합니다.

## 실행 흐름

```text
Frontend reference_id
  -> Backend
  -> Generation Gateway
  -> gpt-image-2-v1
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
python comfyui/scripts/validate_white_overhead_preset.py
python comfyui/scripts/validate_wood_closeup_preset.py
python -m unittest discover -s comfyui/tests -v
```

공용 런타임의 안전 상한은 제품 최대 3장과 reference control 최대 1장을 합친 provider 입력 4장입니다. 프롬프트는 프리셋별 선언 상한을 적용하며 전역 하드 상한은 50,000자입니다. 상한 초과 시 입력이나 프롬프트를 임의 제거·절단하지 않고 제출 전에 실패합니다. 현재 공개 Gateway workflow는 백엔드 다중 업로드 연동 전이므로 제품 1장만 받고, 프리셋별 reference control도 최대 1장만 보냅니다. 실제 published 개수와 기본값은 registry를 기준으로 확인하며, GCP ComfyUI·Gateway 전체 E2E와 CommonQA는 출시 차단 조건입니다.

## 연동 문서

- 백엔드·프론트 계약: `comfyui/deploy/OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`
- ComfyUI 재설계 계획: `comfyui/deploy/COMFYUI_REDESIGN_PLAN_KO.md`
- 실제 검증 기록: `comfyui/deploy/OPENAI_PILOT_VALIDATION_20260721_KO.md`
- 공용 medium 런타임 검증 기록: `comfyui/deploy/OPENAI_COMMON_RUNTIME_VALIDATION_20260724_KO.md`

기본값은 검수된 4:5입니다. 1:1 계약은 전 구간에 준비했지만 실제 시각 QA가 끝날 때까지 공개 UI 선택지는 열지 않습니다. 어떤 비율도 다른 비율에서 잘라 만들지 않습니다.
