import io
import os
import time
import uuid

import requests
from PIL import Image

# --- 기존 (기현님 GCP 직접 호출, 참고용으로만 보존 — 지금은 사용 안 함) ---
MODEL_API_URL = os.environ.get("MODEL_API_URL", "http://136.65.68.28:8001")

# --- ComfyUI Gateway (팀장 제공, BACKEND_HANDOFF.md 스펙) ---
# 값은 절대 코드에 직접 쓰지 않고 항상 환경변수로만 읽는다.
# 로컬: .env 파일 (.gitignore에 이미 포함되어 있어 커밋되지 않음)
# 배포: Render 대시보드의 환경변수 설정에 동일하게 등록해야 함.
GATEWAY_BASE_URL = os.environ.get("COMFYUI_GATEWAY_BASE_URL", "")
GATEWAY_API_KEY = os.environ.get("COMFYUI_GATEWAY_API_KEY", "")

MODEL_C_WORKFLOW_ID = "model-c-v1"
# 2026-07-21 팀장 인계서(OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md) 기준 신규 워크플로.
OPENAI_WORKFLOW_ID = "openai-gpt-image-2-low-v1"

# 서비스 기본 workflow는 코드 상수가 아니라 환경변수로 선택 (인계서 5번-2).
# 아직 미전환 상태이므로 기본값은 계속 model-c-v1 — 검증 끝난 뒤 배포 환경변수만 바꾼다.
DEFAULT_WORKFLOW_ID = os.environ.get("COMFYUI_WORKFLOW_ID", MODEL_C_WORKFLOW_ID)

# openai-gpt-image-2-low-v1에서 실제로 생성 가능한 preset_id (= 프론트 reference_id).
# 나머지는 유료 provider 호출 전에 차단한다.
# 2026-07-24 소연님 검증 완료분 반영: 화이트 4종 + 우드 3종(핸드헬드 제외) 총 7개.
# wood__handheld_lifestyle과 다크그레이(vivid) 4종은 아직 미검증이라 계속 비활성.
OPENAI_ACTIVE_PRESET_IDS = {
    "natural_white__product_large",
    "natural_white__product_center",
    "natural_white__aerial_shot",
    "natural_white__handheld_lifestyle",
    "wood__product_large",
    "wood__product_center",
    "wood__aerial_shot",
}

# references.json의 mood_id/composition_id -> 모델 API가 요구하는 값으로 변환
MOOD_TO_BACKGROUND_STYLE = {
    "natural_white": "white",
    "wood": "wood",
    "vivid": "vivid",
}

COMPOSITION_MAP = {
    "product_large": "closeup",
    "product_center": "medium",
    "aerial_shot": "aerial",
    "handheld_lifestyle": "handheld",
}


def _submit_generation(headers: dict, files: dict, data: dict, max_attempts: int = 4) -> dict:
    """
    POST /v1/generations 제출.
    같은 Idempotency-Key로 재시도해야 하는 상황(429, 409+Retry-After,
    502/503/504)을 BACKEND_HANDOFF.md 표에 따라 처리한다.
    """
    url = f"{GATEWAY_BASE_URL.rstrip('/')}/v1/generations"

    for attempt in range(max_attempts):
        response = requests.post(url, headers=headers, files=files, data=data, timeout=30)

        if response.status_code == 202:
            return response.json()

        if response.status_code == 401:
            raise RuntimeError("ComfyUI Gateway 인증 실패 (API 키를 확인해주세요).")

        if response.status_code == 409:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                # 같은 Idempotency-Key의 최초 제출이 아직 진행 중 -> 잠깐 기다렸다가 같은 요청 재시도
                time.sleep(float(retry_after))
                continue
            # Retry-After 없이 409면 같은 키에 다른 입력을 보낸 경우 -> 재시도해도 의미 없음
            raise RuntimeError(f"생성 요청 충돌(Idempotency-Key 재사용 오류): {response.text[:300]}")

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 3))
            time.sleep(retry_after)
            continue

        if response.status_code in (502, 503, 504):
            generation_id = None
            try:
                body = response.json()
                generation_id = (body.get("detail") or {}).get("generation_id")
            except ValueError:
                pass
            if generation_id:
                # 요청 자체는 접수됐을 수 있으니, 새로 제출하지 않고 상태부터 조회
                return {
                    "generation_id": generation_id,
                    "workflow_id": data.get("workflow_id"),
                    "status": "queued",
                    "status_url": f"/v1/generations/{generation_id}",
                    "result_url": f"/v1/generations/{generation_id}/result",
                }
            time.sleep(2)
            continue

        # 400/413/415/422 등 입력 자체가 잘못된 경우는 재시도해도 소용없음
        raise RuntimeError(f"생성 요청 실패 ({response.status_code}): {response.text[:300]}")

    raise RuntimeError("생성 요청이 반복적으로 실패했습니다 (재시도 한도 초과).")


