import io
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from comfyui.gateway.app import (
    Settings,
    _PromptSubmissionUncertain,
    _attach_prompt,
    _database,
    _delete_unsubmitted_generation,
    _failure_message,
    _generation_record,
    _output_image,
    _queued_prompt_ids,
    _recorded_image,
    _request_hash,
    _reserve_generation,
    _submit_generation,
    _update_generation_record,
    app,
    decode_generation_id,
    encode_generation_id,
)
from comfyui.orchestrator import PresetRegistryConfigurationError


API_KEY = "test-key-" + "x" * 40
SIGNING_KEY = "signing-key-" + "y" * 40
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def _png(color: str = "white") -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(stream, format="PNG")
    return stream.getvalue()


def _request_headers(idempotency_key: str = "request-key-0001") -> dict[str, str]:
    return {**AUTH_HEADERS, "Idempotency-Key": idempotency_key}


def _reserve_test_generation(settings: Settings) -> tuple[str, str]:
    job_id = str(uuid.uuid4())
    generation_id = encode_generation_id(job_id=job_id, secret=SIGNING_KEY)
    _reserve_generation(
        generation_id=generation_id,
        job_id=job_id,
        idempotency_key=f"test-{uuid.uuid4()}",
        request_hash=uuid.uuid4().hex,
        workflow_id="model-c-v1",
        output_node_id="pending",
        settings=settings,
    )
    return generation_id, job_id


