import base64
import asyncio
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from comfyui.orchestrator import (
    PresetRegistryConfigurationError,
    PresetSelectionError,
    UnknownWorkflowError,
    WorkflowRouterError,
    build_prompt,
    published_preset_ids,
    resolve_published_preset,
    workflow_input_names,
)


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_RESULT_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_RESULT_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
JOB_TOKEN_VERSION = 2
SUBMISSION_STALE_SECONDS = 300


@dataclass(frozen=True)
class Settings:
    comfyui_url: str
    model_c_url: str
    api_key: str
    signing_key: str
    database_path: Path
    max_queued: int
    health_workflow_id: str

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("AD_CREATOR_GATEWAY_API_KEY", "")
        if len(api_key) < 32:
            raise RuntimeError("AD_CREATOR_GATEWAY_API_KEY must contain at least 32 characters.")
        signing_key = os.environ.get("AD_CREATOR_GENERATION_SIGNING_KEY", "")
        if len(signing_key) < 32:
            raise RuntimeError("AD_CREATOR_GENERATION_SIGNING_KEY must contain at least 32 characters.")
        if secrets.compare_digest(api_key, signing_key):
            raise RuntimeError("Gateway API and generation signing keys must be different.")
        try:
            max_queued = int(os.environ.get("AD_CREATOR_MAX_QUEUED", "3"))
        except ValueError as exc:
            raise RuntimeError("AD_CREATOR_MAX_QUEUED must be an integer.") from exc
        if not 1 <= max_queued <= 100:
            raise RuntimeError("AD_CREATOR_MAX_QUEUED must be between 1 and 100.")
        return cls(
            comfyui_url=os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/"),
            model_c_url=os.environ.get("AD_CREATOR_MODEL_C_URL", "http://127.0.0.1:8001").rstrip("/"),
            api_key=api_key,
            signing_key=signing_key,
            database_path=Path(
                os.environ.get("AD_CREATOR_GATEWAY_DB", "data/gateway.sqlite3")
            ).expanduser(),
            max_queued=max_queued,
            health_workflow_id=os.environ.get(
                "AD_CREATOR_HEALTH_WORKFLOW_ID", "model-c-v1"
            ),
        )


app = FastAPI(
    title="Ad Creator Generation Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_SUBMISSION_LOCK = asyncio.Lock()
_TERMINAL_STATES = {"succeeded", "failed", "expired"}
_STATE_EVENT_STAGES = {
    "queued": "queued",
    "running": "running",
    "unknown": "unknown",
    "succeeded": "succeeded",
    "failed": "failed",
    "expired": "expired",
}
_REQUIRED_GENERATION_COLUMNS = {
    "generation_id",
    "job_id",
    "idempotency_key",
    "request_hash",
    "prompt_id",
    "workflow_id",
    "output_node_id",
    "state",
    "filename",
    "subfolder",
    "output_type",
    "error",
    "created_at",
    "updated_at",
    "session_id",
    "created_at_ms",
    "completed_at_ms",
}


class _PromptSubmissionUncertain(Exception):
    def __init__(self, error: HTTPException):
        super().__init__(str(error.detail))
        self.error = error


class FrontendCompletedObservation(BaseModel):
    duration_ms: int = Field(ge=1, le=30 * 60 * 1000)


@contextmanager
def _database(settings: Settings):
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path, timeout=5.0)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
        CREATE TABLE IF NOT EXISTS generations (
            generation_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_hash TEXT NOT NULL,
            prompt_id TEXT UNIQUE,
            workflow_id TEXT NOT NULL,
                output_node_id TEXT NOT NULL,
                state TEXT NOT NULL,
                filename TEXT,
                subfolder TEXT,
                output_type TEXT,
                error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                session_id TEXT,
                created_at_ms INTEGER,
                completed_at_ms INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_observability_events (
                event_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                state TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                session_id TEXT,
                occurred_at_ms INTEGER NOT NULL,
                error TEXT,
                duration_ms INTEGER,
                UNIQUE(job_id, stage)
            )
            """
        )
        event_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(generation_observability_events)"
            ).fetchall()
        }
        if "duration_ms" not in event_columns:
            connection.execute(
                "ALTER TABLE generation_observability_events "
                "ADD COLUMN duration_ms INTEGER"
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                generation_observability_events_occurred_idx
            ON generation_observability_events (occurred_at_ms, event_id)
            """
        )
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(generations)").fetchall()
        }
        additive_columns = {
            "session_id": "TEXT",
            "created_at_ms": "INTEGER",
            "completed_at_ms": "INTEGER",
        }
        for name, column_type in additive_columns.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE generations ADD COLUMN {name} {column_type}"
                )
                columns.add(name)
        connection.execute(
            """
            UPDATE generations
            SET created_at_ms = created_at * 1000
            WHERE created_at_ms IS NULL
            """
        )
        connection.execute(
            """
            UPDATE generations
            SET completed_at_ms = updated_at * 1000
            WHERE completed_at_ms IS NULL
              AND state IN ('succeeded', 'failed', 'expired')
            """
        )
        if not _REQUIRED_GENERATION_COLUMNS.issubset(columns):
            raise sqlite3.DatabaseError(
                "Unsupported gateway database schema; start with a fresh gateway database."
            )
        connection.commit()
        yield connection
        connection.commit()
    finally:
        connection.close()


