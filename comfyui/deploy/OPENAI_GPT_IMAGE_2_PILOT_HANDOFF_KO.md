# OpenAI GPT Image 2 저화질 파일럿 인계서

이 문서는 백엔드·프론트엔드 담당자가 ComfyUI의 두 프리셋 파일럿을 연결할 때 따라야 할 고정 계약입니다. 기존 `model-c-v1`은 삭제하지 않으며, 신규 워크플로를 병렬 배포한 뒤 환경변수로 전환합니다.

현재 검증 범위와 adapter-level 실제 유료 smoke 결과는 `OPENAI_PILOT_VALIDATION_20260721_KO.md`에 기록합니다.

## 1. 고정값

| 항목 | 값 |
| --- | --- |
| Gateway workflow ID | `openai-gpt-image-2-low-v1` |
| OpenAI model | `gpt-image-2` |
| OpenAI quality | `low` — 서버 provider profile에서 고정 |
| Provider 생성 | PNG, `1024x1280`, 정확한 4:5 |
| ComfyUI 결과 | PNG, `880x1100`, crop 없는 4:5 축소 |
| 활성 프리셋 | 화이트 미디엄, 우드 미디엄 두 개만 |
| 브라우저의 OpenAI 직접 호출 | 금지 |
| Gateway의 OpenAI 직접 호출 | 금지; OpenAI 호출은 ComfyUI 프로세스가 담당 |
| 파일럿 QA | OpenAI 단독 생성. Gemini 및 CommonQA는 포함하지 않음 |

`strength=low|medium|high`는 기존 로컬 모델의 편집 강도입니다. OpenAI의 `quality`와 의미가 다르므로 서로 매핑하거나 재사용하면 안 됩니다. 이번 파일럿의 OpenAI quality는 사용자가 보내는 값과 무관하게 항상 `low`입니다.

## 2. 출시 차단 조건: 정사각형 중앙 크롭 제거

현재 serving 백엔드의 `resize_to_instagram()`은 모든 결과를 가운데에서 정사각형으로 잘라 `1080x1080`으로 만듭니다. 이 처리가 남아 있으면 4:5 프리셋의 제품 크기, 여백, 그림자와 구도가 손상되므로 파일럿을 켜면 안 됩니다.

신규 워크플로 결과에는 다음 규칙만 허용합니다.

1. Gateway가 받은 `880x1100` PNG를 그대로 반환한다.
2. 백엔드가 리사이즈해야 한다면 전체 프레임을 보존해 `1080x1350`으로만 바꾼다.
3. 중앙 크롭, `ImageOps.fit()` 기반 크롭, 1:1 변환은 금지한다.
4. 신규 워크플로 결과가 4:5가 아니면 조용히 자르지 말고 통합 오류로 실패시킨다.
5. `model-c-v1`의 기존 정사각형 처리가 필요하다면 workflow ID별로 분기해 레거시 동작만 유지한다.

프론트 결과 카드도 현재 공통 `aspect-ratio: 1 / 1`을 사용합니다. 레퍼런스 카드와 분리해 생성 결과 영역만 `aspect-ratio: 4 / 5`로 렌더링해야 합니다.

## 3. 프리셋 매핑

Gateway의 canonical `preset_id`에는 프론트의 기존 `reference_id`를 그대로 보냅니다. 백엔드·프론트가 내부 연구용 프리셋 ID를 추론하지 않습니다.

| 프론트 `reference_id` = Gateway `preset_id` | 표시 | 내부 ComfyUI preset contract | 상태 |
| --- | --- | --- | --- |
| `natural_white__product_center` | 뉴트럴 화이트 · 미디엄샷 | `instagram_white_diffuse_wall_table_v1` | 활성 |
| `wood__product_center` | 우드 · 미디엄샷 | `instagram_wood_45deg_relational_v3` | 활성 |

화이트 authoring reference는 오프라인 구도·조명 설계 근거이며 OpenAI에 보내는 런타임 입력이 아닙니다. 우드 프리셋은 검수·비식별화된 scene hint만 런타임 보조 이미지로 사용할 수 있습니다. 우드 material board는 Git에 포함하되 prompt 작성·검수 authority일 뿐 이번 파일럿의 provider 이미지 입력이 아닙니다. 원본 레퍼런스, 로컬 Mac 절대경로, 원본 속 음료·로고 픽셀을 전송하면 안 됩니다.

