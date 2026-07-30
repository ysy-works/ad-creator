import base64
import io
import json
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from PIL import Image

from app.model.model import (
    OPENAI_WORKFLOW_ID,
    generate_styled_image,
    record_frontend_completion,
    resolve_workflow_id,
)
from app.services.caption_generator import generate_caption_package

router = APIRouter()

REFERENCES_PATH = Path(__file__).resolve().parent.parent / "config" / "references.json"


def _crop_square_legacy(image: Image.Image) -> Image.Image:
    """
    model-c-v1 전용 기존 동작: 인스타그램 1:1 정사각형으로 중앙 크롭.
    1080x1080 픽셀로 고정. (gpt-image-2-v1에는 절대 적용하지 않음 —
    4:5 프리셋의 제품 크기·여백·구도가 손상됨. 2026-07-21 팀장 인계서 2번 항목.)
    """
    target_size = (1080, 1080)

    width, height = image.size
    min_side = min(width, height)
    left = (width - min_side) // 2
    top = (height - min_side) // 2
    right = left + min_side
    bottom = top + min_side
    image = image.crop((left, top, right, bottom))

    image = image.resize(target_size, Image.LANCZOS)
    return image


def finalize_result_image(image: Image.Image, workflow_id: str) -> Image.Image:
    """
    workflow_id별로 최종 결과 이미지 처리를 분기.

    - gpt-image-2-v1: 크롭 없이 그대로 반환. 2026-07-23 팀장 정정으로
      4:5는 1024x1280, 1:1은 1024x1024를 provider가 무크롭으로 그대로 줌
      (예전엔 4:5를 880x1100으로 축소했었는데 그 단계가 없어짐).
    - 그 외(model-c-v1 등 레거시): 기존처럼 1:1 정사각형 중앙 크롭.
    """
    if workflow_id == OPENAI_WORKFLOW_ID:
        return image
    return _crop_square_legacy(image)


def image_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _load_references():
    with open(REFERENCES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_reference(reference_id: str):
    references = _load_references()
    return next((r for r in references if r["id"] == reference_id), None)


@router.get("/references")
async def get_references():
    """
    무드/구도별 레퍼런스 목록을 그대로 반환.
    무드 개수, 구도 개수는 이 파일(references.json) 내용에 따라 자유롭게 바뀔 수 있음.
    프론트엔드는 이 배열을 mood_id 기준으로 그루핑해서 화면에 그린다.
    """
    return _load_references()


@router.post("/generate")
async def generate(
    product_image: UploadFile = File(...),
    reference_id: str = Form(...),
    workflow_id: Optional[str] = Form(None),
    aspect_ratio: Optional[str] = Form(None),
    cup_source: Literal["uploaded", "model"] = Form(...),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """
    사용자가 올린 사진 + 고른 레퍼런스(reference_id) + (선택) workflow_id를 기반으로
    같은 분위기/구도의 이미지를 생성해서 반환.
    workflow_id를 안 보내면 기본값(model.py의 DEFAULT_WORKFLOW_ID, 환경변수로 전환)이 사용됨.

    aspect_ratio: 프론트 4:5/1:1 토글에서 보내는 값("4:5" 또는 "1:1").
    cup_source: 프론트 컵 선택 토글의 필수값("uploaded" 또는 "model").
    model.py에서 Gateway의 container_mode 계약으로 변환하며 누락·오타는 생성
    전에 거부한다.
    2026-07-23 팀장 정정: gpt-image-2-v1은 이제 4:5(1024x1280)와
    1:1(1024x1024) 둘 다 무크롭으로 생성 — 이 workflow에서는 사실상 필수값이며,
    없거나 잘못된 값이면 model.py에서 ValueError로 400 처리됨. 프론트가 사용자
    선택을 강제하므로 정상 흐름에서는 항상 채워져서 옴. model-c-v1은 이 값을
    그냥 무시함(레거시라 비율 선택 개념 자체가 없음).

    x_session_id: 2026-07-27 소연님 Langfuse 연동 요청사항. 프론트가 만든
    익명 세션 UUID를 그대로 받아 Gateway까지 전달한다(선택값 — 없어도 기존처럼
    정상 생성됨). 형식 검증은 우리 쪽에서 하지 않고 Gateway가 그대로 판단하며,
    이 값은 어디에도 로그로 남기지 않는다.
    """
    reference = _find_reference(reference_id)
    if reference is None:
        return JSONResponse(status_code=400, content={"error": "존재하지 않는 reference_id입니다."})

    image_data = await product_image.read()
    pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")

    try:
        result_image, generation_id = generate_styled_image(
            pil_image, reference, workflow_id=workflow_id, aspect_ratio=aspect_ratio,
            cup_source=cup_source, session_id=x_session_id,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"이미지 생성 실패: {e}"})

    result_image = finalize_result_image(result_image, resolve_workflow_id(workflow_id))

    return JSONResponse(content={
        "result_image": image_to_base64(result_image),
        "generation_id": generation_id,
    })


class FrontendCompletedRequest(BaseModel):
    generation_id: str = Field(min_length=1, max_length=2048)
    duration_ms: int = Field(ge=1, le=30 * 60 * 1000)


@router.post(
    "/telemetry/frontend-completed",
    status_code=status.HTTP_202_ACCEPTED,
)
async def frontend_completed(payload: FrontendCompletedRequest):
    try:
        record_frontend_completion(
            generation_id=payload.generation_id,
            duration_ms=payload.duration_ms,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Frontend completion 기록을 일시적으로 처리할 수 없습니다.",
        ) from exc
    return {"accepted": True}


class CaptionRequest(BaseModel):
    reference_id: str
    result_image_base64: str
    menu_name: Optional[str] = None
    purpose: Optional[str] = None
    lang: Optional[str] = "ko"


@router.post("/caption")
async def caption(payload: CaptionRequest):
    """
    이미 생성된 결과 이미지(result_image_base64)를 보고
    캡션 + 해시태그 + 스토리 문구를 생성.

    /generate와 분리된 이유: 사용자가 이미지 결과부터 먼저 확인하고,
    "캡션·해시태그 만들기" 버튼을 눌렀을 때만 (선택적으로) 호출되는 구조이기 때문.

    lang: 프론트 화면 언어("ko"/"en")를 그대로 받아 caption_generator.py로
    전달 -> 영어 화면에서는 GPT가 생성하는 캡션도 영어로 나오게 됨.
    프론트가 값을 안 보내도 기존과 동일하게 "ko"로 동작(하위 호환).
    """
    reference = _find_reference(payload.reference_id)
    if reference is None:
        return JSONResponse(status_code=400, content={"error": "존재하지 않는 reference_id입니다."})

    try:
        result = generate_caption_package(
            result_image_base64=payload.result_image_base64,
            mood_label=reference["mood_label"],
            composition_label=reference["composition_label"],
            menu_name=payload.menu_name,
            purpose=payload.purpose,
            lang=payload.lang or "ko",
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"캡션 생성 실패: {e}"})

    return JSONResponse(content=result)