def _record_generation_event(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    workflow_id: str,
    session_id: str | None,
    stage: str,
    state: str,
    occurred_at_ms: int,
    error: str | None = None,
    duration_ms: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO generation_observability_events (
            event_id, job_id, stage, state, workflow_id, session_id,
            occurred_at_ms, error, duration_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"{job_id}:{stage}",
            job_id,
            stage,
            state,
            workflow_id,
            session_id,
            occurred_at_ms,
            error,
            duration_ms,
        ),
    )


def _reserve_generation(
    *,
    generation_id: str,
    job_id: str,
    idempotency_key: str,
    request_hash: str,
    workflow_id: str,
    output_node_id: str,
    session_id: str | None = None,
    settings: Settings,
) -> tuple[dict[str, Any], bool]:
    now_ms = time.time_ns() // 1_000_000
    now = now_ms // 1000
    with _database(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM generations WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            record = dict(existing)
            if record["request_hash"] != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key was already used for a different request.",
                )
            return record, False
        connection.execute(
            """
            INSERT INTO generations (
                generation_id, job_id, idempotency_key, request_hash,
                workflow_id, output_node_id,
                state, created_at, updated_at, session_id, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, 'submitting', ?, ?, ?, ?)
            """,
            (
                generation_id,
                job_id,
                idempotency_key,
                request_hash,
                workflow_id,
                output_node_id,
                now,
                now,
                session_id,
                now_ms,
            ),
        )
        _record_generation_event(
            connection,
            job_id=job_id,
            workflow_id=workflow_id,
            session_id=session_id,
            stage="accepted",
            state="submitting",
            occurred_at_ms=now_ms,
        )
        record = connection.execute(
            "SELECT * FROM generations WHERE generation_id = ?", (generation_id,)
        ).fetchone()
        if record is None:
            raise sqlite3.DatabaseError("Generation reservation was not stored.")
        return dict(record), True