사용자 제품 사진은 ComfyUI에서 EXIF·파일명을 제거하고 긴 변을 최대 3072px로 제한한 고품질 JPEG로 정규화한 뒤 OpenAI에 전송합니다. 우드 선택 시에는 이 파일과 sanitized scene hint가 함께 외부 전송됩니다. 운영 전 개인정보·영업기밀 처리 고지와 사용자 동의 범위를 백엔드 정책에서 확인해야 합니다.

### 아직 지원하지 않는 10개 ID

다음 ID는 파일럿에서 선택·생성할 수 없습니다.

- `natural_white__product_large`
- `natural_white__aerial_shot`
- `natural_white__handheld_lifestyle`
- `wood__product_large`
- `wood__aerial_shot`
- `wood__handheld_lifestyle`
- `vivid__product_large`
- `vivid__product_center`
- `vivid__aerial_shot`
- `vivid__handheld_lifestyle`

Vivid 계열은 교체 예정이므로 이름이나 프롬프트를 신규 계약에 고정하지 않습니다. 프론트에서는 위 10개 카드를 숨기거나 `준비 중`으로 비활성화하고, 클릭·업로드·생성 요청을 막습니다. Gateway에 직접 들어오면 유료 호출 전에 `400`으로 거부해야 합니다.

## 4. 호출 계약

### 프론트엔드 → 백엔드

기존 공개 API를 유지합니다.

```http
POST /generate
Content-Type: multipart/form-data

product_image=<JPEG 또는 PNG>
reference_id=natural_white__product_center
```

정상 응답도 기존 형식을 유지합니다.

```json
{
  "result_image": "data:image/png;base64,..."
}
```

프론트는 OpenAI 키, Gateway 키, `workflow_id`, 내부 preset contract ID를 알 필요가 없습니다. `/caption` 계약도 변경하지 않습니다.

### 백엔드 → Gateway

파일럿 생성은 다음과 같이 제출합니다.

```http
POST {COMFYUI_GATEWAY_BASE_URL}/v1/generations
Authorization: Bearer {COMFYUI_GATEWAY_API_KEY}
Idempotency-Key: {one-UUID-per-user-generation-action}
Content-Type: multipart/form-data

image=<사용자 원본>
workflow_id=openai-gpt-image-2-low-v1
preset_id=wood__product_center
```

- HTTP 라이브러리가 multipart boundary를 만들게 두고 `Content-Type` 헤더를 직접 조립하지 않습니다.
- OpenAI 파일럿에는 `strength`, `seed`, `background_style`, `composition`을 보내지 않는 것을 기본으로 합니다.
- 기존 백엔드 호환을 위해 `preset_id`가 없을 때에만 Gateway가 다음 두 조합을 명시적으로 변환합니다.

```text
background_style=white + composition=medium -> natural_white__product_center
background_style=wood  + composition=medium -> wood__product_center
```

- 그 밖의 조합은 추론하지 않고 `400`으로 거부합니다.
- `preset_id`를 보낼 수 있는 백엔드가 배포되면 항상 명시적으로 보내고, 위 fallback에는 의존하지 않습니다.
- 업로드 제한은 Gateway의 기존 계약을 유지합니다: JPEG/PNG/WebP, 최대 20 MiB, 최대 4천만 픽셀.

Gateway의 `202 Accepted`, 상태 폴링, 결과 다운로드 계약은 기존과 같습니다.

```json
{
  "generation_id": "signed-token",
  "workflow_id": "openai-gpt-image-2-low-v1",
  "status": "queued",
  "status_url": "/v1/generations/signed-token",
  "result_url": "/v1/generations/signed-token/result"
}
```

상태는 `queued`, `running`, `succeeded`, `failed`, `unknown`, `expired` 중 하나입니다. `status_url`과 `result_url`은 상대 경로이므로 Gateway base URL과 결합합니다.

## 5. 백엔드 담당 변경사항

