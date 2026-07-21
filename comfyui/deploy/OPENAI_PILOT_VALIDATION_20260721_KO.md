# OpenAI 두 프리셋 파일럿 검증 기록 — 2026-07-21

## 대상

- 기준: `upstream/comfyui` `7b098bd`
- 작업 브랜치: `codex/openai-gpt-image-2-presets`
- workflow: `openai-gpt-image-2-low-v1`
- provider: `gpt-image-2`, `quality=low`, `1024x1280` PNG
- 전달 결과: crop 없는 `880x1100` PNG

## 자동 검증 결과

```text
Python compileall                         통과
workflow validator                       2개 통과
preset validator                         12 slot / published 2개 통과
unit test                                55개 통과
git diff --check                         통과
```

검증한 핵심 계약은 다음과 같습니다.

- `natural_white__product_center`는 `instagram_white_diffuse_wall_table_v1`만 사용합니다.
- `wood__product_center`는 `instagram_wood_45deg_relational_v3`만 사용합니다.
- 나머지 10개 slot은 provider 호출 전에 거부됩니다.
- OpenAI model·quality·size는 Git의 provider profile로 고정되고 레거시 `strength`와 분리됩니다.
- OpenAI 요청은 반복 `image[]` multipart이며 `input_fidelity`를 보내지 않습니다.
- 화이트는 정규화한 사용자 제품만 전송합니다.
- 우드는 정규화한 사용자 제품 다음에 sanitized scene hint만 전송합니다.
- 화이트 authoring reference와 우드 material board는 checksum 검증만 하고 provider에는 보내지 않습니다.
- provider가 정확한 `1024x1280` PNG를 반환하지 않으면 crop하지 않고 실패합니다.
- Gateway job ID, 고유 client request ID, OpenAI request ID, usage, 시간, profile/prompt/input hash가 audit sidecar에 연결됩니다.
- provider 원본 PNG와 delivery PNG는 별도 파일로 유지됩니다.
- provider 오류 원문, prompt 본문, 비밀키, 사용자 원본 경로는 외부 오류나 sidecar에 기록하지 않습니다.
- 같은 OpenAI preset의 재시도에서 무시되는 legacy 필드는 idempotency hash를 바꾸지 않습니다.
- preset registry 손상은 `503`, 미지원 preset은 `400`으로 구분됩니다.
- 기존 `model-c-v1`은 기본값과 롤백 경로로 유지됩니다.

## 실제 유료 smoke 상태

실제 제품 사진을 이용한 화이트 1회 호출을 준비했으나, 실행 환경의 외부 데이터 전송 승인 단계에서 중단됐습니다. 따라서 다음은 모두 0건입니다.

```text
OpenAI 업로드       0건
OpenAI API 호출     0건
과금                0건
실제 생성 결과      0건
```

mock 성공을 실제 OpenAI E2E 성공으로 간주하지 않습니다. 화이트·우드 실제 low 생성과 육안 QA는 아직 출시 차단 조건입니다.

## 남은 출시 차단 조건

1. 사용자 제품 사진과 우드 sanitized scene hint의 OpenAI 외부 전송 및 low 두 건 과금을 명시적으로 승인합니다.
2. GCP ComfyUI에 `OPENAI_API_KEY`, `OPENAI_IMAGE_TIMEOUT_SECONDS`, `AD_CREATOR_OPENAI_AUDIT_DIR`을 안전하게 주입합니다.
3. 백엔드의 `1080x1080` 중앙 crop을 신규 workflow에서 제거하고 4:5를 보존합니다.
4. 프론트는 두 preset만 활성화하고 나머지 10개를 비활성화하며 결과를 4:5로 표시합니다.
5. 화이트·우드를 각각 독립 파일로 1회 생성하고 로고·라벨, 제품 수, 잘림, 구도, 조명과 sidecar 연결을 확인합니다.
6. 위 검증이 끝난 뒤에만 Render의 `COMFYUI_WORKFLOW_ID`와 Gateway의 `AD_CREATOR_HEALTH_WORKFLOW_ID`를 전환합니다.

상세 연동 계약은 `OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`, 장기 구조는 `COMFYUI_REDESIGN_PLAN_KO.md`를 기준으로 합니다.
