# Ad Creator Presets

이 브랜치는 Ad Creator 서비스의 **ComfyUI 프리셋 실행 구조**를 개발·검증하기 위한 브랜치입니다. 기존 로컬 모델 설명서가 아니라, 서비스 프리셋과 OpenAI 이미지 생성 파일럿을 기준으로 관리합니다.

## 현재 범위

- 서비스 선택값 12개를 `comfyui/presets/registry.json`에서 단일 관리
- 사용자 검수를 통과한 화이트 미디엄과 A6 우드 미디엄만 공개 실행
- A6 `tokyo_a6_relational_scene_hint_v4`를 기본 프리셋으로 고정
- 화이트 오버헤드와 우드 클로즈업은 `validated`로 보관하며 provider 시각 검증 전에는 공개하지 않음
- OpenAI `gpt-image-2`, `quality=low` provider profile 고정
- 프리셋별 prompt, lighting sheet, grade profile, hint asset과 SHA-256 검증
- 4:5(`1024x1280`)와 1:1(`1024x1024`)를 생성 크기 그대로 전달하는 계약
- 제품 원본은 기본 긴 변 1536px 상한, 저해상도 무확대·메타데이터 제거
- 기존 `model-c-v1`은 삭제하지 않고 롤백 경로로 유지

## 프리셋 진행 상태

프리셋은 여러 작업 환경에서 계속 수정·추가·검증되고 있습니다. 특정 시점의 공개·검증 프리셋 목록이나 개수를 README에 고정하지 않습니다. 실제 서비스 사용 가능 여부, 내부 contract와 provider 입력 정책은 항상 `comfyui/presets/registry.json` 및 각 preset bundle을 기준으로 확인합니다.

통과 프리셋 네 개의 정확한 보관 상태는 `comfyui/presets/passed-presets.json`이 권위입니다. A6만 기본값이며 화이트 확산광, 우드 45도, 화이트 직사광은 삭제하지 않고 추후 확장용으로 보관합니다. 보류된 옅은 우드 프리셋은 통과 목록에서 제외합니다.

컵 정책은 프리셋 JSON이 지원 모드와 기본값을 선언합니다. 신규 프리셋의 기본값은 `adopt_reference`이고, 사용자 컵은 픽셀 합성이 아닌 `reconstruct_source`로 재생성합니다. 사용자 로고 입력은 프론트·API 계약이 완성될 때까지 비활성화합니다. 프리셋이 선언한 기본 표면 문구(현재 우드 close-up의 `CAFE AMERICANO`)는 유지하며, 향후 per-image 로고 입력이 활성화되면 선언된 한 표면의 기본 문구만 교체합니다.

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
    runtime/                         # provider 중립 JSON resolver·prompt compiler·typed transform executor
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

공통 런타임은 프리셋 ID별 분기를 사용하지 않습니다. 총 provider 입력의 설계 상한은 4장(제품 최대 3장 + sanitised reference control 최대 1장)이며 프롬프트는 12,000자 이하입니다. 현재 공개 Gateway workflow는 백엔드 다중 업로드 연동 전이므로 제품 1장만 받고, 프리셋별 reference control도 최대 1장만 보냅니다. 초과 입력·프롬프트는 조용히 제거하거나 자르지 않습니다.

프리셋은 현재 여러 작업 환경에서 수정·추가·시각 검증 중이며, 검증을 통과한 항목부터 registry에 순차 반영됩니다. 따라서 README에 published preset 개수를 고정하지 않으며, 현재 상태와 활성 여부는 `comfyui/presets/registry.json`을 기준으로 확인합니다. GCP ComfyUI·Gateway 전체 E2E와 CommonQA는 출시 차단 조건입니다.

## 연동 문서

- 백엔드·프론트 계약: `comfyui/deploy/OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`
- ComfyUI 재설계 계획: `comfyui/deploy/COMFYUI_REDESIGN_PLAN_KO.md`
- 실제 검증 기록: `comfyui/deploy/OPENAI_PILOT_VALIDATION_20260721_KO.md`

기본값은 검수된 4:5입니다. 1:1 계약은 전 구간에 준비했지만 실제 시각 QA가 끝날 때까지 공개 UI 선택지는 열지 않습니다. 어떤 비율도 다른 비율에서 잘라 만들지 않습니다.
