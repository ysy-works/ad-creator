import argparse
import base64
import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICING_PATH = Path(__file__).with_name("openai_image_pricing.json")
TERMINAL_STATES = {"succeeded", "failed", "expired"}
OPENAI_WORKFLOWS = {"gpt-image-2-v1", "openai-gpt-image-2-low-v1"}
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    gateway_database: Path
    audit_directory: Path
    state_database: Path
    public_key: str
    secret_key: str
    base_url: str
    environment: str
    release: str | None
    pricing_path: Path
    export_timeout_seconds: int

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> "Settings":
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
        base_url = os.environ.get(
            "LANGFUSE_BASE_URL", "https://cloud.langfuse.com"
        ).strip().rstrip("/")
        if require_credentials:
            if len(public_key) < 8 or len(secret_key) < 8:
                raise RuntimeError(
                    "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required."
                )
            if not base_url.startswith("https://"):
                raise RuntimeError("LANGFUSE_BASE_URL must use HTTPS.")
        try:
            timeout = int(
                os.environ.get("AD_CREATOR_LANGFUSE_TIMEOUT_SECONDS", "15")
            )
        except ValueError as exc:
            raise RuntimeError(
                "AD_CREATOR_LANGFUSE_TIMEOUT_SECONDS must be an integer."
            ) from exc
        if not 1 <= timeout <= 120:
            raise RuntimeError(
                "AD_CREATOR_LANGFUSE_TIMEOUT_SECONDS must be between 1 and 120."
            )
        release = os.environ.get("AD_CREATOR_OBSERVABILITY_RELEASE", "").strip()
        return cls(
            gateway_database=Path(
                os.environ.get(
                    "AD_CREATOR_GATEWAY_DB",
                    "/var/lib/ad-creator-gateway/gateway.sqlite3",
                )
            ).expanduser(),
            audit_directory=Path(
                os.environ.get(
                    "AD_CREATOR_OPENAI_AUDIT_DIR",
                    "/opt/comfyui/ComfyUI/output/ad_creator/audit",
                )
            ).expanduser(),
            state_database=Path(
                os.environ.get(
                    "AD_CREATOR_LANGFUSE_STATE_DB",
                    "/var/lib/ad-creator-observability/state.sqlite3",
                )
            ).expanduser(),
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            environment=os.environ.get(
                "AD_CREATOR_OBSERVABILITY_ENVIRONMENT", "production"
            ).strip()
            or "production",
            release=release or None,
            pricing_path=Path(
                os.environ.get(
                    "AD_CREATOR_OPENAI_PRICING_FILE", str(DEFAULT_PRICING_PATH)
                )
            ).expanduser(),
            export_timeout_seconds=timeout,
        )


