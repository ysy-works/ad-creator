# Backend handoff: ComfyUI Gateway v1

백엔드는 ComfyUI `8188`이나 model-c `8001`을 직접 호출하지 않고 HTTPS Gateway만 호출합니다.

## 환경변수

```env
COMFYUI_GATEWAY_BASE_URL=https://GATEWAY_HOSTNAME
COMFYUI_GATEWAY_API_KEY=GCP에서-별도-전달받은-키
COMFYUI_WORKFLOW_ID=model-c-v1
```

API 키는 Render 서버 환경변수에만 저장하고 브라우저·프론트엔드·Git·로그에 넣지 않습니다.

## 생성 요청

```http
POST {COMFYUI_GATEWAY_BASE_URL}/v1/generations
Authorization: Bearer {COMFYUI_GATEWAY_API_KEY}
Idempotency-Key: {one-UUID-per-user-generation-action}
```

HTTP 라이브러리가 `multipart/form-data`의 boundary를 만들도록 두고 `Content-Type`을 직접 지정하지 않습니다.
백엔드는 사용자 생성 동작마다 새 UUID를 만들고 저장합니다. 같은 논리 요청을 재시도할 때는 이미지와 모든 필드를 바꾸지 않고 같은 키를 재사용하며, 사용자가 명시적으로 재생성할 때만 새 키를 발급합니다.

| 필드 | 필수 | 값 |
| --- | --- | --- |
| `image` | 예 | JPEG, PNG, WebP / 최대 20 MiB, 4천만 픽셀 |
| `workflow_id` | 아니요 | 기본 `model-c-v1` |
| `composition` | 아니요 | `closeup`, `medium`, `aerial`, `handheld` / 기본 `medium` |
| `background_style` | 아니요 | `white`, `wood`, `vivid` / 기본 `wood` |
| `strength` | 아니요 | `low`, `medium`, `high` / 기본 `medium` |
| `seed` | 아니요 | `-1` 또는 0~2147483647. 생략하면 랜덤 |

기존 레퍼런스 매핑은 그대로 유지합니다.

```text
natural_white       -> white
wood                -> wood
vivid               -> vivid
product_large       -> closeup
product_center      -> medium
aerial_shot         -> aerial
handheld_lifestyle  -> handheld
```

정상 응답은 `202 Accepted`입니다.

```json
{
  "generation_id": "signed-token",
  "workflow_id": "model-c-v1",
  "status": "queued",
  "status_url": "/v1/generations/signed-token",
  "result_url": "/v1/generations/signed-token/result"
}
```

`status_url`과 `result_url`은 상대 경로이므로 `COMFYUI_GATEWAY_BASE_URL`과 결합합니다.

## 상태 조회

```http
GET {COMFYUI_GATEWAY_BASE_URL}/v1/generations/{generation_id}
Authorization: Bearer {COMFYUI_GATEWAY_API_KEY}
```

```json
{
  "generation_id": "signed-token",
  "workflow_id": "model-c-v1",
  "status": "queued"
}
```

상태는 다음과 같습니다.

- `queued`: 대기 중
- `running`: 생성 중
- `succeeded`: 결과 다운로드 가능
- `failed`: 생성 실패, `error` 확인
- `unknown`: ComfyUI 재시작 등으로 실행 상태를 확인할 수 없음
- `expired`: 보관 기간이 지나 결과 파일 삭제

2초 간격으로 시작해 최대 5초 간격으로 폴링합니다. `failed`, `unknown`, `expired`는 자동으로 같은 요청을 재실행하지 않습니다.

## 결과 다운로드

```http
GET {COMFYUI_GATEWAY_BASE_URL}/v1/generations/{generation_id}/result
Authorization: Bearer {COMFYUI_GATEWAY_API_KEY}
```

응답 본문은 생성 이미지 바이너리입니다. 성공 즉시 백엔드의 영구 파일 저장소로 복사합니다. Gateway 출력 파일은 7일 후 정리됩니다.

## 오류 처리

| HTTP | 의미 | 처리 |
| --- | --- | --- |
| `401` | API 키 오류 | 서버 환경변수 확인 |
| `400` | 잘못된 idempotency key 또는 workflow/옵션 값 | 요청 형식 수정 |
| `404` | 잘못된 generation ID | 요청 종료 |
| `409` | 결과 조회 시 아직 완료되지 않음 | 상태 재조회 |
| `409` + `Retry-After: 2` | 같은 idempotency key의 최초 제출이 아직 진행 중 | `Retry-After` 이후 같은 키·같은 요청으로 POST 재시도 |
| `409` | 같은 idempotency key에 다른 입력 사용 | 요청 버그 수정. 기존 키 재사용 금지 |
| `410` | 결과 만료 | 사용자에게 재생성 안내 |
| `413`, `415`, `422` | 입력 오류 | 사용자 입력 수정 |
| `429` | 생성 큐 가득 참 | `Retry-After` 이후 같은 키·같은 요청으로 재시도 |
| `502`, `503`, `504` | 내부 서비스 오류 | 응답 JSON의 `detail.generation_id`가 있으면 저장 후 상태 조회. 없으면 같은 키·같은 요청으로 재시도 |

동일한 `Idempotency-Key`와 동일한 요청은 기존 `generation_id`를 반환하므로 네트워크 재시도로 중복 생성되지 않습니다. 같은 키에 이미지나 옵션이 달라지면 `409`를 반환합니다. `unknown` 작업은 자동 재실행하지 말고 사용자에게 상태를 안내합니다.

## Health check

```http
GET {COMFYUI_GATEWAY_BASE_URL}/health
```

```json
{
  "ok": true,
  "storage": true,
  "comfyui": true,
  "model_c": true
}
```