def _attach_prompt(
    generation_id: str,
    *,
    prompt_id: str,
    workflow_id: str,
    output_node_id: str,
    settings: Settings,
) -> None:
    with _database(settings) as connection:
        now_ms = time.time_ns() // 1_000_000
        cursor = connection.execute(
            """
            UPDATE generations
            SET prompt_id = ?, workflow_id = ?, output_node_id = ?,
                state = 'queued', error = NULL, updated_at = ?
            WHERE generation_id = ? AND state NOT IN ('succeeded', 'failed', 'expired')
            """,
            (
                prompt_id,
                workflow_id,
                output_node_id,
                now_ms // 1000,
                generation_id,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.DatabaseError("Generation prompt metadata was not stored.")
        record = connection.execute(
            "SELECT * FROM generations WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
        if record is None:
            raise sqlite3.DatabaseError("Generation prompt metadata was not stored.")
        _record_generation_event(
            connection,
            job_id=str(record["job_id"]),
            workflow_id=str(record["workflow_id"]),
            session_id=record["session_id"],
            stage="queued",
            state="queued",
            occurred_at_ms=now_ms,
        )


def _delete_unsubmitted_generation(generation_id: str, settings: Settings) -> None:
    with _database(settings) as connection:
        record = connection.execute(
            """
            SELECT job_id, workflow_id, session_id
            FROM generations
            WHERE generation_id = ? AND prompt_id IS NULL AND state = 'submitting'
            """,
            (generation_id,),
        ).fetchone()
        if record is not None:
            _record_generation_event(
                connection,
                job_id=str(record["job_id"]),
                workflow_id=str(record["workflow_id"]),
                session_id=record["session_id"],
                stage="submission_failed",
                state="failed",
                occurred_at_ms=time.time_ns() // 1_000_000,
                error="Prompt submission was rejected before it was queued.",
            )
        connection.execute(
            """
            DELETE FROM generations
            WHERE generation_id = ? AND prompt_id IS NULL AND state = 'submitting'
            """,
            (generation_id,),
        )


def _generation_record(generation_id: str, settings: Settings) -> dict[str, Any] | None:
    with _database(settings) as connection:
        row = connection.execute(
            "SELECT * FROM generations WHERE generation_id = ?", (generation_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def _update_generation_record(
    generation_id: str,
    *,
    state: str,
    settings: Settings,
    image: dict[str, str] | None = None,
    error: str | None = None,
) -> None:
    with _database(settings) as connection:
        now_ms = time.time_ns() // 1_000_000
        now = now_ms // 1000
        if state == "expired":
            cursor = connection.execute(
                """
                UPDATE generations
                SET state = 'expired', error = ?, updated_at = ?,
                    completed_at_ms = COALESCE(completed_at_ms, ?)
                WHERE generation_id = ? AND state = 'succeeded'
                """,
                (error, now, now_ms, generation_id),
            )
        elif state == "succeeded" and image is not None:
            cursor = connection.execute(
                """
                UPDATE generations
                SET state = 'succeeded', filename = ?, subfolder = ?, output_type = ?,
                    error = NULL, updated_at = ?,
                    completed_at_ms = COALESCE(completed_at_ms, ?)
                WHERE generation_id = ?
                  AND state NOT IN ('succeeded', 'failed', 'expired')
                """,
                (
                    image["filename"],
                    image.get("subfolder", ""),
                    image.get("type", "output"),
                    now,
                    now_ms,
                    generation_id,
                ),
            )
        else:
            completed_at_ms = now_ms if state in _TERMINAL_STATES else None
            cursor = connection.execute(
                """
                UPDATE generations
                SET state = ?, error = ?, updated_at = ?,
                    completed_at_ms = COALESCE(completed_at_ms, ?)
                WHERE generation_id = ?
                  AND state NOT IN ('succeeded', 'failed', 'expired')
                """,
                (state, error, now, completed_at_ms, generation_id),
            )
        stage = _STATE_EVENT_STAGES.get(state)
        if cursor.rowcount == 1 and stage is not None:
            record = connection.execute(
                """
                SELECT job_id, workflow_id, session_id, state, error
                FROM generations
                WHERE generation_id = ?
                """,
                (generation_id,),
            ).fetchone()
            if record is not None and str(record["state"]) == state:
                _record_generation_event(
                    connection,
                    job_id=str(record["job_id"]),
                    workflow_id=str(record["workflow_id"]),
                    session_id=record["session_id"],
                    stage=stage,
                    state=state,
                    occurred_at_ms=now_ms,
                    error=record["error"],
                )


def _recorded_image(record: dict[str, Any]) -> dict[str, str] | None:
    filename = record.get("filename")
    if not isinstance(filename, str) or not filename:
        return None
    return {
        "filename": filename,
        "subfolder": str(record.get("subfolder") or ""),
        "type": str(record.get("output_type") or "output"),
    }


def _request_hash(
    *,
    data: bytes,
    content_type: str,
    workflow_id: str,
    workflow_values: dict[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "content_type": content_type,
            "image_sha256": hashlib.sha256(data).hexdigest(),
            "workflow_id": workflow_id,
            "workflow_values": workflow_values,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonical_workflow_values(
    *,
    workflow_id: str,
    preset_id: str | None,
    composition: str,
    background_style: str,
    strength: str,
    seed: int | None,
    aspect_ratio: str,
    container_mode: str,
    serving_temperature: str,
) -> dict[str, Any]:
    try:
        accepted = workflow_input_names(workflow_id=workflow_id)
    except UnknownWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WorkflowRouterError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow registry is unavailable.",
        ) from exc
    possible: dict[str, Any] = {
        "preset_id": preset_id,
        "composition": composition,
        "background_style": background_style,
        "strength": strength,
        "seed": seed,
        "aspect_ratio": aspect_ratio,
        "container_mode": container_mode,
        "serving_temperature": serving_temperature,
    }
    return {
        name: possible[name]
        for name in sorted(accepted)
        if name in possible
    }


def _resolved_preset_id(
    *,
    workflow_id: str,
    preset_id: str | None,
    background_style: str,
    composition: str,
) -> str | None:
    try:
        input_names = workflow_input_names(workflow_id=workflow_id)
    except UnknownWorkflowError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WorkflowRouterError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow registry is unavailable.",
        ) from exc

    supplied = (preset_id or "").strip() or None
    if "preset_id" not in input_names:
        if supplied is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Workflow {workflow_id} does not accept preset_id.",
            )
        return None

    try:
        return resolve_published_preset(
            preset_id=supplied,
            background_style=background_style,
            composition=composition,
        )
    except PresetSelectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except PresetRegistryConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Preset registry is unavailable.",
        ) from exc


def _idempotency_key(value: str | None) -> str:
    key = (value or "").strip()
    if not 8 <= len(key) <= 128 or any(character.isspace() for character in key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must contain 8 to 128 non-whitespace characters.",
        )
    return key


def _session_id(value: str | None) -> str | None:
    session_id = (value or "").strip()
    if not session_id:
        return None
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "X-Session-ID must contain 8 to 128 safe ASCII characters "
                "(letters, digits, dot, underscore, colon, or hyphen)."
            ),
        )
    return session_id


def _public_status(record: dict[str, Any]) -> str:
    state_value = str(record["state"])
    return "unknown" if state_value == "submitting" else state_value


def _generation_response(record: dict[str, Any]) -> dict[str, Any]:
    generation_id = str(record["generation_id"])
    result: dict[str, Any] = {
        "generation_id": generation_id,
        "workflow_id": str(record["workflow_id"]),
        "status": _public_status(record),
        "status_url": f"/v1/generations/{generation_id}",
        "result_url": f"/v1/generations/{generation_id}/result",
    }
    if record.get("error"):
        result["error"] = str(record["error"])
    return result


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


def encode_generation_id(*, job_id: str, secret: str) -> str:
    payload = json.dumps(
        {"v": JOB_TOKEN_VERSION, "j": job_id},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def decode_generation_id(value: str, *, secret: str) -> dict[str, str]:
    try:
        if len(value) > 2048:
            raise ValueError("token too long")
        encoded, supplied_signature = value.split(".", 1)
        expected_signature = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64decode(supplied_signature), expected_signature):
            raise ValueError("signature mismatch")
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid token payload")
        if payload.get("v") != JOB_TOKEN_VERSION:
            raise ValueError("unsupported token version")
        result = {"j": str(payload["j"])}
        if not all(result.values()):
            raise ValueError("empty token value")
        uuid.UUID(result["j"])
        return result
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as image:
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
    request_id: str,
    preset_id: str | None = None,
    aspect_ratio: str = "4:5",
    container_mode: str = "default",
    serving_temperature: str = "auto",
) -> tuple[str, str, str]:
    extension = _validate_image(data, content_type)
    async with _SUBMISSION_LOCK:
        queue = await _json_request("GET", f"{settings.comfyui_url}/queue", timeout=15.0)
        queued_count = len(_queued_prompt_ids(queue.get("queue_running"))) + len(
            _queued_prompt_ids(queue.get("queue_pending"))
        )
        if queued_count >= settings.max_queued:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Generation queue is full.",
                headers={"Retry-After": "10"},
            )

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

        possible_values: dict[str, Any] = {
            "source_image": source_image,
            "composition": composition,
            "background_style": background_style,
            "strength": strength,
            "preset_id": preset_id,
            "request_id": request_id,
            "aspect_ratio": aspect_ratio,
            "container_mode": container_mode,
            "serving_temperature": serving_temperature,
        }
        if seed is not None:
            possible_values["seed"] = seed
        try:
            accepted_inputs = workflow_input_names(workflow_id=workflow_id)
            values = {
                name: value
                for name, value in possible_values.items()
                if name in accepted_inputs and value is not None
            }
            resolved = build_prompt(workflow_id=workflow_id, values=values)
        except WorkflowRouterError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        try:
            queued = await _json_request(
                "POST",
                f"{settings.comfyui_url}/prompt",
                timeout=30.0,
                json={
                    "prompt": resolved["prompt"],
                    "client_id": f"gateway-{uuid.uuid4().hex}",
                },
            )
        except HTTPException as exc:
            # A timeout or connection loss can happen after ComfyUI accepted the prompt.
            # The caller must keep the reservation and must not submit it automatically again.
            raise _PromptSubmissionUncertain(exc) from exc
        prompt_id = queued.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise _PromptSubmissionUncertain(
                HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="ComfyUI did not return prompt_id.",
                )
            )
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
                match = re.match(r"^\[([A-Za-z0-9_]{2,80})\]", detail)
                code = match.group(1) if match else None
                safe_messages = {
                    "AUDIT_STORAGE_UNAVAILABLE": "Generation audit storage is unavailable.",
                    "IMAGE_TOO_LARGE": "An image input is too large for generation.",
                    "INVALID_IMAGE": "An image input is invalid.",
                    "INVALID_OPENAI_RESPONSE": "The image provider returned an invalid result.",
                    "INVALID_PRESET_CONFIGURATION": "The generation preset is unavailable.",
                    "INVALID_PROVIDER_PROFILE": "The image provider configuration is unavailable.",
                    "OPENAI_API_KEY_MISSING": "The image provider credential is unavailable.",
                    "OPENAI_REQUEST_FAILED": "The image provider request failed.",
                    "PRESET_ASSET_DIMENSION_MISMATCH": "A generation preset asset is invalid.",
                    "PRESET_ASSET_HASH_MISMATCH": "A generation preset asset is invalid.",
                    "moderation_blocked": "The request was blocked during image safety review.",
                    "rate_limit_exceeded": "The image provider is temporarily rate limited.",
                }
                if code in safe_messages:
                    return f"{code}: {safe_messages[code]}"
                return "Generation failed."
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
    async def read_history() -> dict[str, Any] | None:
        history = await _json_request(
            "GET", f"{settings.comfyui_url}/history/{prompt_id}", timeout=15.0
        )
        value = history.get(prompt_id)
        return value if isinstance(value, dict) else None

    def completed_state(
        entry: dict[str, Any],
    ) -> tuple[str, dict[str, str] | None, str | None]:
        image = _output_image(entry, output_node_id)
        if image is not None:
            return "succeeded", image, None
        failure = _failure_message(entry)
        if failure is not None:
            return "failed", None, failure
        return "failed", None, "Generation completed without an output image."

    entry = await read_history()
    if isinstance(entry, dict):
        return completed_state(entry)

    queue = await _json_request("GET", f"{settings.comfyui_url}/queue", timeout=15.0)
    if prompt_id in _queued_prompt_ids(queue.get("queue_running")):
        return "running", None, None
    if prompt_id in _queued_prompt_ids(queue.get("queue_pending")):
        return "queued", None, None

    # A job can move from the queue to history between the two reads above.
    entry = await read_history()
    if isinstance(entry, dict):
        return completed_state(entry)
    return "unknown", None, None