1. `WORKFLOW_REGISTRY` 또는 동등한 allowlist에 `openai-gpt-image-2-low-v1`을 등록합니다. `model-c-v1`은 유지합니다.
2. 서비스 기본 workflow를 코드 상수가 아닌 `COMFYUI_WORKFLOW_ID`로 선택할 수 있게 합니다.
3. `/generate`에서 검증한 `reference_id`를 Gateway의 `preset_id`에 그대로 전달합니다.
4. 신규 workflow에서는 두 활성 ID 외 요청을 Gateway 호출 전에 차단합니다.
5. 신규 workflow payload에는 `strength="medium"`을 넣지 않습니다. 넣더라도 OpenAI quality가 바뀌어서는 안 됩니다.
6. 신규 결과에는 정사각형 크롭을 적용하지 않습니다. 원본 `880x1100`을 유지하거나 무크롭 `1080x1350` 리사이즈만 합니다.
7. 성공 결과는 즉시 영구 저장소로 복사합니다. Gateway 임시 결과는 기존 정책상 만료될 수 있습니다.
8. 동일 논리 요청의 네트워크 재시도에는 같은 `Idempotency-Key`와 같은 바이트·필드를 사용합니다. 사용자가 재생성을 명시했을 때만 새 키를 만듭니다.
9. `failed`, `unknown`, `expired` 상태를 자동으로 새 유료 생성으로 재실행하지 않습니다.
10. OpenAI/Gateway 내부 오류 원문에 비밀키, 파일 경로, provider response body가 섞이지 않게 사용자 메시지를 정제합니다.

권장 전환 방식은 다음과 같습니다.

```env
COMFYUI_WORKFLOW_ID=openai-gpt-image-2-low-v1
```

프론트가 임의의 workflow ID를 보내 provider를 선택하게 만들지 않습니다.

## 6. 프론트엔드 담당 변경사항

1. 정적 `references.json`에서 활성 두 항목에 `enabled: true`, 나머지 10개에 `enabled: false`를 추가합니다.
2. 비활성 카드는 `준비 중`으로 표시하거나 목록에서 숨깁니다. 비활성 카드가 `selectedReferenceId`가 되지 않도록 이벤트 단계와 생성 직전 양쪽에서 막습니다.
3. `/generate`에는 기존처럼 `product_image`, `reference_id`만 전송합니다.
4. `natural_white__product_center`, `wood__product_center` 문자열을 변경하지 않습니다.
5. 생성 결과 프레임은 4:5로 표시합니다. 결과 `<img>`에 정사각형 `object-fit: cover`가 적용되어 잘리지 않는지 확인합니다.
6. 미지원 ID의 서버 오류는 일반적인 `생성 실패`가 아니라 `아직 준비 중인 스타일입니다`로 표시합니다.
7. 생성 중 중복 클릭을 막되, 사용자가 명시적으로 다시 생성하면 새 논리 요청으로 처리합니다.
8. `/caption`은 이미지 생성 성공 뒤에만 호출하는 현재 2단계 동작을 유지합니다.

프론트 정적 `references.json`과 백엔드 `references.json`을 따로 손으로 고치는 구조는 장기적으로 제거합니다. 이번 파일럿에서는 두 파일의 ID·활성 상태를 동일하게 맞추고, 다음 단계에서 ComfyUI preset registry로부터 생성하도록 전환합니다.

## 7. 환경변수와 비밀정보

| 실행 위치 | 변수 | 규칙 |
| --- | --- | --- |
| GCP ComfyUI 서비스 | `OPENAI_API_KEY` | 필수. systemd 환경 파일 또는 Secret Manager에서만 주입 |
| GCP ComfyUI 서비스 | `OPENAI_IMAGE_TIMEOUT_SECONDS` | 선택. 기본 `1200`, 허용 범위 `30`~`3600`초 |
| GCP ComfyUI 서비스 | `AD_CREATOR_OPENAI_AUDIT_DIR` | provider 원본·sidecar 저장 경로. 권장 `/opt/comfyui/ComfyUI/output/ad_creator/audit` |
| GCP Gateway | `COMFYUI_BASE_URL` | 기존 내부 URL 유지 |
| GCP Gateway | `AD_CREATOR_GATEWAY_API_KEY` | 기존 32자 이상 비밀키 유지 |
| GCP Gateway | `AD_CREATOR_GENERATION_SIGNING_KEY` | API 키와 다른 값 유지 |
| GCP Gateway | `AD_CREATOR_GATEWAY_DB` | 기존 영속 SQLite 경로 유지 |
| GCP Gateway | `AD_CREATOR_MAX_QUEUED` | 기존 큐 제한 유지 |
| GCP Gateway | `AD_CREATOR_HEALTH_WORKFLOW_ID` | 전환 전 `model-c-v1`, 파일럿 전환 시 `openai-gpt-image-2-low-v1` |
| Render 백엔드 | `COMFYUI_GATEWAY_BASE_URL` | HTTPS Gateway URL |
| Render 백엔드 | `COMFYUI_GATEWAY_API_KEY` | 서버 환경변수에만 저장 |
| Render 백엔드 | `COMFYUI_WORKFLOW_ID` | 파일럿 활성 시 `openai-gpt-image-2-low-v1` |