class GatewayHelpersTest(unittest.TestCase):
    def test_generation_id_round_trip_and_tamper_rejection(self):
        job_id = str(uuid.uuid4())
        token = encode_generation_id(job_id=job_id, secret=SIGNING_KEY)
        self.assertEqual(decode_generation_id(token, secret=SIGNING_KEY), {"j": job_id})
        with self.assertRaises(HTTPException):
            decode_generation_id(token + "x", secret=SIGNING_KEY)

    def test_extracts_output_and_failure(self):
        entry = {
            "outputs": {
                "3": {
                    "images": [
                        {
                            "filename": "result.png",
                            "subfolder": "ad",
                            "type": "output",
                        }
                    ]
                }
            },
            "status": {"status_str": "success"},
        }
        self.assertEqual(
            _output_image(entry, "3"),
            {"filename": "result.png", "subfolder": "ad", "type": "output"},
        )
        failed = {
            "status": {
                "status_str": "error",
                "messages": [
                    ["execution_error", {"exception_message": "model failed"}]
                ],
            }
        }
        self.assertEqual(_failure_message(failed), "Generation failed.")
        failed["status"]["messages"][0][1]["exception_message"] = (
            "[rate_limit_exceeded] provider details must stay private"
        )
        self.assertEqual(
            _failure_message(failed),
            "rate_limit_exceeded: The image provider is temporarily rate limited.",
        )

    def test_extracts_queue_prompt_ids(self):
        self.assertEqual(_queued_prompt_ids([[1, "a"], [2, "b"]]), {"a", "b"})

    def test_completed_result_metadata_survives_new_database_connection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "AD_CREATOR_GATEWAY_API_KEY": API_KEY,
                    "AD_CREATOR_GENERATION_SIGNING_KEY": SIGNING_KEY,
                    "AD_CREATOR_GATEWAY_DB": str(
                        Path(temp_dir) / "gateway.sqlite3"
                    ),
                },
                clear=False,
            ):
                settings = Settings.from_env()
                generation_id, _ = _reserve_test_generation(settings)
                _attach_prompt(
                    generation_id,
                    prompt_id=str(uuid.uuid4()),
                    workflow_id="model-c-v1",
                    output_node_id="3",
                    settings=settings,
                )
                expected = {
                    "filename": "result.png",
                    "subfolder": "ad_creator",
                    "type": "output",
                }
                _update_generation_record(
                    generation_id,
                    state="succeeded",
                    settings=settings,
                    image=expected,
                )

                reloaded = _generation_record(generation_id, Settings.from_env())
                self.assertIsNotNone(reloaded)
                self.assertEqual(reloaded["state"], "succeeded")
                self.assertEqual(_recorded_image(reloaded), expected)

    def test_terminal_state_cannot_regress_or_lose_result_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "AD_CREATOR_GATEWAY_API_KEY": API_KEY,
                    "AD_CREATOR_GENERATION_SIGNING_KEY": SIGNING_KEY,
                    "AD_CREATOR_GATEWAY_DB": str(
                        Path(temp_dir) / "gateway.sqlite3"
                    ),
                },
                clear=False,
            ):
                settings = Settings.from_env()
                generation_id, _ = _reserve_test_generation(settings)
                expected = {
                    "filename": "result.png",
                    "subfolder": "ad_creator",
                    "type": "output",
                }
                _update_generation_record(
                    generation_id,
                    state="succeeded",
                    settings=settings,
                    image=expected,
                )
                _update_generation_record(
                    generation_id,
                    state="running",
                    settings=settings,
                )
                record = _generation_record(generation_id, settings)
                self.assertEqual(record["state"], "succeeded")
                self.assertEqual(_recorded_image(record), expected)
                self.assertIsNotNone(record["completed_at_ms"])
                completed_at_ms = record["completed_at_ms"]
                _update_generation_record(
                    generation_id,
                    state="running",
                    settings=settings,
                )
                record = _generation_record(generation_id, settings)
                self.assertEqual(record["completed_at_ms"], completed_at_ms)

    def test_legacy_database_receives_additive_observability_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "gateway.sqlite3"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE generations (
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
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO generations (
                        generation_id, job_id, idempotency_key, request_hash,
                        prompt_id, workflow_id, output_node_id, state,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy-generation",
                        "legacy-job",
                        "legacy-key",
                        "legacy-hash",
                        "legacy-prompt",
                        "model-c-v1",
                        "3",
                        "failed",
                        100,
                        120,
                    ),
                )
                connection.commit()
            with patch.dict(
                os.environ,
                {
                    "AD_CREATOR_GATEWAY_API_KEY": API_KEY,
                    "AD_CREATOR_GENERATION_SIGNING_KEY": SIGNING_KEY,
                    "AD_CREATOR_GATEWAY_DB": str(database_path),
                },
                clear=False,
            ):
                settings = Settings.from_env()
                with _database(settings) as connection:
                    columns = {
                        str(row[1])
                        for row in connection.execute(
                            "PRAGMA table_info(generations)"
                        ).fetchall()
                    }
                    row = connection.execute(
                        "SELECT * FROM generations WHERE job_id = 'legacy-job'"
                    ).fetchone()
            self.assertTrue(
                {"session_id", "created_at_ms", "completed_at_ms"}.issubset(
                    columns
                )
            )
            self.assertEqual(row["created_at_ms"], 100_000)
            self.assertEqual(row["completed_at_ms"], 120_000)


class GatewayApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "AD_CREATOR_GATEWAY_API_KEY": API_KEY,
                "AD_CREATOR_GENERATION_SIGNING_KEY": SIGNING_KEY,
                "AD_CREATOR_GATEWAY_DB": str(
                    Path(self.temp_dir.name) / "gateway.sqlite3"
                ),
            },
            clear=False,
        )
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def test_requires_bearer_key(self):
        response = self.client.post(
            "/v1/generations",
            headers={"Idempotency-Key": "request-key-0001"},
            files={"image": ("input.png", _png(), "image/png")},
        )
        self.assertEqual(response.status_code, 401)

    def test_requires_idempotency_key(self):
        response = self.client.post(
            "/v1/generations",
            headers=AUTH_HEADERS,
            files={"image": ("input.png", _png(), "image/png")},
        )
        self.assertEqual(response.status_code, 400)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_session_id_is_persisted_without_being_exposed(
        self, submit_generation
    ):
        submit_generation.return_value = (str(uuid.uuid4()), "model-c-v1", "3")
        response = self.client.post(
            "/v1/generations",
            headers={
                **_request_headers("session-request-key"),
                "X-Session-ID": "7d458bed-96ed-4b70-b90e-096db76ae153",
            },
            files={"image": ("input.png", _png(), "image/png")},
        )
        self.assertEqual(response.status_code, 202)
        record = _generation_record(
            response.json()["generation_id"], Settings.from_env()
        )
        self.assertEqual(
            record["session_id"], "7d458bed-96ed-4b70-b90e-096db76ae153"
        )
        self.assertIsNotNone(record["created_at_ms"])
        self.assertNotIn("session_id", response.json())

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_invalid_session_id_is_rejected_before_submission(
        self, submit_generation
    ):
        response = self.client.post(
            "/v1/generations",
            headers={
                **_request_headers("invalid-session-key"),
                "X-Session-ID": "contains spaces",
            },
            files={"image": ("input.png", _png(), "image/png")},
        )
        self.assertEqual(response.status_code, 400)
        submit_generation.assert_not_awaited()

    def test_health_reports_misconfigured_gateway(self):
        with patch.dict(
            os.environ, {"AD_CREATOR_GATEWAY_API_KEY": ""}, clear=False
        ):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"ok": False, "gateway": "misconfigured"}
        )

    @patch("comfyui.gateway.app._json_request", new_callable=AsyncMock)
    def test_openai_health_does_not_require_model_c(self, json_request):
        async def response_for(method, url, **kwargs):
            if "/object_info/" in url:
                return {"AdCreatorOpenAIImageGenerate": {"input": {}}}
            return {"system": "ready"}

        json_request.side_effect = response_for
        with patch.dict(
            os.environ,
            {"AD_CREATOR_HEALTH_WORKFLOW_ID": "openai-gpt-image-2-low-v1"},
            clear=False,
        ):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["health_workflow_id"], "openai-gpt-image-2-low-v1"
        )
        self.assertTrue(payload["workflow_registry"])
        self.assertTrue(payload["preset_registry"])
        self.assertTrue(payload["openai_node"])
        self.assertTrue(payload["comfyui"])
        self.assertNotIn("model_c", payload)
        self.assertEqual(json_request.await_count, 2)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_submits_generation_and_returns_signed_job(self, submit_generation):
        prompt_id = str(uuid.uuid4())
        submit_generation.return_value = (
            prompt_id,
            "openai-gpt-image-2-low-v1",
            "3",
        )
        response = self.client.post(
            "/v1/generations",
            headers=_request_headers(),
            files={"image": ("input.png", _png(), "image/png")},
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "composition": "medium",
                "background_style": "white",
                "strength": "low",
            },
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        decoded = decode_generation_id(
            payload["generation_id"], secret=SIGNING_KEY
        )
        record = _generation_record(
            payload["generation_id"], Settings.from_env()
        )
        self.assertEqual(decoded["j"], record["job_id"])
        self.assertEqual(record["prompt_id"], prompt_id)
        self.assertEqual(record["output_node_id"], "3")
        self.assertEqual(
            submit_generation.await_args.kwargs["preset_id"],
            "natural_white__product_center",
        )
        self.assertEqual(
            submit_generation.await_args.kwargs["request_id"], record["job_id"]
        )

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_explicit_preset_id_selects_published_wood_preset(self, submit_generation):
        submit_generation.return_value = (
            str(uuid.uuid4()),
            "openai-gpt-image-2-low-v1",
            "3",
        )
        response = self.client.post(
            "/v1/generations",
            headers=_request_headers("explicit-preset-key"),
            files={"image": ("input.png", _png(), "image/png")},
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "wood__product_center",
                "container_mode": "reconstruct_source",
                "serving_temperature": "cold",
                "aspect_ratio": "1:1",
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            submit_generation.await_args.kwargs["preset_id"], "wood__product_center"
        )
        self.assertEqual(submit_generation.await_args.kwargs["aspect_ratio"], "1:1")
        self.assertEqual(
            submit_generation.await_args.kwargs["container_mode"],
            "reconstruct_source",
        )
        self.assertEqual(
            submit_generation.await_args.kwargs["serving_temperature"], "cold"
        )

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_unknown_preset_is_rejected_before_submission(self, submit_generation):
        response = self.client.post(
            "/v1/generations",
            headers=_request_headers("unpublished-preset-key"),
            files={"image": ("input.png", _png(), "image/png")},
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "unknown__handheld_lifestyle",
            },
        )
        self.assertEqual(response.status_code, 400)
        submit_generation.assert_not_awaited()

    @patch("comfyui.gateway.app.resolve_published_preset")
    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_broken_preset_registry_is_service_unavailable(
        self, submit_generation, resolve_preset
    ):
        resolve_preset.side_effect = PresetRegistryConfigurationError("broken")
        response = self.client.post(
            "/v1/generations",
            headers=_request_headers("broken-preset-registry"),
            files={"image": ("input.png", _png(), "image/png")},
            data={"workflow_id": "openai-gpt-image-2-low-v1"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Preset registry is unavailable.")
        submit_generation.assert_not_awaited()

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_openai_idempotency_ignores_legacy_fields(self, submit_generation):
        submit_generation.return_value = (
            str(uuid.uuid4()),
            "openai-gpt-image-2-low-v1",
            "3",
        )
        image = _png()
        first = self.client.post(
            "/v1/generations",
            headers=_request_headers("openai-canonical-retry"),
            files={"image": ("input.png", image, "image/png")},
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "natural_white__product_center",
            },
        )
        second = self.client.post(
            "/v1/generations",
            headers=_request_headers("openai-canonical-retry"),
            files={"image": ("input.png", image, "image/png")},
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "natural_white__product_center",
                "background_style": "white",
                "composition": "aerial",
                "strength": "high",
                "seed": "42",
            },
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["generation_id"], second.json()["generation_id"])
        self.assertEqual(submit_generation.await_count, 1)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_openai_idempotency_distinguishes_aspect_ratio(self, submit_generation):
        submit_generation.return_value = (
            str(uuid.uuid4()),
            "openai-gpt-image-2-low-v1",
            "3",
        )
        image = _png()
        common = {
            "headers": _request_headers("openai-aspect-conflict"),
            "files": {"image": ("input.png", image, "image/png")},
        }
        portrait = self.client.post(
            "/v1/generations",
            **common,
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "natural_white__product_center",
                "aspect_ratio": "4:5",
            },
        )
        square = self.client.post(
            "/v1/generations",
            **common,
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "natural_white__product_center",
                "aspect_ratio": "1:1",
            },
        )
        self.assertEqual(portrait.status_code, 202)
        self.assertEqual(square.status_code, 409)
        self.assertEqual(submit_generation.await_count, 1)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_openai_idempotency_distinguishes_runtime_policy(self, submit_generation):
        submit_generation.return_value = (
            str(uuid.uuid4()),
            "openai-gpt-image-2-low-v1",
            "3",
        )
        image = _png()
        common = {
            "headers": _request_headers("openai-runtime-policy-conflict"),
            "files": {"image": ("input.png", image, "image/png")},
        }
        cold = self.client.post(
            "/v1/generations",
            **common,
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "wood__product_center",
                "container_mode": "reconstruct_source",
                "serving_temperature": "cold",
            },
        )
        hot = self.client.post(
            "/v1/generations",
            **common,
            data={
                "workflow_id": "openai-gpt-image-2-low-v1",
                "preset_id": "wood__product_center",
                "container_mode": "reconstruct_source",
                "serving_temperature": "hot",
            },
        )
        self.assertEqual(cold.status_code, 202)
        self.assertEqual(hot.status_code, 409)
        self.assertEqual(submit_generation.await_count, 1)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_same_idempotent_request_is_submitted_once(self, submit_generation):
        submit_generation.return_value = (str(uuid.uuid4()), "model-c-v1", "3")
        request = {
            "headers": _request_headers("same-request-key"),
            "files": {"image": ("input.png", _png(), "image/png")},
            "data": {"background_style": "white"},
        }
        first = self.client.post("/v1/generations", **request)
        second = self.client.post("/v1/generations", **request)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(
            first.json()["generation_id"], second.json()["generation_id"]
        )
        self.assertEqual(submit_generation.await_count, 1)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_in_flight_duplicate_cannot_invalidate_original_reservation(
        self, submit_generation
    ):
        settings = Settings.from_env()
        data = _png()
        request_key = "in-flight-request-key"
        job_id = str(uuid.uuid4())
        generation_id = encode_generation_id(job_id=job_id, secret=SIGNING_KEY)
        _reserve_generation(
            generation_id=generation_id,
            job_id=job_id,
            idempotency_key=request_key,
            request_hash=_request_hash(
                data=data,
                content_type="image/png",
                workflow_id="model-c-v1",
                workflow_values={
                    "background_style": "wood",
                    "composition": "medium",
                    "seed": None,
                    "strength": "medium",
                },
            ),
            workflow_id="model-c-v1",
            output_node_id="pending",
            settings=settings,
        )

        duplicate = self.client.post(
            "/v1/generations",
            headers=_request_headers(request_key),
            files={"image": ("input.png", data, "image/png")},
            data={"workflow_id": "model-c-v1"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.headers["Retry-After"], "2")
        submit_generation.assert_not_awaited()

        polled = self.client.get(
            f"/v1/generations/{generation_id}", headers=AUTH_HEADERS
        )
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json()["status"], "unknown")
        self.assertEqual(
            _generation_record(generation_id, settings)["state"], "submitting"
        )

        _delete_unsubmitted_generation(generation_id, settings)
        self.assertIsNone(_generation_record(generation_id, settings))

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_stale_submission_becomes_unknown_without_resubmission(
        self, submit_generation
    ):
        settings = Settings.from_env()
        data = _png()
        request_key = "stale-request-key"
        job_id = str(uuid.uuid4())
        generation_id = encode_generation_id(job_id=job_id, secret=SIGNING_KEY)
        _reserve_generation(
            generation_id=generation_id,
            job_id=job_id,
            idempotency_key=request_key,
            request_hash=_request_hash(
                data=data,
                content_type="image/png",
                workflow_id="model-c-v1",
                workflow_values={
                    "background_style": "wood",
                    "composition": "medium",
                    "seed": None,
                    "strength": "medium",
                },
            ),
            workflow_id="model-c-v1",
            output_node_id="pending",
            settings=settings,
        )
        with closing(sqlite3.connect(settings.database_path)) as connection:
            with connection:
                connection.execute(
                    "UPDATE generations SET updated_at = ? WHERE generation_id = ?",
                    (int(time.time()) - 301, generation_id),
                )

        response = self.client.post(
            "/v1/generations",
            headers=_request_headers(request_key),
            files={"image": ("input.png", data, "image/png")},
            data={"workflow_id": "model-c-v1"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["generation_id"], generation_id)
        self.assertEqual(response.json()["status"], "unknown")
        submit_generation.assert_not_awaited()

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_reused_key_with_different_request_is_rejected(self, submit_generation):
        submit_generation.return_value = (str(uuid.uuid4()), "model-c-v1", "3")
        headers = _request_headers("conflicting-request-key")
        first = self.client.post(
            "/v1/generations",
            headers=headers,
            files={"image": ("input.png", _png("white"), "image/png")},
        )
        second = self.client.post(
            "/v1/generations",
            headers=headers,
            files={"image": ("input.png", _png("black"), "image/png")},
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(submit_generation.await_count, 1)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_pre_submit_rejection_does_not_consume_idempotency_key(
        self, submit_generation
    ):
        submit_generation.side_effect = [
            HTTPException(
                status_code=429,
                detail="Generation queue is full.",
                headers={"Retry-After": "10"},
            ),
            (str(uuid.uuid4()), "model-c-v1", "3"),
        ]
        request = {
            "headers": _request_headers("retryable-request-key"),
            "files": {"image": ("input.png", _png(), "image/png")},
        }
        first = self.client.post("/v1/generations", **request)
        second = self.client.post("/v1/generations", **request)
        self.assertEqual(first.status_code, 429)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(submit_generation.await_count, 2)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_uncertain_prompt_submission_is_not_automatically_repeated(
        self, submit_generation
    ):
        submit_generation.side_effect = _PromptSubmissionUncertain(
            HTTPException(status_code=504, detail="Upstream timeout.")
        )
        request = {
            "headers": _request_headers("uncertain-request-key"),
            "files": {"image": ("input.png", _png(), "image/png")},
        }
        first = self.client.post("/v1/generations", **request)
        self.assertEqual(first.status_code, 504)
        generation_id = first.json()["detail"]["generation_id"]

        retry = self.client.post("/v1/generations", **request)
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(retry.json()["generation_id"], generation_id)
        self.assertEqual(retry.json()["status"], "unknown")
        self.assertEqual(submit_generation.await_count, 1)

    @patch("comfyui.gateway.app._submit_generation", new_callable=AsyncMock)
    def test_completed_status_is_loaded_from_sqlite_after_refresh(
        self, submit_generation
    ):
        prompt_id = str(uuid.uuid4())
        submit_generation.return_value = (prompt_id, "model-c-v1", "3")
        created = self.client.post(
            "/v1/generations",
            headers=_request_headers("completed-request-key"),
            files={"image": ("input.png", _png(), "image/png")},
        )
        generation_id = created.json()["generation_id"]
        result_image = {
            "filename": "result.png",
            "subfolder": "ad_creator",
            "type": "output",
        }

        with patch(
            "comfyui.gateway.app._generation_state",
            new=AsyncMock(return_value=("succeeded", result_image, None)),
        ) as generation_state:
            completed = self.client.get(
                f"/v1/generations/{generation_id}", headers=AUTH_HEADERS
            )
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(completed.json()["status"], "succeeded")
            generation_state.assert_awaited_once()

        with patch(
            "comfyui.gateway.app._generation_state", new=AsyncMock()
        ) as generation_state:
            persisted = self.client.get(
                f"/v1/generations/{generation_id}", headers=AUTH_HEADERS
            )
            self.assertEqual(persisted.json()["status"], "succeeded")
            generation_state.assert_not_awaited()

    def test_generation_without_prompt_is_reported_unknown(self):
        settings = Settings.from_env()
        generation_id, _ = _reserve_test_generation(settings)
        with patch(
            "comfyui.gateway.app._generation_state", new=AsyncMock()
        ) as generation_state:
            response = self.client.get(
                f"/v1/generations/{generation_id}", headers=AUTH_HEADERS
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unknown")
        generation_state.assert_not_awaited()

    def test_expired_result_always_returns_gone(self):
        settings = Settings.from_env()
        generation_id, _ = _reserve_test_generation(settings)
        image = {
            "filename": "expired.png",
            "subfolder": "ad_creator",
            "type": "output",
        }
        _update_generation_record(
            generation_id,
            state="succeeded",
            settings=settings,
            image=image,
        )
        _update_generation_record(
            generation_id,
            state="expired",
            settings=settings,
            error="Generated image has expired.",
        )
        for _ in range(2):
            response = self.client.get(
                f"/v1/generations/{generation_id}/result", headers=AUTH_HEADERS
            )
            self.assertEqual(response.status_code, 410)


class GatewayQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_submission_when_queue_is_full(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "AD_CREATOR_GATEWAY_API_KEY": API_KEY,
                    "AD_CREATOR_GENERATION_SIGNING_KEY": SIGNING_KEY,
                    "AD_CREATOR_GATEWAY_DB": str(
                        Path(temp_dir) / "gateway.sqlite3"
                    ),
                    "AD_CREATOR_MAX_QUEUED": "1",
                },
                clear=False,
            ):
                with patch(
                    "comfyui.gateway.app._json_request",
                    new=AsyncMock(
                        return_value={
                            "queue_running": [[1, str(uuid.uuid4())]]
                        }
                    ),
                ):
                    with self.assertRaises(HTTPException) as caught:
                        await _submit_generation(
                            data=_png(),
                            content_type="image/png",
                            workflow_id="model-c-v1",
                            composition="medium",
                            background_style="white",
                            strength="medium",
                            seed=None,
                            settings=Settings.from_env(),
                            request_id=str(uuid.uuid4()),
                        )
                self.assertEqual(caught.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