async def _refresh_generation(
    generation_id: str,
    *,
    token: dict[str, str],
    settings: Settings,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    record = _generation_record(generation_id, settings)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")
    if str(record["job_id"]) != token["j"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")

    recorded_image = _recorded_image(record)
    if record["state"] in _TERMINAL_STATES:
        return record, recorded_image

    prompt_id = record.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        # A concurrent retry can observe this reservation while the original
        # request is still uploading. A read must not change it, otherwise a
        # definite pre-submit failure can no longer remove the reservation.
        return record, _recorded_image(record)

    current_status, image, error = await _generation_state(
        prompt_id=prompt_id,
        output_node_id=str(record["output_node_id"]),
        settings=settings,
    )
    _update_generation_record(
        generation_id,
        state=current_status,
        settings=settings,
        image=image,
        error=error,
    )
    record = _generation_record(generation_id, settings)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")
    return record, _recorded_image(record)


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
    try:
        with _database(settings) as connection:
            connection.execute("SELECT 1").fetchone()
        checks["storage"] = True
    except (OSError, sqlite3.Error):
        checks["storage"] = False
    try:
        workflow_input_names(workflow_id=settings.health_workflow_id)
        checks["workflow_registry"] = True
    except WorkflowRouterError:
        checks["workflow_registry"] = False

    upstreams = [("comfyui", f"{settings.comfyui_url}/system_stats")]
    if settings.health_workflow_id == "model-c-v1":
        upstreams.append(("model_c", f"{settings.model_c_url}/health"))
    for name, url in upstreams:
        try:
            await _json_request("GET", url, timeout=5.0)
            checks[name] = True
        except HTTPException:
            checks[name] = False
    if settings.health_workflow_id in {
        "gpt-image-2-v1",
        "openai-gpt-image-2-low-v1",
    }:
        try:
            checks["preset_registry"] = bool(published_preset_ids())
        except PresetRegistryConfigurationError:
            checks["preset_registry"] = False
        try:
            object_info = await _json_request(
                "GET",
                f"{settings.comfyui_url}/object_info/AdCreatorOpenAIImageGenerate",
                timeout=5.0,
            )
            checks["openai_node"] = "AdCreatorOpenAIImageGenerate" in object_info
        except HTTPException:
            checks["openai_node"] = False
    healthy = all(checks.values())
    return JSONResponse(
        {"ok": healthy, "health_workflow_id": settings.health_workflow_id, **checks},
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.post("/v1/generations", status_code=status.HTTP_202_ACCEPTED)
async def create_generation(
    image: Annotated[UploadFile, File()],
    workflow_id: Annotated[str, Form()] = "model-c-v1",
    preset_id: Annotated[str | None, Form()] = None,
    composition: Annotated[Literal["closeup", "medium", "aerial", "handheld"], Form()] = "medium",
    background_style: Annotated[Literal["vivid", "wood", "white"], Form()] = "wood",
    strength: Annotated[Literal["low", "medium", "high"], Form()] = "medium",
    seed: Annotated[int | None, Form(ge=-1, le=2147483647)] = None,
    aspect_ratio: Annotated[Literal["4:5", "1:1"], Form()] = "4:5",
    container_mode: Annotated[
        Literal["default", "adopt_reference", "reconstruct_source"], Form()
    ] = "default",
    serving_temperature: Annotated[
        Literal["auto", "iced", "cold", "ambient", "hot"], Form()
    ] = "auto",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    session_id: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    settings: Settings = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        with _database(settings) as connection:
            connection.execute("SELECT 1").fetchone()
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation storage is unavailable.",
        ) from exc

    request_key = _idempotency_key(idempotency_key)
    resolved_session_id = _session_id(session_id)
    data = await image.read(MAX_IMAGE_BYTES + 1)
    content_type = image.content_type or "application/octet-stream"
    _validate_image(data, content_type)
    selected_preset_id = _resolved_preset_id(
        workflow_id=workflow_id,
        preset_id=preset_id,
        background_style=background_style,
        composition=composition,
    )
    canonical_values = _canonical_workflow_values(
        workflow_id=workflow_id,
        preset_id=selected_preset_id,
        composition=composition,
        background_style=background_style,
        strength=strength,
        seed=seed,
        aspect_ratio=aspect_ratio,
        container_mode=container_mode,
        serving_temperature=serving_temperature,
    )
    request_hash = _request_hash(
        data=data,
        content_type=content_type,
        workflow_id=workflow_id,
        workflow_values=canonical_values,
    )
    job_id = str(uuid.uuid4())
    generation_id = encode_generation_id(job_id=job_id, secret=settings.signing_key)
    try:
        record, created = _reserve_generation(
            generation_id=generation_id,
            job_id=job_id,
            idempotency_key=request_key,
            request_hash=request_hash,
            workflow_id=workflow_id,
            output_node_id="pending",
            session_id=resolved_session_id,
            settings=settings,
        )
    except HTTPException:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation storage is unavailable.",
        ) from exc

    if not created:
        if record["state"] == "submitting":
            age_seconds = int(time.time()) - int(record["updated_at"])
            if age_seconds < SUBMISSION_STALE_SECONDS:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The original request is still being submitted.",
                    headers={"Retry-After": "2"},
                )
            _update_generation_record(
                str(record["generation_id"]),
                state="unknown",
                settings=settings,
                error="Prompt submission did not complete before the gateway restarted.",
            )
            refreshed = _generation_record(str(record["generation_id"]), settings)
            if refreshed is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Generation storage is unavailable.",
                )
            record = refreshed
        return _generation_response(record)

    try:
        prompt_id, selected_workflow_id, output_node_id = await _submit_generation(
            data=data,
            content_type=content_type,
            workflow_id=workflow_id,
            composition=composition,
            background_style=background_style,
            strength=strength,
            seed=seed,
            settings=settings,
            request_id=job_id,
            preset_id=selected_preset_id,
            aspect_ratio=aspect_ratio,
            container_mode=container_mode,
            serving_temperature=serving_temperature,
        )
    except _PromptSubmissionUncertain as exc:
        message = str(exc.error.detail)
        try:
            _update_generation_record(
                generation_id,
                state="unknown",
                settings=settings,
                error=message,
            )
        except (OSError, sqlite3.Error):
            pass
        raise HTTPException(
            status_code=exc.error.status_code,
            headers=exc.error.headers,
            detail={
                "message": message,
                "generation_id": generation_id,
                "status": "unknown",
                "status_url": f"/v1/generations/{generation_id}",
            },
        ) from exc
    except HTTPException:
        _delete_unsubmitted_generation(generation_id, settings)
        raise

    try:
        _attach_prompt(
            generation_id,
            prompt_id=prompt_id,
            workflow_id=selected_workflow_id,
            output_node_id=output_node_id,
            settings=settings,
        )
        record = _generation_record(generation_id, settings)
    except (OSError, sqlite3.Error) as exc:
        try:
            _update_generation_record(
                generation_id,
                state="unknown",
                settings=settings,
                error="Prompt was accepted but its metadata could not be stored.",
            )
        except (OSError, sqlite3.Error):
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Prompt was accepted but generation storage is unavailable.",
                "generation_id": generation_id,
                "status": "unknown",
                "status_url": f"/v1/generations/{generation_id}",
            },
        ) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation storage is unavailable.",
        )
    return _generation_response(record)


