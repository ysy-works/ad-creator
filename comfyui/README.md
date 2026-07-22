# Ad Creator ComfyUI 패키지

여러 이미지 생성 파이프라인을 `workflow_id`로 선택해 실행하기 위한 ComfyUI 계층입니다.

> `model-c`의 기존 코드·문서·브랜치·이름은 수정하지 않습니다. 이 패키지의 변경 범위는 `comfyui/`뿐입니다.

## 실행 구조

```text
Frontend
  -> Backend (workflow_id 전달, 기본값: model-c-v1)
    -> HTTPS Generation Gateway (Bearer 인증)
      -> ComfyUI /upload/image + /prompt
      -> workflow registry
        -> model-c-v1 custom node -> 기존 model-c HTTP API
        -> openai-gpt-image-2-low-v1 custom node -> OpenAI Images API
      -> ComfyUI SaveImage
    <- generation_id / 상태 / 결과
```

ComfyUI와 `model-c`는 **별도 프로세스·별도 Python 환경**으로 실행합니다. OpenAI 파일럿은 ComfyUI 프로세스가 직접 API를 호출하며 `OPENAI_API_KEY`는 그 프로세스에만 주입합니다.

## 브랜치 역할

```text
model-c ──────────────┐
comfyui ──────────────┤
backend ──────────────┼─> deploy ─> main
frontend ─────────────┘
```

| 브랜치 | 역할 |
| --- | --- |
| `frontend` | 이미지 업로드·옵션 선택·결과 UI |
| `backend` | 생성 API, `workflow_id` 전달, 결과 응답 |
| `model-c` | 기존 FLUX.1 Kontext 모델 파이프라인 개발 원본 |
| `serving` | 기존 백엔드·모델 서빙 연동 |
| `comfyui` | 워크플로, 레지스트리, 커스텀 노드, 호출 어댑터 |
| `deploy` | 프론트·백엔드·ComfyUI·모델 통합 검증 |
| `main` | 검증 완료된 안정 버전 |

`model-c` 변경이 필요할 때는 해당 브랜치를 직접 고치지 않습니다. 기존 HTTP 계약을 유지하면 ComfyUI 수정도 필요 없고, 계약이 달라지면 `model-c-v2`처럼 새 워크플로를 추가합니다.

## 디렉터리

```text
comfyui/
  workflows/
    registry.json
    model-c-v1.api.json
    model-c-v1.ui.json
    openai-gpt-image-2-low-v1.api.json
    openai-gpt-image-2-low-v1.ui.json
  presets/
    registry.json
    natural_white__product_center/
    wood__product_center/
    wood__product_center_a6/
  custom_nodes/ad_creator/
    nodes/model_c.py
    nodes/openai_image.py
    adapters/model_c.py
    adapters/openai_image.py
  orchestrator/workflow_router.py
  scripts/validate_workflows.py
  tests/
```

- `registry.json`: 기본 워크플로와 ID별 API/UI JSON 경로
- `*.api.json`: 백엔드가 `/prompt`에 제출하는 실행용 워크플로
- `*.ui.json`: ComfyUI 화면에서 불러와 확인하는 편집용 워크플로
- `nodes/model_c.py`: ComfyUI IMAGE와 model-c HTTP 응답 이미지 간 변환
- `adapters/model_c.py`: 기존 `/generate`, `/outputs/{filename}` 계약 호출
- `workflow_router.py`: `workflow_id` 검증, 입력 치환, ComfyUI 제출

## 현재 model-c-v1 계약

ComfyUI 노드는 기존 model-c API가 공개한 값만 전달합니다.

```text
POST /generate (multipart/form-data)
- image
- composition: closeup | medium | aerial | handheld
- background_style: vivid | wood | white
- strength: low | medium | high
- seed: 선택
```

`guidance_scale`, `steps`, `width`, `height`, 자유 프롬프트, 별도 레퍼런스 이미지는 현재 API 계약에 없으므로 임의로 노출하지 않습니다.

## OpenAI GPT Image 2 low 파일럿

`openai-gpt-image-2-low-v1`은 `gpt-image-2`, `quality=low`를 서버 profile에서 고정합니다. 프리셋은 현재 여러 작업 환경에서 수정·추가·시각 검증 중이며, 검증을 통과한 항목부터 registry에 순차 반영됩니다. README에 published 개수를 고정하지 않고 `presets/registry.json`의 현재 상태와 활성 여부를 기준으로 합니다. 기존 대안 프리셋은 실행 의존성과 비교 검증을 위해 삭제하지 않습니다. `aspect_ratio=4:5`는 `1024x1280` 생성 후 무크롭 `880x1100`, `aspect_ratio=1:1`은 처음부터 `1024x1024`로 생성합니다. 1:1은 시각 QA 전까지 공개 UI에서 숨깁니다.

제품 원본은 기본적으로 EXIF·파일명을 제거하고 긴 변 1536px까지만 축소하며 작은 사진은 확대하지 않습니다. 비용·OCR·제품 보존 비교 시에만 `AD_CREATOR_OPENAI_SOURCE_MAX_EDGE=3072`를 명시합니다.