`OPENAI_API_KEY`는 프론트, Render 백엔드, Git, workflow JSON, 로그에 넣지 않습니다. 이번 파일럿에는 `GEMINI_API_KEY`가 필요하지 않습니다.

Gateway `/health`는 저장소, workflow registry, ComfyUI를 항상 확인하고 `AD_CREATOR_HEALTH_WORKFLOW_ID=model-c-v1`일 때만 기존 model-c도 확인합니다. OpenAI health에서는 published preset registry와 `AdCreatorOpenAIImageGenerate` 노드 등록도 확인하며 응답 필드는 `health_workflow_id`입니다. 이는 실제 생성 기본값을 뜻하지 않습니다. health 성공은 OpenAI credential과 유료 생성 가능 여부를 증명하지 않으므로 실제 low smoke test로 별도 확인합니다.

## 8. 오류 처리

| 상황 | 관찰값 | 백엔드 처리 | 프론트 표시 |
| --- | --- | --- | --- |
| 미지원 preset/조합 | Gateway `400` | 재시도 금지 | 아직 준비 중인 스타일 |
| 잘못된 multipart/파일 | `400`, `413`, `415`, `422` | 입력 수정 전 재시도 금지 | 파일 형식·크기 안내 |
| Gateway 인증 실패 | `401` | 비밀변수/배포 오류로 알림 | 일시적 서비스 오류 |
| 같은 idempotency key에 다른 요청 | `409`, `Retry-After` 없음 | 코드 버그로 기록, 새 자동 생성 금지 | 중복 요청 오류 |
| 최초 제출 진행 중 | `409` + `Retry-After` | 같은 키·같은 요청으로 대기 후 재시도 | 생성 대기 유지 |
| 큐 포화 | `429` + `Retry-After` | 같은 키·같은 요청으로 재시도 | 잠시 대기 안내 |
| 제출 결과 불확실 | `502/503/504` + `detail.generation_id` | 재제출하지 말고 해당 ID 상태 조회 | 생성 대기 유지 |
| OpenAI rate limit/결제/정책 오류 | 작업 `failed` | 자동 유료 재생성 금지, 분류해 운영 로그 기록 | 안전한 일반 오류 문구 |
| ComfyUI 재시작 중 작업 유실 | `unknown` | 자동 재실행 금지 | 상태 확인 또는 수동 재생성 안내 |
| 결과 만료 | `expired` 또는 `410` | 영구 저장 누락 조사 | 수동 재생성 안내 |
| 결과 비율이 4:5가 아님 | 백엔드 통합 검증 실패 | 자르지 말고 실패, 배포 회귀로 알림 | 일시적 서비스 오류 |

OpenAI provider profile의 `automatic_retries`는 파일럿에서 `0`입니다. Gateway 수준의 제출 재시도와 새 OpenAI 유료 생성은 다른 동작이므로 혼동하지 않습니다.

## 9. 자산 배포

첫 파일럿은 파일 수와 크기가 작으므로 preset contract, lighting sheet, 검수된 hint/material board와 manifest를 Git 커밋에 포함합니다.

- 모든 자산 경로는 저장소 루트 기준 상대경로여야 합니다.
- manifest에는 파일 역할, 픽셀 크기, SHA-256, provider 전송 허용 여부를 기록합니다.
- Mac의 `/Users/...` 절대경로나 원본 reference 경로가 런타임 검증 조건으로 남아 있으면 배포하지 않습니다.
- 화이트 authoring reference는 `send_to_provider: false`를 유지합니다.
- 우드 sanitized scene hint만 `send_to_provider: true`인 순서와 역할로 전송합니다. Material board는 `send_to_provider: false`로 고정합니다.
- 추후 GCS로 옮길 때 preset ID와 프롬프트를 바꾸지 말고 asset resolver만 `repo-relative -> gs://... + checksum`으로 교체합니다.
- GCS 객체는 mutable한 `latest` 경로가 아니라 버전 경로와 checksum으로 고정합니다.

## 10. 배포 순서

