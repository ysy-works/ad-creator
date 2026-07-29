import importlib.util
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from comfyui.observability.collector import (
    Settings,
    _export_observation,
    _export_trace,
    _trace_definition,
    calculate_openai_cost,
    collect,
    collect_events,
    normalize_openai_usage,
)


PRICING = {
    "schema_version": 1,
    "currency": "USD",
    "models": {
        "gpt-image-2": {
            "input_text_per_token": 0.000005,
            "input_image_per_token": 0.000008,
            "output_image_per_token": 0.00003,
        }
    },
}


def _otel_available() -> bool:
    try:
        return importlib.util.find_spec("opentelemetry.sdk") is not None
    except ModuleNotFoundError:
        return False


def _settings(root: Path) -> Settings:
    pricing_path = root / "pricing.json"
    pricing_path.write_text(json.dumps(PRICING), encoding="utf-8")
    audit_directory = root / "audit"
    audit_directory.mkdir()
    return Settings(
        gateway_database=root / "gateway.sqlite3",
        audit_directory=audit_directory,
        state_database=root / "state.sqlite3",
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        base_url="https://cloud.langfuse.com",
        environment="test",
        release="test-release",
        pricing_path=pricing_path,
        export_timeout_seconds=5,
    )


def _create_gateway_database(path: Path, *, job_id: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE generations (
                generation_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE,
                workflow_id TEXT NOT NULL,
                state TEXT NOT NULL,
                error TEXT,
                session_id TEXT,
                created_at_ms INTEGER,
                completed_at_ms INTEGER,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO generations (
                generation_id, job_id, workflow_id, state, error, session_id,
                created_at_ms, completed_at_ms, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "generation-token",
                job_id,
                "openai-gpt-image-2-low-v1",
                "succeeded",
                None,
                "session-12345678",
                1_000,
                6_000,
                6,
            ),
        )
        connection.commit()


def _create_event_database(path: Path, *, job_id: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE generations (
                generation_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE,
                workflow_id TEXT NOT NULL,
                state TEXT NOT NULL,
                error TEXT,
                session_id TEXT,
                created_at_ms INTEGER,
                completed_at_ms INTEGER,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE generation_observability_events (
                event_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                state TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                session_id TEXT,
                occurred_at_ms INTEGER NOT NULL,
                error TEXT,
                UNIQUE(job_id, stage)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO generations (
                generation_id, job_id, workflow_id, state, error, session_id,
                created_at_ms, completed_at_ms, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "generation-token",
                job_id,
                "model-c-v1",
                "queued",
                None,
                "session-12345678",
                1_000,
                None,
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO generation_observability_events (
                event_id, job_id, stage, state, workflow_id, session_id,
                occurred_at_ms, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{job_id}:accepted",
                job_id,
                "accepted",
                "submitting",
                "model-c-v1",
                "session-12345678",
                1_000,
                None,
            ),
        )
        connection.commit()


class UsageAndCostTest(unittest.TestCase):
    def test_openai_image_usage_is_split_into_exclusive_buckets(self):
        usage, issue = normalize_openai_usage(
            {
                "input_tokens": 1_100,
                "input_tokens_details": {
                    "text_tokens": 100,
                    "image_tokens": 1_000,
                },
                "output_tokens": 2_000,
                "total_tokens": 3_100,
            }
        )
        self.assertIsNone(issue)
        self.assertEqual(
            usage,
            {
                "input_text": 100,
                "input_image": 1_000,
                "output_image": 2_000,
                "total": 3_100,
            },
        )
        cost, complete = calculate_openai_cost(
            model="gpt-image-2", usage_details=usage, pricing=PRICING
        )
        self.assertTrue(complete)
        self.assertEqual(cost["input_text"], 0.0005)
        self.assertEqual(cost["input_image"], 0.008)
        self.assertEqual(cost["output_image"], 0.06)
        self.assertEqual(cost["total"], 0.0685)

    def test_unclassified_input_never_produces_a_false_total_cost(self):
        usage, issue = normalize_openai_usage(
            {
                "input_tokens": 10_000,
                "output_tokens": 2_000,
                "total_tokens": 12_000,
            }
        )
        self.assertEqual(issue, "input_cost_partial")
        self.assertEqual(usage["input_unclassified"], 10_000)
        cost, complete = calculate_openai_cost(
            model="gpt-image-2", usage_details=usage, pricing=PRICING
        )
        self.assertFalse(complete)
        self.assertNotIn("total", cost)
        self.assertEqual(cost["output_image"], 0.06)


class CollectorTest(unittest.TestCase):
    def test_dry_run_reads_terminal_job_and_never_marks_it_exported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _settings(root)
            job_id = "f8bcd81f-60ac-45df-a952-8e5e08dce994"
            _create_gateway_database(settings.gateway_database, job_id=job_id)
            manifest_path = (
                settings.audit_directory / f"{job_id}.request.manifest.json"
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "run_id": job_id,
                        "provider": "openai_images_api",
                        "model": "gpt-image-2",
                        "quality": "low",
                        "preset_id": "natural_white__product_center",
                        "aspect_ratio": "4:5",
                        "elapsed_ms": 2_000,
                        "usage": {
                            "input_tokens": 1_100,
                            "input_tokens_details": {
                                "text_tokens": 100,
                                "image_tokens": 1_000,
                            },
                            "output_tokens": 2_000,
                            "total_tokens": 3_100,
                        },
                    }
                ),
                encoding="utf-8",
            )
            counts = collect(settings=settings, dry_run=True)
            self.assertEqual(counts["exported"], 1)
            with closing(sqlite3.connect(settings.state_database)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM exports").fetchone()[0],
                    0,
                )

    def test_trace_contains_metrics_but_not_raw_prompt_or_image_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _settings(root)
            job_id = "81a8150d-76e9-43fd-ab01-b4d46124efe7"
            manifest_path = root / "audit" / f"{job_id}.request.manifest.json"
            manifest = {
                "run_id": job_id,
                "provider": "openai_images_api",
                "model": "gpt-image-2",
                "quality": "low",
                "preset_id": "natural_white__product_center",
                "aspect_ratio": "4:5",
                "prompt_sha256": "must-not-be-exported",
                "input_images": [{"path": "must-not-be-exported.png"}],
                "elapsed_ms": 2_000,
                "usage": {
                    "input_tokens": 1_100,
                    "input_tokens_details": {
                        "text_tokens": 100,
                        "image_tokens": 1_000,
                    },
                    "output_tokens": 2_000,
                    "total_tokens": 3_100,
                },
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            definition = _trace_definition(
                row={
                    "job_id": job_id,
                    "workflow_id": "openai-gpt-image-2-low-v1",
                    "state": "succeeded",
                    "error": None,
                    "session_id": "session-12345678",
                    "created_at_ms": 1_000,
                    "completed_at_ms": 6_000,
                    "updated_at": 6,
                },
                manifest_entry=(manifest, manifest_path),
                pricing=PRICING,
                settings=settings,
            )
            serialized = json.dumps(definition, sort_keys=True)
            self.assertIn("gateway_observed_duration_ms", serialized)
            self.assertIn("provider_elapsed_ms", serialized)
            self.assertIn("session-12345678", serialized)
            self.assertNotIn("must-not-be-exported", serialized)

    def test_event_is_exported_only_once_across_collector_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _settings(root)
            job_id = "a4e5f7cd-00d8-4ba1-a0b6-3ca33d5d5eb4"
            _create_event_database(settings.gateway_database, job_id=job_id)
            with patch(
                "comfyui.observability.collector._export_observation"
            ) as export:
                first = collect_events(settings=settings)
                second = collect_events(settings=settings)
            self.assertEqual(first["exported"], 1)
            self.assertEqual(second["already_exported"], 1)
            export.assert_called_once()

    def test_release_change_does_not_reexport_sent_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _settings(root)
            job_id = "acfb8390-c279-4d42-807a-5145b7a5ae2a"
            _create_event_database(settings.gateway_database, job_id=job_id)
            with patch(
                "comfyui.observability.collector._export_observation"
            ) as export:
                first = collect_events(settings=settings)
                second = collect_events(
                    settings=replace(settings, release="next-release")
                )
            self.assertEqual(first["exported"], 1)
            self.assertEqual(second["already_exported"], 1)
            self.assertEqual(second["failed"], 0)
            export.assert_called_once()

    def test_uncertain_export_is_not_retried_without_reconciliation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _settings(root)
            job_id = "f2dbe1f7-aa65-4ddf-95bd-0e1b928996e3"
            _create_event_database(settings.gateway_database, job_id=job_id)
            with patch(
                "comfyui.observability.collector._export_observation",
                side_effect=RuntimeError("timeout"),
            ) as export:
                first = collect_events(settings=settings)
                second = collect_events(settings=settings)
            self.assertEqual(first["uncertain"], 1)
            self.assertEqual(second["uncertain"], 1)
            export.assert_called_once()

    def test_uncertain_export_is_reconciled_before_any_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = replace(
                _settings(root),
                reconcile_after_seconds=60,
            )
            job_id = "ac48c843-4c6f-4537-ab46-0bcd24be7563"
            _create_event_database(settings.gateway_database, job_id=job_id)
            with patch(
                "comfyui.observability.collector._export_observation",
                side_effect=RuntimeError("connection reset"),
            ):
                collect_events(settings=settings)
            with closing(
                sqlite3.connect(settings.state_database)
            ) as connection:
                connection.execute(
                    """
                    UPDATE observation_exports
                    SET uncertain_since_ms = ?, last_checked_at_ms = NULL
                    """,
                    (int(time.time() * 1000) - 61_000,),
                )
                connection.commit()
            with (
                patch(
                    "comfyui.observability.collector._observation_exists",
                    return_value=True,
                ) as exists,
                patch(
                    "comfyui.observability.collector._export_observation"
                ) as export,
            ):
                reconciled = collect_events(settings=settings)
            self.assertEqual(reconciled["reconciled"], 1)
            exists.assert_called_once()
            export.assert_not_called()

    def test_absent_uncertain_export_retries_only_after_two_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = replace(
                _settings(root),
                reconcile_after_seconds=60,
            )
            job_id = "ddc92eb2-a1f5-46f9-9cd5-9fd5f5f23206"
            _create_event_database(settings.gateway_database, job_id=job_id)
            with patch(
                "comfyui.observability.collector._export_observation",
                side_effect=RuntimeError("connection reset"),
            ):
                collect_events(settings=settings)
            with closing(
                sqlite3.connect(settings.state_database)
            ) as connection:
                connection.execute(
                    """
                    UPDATE observation_exports
                    SET uncertain_since_ms = ?, last_checked_at_ms = NULL
                    """,
                    (int(time.time() * 1000) - 61_000,),
                )
                connection.commit()
            with (
                patch(
                    "comfyui.observability.collector._observation_exists",
                    return_value=False,
                ) as exists,
                patch(
                    "comfyui.observability.collector._export_observation"
                ) as export,
            ):
                first_check = collect_events(settings=settings)
                with closing(
                    sqlite3.connect(settings.state_database)
                ) as connection:
                    connection.execute(
                        """
                        UPDATE observation_exports
                        SET last_checked_at_ms = ?
                        """,
                        (int(time.time() * 1000) - 31_000,),
                    )
                    connection.commit()
                second_check = collect_events(settings=settings)
                retry = collect_events(settings=settings)
            self.assertEqual(first_check["uncertain"], 1)
            self.assertEqual(second_check["retry_ready"], 1)
            self.assertEqual(retry["exported"], 1)
            self.assertEqual(exists.call_count, 2)
            export.assert_called_once()

    def test_legacy_export_skips_jobs_with_stage_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _settings(root)
            job_id = "94819034-7e25-4fea-a18a-43df83185a31"
            _create_event_database(settings.gateway_database, job_id=job_id)
            with closing(
                sqlite3.connect(settings.gateway_database)
            ) as connection:
                connection.execute(
                    """
                    UPDATE generations
                    SET state = 'succeeded', completed_at_ms = 6_000,
                        updated_at = 6
                    WHERE job_id = ?
                    """,
                    (job_id,),
                )
                connection.commit()
            counts = collect(settings=settings, dry_run=True)
            self.assertEqual(counts["terminal"], 0)
            self.assertEqual(counts["exported"], 0)

    @unittest.skipUnless(
        _otel_available(),
        "OpenTelemetry test dependencies are not installed.",
    )
    def test_single_observation_uses_fixed_trace_span_and_parent_ids(self):
        from opentelemetry.sdk.trace.export import SpanExportResult

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings(Path(temp_dir))
            captured = []

            class FakeExporter:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

                def export(self, spans):
                    captured.extend(spans)
                    return SpanExportResult.SUCCESS

                def shutdown(self):
                    return None

            definition = {
                "trace_id": "1" * 32,
                "observation_id": "2" * 16,
                "parent_observation_id": "3" * 16,
                "name": "generation-queued",
                "start_ns": 1_000_000_000,
                "end_ns": 1_001_000_000,
                "attributes": {
                    "langfuse.observation.type": "span",
                    "langfuse.trace.name": "ad-creator.image-generation",
                },
            }
            with patch(
                "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
                FakeExporter,
            ):
                _export_observation(definition, settings)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0].context.trace_id, int("1" * 32, 16))
            self.assertEqual(captured[0].context.span_id, int("2" * 16, 16))
            self.assertEqual(captured[0].parent.span_id, int("3" * 16, 16))

    @unittest.skipUnless(
        _otel_available(),
        "OpenTelemetry test dependencies are not installed.",
    )
    def test_export_builds_one_root_and_one_generation_span(self):
        from opentelemetry.sdk.trace.export import SpanExportResult

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings(Path(temp_dir))
            captured = []

            class FakeExporter:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

                def export(self, spans):
                    captured.extend(spans)
                    return SpanExportResult.SUCCESS

                def shutdown(self):
                    return None

            definition = {
                "job_id": "f8bcd81f-60ac-45df-a952-8e5e08dce994",
                "start_ns": 1_000_000_000,
                "end_ns": 6_000_000_000,
                "root_attributes": {
                    "langfuse.observation.type": "span",
                    "langfuse.trace.name": "ad-creator.image-generation",
                },
                "child": {
                    "name": "openai-image-edit",
                    "start_ns": 2_000_000_000,
                    "end_ns": 5_000_000_000,
                    "attributes": {
                        "langfuse.observation.type": "generation",
                        "langfuse.observation.model.name": "gpt-image-2",
                    },
                },
            }
            with patch(
                "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
                FakeExporter,
            ):
                trace_id = _export_trace(definition, settings)
            self.assertEqual(len(trace_id), 32)
            self.assertEqual(len(captured), 2)
            self.assertEqual(
                {span.name for span in captured},
                {"image-generation", "openai-image-edit"},
            )


if __name__ == "__main__":
    unittest.main()
