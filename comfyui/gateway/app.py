import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, Response
from PIL import Image, UnidentifiedImageError

from comfyui.orchestrator import WorkflowRouterError, build_prompt


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_RESULT_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
JOB_TOKEN_VERSION = 1


@dataclass(frozen=True)
class Settings:
    comfyui_url: str
    model_c_url: str
    api_key: str

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("AD_CREATOR_GATEWAY_API_KEY", "")
        if len(api_key) < 32:
            raise RuntimeError("AD_CREATOR_GATEWAY_API_KEY must contain at least 32 characters.")
        return cls(
            comfyui_url=os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/"),
            model_c_url=os.environ.get("AD_CREATOR_MODEL_C_URL", "http://127.0.0.1:8001").rstrip("/"),
            api_key=api_key,
        )


app = FastAPI(
    title="Ad Creator Generation Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def require_api_key(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(_settings),
) -> Settings:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return settings


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def encode_generation_id(*, prompt_id: str, workflow_id: str, output_node_id: str, secret: str) -> str:
    payload = json.dumps(
        {"v": JOB_TOKEN_VERSION, "p": prompt_id, "w": workflow_id, "o": output_node_id},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def decode_generation_id(value: str, *, secret: str) -> dict[str, str]:
    try:
        encoded, supplied_signature = value.split(".", 1)
        expected_signature = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64decode(supplied_signature), expected_signature):
            raise ValueError("signature mismatch")
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        if payload.get("v") != JOB_TOKEN_VERSION:
            raise ValueError("unsupported token version")
        result = {key: str(payload[key]) for key in ("p", "w", "o")}
        if not all(result.values()):
            raise ValueError("empty token value")
        return result
    except (ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.") from exc


async def _json_request(
    method: str,
    url: str,
    *,
    timeout: float,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Upstream timeout.") from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Upstream request failed.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid upstream response.")
    return payload


def _validate_image(data: bytes, content_type: str | None) -> str:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Use JPEG, PNG, or WebP.")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image exceeds 20 MiB.")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Image exceeds 40 million pixels.",
                )
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image file.") from exc

    extension = FORMAT_EXTENSIONS.get(str(image_format))
    if extension is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported image format.")
    return extension


async def _submit_generation(
    *,
    data: bytes,
    content_type: str,
    workflow_id: str,
    composition: str,
    background_style: str,
    strength: str,
    seed: int | None,
    settings: Settings,
) -> tuple[str, str, str]:
    extension = _validate_image(data, content_type)
    upload_name = f"{uuid.uuid4().hex}{extension}"
    upload_payload = await _json_request(
        "POST",
        f"{settings.comfyui_url}/upload/image",
        timeout=30.0,
        files={"image": (upload_name, data, content_type)},
        data={"type": "input", "subfolder": "ad_creator", "overwrite": "false"},
    )
    uploaded_name = upload_payload.get("name")
    uploaded_subfolder = upload_payload.get("subfolder") or ""
    if not isinstance(uploaded_name, str) or not uploaded_name:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="ComfyUI upload failed.")
    source_image = f"{uploaded_subfolder}/{uploaded_name}" if uploaded_subfolder else uploaded_name

    values: dict[str, Any] = {
        "source_image": source_image,
        "composition": composition,
        "background_style": background_style,
        "strength": strength,
    }
    if seed is not None:
        values["seed"] = seed
    try:
        resolved = build_prompt(workflow_id=workflow_id, values=values)
    except WorkflowRouterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    queued = await _json_request(
        "POST",
        f"{settings.comfyui_url}/prompt",
        timeout=30.0,
        json={"prompt": resolved["prompt"], "client_id": f"gateway-{uuid.uuid4().hex}"},
    )
    prompt_id = queued.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="ComfyUI did not return prompt_id.")
    return prompt_id, str(resolved["workflow_id"]), str(resolved["output_node_id"])


def _output_image(entry: dict[str, Any], output_node_id: str) -> dict[str, str] | None:
    outputs = entry.get("outputs")
    if not isinstance(outputs, dict):
        return None
    node_output = outputs.get(output_node_id)
    if not isinstance(node_output, dict):
        return None
    images = node_output.get("images")
    if not isinstance(images, list) or not images or not isinstance(images[0], dict):
        return None
    image = images[0]
    filename = image.get("filename")
    if not isinstance(filename, str) or not filename:
        return None
    return {
        "filename": filename,
        "subfolder": str(image.get("subfolder") or ""),
        "type": str(image.get("type") or "output"),
    }


def _failure_message(entry: dict[str, Any]) -> str | None:
    status_value = entry.get("status")
    if not isinstance(status_value, dict) or status_value.get("status_str") != "error":
        return None
    messages = status_value.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, list) or len(message) < 2 or not isinstance(message[1], dict):
                continue
            detail = message[1].get("exception_message")
            if isinstance(detail, str) and detail:
                return detail[:500]
    return "Generation failed."