def _wait_until_done(status_url: str, headers: dict, max_wait_seconds: int = 420) -> None:
    """
    2초 간격으로 시작해 최대 5초 간격까지 늘려가며 상태를 폴링.
    failed/unknown/expired는 자동 재실행하지 않고 바로 에러로 처리.
    """
    elapsed = 0
    interval = 2

    while elapsed < max_wait_seconds:
        response = requests.get(status_url, headers=headers, timeout=15)
        response.raise_for_status()
        body = response.json()
        status = body.get("status")

        if status == "succeeded":
            return
        if status in ("failed", "unknown", "expired"):
            raise RuntimeError(f"이미지 생성 실패 (status={status}): {body.get('error', '알 수 없는 오류')}")

        time.sleep(interval)
        elapsed += interval
        interval = min(interval + 1, 5)

    raise RuntimeError("이미지 생성이 제한 시간 내에 끝나지 않았습니다.")


def _generate_with_model_c_v1(product_image: Image.Image, reference: dict, aspect_ratio: str = None, cup_source: str = None) -> Image.Image:
    """
    model-c-v1 워크플로 — ComfyUI Gateway 경유 (팀장 제공 BACKEND_HANDOFF.md 스펙).

    흐름: POST로 생성 요청 제출(202) -> status_url 폴링 -> succeeded 되면
    result_url에서 이미지 바이너리 다운로드.
    router.py 입장에서 보이는 함수 시그니처/반환값(PIL Image, 실패 시 예외)은
    이전 GCP 직접 호출 버전과 동일하게 유지 — 워크플로가 뭐든 응답 형식은 안 바뀜.
    """
    if not GATEWAY_BASE_URL or not GATEWAY_API_KEY:
        raise RuntimeError(
            "ComfyUI Gateway 환경변수가 설정되지 않았습니다 "
            "(COMFYUI_GATEWAY_BASE_URL / COMFYUI_GATEWAY_API_KEY 확인 필요)."
        )

    background_style = MOOD_TO_BACKGROUND_STYLE[reference["mood_id"]]
    composition = COMPOSITION_MAP[reference["composition_id"]]

    buffer = io.BytesIO()
    product_image.save(buffer, format="PNG")
    buffer.seek(0)

    # 사용자가 "이미지 생성"을 누른 이 동작 하나당 새 Idempotency-Key 하나.
    # 아래 _submit_generation 안에서 벌어지는 재시도는 전부 이 같은 키를 재사용한다
    # (같은 논리 요청의 재시도이지, 새 생성 요청이 아니므로).
    idempotency_key = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {GATEWAY_API_KEY}",
        "Idempotency-Key": idempotency_key,
    }
    files = {"image": ("product.png", buffer, "image/png")}
    data = {
        "workflow_id": MODEL_C_WORKFLOW_ID,
        "composition": composition,
        "background_style": background_style,
        "strength": "medium",
    }
    # multipart boundary는 requests가 자동으로 만들게 두고 Content-Type을 직접 지정하지 않음

    submitted = _submit_generation(headers, files, data)

    status_url = f"{GATEWAY_BASE_URL.rstrip('/')}{submitted['status_url']}"
    result_url = f"{GATEWAY_BASE_URL.rstrip('/')}{submitted['result_url']}"

    _wait_until_done(status_url, headers)

    image_response = requests.get(result_url, headers=headers, timeout=60)
    image_response.raise_for_status()

    return Image.open(io.BytesIO(image_response.content)).convert("RGB")


