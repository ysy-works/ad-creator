import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


MAX_RESULT_BYTES = 50 * 1024 * 1024


class ModelCExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, result: dict[str, Any] | None = None):
        self.code = code
        self.result = result or {}
        super().__init__(f"[{code}] {message}")


def _server_url() -> str:
    return os.environ.get("AD_CREATOR_MODEL_C_URL", "http://127.0.0.1:8001").rstrip("/")


def _timeout_seconds() -> float:
    try:
        value = float(os.environ.get("AD_CREATOR_MODEL_C_TIMEOUT_SECONDS", "420"))
    except ValueError as exc:
        raise ModelCExecutionError("INVALID_CONFIGURATION", "Invalid model-c timeout value.") from exc
    if value <= 0:
        raise ModelCExecutionError("INVALID_CONFIGURATION", "model-c timeout must be positive.")
    return value


def _multipart_body(source: Path, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----AdCreator{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="image"; filename="{source.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            source.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), boundary


def _http_error(exc: urllib.error.HTTPError) -> ModelCExecutionError:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        code = str(detail.get("error_code") or f"MODEL_C_HTTP_{exc.code}")
        message = str(detail.get("error_message") or detail)
        result = detail
    else:
        code = f"MODEL_C_HTTP_{exc.code}"
        message = str(detail or exc.reason or "model-c request failed.")
        result = payload if isinstance(payload, dict) else {}
    return ModelCExecutionError(code, message, result)


def _download_result(base_url: str, image_url: str, timeout_seconds: float) -> bytes:
    result_url = urllib.parse.urljoin(f"{base_url}/", image_url)
    base = urllib.parse.urlparse(base_url)
    result = urllib.parse.urlparse(result_url)
    if (result.scheme, result.netloc) != (base.scheme, base.netloc):
        raise ModelCExecutionError("INVALID_RESULT_URL", "model-c returned an external image URL.")

    try:
        with urllib.request.urlopen(result_url, timeout=timeout_seconds) as response:
            final_result = urllib.parse.urlparse(response.geturl())
            if (final_result.scheme, final_result.netloc) != (base.scheme, base.netloc):
                raise ModelCExecutionError("INVALID_RESULT_URL", "model-c result redirected to an external URL.")
            content = response.read(MAX_RESULT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ModelCExecutionError("MODEL_C_RESULT_DOWNLOAD_FAILED", str(exc)) from exc

    if len(content) > MAX_RESULT_BYTES:
        raise ModelCExecutionError("MODEL_C_RESULT_TOO_LARGE", "model-c result exceeds 50 MiB.")
    return content


def run_model_c(
    *,
    image_path: str | Path,
    composition: str,
    background_style: str,
    strength: str,
    seed: int | None,
) -> tuple[dict[str, Any], bytes]:
    source = Path(image_path).resolve()
    if not source.is_file():
        raise ModelCExecutionError("INVALID_IMAGE", f"Input image not found: {source}")

    fields = {
        "composition": composition,
        "background_style": background_style,
        "strength": strength,
    }
    if seed is not None:
        fields["seed"] = str(seed)

    body, boundary = _multipart_body(source, fields)
    base_url = _server_url()
    timeout_seconds = _timeout_seconds()
    request = urllib.request.Request(
        f"{base_url}/generate",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelCExecutionError("MODEL_C_REQUEST_FAILED", str(exc)) from exc

    if not isinstance(result, dict) or not result.get("success"):
        raise ModelCExecutionError("INVALID_MODEL_RESPONSE", "model-c returned an invalid response.")
    image_url = result.get("image_url")
    if not isinstance(image_url, str) or not image_url:
        raise ModelCExecutionError("RESULT_URL_MISSING", "model-c response has no image_url.", result)
    return result, _download_result(base_url, image_url, timeout_seconds)