def _queued_prompt_ids(queue_entries: Any) -> set[str]:
    if not isinstance(queue_entries, list):
        return set()
    return {
        str(entry[1])
        for entry in queue_entries
        if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], str)
    }


async def _generation_state(
    *, prompt_id: str, output_node_id: str, settings: Settings
) -> tuple[str, dict[str, str] | None, str | None]:
    history = await _json_request(
        "GET", f"{settings.comfyui_url}/history/{prompt_id}", timeout=15.0
    )
    entry = history.get(prompt_id)
    if isinstance(entry, dict):
        image = _output_image(entry, output_node_id)
        if image is not None:
            return "succeeded", image, None
        failure = _failure_message(entry)
        if failure is not None:
            return "failed", None, failure
        return "failed", None, "Generation completed without an output image."

    queue = await _json_request("GET", f"{settings.comfyui_url}/queue", timeout=15.0)
    if prompt_id in _queued_prompt_ids(queue.get("queue_running")):
        return "running", None, None
    if prompt_id in _queued_prompt_ids(queue.get("queue_pending")):
        return "queued", None, None
    return "not_found", None, None


@app.get("/health")
async def health() -> JSONResponse:
    try:
        settings = Settings.from_env()
    except RuntimeError:
        return JSONResponse(
            {"ok": False, "gateway": "misconfigured"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    checks: dict[str, bool] = {}
    for name, url in (
        ("comfyui", f"{settings.comfyui_url}/system_stats"),
        ("model_c", f"{settings.model_c_url}/health"),
    ):
        try:
            await _json_request("GET", url, timeout=5.0)
            checks[name] = True
        except HTTPException:
            checks[name] = False
    healthy = all(checks.values())
    return JSONResponse(
        {"ok": healthy, **checks},
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.post("/v1/generations", status_code=status.HTTP_202_ACCEPTED)
async def create_generation(
    image: Annotated[UploadFile, File()],
    workflow_id: Annotated[str, Form()] = "model-c-v1",
    composition: Annotated[Literal["closeup", "medium", "aerial", "handheld"], Form()] = "medium",
    background_style: Annotated[Literal["vivid", "wood", "white"], Form()] = "wood",
    strength: Annotated[Literal["low", "medium", "high"], Form()] = "medium",
    seed: Annotated[int | None, Form(ge=-1, le=2147483647)] = None,
    settings: Settings = Depends(require_api_key),
) -> dict[str, Any]:
    data = await image.read(MAX_IMAGE_BYTES + 1)
    prompt_id, selected_workflow_id, output_node_id = await _submit_generation(
        data=data,
        content_type=image.content_type or "application/octet-stream",
        workflow_id=workflow_id,
        composition=composition,
        background_style=background_style,
        strength=strength,
        seed=seed,
        settings=settings,
    )
    generation_id = encode_generation_id(
        prompt_id=prompt_id,
        workflow_id=selected_workflow_id,
        output_node_id=output_node_id,
        secret=settings.api_key,
    )
    return {
        "generation_id": generation_id,
        "workflow_id": selected_workflow_id,
        "status": "queued",
        "status_url": f"/v1/generations/{generation_id}",
        "result_url": f"/v1/generations/{generation_id}/result",
    }


@app.get("/v1/generations/{generation_id}")
async def get_generation(
    generation_id: str,
    settings: Settings = Depends(require_api_key),
) -> dict[str, Any]:
    token = decode_generation_id(generation_id, secret=settings.api_key)
    current_status, image, error = await _generation_state(
        prompt_id=token["p"], output_node_id=token["o"], settings=settings
    )
    result: dict[str, Any] = {
        "generation_id": generation_id,
        "workflow_id": token["w"],
        "status": current_status,
    }
    if current_status == "succeeded":
        result["result_url"] = f"/v1/generations/{generation_id}/result"
    if error:
        result["error"] = error
    return result


@app.get("/v1/generations/{generation_id}/result")
async def get_generation_result(
    generation_id: str,
    settings: Settings = Depends(require_api_key),
) -> Response:
    token = decode_generation_id(generation_id, secret=settings.api_key)
    current_status, image, error = await _generation_state(
        prompt_id=token["p"], output_node_id=token["o"], settings=settings
    )
    if current_status != "succeeded" or image is None:
        detail = error or f"Generation is {current_status}."
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{settings.comfyui_url}/view", params=image)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Result timeout.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Result download failed.") from exc
    if len(response.content) > MAX_RESULT_BYTES:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Result exceeds 50 MiB.")
    media_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
    return Response(content=response.content, media_type=media_type)