def _generate_with_model_c_v1_legacy_direct(product_image: Image.Image, reference: dict) -> Image.Image:
    """
    예전 방식 (기현님 GCP 서버 136.65.68.28:8001 직접 호출).
    ComfyUI Gateway로 전환하면서 더 이상 쓰지 않지만, 문제 생기면 롤백할 수 있도록
    보존만 해둠. WORKFLOW_REGISTRY에는 등록하지 않음.
    """
    background_style = MOOD_TO_BACKGROUND_STYLE[reference["mood_id"]]
    composition = COMPOSITION_MAP[reference["composition_id"]]

    buffer = io.BytesIO()
    product_image.save(buffer, format="PNG")
    buffer.seek(0)

    files = {"image": ("product.png", buffer, "image/png")}
    data = {
        "composition": composition,
        "background_style": background_style,
        "strength": "medium",
    }

    response = requests.post(
        f"{MODEL_API_URL}/generate",
        files=files,
        data=data,
        timeout=420,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("success"):
        raise RuntimeError(f"모델 서버 생성 실패: {result}")

    image_url = f"{MODEL_API_URL}{result['image_url']}"
    image_response = requests.get(image_url, timeout=30)
    image_response.raise_for_status()

    return Image.open(io.BytesIO(image_response.content)).convert("RGB")


VALID_ASPECT_RATIOS = {"4:5", "1:1"}


def _generate_with_openai_gpt_image_2_low(product_image: Image.Image, reference: dict, aspect_ratio: str = None, cup_source: str = None) -> Image.Image:
    """
    openai-gpt-image-2-low-v1 워크플로.

    2026-07-21 팀장 인계서(OPENAI_GPT_IMAGE_2_PILOT_HANDOFF_KO.md) 반영, 이후
    2026-07-23 팀장 정정사항 반영:
    model-c-v1과 달리 background_style/composition/strength/seed를 보내지 않고,
    Gateway의 canonical preset_id에 프론트 reference_id를 그대로 전달한다.
    현재는 natural_white__product_center, wood__product_center 두 개만 활성 —
    나머지 10개는 유료 provider 호출 전에 차단(ValueError -> router.py에서 400).

    aspect_ratio는 "4:5" 또는 "1:1" 중 하나가 반드시 있어야 함 (프론트가 사용자
    선택을 강제하므로 항상 채워져서 옴). provider가 4:5는 1024x1280,
    1:1은 1024x1024를 무크롭으로 그대로 반환 — 백엔드는 리사이즈/크롭을
    전혀 하지 않는다 (router.py의 workflow별 분기 참고. 예전엔 4:5를
    880x1100으로 축소했었는데, 그 축소 단계 자체가 없어졌음).

    cup_source는 "uploaded"(업로드한 컵 그대로) 또는 "model"(모델이 준비한
    컵으로 교체). 2026-07-24 소연님 회의 요청사항인데, Gateway/모델 쪽 정확한
    파라미터명·스타일별 지원 여부가 아직 확정 전이라 값이 있으면 그대로
    실어 보내기만 하고 검증은 하지 않는다. 계약 확정되면 OPENAI_ACTIVE_PRESET_IDS
    처럼 preset_id별 유효성 검증을 추가할 예정.
    """
    if not GATEWAY_BASE_URL or not GATEWAY_API_KEY:
        raise RuntimeError(
            "ComfyUI Gateway 환경변수가 설정되지 않았습니다 "
            "(COMFYUI_GATEWAY_BASE_URL / COMFYUI_GATEWAY_API_KEY 확인 필요)."
        )

    preset_id = reference["id"]
    if preset_id not in OPENAI_ACTIVE_PRESET_IDS:
        raise ValueError(f"아직 지원하지 않는 스타일입니다: {preset_id}")

    if aspect_ratio not in VALID_ASPECT_RATIOS:
        raise ValueError("결과 비율(4:5 또는 1:1)을 선택해주세요.")

    buffer = io.BytesIO()
    product_image.save(buffer, format="PNG")
    buffer.seek(0)

    # 사용자가 "이미지 생성"을 누른 이 동작 하나당 새 Idempotency-Key 하나 (기존과 동일 원칙).
    idempotency_key = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {GATEWAY_API_KEY}",
        "Idempotency-Key": idempotency_key,
    }
    files = {"image": ("product.png", buffer, "image/png")}
    data = {
        "workflow_id": OPENAI_WORKFLOW_ID,
        "preset_id": preset_id,
        "aspect_ratio": aspect_ratio,
    }
    if cup_source:
        data["cup_source"] = cup_source

    submitted = _submit_generation(headers, files, data)

    status_url = f"{GATEWAY_BASE_URL.rstrip('/')}{submitted['status_url']}"
    result_url = f"{GATEWAY_BASE_URL.rstrip('/')}{submitted['result_url']}"

    _wait_until_done(status_url, headers)

    image_response = requests.get(result_url, headers=headers, timeout=60)
    image_response.raise_for_status()

    return Image.open(io.BytesIO(image_response.content)).convert("RGB")


# workflow_id -> 실제 호출 함수. 새 워크플로가 추가되면 여기 한 줄만 등록하면 됨.
WORKFLOW_REGISTRY = {
    "model-c-v1": _generate_with_model_c_v1,
    OPENAI_WORKFLOW_ID: _generate_with_openai_gpt_image_2_low,
}


def resolve_workflow_id(workflow_id: str = None) -> str:
    """router.py에서도 크롭 여부 등을 판단할 때 같은 기준(기본값 포함)을 쓰기 위한 헬퍼."""
    return workflow_id or DEFAULT_WORKFLOW_ID


def generate_styled_image(product_image: Image.Image, reference: dict, workflow_id: str = None, aspect_ratio: str = None, cup_source: str = None) -> Image.Image:
    """
    입력:
      - product_image: 사용자가 업로드한 원본 사진
      - reference: 선택한 레퍼런스 정보 (mood_id, composition_id 등 포함)
      - workflow_id: 사용할 워크플로 식별자. 없으면 DEFAULT_WORKFLOW_ID 사용.
      - aspect_ratio: "4:5" 또는 "1:1". openai-gpt-image-2-low-v1에서는 필수
        (2026-07-23 팀장 정정: 4:5=1024x1280, 1:1=1024x1024, 둘 다 무크롭).
        model-c-v1은 이 값을 그냥 무시함(레거시 워크플로라 비율 선택 개념이 없음).
      - cup_source: "uploaded" 또는 "model". 2026-07-24 소연님 요청사항이며
        계약 미확정 상태라 있으면 전달만 하고 검증은 안 함.
    """
    workflow_id = resolve_workflow_id(workflow_id)
    handler = WORKFLOW_REGISTRY.get(workflow_id)
    if handler is None:
        raise ValueError(f"알 수 없는 workflow_id입니다: {workflow_id}")
    return handler(product_image, reference, aspect_ratio=aspect_ratio, cup_source=cup_source)