def _safe_number(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or int(value) != value:
        return None
    return int(value)


def normalize_openai_usage(usage: Any) -> tuple[dict[str, int], str | None]:
    if not isinstance(usage, dict):
        return {}, "usage_missing"
    input_total = _safe_number(usage.get("input_tokens"))
    output_image = _safe_number(usage.get("output_tokens"))
    provider_total = _safe_number(usage.get("total_tokens"))
    details = usage.get("input_tokens_details")
    details = details if isinstance(details, dict) else {}
    input_text = _safe_number(details.get("text_tokens"))
    input_image = _safe_number(details.get("image_tokens"))

    result: dict[str, int] = {}
    issue: str | None = None
    classified_input = 0
    if input_text is not None:
        result["input_text"] = input_text
        classified_input += input_text
    if input_image is not None:
        result["input_image"] = input_image
        classified_input += input_image
    if input_total is not None:
        if classified_input > input_total:
            return {}, "input_detail_exceeds_total"
        if classified_input < input_total:
            result["input_unclassified"] = input_total - classified_input
            issue = "input_cost_partial"
    elif classified_input == 0:
        issue = "input_usage_missing"

    if output_image is not None:
        result["output_image"] = output_image
    else:
        issue = issue or "output_usage_missing"

    exclusive_total = sum(result.values())
    if provider_total is not None and provider_total == exclusive_total:
        result["total"] = provider_total
    elif provider_total is not None:
        issue = issue or "provider_total_mismatch"
        result["total"] = exclusive_total
    elif result:
        result["total"] = exclusive_total
    return result, issue


def calculate_openai_cost(
    *, model: str, usage_details: dict[str, int], pricing: dict[str, Any]
) -> tuple[dict[str, float], bool]:
    models = pricing.get("models")
    rates = models.get(model) if isinstance(models, dict) else None
    if not isinstance(rates, dict):
        return {}, False
    rate_keys = {
        "input_text": "input_text_per_token",
        "input_image": "input_image_per_token",
        "output_image": "output_image_per_token",
    }
    result: dict[str, float] = {}
    for usage_key, rate_key in rate_keys.items():
        units = usage_details.get(usage_key)
        rate = rates.get(rate_key)
        if (
            isinstance(units, int)
            and not isinstance(rate, bool)
            and isinstance(rate, (int, float))
            and rate >= 0
        ):
            result[usage_key] = round(units * float(rate), 12)
    complete = (
        "input_unclassified" not in usage_details
        and all(
            key not in usage_details or key in result
            for key in ("input_text", "input_image", "output_image")
        )
        and bool(result)
    )
    if complete:
        result["total"] = round(sum(result.values()), 12)
    return result, complete


def _load_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    if path.stat().st_size > maximum_bytes:
        raise ValueError(f"JSON file is larger than {maximum_bytes} bytes.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object.")
    return value


def _terminal_rows(database_path: Path) -> list[dict[str, Any]]:
    if not database_path.is_file():
        raise RuntimeError(f"Gateway database does not exist: {database_path}")
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        connection.row_factory = sqlite3.Row
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(generations)"
            ).fetchall()
        }
        required = {
            "job_id",
            "workflow_id",
            "state",
            "error",
            "session_id",
            "created_at_ms",
            "completed_at_ms",
            "updated_at",
        }
        if not required.issubset(columns):
            raise RuntimeError(
                "Gateway database has not been migrated for observability."
            )
        rows = connection.execute(
            """
            SELECT job_id, workflow_id, state, error, session_id,
                   created_at_ms, completed_at_ms, updated_at
            FROM generations
            WHERE state IN ('succeeded', 'failed', 'expired')
              AND created_at_ms IS NOT NULL
              AND completed_at_ms IS NOT NULL
            ORDER BY completed_at_ms, job_id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _state_connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS exports (
            job_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            exported_at_ms INTEGER NOT NULL
        )
        """
    )
    connection.commit()
    if os.name != "nt":
        path.chmod(0o600)
    return connection


def _manifest_for_job(
    job_id: str, audit_directory: Path
) -> tuple[dict[str, Any], Path] | None:
    matches = sorted(audit_directory.glob(f"{job_id}.*.manifest.json"))
    if not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError(f"Multiple audit manifests found for job {job_id}.")
    manifest = _load_json(matches[0], maximum_bytes=MAX_MANIFEST_BYTES)
    if manifest.get("run_id") != job_id:
        raise RuntimeError(f"Audit manifest run_id mismatch for job {job_id}.")
    return manifest, matches[0]


def _pricing(path: Path) -> dict[str, Any]:
    value = _load_json(path, maximum_bytes=256 * 1024)
    if value.get("schema_version") != 1 or value.get("currency") != "USD":
        raise RuntimeError("Unsupported OpenAI pricing file.")
    return value


