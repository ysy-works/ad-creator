from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable

import certifi

from ..generation_inputs import ordered_image_inputs
from ..paid_readiness import require_v3_paid_submission_allowed
from .base import ProviderJob


class HiggsfieldProviderError(RuntimeError):
    pass


JsonRunner = Callable[[list[str]], Any]
Downloader = Callable[[str, Path], None]


def _first_job(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        if not value:
            raise HiggsfieldProviderError("Higgsfield returned an empty job list")
        value = value[0]
    if isinstance(value, str) and value:
        return {"id": value, "status": "queued"}
    if not isinstance(value, dict) or not value.get("id"):
        raise HiggsfieldProviderError(f"Higgsfield returned an invalid job payload: {value!r}")
    return value


class HiggsfieldProvider:
    name = "higgsfield_cli"
    is_zero_credit = False

    def __init__(
        self,
        output_dir: str | Path,
        *,
        cli_path: str | Path,
        maximum_base_credits: float = 2,
        runner: JsonRunner | None = None,
        downloader: Downloader | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cli_path = Path(cli_path)
        if runner is None and not self.cli_path.is_file():
            raise FileNotFoundError(f"Higgsfield CLI does not exist: {self.cli_path}")
        self.maximum_base_credits = maximum_base_credits
        self._runner = runner or self._run_json
        self._downloader = downloader or self._download

    def _run_json(self, args: list[str]) -> Any:
        command_prefix = [str(self.cli_path)]
        if os.name == "nt" and self.cli_path.suffix.lower() in {".cmd", ".bat"}:
            node_executable = shutil.which("node")
            appdata = os.environ.get("APPDATA")
            cli_entrypoint = (
                Path(appdata)
                / "npm"
                / "node_modules"
                / "@higgsfield"
                / "cli"
                / "bin"
                / "higgsfield.js"
                if appdata
                else None
            )
            if node_executable and cli_entrypoint and cli_entrypoint.is_file():
                # cmd.exe truncates command lines near 8 KiB. Invoke the installed
                # Node entrypoint directly so full-fidelity image prompts survive.
                command_prefix = [node_executable, str(cli_entrypoint)]
        command = [*command_prefix, *args, "--json"]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "unknown CLI error"
            raise HiggsfieldProviderError(message)
        if not isinstance(completed.stdout, str) or not completed.stdout.strip():
            raise HiggsfieldProviderError("Higgsfield CLI returned empty output")
        try:
            return json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise HiggsfieldProviderError("Higgsfield CLI returned non-JSON output") from exc

    @staticmethod
    def _download(url: str, destination: Path) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "ad-creator/0.1"})
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        tls_context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(
            request,
            timeout=120,
            context=tls_context,
        ) as response, temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        temporary.replace(destination)

    def _record_path(self, job_id: str) -> Path:
        return self.output_dir / "jobs" / f"{job_id}.json"

    def _request_path(self, idempotency_key: str) -> Path:
        return self.output_dir / "requests" / f"{idempotency_key}.json"

    def _save_record(self, record: dict[str, Any]) -> None:
        path = self._record_path(record["job_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    def _save_request_mapping(self, idempotency_key: str, job_id: str) -> None:
        path = self._request_path(idempotency_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"job_id": job_id}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _load_record(self, job_id: str) -> dict[str, Any]:
        path = self._record_path(job_id)
        if not path.is_file():
            raise KeyError(f"Unknown Higgsfield job: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _find_record_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        request_path = self._request_path(idempotency_key)
        if request_path.is_file():
            mapping = json.loads(request_path.read_text(encoding="utf-8"))
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

    def find_by_idempotency_key(self, idempotency_key: str) -> ProviderJob | None:
        record = self._find_record_by_idempotency_key(idempotency_key)
        if record is None:
            return None
        if record["status"] == "completed" and not record.get("output_path"):
            return self.get(record["job_id"])
        return self._provider_job(record)

    def reconcile_submitted_job(
        self,
        *,
        idempotency_key: str,
        job_id: str,
        estimated_credits: float,
        credits_before: float,
    ) -> ProviderJob:
        existing = self._find_record_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing["job_id"] != job_id:
                raise HiggsfieldProviderError(
                    "Request is already mapped to a different Higgsfield job"
                )
            if existing["status"] == "completed" and not existing.get("output_path"):
                return self.get(job_id)
            return self._provider_job(existing)

        payload = _first_job(self._runner(["generate", "get", job_id]))
        if payload["id"] != job_id:
            raise HiggsfieldProviderError("Higgsfield returned a different job during reconciliation")
        record = {
            "job_id": job_id,
            "idempotency_key": idempotency_key,
            "status": payload.get("status", "queued"),
            "estimated_credits": estimated_credits,
            "credits_before": credits_before,
            "credits_after": None,
            "actual_credits": None,
            "cost_source": None,
            "result_url": payload.get("result_url"),
            "output_path": None,
        }
        self._save_record(record)
        self._save_request_mapping(idempotency_key, job_id)
        if record["status"] == "completed":
            return self._complete_record(record, payload)
        return self._provider_job(record)

    def account_credits(self) -> float:
        payload = self._runner(["account", "status"])
        credits = payload.get("credits") if isinstance(payload, dict) else None
        if not isinstance(credits, (int, float)):
            raise HiggsfieldProviderError("Higgsfield account status did not include credits")
        return float(credits)

    def estimate_cost(self, request: dict[str, Any]) -> float:
        generation = request["generation"]
        args = ["generate", "cost", generation["job_type"], "--prompt", generation["prompt"]]
        for image_input in ordered_image_inputs(generation):
            args.extend(["--image-references", image_input["path"]])
        args.extend(
            [
                "--aspect-ratio",
                generation["aspect_ratio"],
                "--resolution",
                generation["resolution"],
                "--quality",
                generation["quality"],
            ]
        )
        payload = self._runner(args)
        credits = payload.get("credits") if isinstance(payload, dict) else None
        if not isinstance(credits, (int, float)):
            raise HiggsfieldProviderError("Higgsfield cost response did not include credits")
        return float(credits)

    def _provider_job(self, record: dict[str, Any]) -> ProviderJob:
        output_path = Path(record["output_path"]) if record.get("output_path") else None
        return ProviderJob(
            job_id=record["job_id"],
            status=record["status"],
            output_path=output_path,
            actual_credits=record.get("actual_credits"),
            metadata={
                "estimated_credits": record["estimated_credits"],
                "credits_before": record.get("credits_before"),
                "credits_after": record.get("credits_after"),
                "cost_source": record.get("cost_source"),
                "result_url": record.get("result_url"),
            },
        )

    def submit(self, request: dict[str, Any], *, idempotency_key: str) -> ProviderJob:
        # Keep this adapter safe even when called without the shared RunStore.
        # The guard precedes cost lookup, account lookup, and idempotency I/O.
        require_v3_paid_submission_allowed(
            request,
            provider_name=self.name,
            idempotency_key=idempotency_key,
        )
        existing = self._find_record_by_idempotency_key(idempotency_key)
        if existing is not None:
            return self._provider_job(existing)

        generation = request["generation"]
        estimated = self.estimate_cost(request)
        if estimated > self.maximum_base_credits:
            raise HiggsfieldProviderError(
                f"Estimated cost {estimated} exceeds the {self.maximum_base_credits}-credit base limit"
            )
        if abs(estimated - float(generation["estimated_credits"])) > 1e-9:
            raise HiggsfieldProviderError(
                f"Provider estimate {estimated} does not match request estimate "
                f"{generation['estimated_credits']}"
            )
        credits_before = self.account_credits()
        args = ["generate", "create", generation["job_type"], "--prompt", generation["prompt"]]
        for image_input in ordered_image_inputs(generation):
            args.extend(["--image-references", image_input["path"]])
        args.extend(
            [
                "--aspect-ratio",
                generation["aspect_ratio"],
                "--resolution",
                generation["resolution"],
                "--quality",
                generation["quality"],
            ]
        )
        payload = _first_job(self._runner(args))
        record = {
            "job_id": payload["id"],
            "idempotency_key": idempotency_key,
            "status": payload.get("status", "queued"),
            "estimated_credits": estimated,
            "credits_before": credits_before,
            "credits_after": None,
            "actual_credits": None,
            "cost_source": None,
            "result_url": payload.get("result_url"),
            "output_path": None,
        }
        self._save_record(record)
        self._save_request_mapping(idempotency_key, payload["id"])
        if record["status"] == "completed":
            return self._complete_record(record, payload)
        return self._provider_job(record)

    def _complete_record(self, record: dict[str, Any], payload: dict[str, Any]) -> ProviderJob:
        result_url = payload.get("result_url") or record.get("result_url")
        if not result_url:
            raise HiggsfieldProviderError("Completed Higgsfield job has no result URL")
        output_path = self.output_dir / "images" / f"{record['job_id']}.png"
        if not output_path.is_file():
            self._downloader(result_url, output_path)
        credits_after = self.account_credits()
        measured = max(0.0, float(record["credits_before"]) - credits_after)
        actual = measured if measured > 0 else float(record["estimated_credits"])
        record.update(
            {
                "status": "completed",
                "result_url": result_url,
                "output_path": str(output_path.resolve()),
                "credits_after": credits_after,
                "actual_credits": actual,
                "cost_source": "account_balance_delta" if measured > 0 else "preflight_estimate",
            }
        )
        self._save_record(record)
        return self._provider_job(record)

    def get(self, job_id: str) -> ProviderJob:
        record = self._load_record(job_id)
        if record["status"] == "completed" and record.get("output_path"):
            return self._provider_job(record)
        try:
            payload = _first_job(self._runner(["generate", "get", job_id]))
        except HiggsfieldProviderError as exc:
            if str(exc) == "Higgsfield CLI returned empty output":
                return self._provider_job(record)
            raise
        record["status"] = payload.get("status", record["status"])
        record["result_url"] = payload.get("result_url") or record.get("result_url")
        self._save_record(record)
        if record["status"] == "completed":
            return self._complete_record(record, payload)
        return self._provider_job(record)
