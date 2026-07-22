# OpenAI 두 프리셋 파일럿 검증 기록 — 2026-07-21

> 이 문서는 당시 45도 우드 preset의 과거 유료 smoke 증거입니다. 현재 기본 우드는 `tokyo_a6_relational_scene_hint_v4`이며, A6 및 1:1은 별도 시각 검증 전이므로 이 결과를 현재 기본 preset 검증으로 해석하지 않습니다.

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

## 실제 유료 smoke 결과

사용자가 제품 원본과 검수된 우드 scene hint의 외부 전송 및 `low` 2회 과금을 명시적으로 승인한 뒤 실행했습니다. 성공한 유료 호출은 정확히 2건이며 자동 재시도는 없었습니다.

| preset | provider 입력 | OpenAI request ID | 시간 | 결과 |
| --- | --- | --- | ---: | --- |
| `natural_white__product_center` | 제품 원본 | `req_b664c9f6148b436bad53e5cef12936ed` | 36.828초 | 성공 |
| `wood__product_center` | 제품 원본 + sanitized scene hint | `req_7b0b71553c02421d98f90a8128e082b6` | 38.431초 | 성공 |

두 provider 원본은 `1024x1280` PNG, 전달 결과는 crop 없는 `880x1100` PNG로 확인했습니다. 출력은 Git에 넣지 않고 다음 로컬 경로에 각각 독립 파일로 저장했습니다.

```text
outputs/openai-gpt-image-2-low-pilot-20260721/white/natural_white__product_center.png
outputs/openai-gpt-image-2-low-pilot-20260721/wood/wood__product_center.png
```

provider 호출 전 실패도 기록합니다. 첫 시도는 `.env` 값이 자식 프로세스로 export되지 않아 키 검증에서 중단됐고, 다음 시도는 로컬 Python CA 경로 문제로 TLS handshake에서 중단됐습니다. 두 경우 모두 OpenAI HTTP 본문 전송 전에 실패했으며 결과·request ID·과금 가능한 응답이 없었습니다. CA 검증은 끄지 않고 certifi CA bundle을 명시해 해결했습니다.

## 실제 결과 육안 QA

| 항목 | 화이트 | 우드 |
| --- | --- | --- |
| 단일 제품·잘림·복제 | 통과 | 통과 |
| 제품 종류·층·용기 정체성 | 통과 | 통과 |
| 핵심 로고·라벨 가독성 | 육안 통과 | 육안 통과 |
| 4:5·무크롭 | 통과 | 통과 |
| 무드·조명 방향 | 통과 | 통과 |
| preset 수치형 bbox/배치 | 재검토 필요: 제품이 계약보다 크게 보임 | 재검토 필요: 제품 중심·크기가 계약 범위를 벗어난 것으로 보임 |

따라서 OpenAI adapter와 provider 입출력 계약은 실제 유료 E2E를 통과했습니다. 이번 호출은 명시적 smoke script로 adapter를 직접 실행했으므로 Gateway job과 ComfyUI prompt ID는 없습니다. ComfyUI 노드·Gateway 조립은 mock 통합 테스트를 통과했지만 실제 GCP ComfyUI 서버 E2E는 배포 뒤 별도로 수행해야 합니다. 또한 CommonQA가 아직 구현되지 않았고 수치형 bbox는 육안 추정이므로 두 이미지를 곧바로 최종 preset 합격본으로 승격하지 않습니다.

## 남은 출시 차단 조건

1. GCP ComfyUI에 `OPENAI_API_KEY`, `OPENAI_IMAGE_TIMEOUT_SECONDS`, `AD_CREATOR_OPENAI_AUDIT_DIR`을 안전하게 주입합니다.
2. 백엔드의 `1080x1080` 중앙 crop을 신규 workflow에서 제거하고 4:5를 보존합니다.
3. 프론트는 두 preset만 활성화하고 나머지 10개를 비활성화하며 결과를 4:5로 표시합니다.
4. CommonQA 또는 동등한 bbox 측정을 붙여 수치형 구도 계약을 검증하고, 필요한 prompt·hint 보정은 새 profile/version에서 수행합니다.
5. 위 검증이 끝난 뒤에만 Render의 `COMFYUI_WORKFLOW_ID`와 Gateway의 `AD_CREATOR_HEALTH_WORKFLOW_ID`를 전환합니다.

상세 연동 계약은 `OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`, 장기 구조는 `COMFYUI_REDESIGN_PLAN_KO.md`를 기준으로 합니다.