def _json_attribute(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def _trace_definition(
    *,
    row: dict[str, Any],
    manifest_entry: tuple[dict[str, Any], Path] | None,
    pricing: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    start_ms = int(row["created_at_ms"])
    end_ms = int(row["completed_at_ms"])
    if end_ms < start_ms:
        raise RuntimeError(f"Invalid gateway timestamps for job {row['job_id']}.")
    workflow_id = str(row["workflow_id"])
    state = str(row["state"])
    session_id = row.get("session_id")
    common: dict[str, Any] = {
        "langfuse.trace.name": "ad-creator.image-generation",
        "langfuse.environment": settings.environment,
        "langfuse.observation.metadata.workflow_id": workflow_id,
    }
    if settings.release:
        common["langfuse.release"] = settings.release
    if isinstance(session_id, str) and session_id:
        common["langfuse.session.id"] = session_id

    root_attributes = {
        **common,
        "langfuse.observation.type": "span",
        "langfuse.observation.input": _json_attribute(
            {"workflow_id": workflow_id}
        ),
        "langfuse.observation.output": _json_attribute({"status": state}),
        "langfuse.observation.metadata.status": state,
        "langfuse.observation.metadata.gateway_observed_duration_ms": (
            end_ms - start_ms
        ),
        "langfuse.observation.metadata.gateway_timing_definition": (
            "request accepted to terminal state first observed"
        ),
    }
    if state == "failed":
        root_attributes["langfuse.observation.level"] = "ERROR"
        root_attributes["langfuse.observation.status_message"] = str(
            row.get("error") or "Generation failed."
        )[:500]

    child: dict[str, Any] | None = None
    if manifest_entry is not None:
        manifest, manifest_path = manifest_entry
        model = str(manifest.get("model") or "")
        usage_details, usage_issue = normalize_openai_usage(
            manifest.get("usage")
        )
        cost_details, cost_complete = calculate_openai_cost(
            model=model, usage_details=usage_details, pricing=pricing
        )
        if usage_issue is not None:
            cost_complete = False
            cost_details.pop("total", None)
        elapsed_ms = _safe_number(manifest.get("elapsed_ms")) or 0
        provider_end_ms = min(
            end_ms, manifest_path.stat().st_mtime_ns // 1_000_000
        )
        provider_start_ms = max(start_ms, provider_end_ms - elapsed_ms)
        child_attributes: dict[str, Any] = {
            **common,
            "langfuse.observation.type": "generation",
            "langfuse.observation.model.name": model,
            "langfuse.observation.input": _json_attribute(
                {"preset_id": manifest.get("preset_id")}
            ),
            "langfuse.observation.output": _json_attribute(
                {"status": "succeeded"}
            ),
            "langfuse.observation.model.parameters": _json_attribute(
                {
                    "quality": manifest.get("quality"),
                    "aspect_ratio": manifest.get("aspect_ratio"),
                }
            ),
            "langfuse.observation.metadata.provider": str(
                manifest.get("provider") or "openai_images_api"
            ),
            "langfuse.observation.metadata.preset_id": str(
                manifest.get("preset_id") or ""
            ),
            "langfuse.observation.metadata.provider_elapsed_ms": elapsed_ms,
            "langfuse.observation.metadata.provider_timing_anchor": (
                "audit_manifest_mtime"
            ),
            "langfuse.observation.metadata.cost_complete": cost_complete,
        }
        if usage_details:
            child_attributes["langfuse.observation.usage_details"] = (
                _json_attribute(usage_details)
            )
        if cost_details:
            child_attributes["langfuse.observation.cost_details"] = (
                _json_attribute(cost_details)
            )
        if usage_issue:
            child_attributes[
                "langfuse.observation.metadata.usage_issue"
            ] = usage_issue
        child = {
            "name": "openai-image-edit",
            "start_ns": provider_start_ms * 1_000_000,
            "end_ns": provider_end_ms * 1_000_000,
            "attributes": child_attributes,
        }

    fingerprint = hashlib.sha256(
        _json_attribute(
            {
                "job_id": row["job_id"],
                "workflow_id": workflow_id,
                "state": state,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "child": child,
            }
        ).encode("ascii")
    ).hexdigest()
    return {
        "job_id": str(row["job_id"]),
        "start_ns": start_ms * 1_000_000,
        "end_ns": end_ms * 1_000_000,
        "root_attributes": root_attributes,
        "child": child,
        "fingerprint": fingerprint,
    }


def _trace_id(job_id: str) -> str:
    value = hashlib.sha256(f"trace:{job_id}".encode("ascii")).hexdigest()[:32]
    return value if int(value, 16) != 0 else "1".zfill(32)


def _export_trace(definition: dict[str, Any], settings: Settings) -> str:
    try:
        from opentelemetry import trace
        from opentelemetry.context import Context
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import (
            IdGenerator,
            ReadableSpan,
            Span,
            SpanProcessor,
            TracerProvider,
        )
        from opentelemetry.sdk.trace.export import SpanExportResult
    except ImportError as exc:
        raise RuntimeError(
            "Install comfyui/observability/requirements.txt before exporting."
        ) from exc

    job_id = str(definition["job_id"])

    class DeterministicIdGenerator(IdGenerator):
        def __init__(self) -> None:
            self.counter = 0

        def generate_trace_id(self) -> int:
            return int(_trace_id(job_id), 16)

        def generate_span_id(self) -> int:
            self.counter += 1
            digest = hashlib.sha256(
                f"span:{job_id}:{self.counter}".encode("ascii")
            ).digest()
            value = int.from_bytes(digest[:8], "big")
            return value or 1

    class CollectingProcessor(SpanProcessor):
        def __init__(self) -> None:
            self.spans: list[ReadableSpan] = []

        def on_start(
            self, span: Span, parent_context: Context | None = None
        ) -> None:
            return None

        def on_end(self, span: ReadableSpan) -> None:
            self.spans.append(span)

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    processor = CollectingProcessor()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "ad-creator-observability"}),
        id_generator=DeterministicIdGenerator(),
    )
    provider.add_span_processor(processor)
    tracer = provider.get_tracer("ad-creator.langfuse-collector", "1.0.0")
    root = tracer.start_span(
        "image-generation",
        start_time=int(definition["start_ns"]),
        attributes=definition["root_attributes"],
    )
    child = definition.get("child")
    if isinstance(child, dict):
        context = trace.set_span_in_context(root)
        provider_span = tracer.start_span(
            str(child["name"]),
            context=context,
            start_time=int(child["start_ns"]),
            attributes=child["attributes"],
        )
        provider_span.end(end_time=int(child["end_ns"]))
    root.end(end_time=int(definition["end_ns"]))

    authorization = base64.b64encode(
        f"{settings.public_key}:{settings.secret_key}".encode("utf-8")
    ).decode("ascii")
    exporter = OTLPSpanExporter(
        endpoint=f"{settings.base_url}/api/public/otel/v1/traces",
        headers={
            "Authorization": f"Basic {authorization}",
            "x-langfuse-ingestion-version": "4",
        },
        timeout=settings.export_timeout_seconds,
    )
    try:
        result = exporter.export(processor.spans)
    finally:
        exporter.shutdown()
        provider.shutdown()
    if result is not SpanExportResult.SUCCESS:
        raise RuntimeError("Langfuse OTLP export failed.")
    return _trace_id(job_id)