1. `upstream/comfyui` 기준 신규 커밋을 배포하되 `model-c-v1` 파일과 registry 항목을 유지합니다.
2. 신규 preset/profile/workflow/assets가 모두 Git에 포함됐고 상대경로와 checksum 검증을 통과했는지 확인합니다.
3. GCP ComfyUI 서비스에 `OPENAI_API_KEY`를 주입하고 재시작합니다. 키 값은 출력하지 않습니다.
4. workflow validator, preset validator, unit test, `/object_info` 또는 동등한 노드 등록 검사를 실행합니다.
5. Gateway를 배포하되 기본 workflow는 아직 `model-c-v1`로 둡니다. 기존 health와 model-c smoke test를 확인합니다.
6. 백엔드에 신규 workflow allowlist, `preset_id` 전달, workflow별 4:5 처리를 배포합니다. 기본 workflow는 아직 바꾸지 않습니다.
7. 프론트에 두 항목 활성·10개 비활성·4:5 결과 표시를 배포합니다.
8. 내부 테스트 계정으로 화이트 1회, 우드 1회 실제 `low` 생성 테스트를 수행합니다. 결과 파일은 각각 따로 저장합니다.
9. Gateway DB의 job ID·ComfyUI prompt ID와 audit manifest의 `run_id`, OpenAI `request_id`, `client_request_id`, usage, elapsed time, provider 원본 파일이 한 실행으로 연결되는지 확인합니다.
10. 출력 크기, 단일 제품 수, 잘림, 핵심 로고/라벨, 프리셋 구도·조명을 수동 확인합니다.
11. 통과 후에만 Gateway의 `AD_CREATOR_HEALTH_WORKFLOW_ID`와 Render의 `COMFYUI_WORKFLOW_ID`를 각각 `openai-gpt-image-2-low-v1`로 바꾸고 두 서비스를 재시작합니다.

## 11. 롤백

장애 시 가장 먼저 Render 백엔드의 환경변수만 되돌립니다.

```env
COMFYUI_WORKFLOW_ID=model-c-v1
```

Gateway의 `AD_CREATOR_HEALTH_WORKFLOW_ID`도 `model-c-v1`로 되돌립니다.

그 뒤 백엔드를 재시작하고 `model-c-v1` smoke test를 확인합니다. 신규 workflow, preset 자산, Gateway DB를 삭제하지 않습니다. 진행 중인 신규 작업은 상태를 확인하며 `unknown`/`failed` 작업을 자동 재생성하지 않습니다. 프론트의 활성 항목 정책은 레거시 모델이 실제 지원하는 범위와 맞춰 별도로 되돌립니다.

롤백이 단순 환경변수 전환으로 끝나려면 다음 조건을 지켜야 합니다.

- `model-c-v1` registry와 노드를 덮어쓰지 않는다.
- backend의 4:5 처리는 workflow ID별로 분기하고 레거시 결과 계약을 깨지 않는다.
- Gateway DB schema를 비가역적으로 바꾸지 않는다.
- 신규 preset field는 optional로 추가한다.

## 12. 인수 기준

- [ ] 활성 두 ID만 실제 생성 가능하고 나머지 10개는 유료 호출 전에 거부된다.
- [ ] backend가 Gateway에 canonical `preset_id`를 명시한다.
- [ ] OpenAI 요청은 `gpt-image-2`, `quality=low`이며 사용자 `strength`에 영향받지 않는다.
- [ ] `OPENAI_API_KEY`가 GCP ComfyUI 외부로 노출되지 않는다.
- [ ] 화이트/우드 각각의 lighting sheet, preset contract, 허용 자산과 checksum이 배포된다.
- [ ] 화이트 authoring reference가 provider 입력으로 전송되지 않는다.
- [ ] 우드의 provider 입력에는 sanitized scene hint만 추가되고 material board는 전송되지 않는다.
- [ ] 결과가 `880x1100` PNG이고 정사각형 크롭 없이 표시·다운로드된다.
- [ ] provider 원본 PNG와 audit sidecar가 job ID로 Gateway 기록에 연결되며 prompt·비밀키·원본 경로를 포함하지 않는다.
- [ ] 기존 `model-c-v1` 회귀 테스트와 환경변수 롤백이 통과한다.
- [ ] 실제 저화질 유료 smoke test 두 건의 ComfyUI prompt ID, OpenAI request ID, workflow ID, preset ID, 시간, 결과 파일을 운영 기록에 남긴다. 비밀키와 원본 이미지는 로그에 남기지 않는다.