@app.get("/v1/generations/{generation_id}")
async def get_generation(
    generation_id: str,
    settings: Settings = Depends(require_api_key),
) -> dict[str, Any]:
    token = decode_generation_id(generation_id, secret=settings.signing_key)
    record, _ = await _refresh_generation(generation_id, token=token, settings=settings)
    return _generation_response(record)


@app.post(
    "/v1/generations/{generation_id}/client-observations/frontend-completed",
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_frontend_completed(
    generation_id: str,
    payload: FrontendCompletedObservation,
    settings: Settings = Depends(require_api_key),
) -> dict[str, bool]:
    token = decode_generation_id(generation_id, secret=settings.signing_key)
    record = _generation_record(generation_id, settings)
    if record is None or str(record["job_id"]) != token["j"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation not found.",
        )
    if str(record["state"]) != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Frontend completion can only be recorded for a succeeded generation.",
        )

    with _database(settings) as connection:
        _record_generation_event(
            connection,
            job_id=str(record["job_id"]),
            workflow_id=str(record["workflow_id"]),
            session_id=record.get("session_id"),
            stage="frontend_completed",
            state="completed",
            occurred_at_ms=time.time_ns() // 1_000_000,
            duration_ms=payload.duration_ms,
        )
    return {"accepted": True}


@app.get("/v1/generations/{generation_id}/result")
async def get_generation_result(
    generation_id: str,
    settings: Settings = Depends(require_api_key),
) -> Response:
    token = decode_generation_id(generation_id, secret=settings.signing_key)
    record, image = await _refresh_generation(generation_id, token=token, settings=settings)
    current_status = str(record["state"])
    if current_status == "expired":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Generated image has expired.",
        )
    if current_status != "succeeded" or image is None:
        detail = str(record.get("error") or f"Generation is {current_status}.")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{settings.comfyui_url}/view", params=image)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Result timeout.") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == status.HTTP_404_NOT_FOUND:
            _update_generation_record(
                generation_id,
                state="expired",
                settings=settings,
                error="Generated image has expired.",
            )
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Generated image has expired.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Result download failed.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Result download failed.") from exc
    if len(response.content) > MAX_RESULT_BYTES:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Result exceeds 50 MiB.")
    media_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
    if media_type not in ALLOWED_RESULT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Result has an unsupported content type.",
        )
    return Response(content=response.content, media_type=media_type)
