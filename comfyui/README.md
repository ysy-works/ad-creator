# Ad Creator ComfyUI 패키징

ComfyUI를 여러 이미지 생성 파이프라인을 선택해 실행하는 오케스트레이션 계층으로 사용합니다.

## 작업 소유권 원칙

> `model-c` 담당자가 작성한 코드와 문서는 수정·이동·이름 변경하지 않는다.

- 기존 `app/`, `presets/`, `scripts/`, `templates_lib/`, 루트 `README.md`는 읽기 전용 의존 대상으로 취급합니다.
- ComfyUI 관련 코드, 워크플로 및 문서는 모두 `comfyui/` 아래에만 추가합니다.
- 기존 모델 호출은 얇은 어댑터가 담당하며, 모델 내부 구현을 직접 고치지 않습니다.
- 모델 측 호출 계약 변경이 필요하면 담당자와 먼저 합의하고 별도 변경으로 진행합니다.

## 실행 구조

```text
프론트엔드
  -> 백엔드 (workflow_id 전달, 기본값: model-c-v1)
    -> 워크플로 레지스트리
      -> model-c-v1  : 현재 FLUX.1 Kontext 파이프라인
      -> openai-v1   : OpenAI 전처리·프롬프트·생성·후처리 파이프라인 (후속)
        -> 결과를 기존 백엔드 응답 형식으로 반환
```

프론트엔드의 워크플로 선택 UI는 초기 범위에서 제외합니다. 백엔드는 기존 생성 요청 필드를 유지하고 `workflow_id`만 추가하며, 값이 없으면 `model-c-v1`을 사용합니다. `model-c` Git 브랜치와 `model-c-v1` 워크플로 ID는 서로 다른 개념입니다.

## 브랜치 역할

| 브랜치 | 역할 |
| --- | --- |
| `frontend` | 업로드·스타일 선택·결과 UI |
| `backend` | 생성 API, `workflow_id` 전달, 결과 응답 |
| `model-c` | 현재 FLUX.1 Kontext 모델 파이프라인 개발 |
| `serving` | 백엔드와 모델 서비스의 기존 연동 |
| `comfyui` | ComfyUI 워크플로, 레지스트리, 커스텀 노드 패키징 |
| `deploy` | 프론트·백엔드·모델 실행 계층 통합 검증 |
| `main` | 검토가 끝난 안정 버전 |

```text
model-c ──> comfyui ──┐
backend ──────────────┼─> deploy ─> main
frontend ─────────────┘
```

`comfyui`는 `model-c`에서 분기합니다. 이후 `model-c`의 구현 변경은 일반적인 merge/PR로 `comfyui`에 동기화해야 하며 자동 반영되지는 않습니다. 기존 입출력 계약을 깨는 변경은 `model-c-v1`을 덮어쓰지 않고 `model-c-v2` 워크플로로 분리합니다.

## 구현된 디렉터리 구조

```text
comfyui/
  .gitignore
  __init__.py
  README.md
  workflows/
    registry.json
    model-c-v1.api.json
    model-c-v1.ui.json

  custom_nodes/
    ad_creator/
      __init__.py
      nodes/
        model_c.py
      adapters/
        model_c.py
      requirements.txt

  orchestrator/
    __init__.py
    workflow_router.py

  scripts/
    validate_workflows.py

  tests/
    test_model_c_adapter.py
    test_node_registration.py
    test_workflow_registry.py
    test_workflow_router.py
```

- `model-c-v1`은 현재 공개된 `app.inference.generate_beverage_image()`를 호출하는 단일 생성 노드입니다.
- 모델 로딩과 추론 세부 구현은 기존 Python 모듈에 그대로 유지하고, 커스텀 노드는 IMAGE 변환과 함수 호출만 담당합니다.
- 모델 경로와 API 키는 워크플로 JSON에 저장하지 않고 환경 변수 또는 배포 설정으로 주입합니다.
- API 실행용 `*.api.json`과 사람이 ComfyUI 화면에서 편집할 `*.ui.json`을 함께 버전 관리합니다.

## 설치 및 실행

현재 어댑터는 model-c Python 모듈을 같은 프로세스에서 직접 호출합니다. ComfyUI와 model-c 의존성이 설치된 하나의 고정된 가상환경에서 실행해야 합니다.