각 성공 실행은 Gateway job ID와 연결된 provider 원본 PNG 및 JSON audit manifest를 `output/ad_creator/audit`에 별도 저장합니다. manifest에는 preset/profile/prompt/input hash, OpenAI·client request ID, usage, 소요 시간과 결과 hash만 기록하며 prompt 본문, 비밀키, 사용자 원본 파일과 로컬 경로는 기록하지 않습니다.

정확한 백엔드·프론트 계약과 전환 순서는 `deploy/OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md`, 장기 구조는 `deploy/COMFYUI_REDESIGN_PLAN_KO.md`를 따릅니다.

## 실행 설정

model-c 서버는 GCP에서 기존 환경으로 실행하고, ComfyUI에는 내부 주소만 주입합니다.

```env
AD_CREATOR_MODEL_C_URL=http://127.0.0.1:8001
AD_CREATOR_MODEL_C_TIMEOUT_SECONDS=420
OPENAI_API_KEY=서버에서만-주입
OPENAI_IMAGE_TIMEOUT_SECONDS=1200
AD_CREATOR_OPENAI_AUDIT_DIR=/opt/comfyui/ComfyUI/output/ad_creator/audit
AD_CREATOR_OPENAI_SOURCE_MAX_EDGE=1536
```

- 같은 VM이면 loopback 주소를 사용합니다.
- 다른 VM/서비스이면 외부 공개 URL 대신 GCP 내부 IP 또는 인증된 내부 주소를 사용합니다.
- 현재 model-c의 `0.0.0.0:8001` 바인딩과 기존 방화벽은 변경하지 않으며, ComfyUI는 같은 VM의 `127.0.0.1:8001`로만 호출합니다.

ComfyUI는 재현 가능한 검증 기준으로 공식 `v0.28.0`을 고정합니다.

```text
ComfyUI tag: v0.28.0
commit: 700821e1364eaab0e8f21c538a2131719fec57bf
```

`comfyui/custom_nodes/ad_creator`를 ComfyUI의 `custom_nodes/ad_creator`에 심볼릭 링크로 연결한 뒤 실행합니다. 프리셋과 provider profile을 함께 찾기 위해 디렉터리만 따로 복사하는 설치 방식은 지원하지 않습니다.

## 백엔드 호출 예시

```python
from comfyui.orchestrator import build_prompt, submit_prompt

resolved = build_prompt(
    workflow_id="model-c-v1",
    values={
        "source_image": "uploads/request.png",
        "composition": "medium",
        "background_style": "wood",
        "strength": "medium",
        "seed": 42,
    },
)
queued = submit_prompt(
    server_url="http://127.0.0.1:8188",
    resolved_workflow=resolved,
)
```

API 실행 전 입력 이미지는 ComfyUI `/upload/image`에 업로드합니다. 반환된 파일명을 워크플로의 `source_image`로 전달한 뒤 `/prompt`에 제출합니다.

## Generation Gateway

Render 백엔드는 ComfyUI의 8188 포트를 직접 호출하지 않습니다. GCP에서 함께 실행되는 Gateway만 HTTPS로 호출합니다.

```text
POST /v1/generations
GET  /v1/generations/{generation_id}
GET  /v1/generations/{generation_id}/result
GET  /health
```

모든 `/v1/*` 요청에는 다음 인증 헤더가 필요합니다.

```http
Authorization: Bearer ${COMFYUI_GATEWAY_API_KEY}
```

생성 `POST`에는 추가로 요청별 키가 필요합니다.

```http
Idempotency-Key: ${ONE_UUID_PER_USER_GENERATION_ACTION}
```

생성 요청은 `multipart/form-data`입니다. HTTP 라이브러리가 multipart boundary를 만들도록 두고 `Content-Type`을 직접 지정하지 않습니다. 같은 논리 요청을 재시도할 때는 동일한 idempotency key와 동일한 입력을 사용하고, 사용자가 명시적으로 재생성할 때만 새 키를 발급합니다.

```text
image              JPEG | PNG | WebP, 최대 20 MiB
workflow_id        기본 model-c-v1
composition        closeup | medium | aerial | handheld
background_style   vivid | wood | white
strength           low | medium | high
seed               선택 정수
preset_id          OpenAI workflow에서 canonical service preset ID
aspect_ratio       4:5(기본) | 1:1
```

Gateway는 업로드 후 즉시 `202 Accepted`와 서명된 `generation_id`를 반환합니다. 백엔드는 상태 URL을 폴링하고 `succeeded`가 되면 결과 URL을 내려받습니다.

```json
{
  "generation_id": "signed-job-token",
  "workflow_id": "model-c-v1",
  "status": "queued",
  "status_url": "/v1/generations/signed-job-token",
  "result_url": "/v1/generations/signed-job-token/result"
}
```

