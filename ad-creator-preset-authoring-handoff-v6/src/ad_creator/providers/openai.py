from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import certifi
from PIL import Image

from ..generation_inputs import ordered_image_inputs
from ..paid_readiness import require_v3_paid_submission_allowed
from .base import ProviderJob


OPENAI_IMAGE_EDITS_ENDPOINT = "https://api.openai.com/v1/images/edits"
OPENAI_IMAGE_MODEL = "gpt-image-1-mini"
OPENAI_IMAGE_SIZES = {"1024x1024", "1024x1536", "1536x1024"}


class OpenAIProviderError(RuntimeError):
    pass


class OpenAIUnavailable(OpenAIProviderError):
    pass


@dataclass(frozen=True)
class OpenAIHTTPResponse:
    payload: dict[str, Any]
    request_id: str | None = None


Transport = Callable[
    [str, dict[str, str], dict[str, Any]],
    OpenAIHTTPResponse | dict[str, Any],
]


def _safe_identity(value: str) -> str:
    if len(value) == 64 and all(character in "0123456789abcdef" for character in value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _image_mime_type(path: Path) -> str:
    with Image.open(path) as opened:
        image_format = (opened.format or "").upper()
        opened.verify()
    by_format = {
        "GIF": "image/gif",
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }
    if image_format in by_format:
        return by_format[image_format]
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return guessed
    raise OpenAIProviderError(f"Unsupported input image format: {path.name}")


def _data_url(path: Path) -> str:
    mime_type = _image_mime_type(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _error_details(body: bytes) -> tuple[str | None, str]:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None, "OpenAI returned an unreadable error response"
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None, "OpenAI returned an error response"
    code = error.get("code")
    message = error.get("message")
    safe_code = code if isinstance(code, str) and code else None
    safe_message = (
        message[:500]
        if isinstance(message, str) and message
        else "OpenAI returned an error response"
    )
    return safe_code, safe_message


def _usage_counts(value: Any) -> dict[str, Any]:
    """Keep numeric usage counters while excluding arbitrary response strings."""
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            sanitized[key] = item
        elif isinstance(item, dict):
            nested = _usage_counts(item)
            if nested:
                sanitized[key] = nested
    return sanitized


class OpenAIImageProvider:
    """Synchronous GPT Image 1 Mini adapter for one-shot image editing."""

    name = "openai_images_api"
    is_zero_credit = False

    def __init__(
        self,
        output_dir: str | Path,
        *,
        api_key: str | None = None,
        model: str = OPENAI_IMAGE_MODEL,
        endpoint: str = OPENAI_IMAGE_EDITS_ENDPOINT,
        size: str = "1024x1536",
        input_fidelity: str = "high",
        output_format: str = "png",
        moderation: str = "auto",
        timeout_seconds: float = 1200,
        transport: Transport | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise OpenAIUnavailable("OPENAI_API_KEY is not configured")
        if model != OPENAI_IMAGE_MODEL:
            raise ValueError(f"Unsupported OpenAI image model: {model}")
        if endpoint != OPENAI_IMAGE_EDITS_ENDPOINT:
            raise ValueError("OpenAI image provider must use the official image edits endpoint")
        if size not in OPENAI_IMAGE_SIZES:
            raise ValueError(f"Unsupported OpenAI image size: {size}")
        if input_fidelity not in {"low", "high"}:
            raise ValueError(f"Unsupported OpenAI input fidelity: {input_fidelity}")
        if output_format != "png":
            raise ValueError("OpenAI image provider currently persists PNG output only")
        if moderation not in {"auto", "low"}:
            raise ValueError(f"Unsupported OpenAI moderation mode: {moderation}")
        if timeout_seconds <= 0:
            raise ValueError("OpenAI timeout must be positive")
        self.model = model
        self.endpoint = endpoint
        self.size = size
        self.input_fidelity = input_fidelity
        self.output_format = output_format
        self.moderation = moderation
        self.timeout_seconds = float(timeout_seconds)
        self._transport = transport or self._post

    def _post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> OpenAIHTTPResponse:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=context,
            ) as response:
                body = response.read()
                request_id = response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            code, message = _error_details(exc.read())
            label = f" ({code})" if code else ""
            raise OpenAIProviderError(f"OpenAI HTTP {exc.code}{label}: {message}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise OpenAIProviderError(
                "OpenAI image request failed before a response was saved"
            ) from exc
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenAIProviderError("OpenAI returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise OpenAIProviderError("OpenAI returned a non-object response")
        return OpenAIHTTPResponse(payload=decoded, request_id=request_id)

    def _record_path(self, job_id: str) -> Path:
        return self.output_dir / "jobs" / f"{job_id}.json"

    def _request_path(self, idempotency_key: str) -> Path:
        return self.output_dir / "requests" / f"{_safe_identity(idempotency_key)}.json"

    def _save_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _save_record(self, record: dict[str, Any]) -> None:
        self._save_json(self._record_path(record["job_id"]), record)

    def _save_request_mapping(self, idempotency_key: str, job_id: str) -> None:
        self._save_json(self._request_path(idempotency_key), {"job_id": job_id})

    def _load_record(self, job_id: str) -> dict[str, Any]:
        path = self._record_path(job_id)
        if not path.is_file():
            raise KeyError(f"Unknown OpenAI image job: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _find_record(self, idempotency_key: str) -> dict[str, Any] | None:
        mapping_path = self._request_path(idempotency_key)
        if mapping_path.is_file():
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            record_path = self._record_path(mapping["job_id"])
            if record_path.is_file():
                return self._load_record(mapping["job_id"])
        jobs_dir = self.output_dir / "jobs"
        if jobs_dir.is_dir():
            for path in jobs_dir.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("idempotency_key") == idempotency_key:
                    self._save_request_mapping(idempotency_key, record["job_id"])
                    return record
        return None

    @staticmethod
    def _provider_job(record: dict[str, Any]) -> ProviderJob:
        output_path = Path(record["output_path"]) if record.get("output_path") else None
        return ProviderJob(
            job_id=record["job_id"],
            status=record["status"],
            output_path=output_path,
            actual_credits=None,
            metadata=record.get("metadata") or {},
        )

    def find_by_idempotency_key(self, idempotency_key: str) -> ProviderJob | None:
        record = self._find_record(idempotency_key)
        return self._provider_job(record) if record is not None else None

    def get(self, job_id: str) -> ProviderJob:
        return self._provider_job(self._load_record(job_id))

    def submit(self, request: dict[str, Any], *, idempotency_key: str) -> ProviderJob:
        # Keep this adapter safe even when called without the shared RunStore.
        # The guard precedes payload construction and the network transport.
        require_v3_paid_submission_allowed(
            request,
            provider_name=self.name,
            idempotency_key=idempotency_key,
        )
        existing = self._find_record(idempotency_key)
        if existing is not None:
            return self._provider_job(existing)

        generation = request.get("generation")
        if not isinstance(generation, dict):
            raise ValueError("OpenAI generation request is missing generation")
        if generation.get("provider") != self.name:
            raise ValueError("OpenAI provider received a request for a different provider")
        if generation.get("job_type") != self.model:
            raise ValueError("OpenAI provider received a request for a different model")
        submission_path = generation.get("submission_path")
        if submission_path not in {None, "images_edit"}:
            raise ValueError(f"Unsupported OpenAI submission path: {submission_path}")
        prompt = generation.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("OpenAI image prompt is empty")
        quality = generation.get("quality")
        if quality not in {"low", "medium", "high", "auto"}:
            raise ValueError(f"Unsupported OpenAI image quality: {quality}")
        image_inputs = ordered_image_inputs(generation)
        if len(image_inputs) > 16:
            raise ValueError("OpenAI image edits accept at most 16 input images")
        image_paths = [
            Path(item["path"]).expanduser().resolve() for item in image_inputs
        ]
        for path in image_paths:
            if not path.is_file():
                raise FileNotFoundError(f"OpenAI input image does not exist: {path}")

        identity = _safe_identity(idempotency_key)
        payload = {
            "model": self.model,
            "images": [{"image_url": _data_url(path)} for path in image_paths],
            "prompt": prompt,
            "quality": quality,
            "size": self.size,
            "input_fidelity": self.input_fidelity,
            "output_format": self.output_format,
            "moderation": self.moderation,
            "n": 1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ad-creator/0.1",
            "X-Client-Request-Id": identity,
        }
        response = self._transport(self.endpoint, headers, payload)
        if isinstance(response, dict):
            response = OpenAIHTTPResponse(payload=response)
        if not isinstance(response, OpenAIHTTPResponse):
            raise OpenAIProviderError("OpenAI transport returned an invalid response")
        data = response.payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise OpenAIProviderError("OpenAI response contained no generated image")
        encoded = data[0].get("b64_json")
        if not isinstance(encoded, str) or not encoded:
            raise OpenAIProviderError("OpenAI response contained no base64 image data")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise OpenAIProviderError("OpenAI returned invalid base64 image data") from exc
        try:
            with Image.open(io.BytesIO(image_bytes)) as opened:
                opened.verify()
        except Exception as exc:
            raise OpenAIProviderError("OpenAI returned an invalid image") from exc

        job_id = f"openai-{identity[:20]}"
        output_path = self.output_dir / "images" / f"{job_id}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_image = output_path.with_suffix(".png.tmp")
        temporary_image.write_bytes(image_bytes)
        os.replace(temporary_image, output_path)

        metadata = {
            "provider": self.name,
            "endpoint": "images.edits",
            "model": self.model,
            "quality": quality,
            "size": self.size,
            "input_fidelity": self.input_fidelity,
            "output_format": self.output_format,
            "image_roles": [item["role"] for item in image_inputs],
            "request_id": response.request_id,
            "usage": _usage_counts(response.payload.get("usage")),
        }
        record = {
            "job_id": job_id,
            "idempotency_key": idempotency_key,
            "status": "completed",
            "output_path": str(output_path.resolve()),
            "actual_credits": None,
            "metadata": metadata,
        }
        self._save_record(record)
        self._save_request_mapping(idempotency_key, job_id)
        return self._provider_job(record)