def collect(*, settings: Settings, dry_run: bool = False) -> dict[str, int]:
    rows = _terminal_rows(settings.gateway_database)
    pricing = _pricing(settings.pricing_path)
    counts = {
        "terminal": len(rows),
        "already_exported": 0,
        "exported": 0,
        "waiting_for_manifest": 0,
        "failed": 0,
    }
    with closing(_state_connection(settings.state_database)) as state:
        exported = {
            str(row[0])
            for row in state.execute("SELECT job_id FROM exports").fetchall()
        }
        for row in rows:
            job_id = str(row["job_id"])
            if job_id in exported:
                counts["already_exported"] += 1
                continue
            manifest_entry = None
            if str(row["workflow_id"]) in OPENAI_WORKFLOWS:
                try:
                    manifest_entry = _manifest_for_job(
                        job_id, settings.audit_directory
                    )
                except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
                    print(
                        f"collector skipped job {job_id}: {exc}",
                        file=sys.stderr,
                    )
                    counts["failed"] += 1
                    continue
                if row["state"] in {"succeeded", "expired"} and manifest_entry is None:
                    counts["waiting_for_manifest"] += 1
                    continue
            try:
                definition = _trace_definition(
                    row=row,
                    manifest_entry=manifest_entry,
                    pricing=pricing,
                    settings=settings,
                )
                if dry_run:
                    counts["exported"] += 1
                    continue
                trace_id = _export_trace(definition, settings)
                state.execute(
                    """
                    INSERT INTO exports (
                        job_id, trace_id, fingerprint, exported_at_ms
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        trace_id,
                        definition["fingerprint"],
                        time.time_ns() // 1_000_000,
                    ),
                )
                state.commit()
                counts["exported"] += 1
            except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
                print(
                    f"collector failed job {job_id}: {exc}",
                    file=sys.stderr,
                )
                counts["failed"] += 1
    return counts


def send_canary(settings: Settings) -> str:
    now_ns = time.time_ns()
    definition = {
        "job_id": str(uuid.uuid4()),
        "start_ns": now_ns - 2_000_000_000,
        "end_ns": now_ns,
        "root_attributes": {
            "langfuse.observation.type": "span",
            "langfuse.trace.name": "ad-creator.observability-canary",
            "langfuse.environment": settings.environment,
            "langfuse.observation.input": '{"kind":"canary"}',
            "langfuse.observation.output": '{"status":"ok"}',
        },
        "child": {
            "name": "openai-image-edit-canary",
            "start_ns": now_ns - 1_500_000_000,
            "end_ns": now_ns - 500_000_000,
            "attributes": {
                "langfuse.observation.type": "generation",
                "langfuse.observation.model.name": "gpt-image-2",
                "langfuse.environment": settings.environment,
                "langfuse.observation.input": '{"kind":"canary"}',
                "langfuse.observation.output": '{"status":"ok"}',
            },
        },
    }
    return _export_trace(definition, settings)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export completed ad-creator generations to Langfuse."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate pending records without sending data.",
    )
    parser.add_argument(
        "--canary",
        action="store_true",
        help="Send one synthetic trace without reading generation data.",
    )
    args = parser.parse_args()
    if args.dry_run and args.canary:
        parser.error("--dry-run and --canary cannot be used together.")
    try:
        settings = Settings.from_env(require_credentials=not args.dry_run)
        if args.canary:
            print(
                json.dumps(
                    {"canary": "exported", "trace_id": send_canary(settings)},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
            return 0
        counts = collect(settings=settings, dry_run=args.dry_run)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        print(f"collector error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(counts, ensure_ascii=True, sort_keys=True))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
