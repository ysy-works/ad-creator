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

## 목표 디렉터리 구조

```text
comfyui/
  README.md
  workflows/
    registry.json
    model-c-v1.api.json
    model-c-v1.ui.json
    # openai-v1.*.json은 후속 단계에서 추가

  custom_nodes/
    ad_creator/
      __init__.py
      nodes/
        input.py
        prompt.py
        model_c.py
        postprocess.py
      adapters/
        model_c.py
      requirements.txt

  scripts/
    validate_workflows.py
```

- 노드는 입력·전처리, 프롬프트 조립, 생성 provider, 후처리처럼 실제로 켜고 끄거나 교체할 경계만 분리합니다.
- 모델 로딩과 추론 세부 구현은 기존 Python 모듈에 유지하고, 커스텀 노드는 이를 호출하는 얇은 어댑터로 둡니다.
- 모델 경로와 API 키는 워크플로 JSON에 저장하지 않고 환경 변수 또는 배포 설정으로 주입합니다.
- API 실행용 `*.api.json`과 사람이 ComfyUI 화면에서 편집할 `*.ui.json`을 함께 버전 관리합니다.

## 워크플로 ID와 버전 규칙

| `workflow_id` | 상태 | 설명 |
| --- | --- | --- |
| `model-c-v1` | 1차 구현·기본값 | 현재 Diffusers 기반 FLUX.1 Kontext 파이프라인 |
| `openai-v1` | 후속 구현 | 전처리·프롬프트 조립·OpenAI 이미지 API·후처리 파이프라인 |

- 내부 모델명이나 호환 가능한 설정만 바뀌면 같은 워크플로 ID를 유지합니다.
- 노드 연결, 필수 입력, 결과 계약이 바뀌면 새 버전 ID를 추가합니다.
- 1차 MVP는 `model-c-v1` 하나를 끝까지 실행하고 검증한 뒤 `openai-v1`을 추가합니다.

## 패키징 순서

1. 기존 `model-c` 추론 함수를 수정하지 않고 어댑터로 연결
2. `model-c-v1` UI/API 워크플로와 레지스트리 생성
3. 로컬에서 입력 이미지부터 결과 저장까지 smoke test
4. 백엔드의 `workflow_id=model-c-v1` 요청과 통합 검증
5. GPU 배포 환경에서 end-to-end 검증 후 `deploy`에 병합
6. 검증이 끝난 뒤 `openai-v1` 추가

참고: [ComfyUI 공식 문서](https://docs.comfy.org/), [Custom Nodes 공식 문서](https://docs.comfy.org/development/core-concepts/custom-nodes)