상태값은 `queued`, `running`, `succeeded`, `failed`, `unknown`, `expired` 중 하나입니다. Gateway의 SQLite에는 ComfyUI prompt, workflow, 상태와 완료 이미지 위치를 저장하고 실제 이미지는 ComfyUI 출력 폴더에 둡니다. `generation_id`에는 불투명한 job ID만 포함하며 별도 HMAC 키로 서명해 위변조를 거부합니다.

- Gateway만 재시작하면 SQLite와 ComfyUI 상태를 사용해 계속 조회합니다.
- ComfyUI 또는 VM이 실행 중 작업 도중 재시작되면 해당 작업은 재개되지 않으며 `unknown`으로 남을 수 있습니다.
- 완료 작업은 SQLite에 저장된 파일 위치로 다시 조회할 수 있지만 출력 파일은 7일 후 정리됩니다. 백엔드는 성공 직후 결과를 영구 저장소로 복사합니다.
- `POST` 응답을 받지 못한 경우 같은 idempotency key와 동일한 입력으로 재시도합니다. 같은 키에 다른 입력을 보내면 `409`를 반환하며, `unknown` 작업은 자동 재실행하지 않습니다.

Gateway 실행 환경 변수:

```env
COMFYUI_BASE_URL=http://127.0.0.1:8188
AD_CREATOR_MODEL_C_URL=http://127.0.0.1:8001
AD_CREATOR_GATEWAY_API_KEY=32자-이상의-랜덤-비밀키
AD_CREATOR_GENERATION_SIGNING_KEY=API-키와-다른-32자-이상의-비밀키
AD_CREATOR_GATEWAY_DB=/var/lib/ad-creator-gateway/gateway.sqlite3
AD_CREATOR_MAX_QUEUED=3
AD_CREATOR_HEALTH_WORKFLOW_ID=model-c-v1
```

Gateway는 다음처럼 로컬에서 실행합니다.

```bash
uvicorn comfyui.gateway.app:app --host 127.0.0.1 --port 8002 --workers 1
```

## GCP 배포 구조

```text
Internet :443
  -> Caddy (자동 HTTPS)
    -> Gateway 127.0.0.1:8002
      -> ComfyUI 127.0.0.1:8188 (CPU 전용)
        -> model-c의 기존 0.0.0.0:8001 서비스에 loopback으로 호출
```

```text
/opt/ad-creator/                 comfyui 브랜치 체크아웃
/opt/comfyui/ComfyUI/           공식 ComfyUI v0.28.0
/opt/venv/comfyui/              독립 CPU Python 환경
/etc/ad-creator/comfyui.env     내부 모델 주소
/etc/ad-creator/gateway.env     Gateway 주소와 비밀키
/var/lib/ad-creator-gateway/    작업 상태 SQLite
```

- `model-c` 코드, 가상환경, 실행 사용자와 포트는 변경하지 않습니다.
- ComfyUI와 Gateway는 `spai0813` 사용자로 별도 systemd 서비스에서 실행합니다.
- ComfyUI 8188과 Gateway 8002는 loopback에만 바인딩합니다.
- 신규 ComfyUI/Gateway는 Caddy의 80/443으로만 공개하고 8002/8188은 열지 않습니다. 기존 model-c 8001의 바인딩과 방화벽은 변경하지 않습니다.
- Caddy는 요청 본문을 22 MB로 제한합니다.
- `input/ad_creator`는 1일, `output/ad_creator`는 7일 기준으로 systemd-tmpfiles가 정리합니다.
- 서비스 템플릿과 환경변수 예시는 `comfyui/deploy/`에 있습니다.

## 검증

```bash
python comfyui/scripts/validate_workflows.py
python comfyui/scripts/validate_presets.py
python -B -m unittest discover -s comfyui/tests -v
```

GCP GPU 환경에서는 다음 순서로 확인합니다.

```text
model-c GET /health
-> ComfyUI custom node 등록 확인
-> GET /object_info/AdCreatorModelCGenerate
-> model-c-v1 이미지 1장 smoke test
-> Backend workflow_id=model-c-v1 통합 테스트
-> deploy 브랜치에서 전체 E2E 검증
```

기존 model-c API는 결과 이미지를 자체 출력 폴더에도 저장하고 ComfyUI의 `SaveImage`도 최종 결과를 저장합니다. 배포 시 model-c 출력 폴더는 임시 저장소로 운영하거나 정리 정책을 둡니다.

## 버전 규칙

| `workflow_id` | 상태 | 설명 |
| --- | --- | --- |
| `model-c-v1` | 현재 기본값 | 기존 NF4 API 파이프라인 |
| `openai-gpt-image-2-low-v1` | 두 프리셋 파일럿 | GPT Image 2 low·4:5 파이프라인 |

- 모델의 내부 구현만 바뀌고 입출력 계약이 같으면 같은 ID를 유지합니다.
- 필수 입력, 노드 연결, 결과 계약이 바뀌면 새 ID를 추가합니다.
- 새 워크플로는 기존 JSON을 덮어쓰지 않고 레지스트리에 병렬 추가합니다.

참고: [Workflow API Format](https://docs.comfy.org/development/api-development/workflow-api-format), [Custom Nodes](https://docs.comfy.org/custom-nodes/overview), [Server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