1. `comfyui/custom_nodes/ad_creator`를 실행할 ComfyUI의 `custom_nodes/ad_creator`에 링크하거나 복사합니다.
2. 복사한 경우 저장소 위치를 환경 변수로 지정합니다.

```env
AD_CREATOR_REPO_ROOT=/absolute/path/to/ad-creator
AD_CREATOR_COMFYUI_OUTPUT_DIR=/absolute/path/to/output
```

3. ComfyUI에서 `model-c-v1.ui.json`을 불러옵니다.
4. API 실행 시 이미지를 먼저 ComfyUI의 `/upload/image`로 올린 뒤, `model-c-v1.api.json`의 `__INPUT_IMAGE__`를 반환된 파일명으로 교체해 `/prompt`에 제출합니다.

백엔드 또는 통합 계층에서는 라우터를 사용해 `workflow_id`를 실제 API 워크플로로 변환합니다.

```python
from comfyui.orchestrator import build_prompt, submit_prompt

resolved = build_prompt(
    workflow_id="model-c-v1",  # 생략하면 registry의 기본값 사용
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

알 수 없거나 비활성화된 `workflow_id`는 `UnknownWorkflowError`로 거부합니다. 모델이 만든 중간 PNG는 IMAGE tensor 변환 후 삭제하며, 최종 결과 파일은 ComfyUI `SaveImage` 노드가 한 번만 저장합니다.

워크플로와 등록 정보의 오프라인 검증:

```bash
python comfyui/scripts/validate_workflows.py
python -m unittest discover -s comfyui/tests -v
```

실제 배포 환경에서는 ComfyUI 커밋과 model-c 의존성 버전을 먼저 고정한 뒤 다음 순서로 확인합니다.

```text
ComfyUI --quick-test-for-ci
-> GET /object_info/AdCreatorModelCGenerate
-> model-c-v1 smoke generation 1회
```

## 현재 제약

- 기존 model-c 공개 함수에는 자유 프롬프트와 별도 레퍼런스 이미지 입력이 없습니다. 현재 노드도 해당 기능을 제공하지 않습니다.
- `strength`는 denoise 비율이 아니라 기존 model-c 내부 프롬프트 규칙의 강도입니다.
- Diffusers 파이프라인은 ComfyUI 모델 관리 밖에서 로드되므로 같은 GPU에 다른 대형 모델을 동시에 적재하지 않습니다.
- 기존 model-c 의존성이 넓게 지정되어 있어 실제 배포 전 ComfyUI 버전과의 GPU smoke test가 필요합니다.
- 호환성 문제가 발생하면 model-c를 수정하지 않고 별도 프로세스/API 어댑터로 분리하는 것이 Plan B입니다.

## 워크플로 ID와 버전 규칙

| `workflow_id` | 상태 | 설명 |
| --- | --- | --- |
| `model-c-v1` | 1차 구현·기본값 | 현재 Diffusers 기반 FLUX.1 Kontext 파이프라인 |
| `openai-v1` | 후속 구현 | 전처리·프롬프트 조립·OpenAI 이미지 API·후처리 파이프라인 |

- 내부 모델명이나 호환 가능한 설정만 바뀌면 같은 워크플로 ID를 유지합니다.
- 노드 연결, 필수 입력, 결과 계약이 바뀌면 새 버전 ID를 추가합니다.
- 1차 MVP는 `model-c-v1` 하나를 끝까지 실행하고 검증한 뒤 `openai-v1`을 추가합니다.

## 패키징 순서

1. ~~기존 `model-c` 추론 함수를 수정하지 않고 어댑터로 연결~~
2. ~~`model-c-v1` UI/API 워크플로와 레지스트리 생성~~
3. ~~모델을 로드하지 않는 오프라인 단위 테스트~~
4. ComfyUI가 설치된 GPU 환경에서 smoke generation 1회
5. 백엔드의 `workflow_id=model-c-v1` 요청과 통합 검증
6. GPU 배포 환경에서 end-to-end 검증 후 `deploy`에 병합
7. 검증이 끝난 뒤 `openai-v1` 추가

참고: [Workflow API Format](https://docs.comfy.org/development/api-development/workflow-api-format), [Custom Nodes](https://docs.comfy.org/custom-nodes/overview), [Images, Latents, and Masks](https://docs.comfy.org/custom-nodes/backend/images_and_masks)
