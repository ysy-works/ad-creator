from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .generation_inputs import ordered_image_inputs
from .paid_readiness import guard_generation_provider_boundary
from .providers.base import GenerationProvider, ProviderJob


class ManualReconciliationRequired(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_request(request: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(request)
    generation = value.get("generation")
    if not isinstance(generation, dict):
        return value
    if "image_inputs" not in generation and not generation.get("image_paths"):
        # Some configuration-only hashes intentionally contain no runtime
        # image inputs. Preserve that legacy payload unchanged.
        return value
    inputs = ordered_image_inputs(generation)
    identities: list[dict[str, Any]] = []
    for image_input in inputs:
        raw_path = image_input["path"]
        path = Path(raw_path)
        if path.is_file():
            identity = {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
        else:
            identity = {"virtual_path": str(raw_path)}
        identities.append({
            **{key: item for key, item in image_input.items() if key != "path"},
            "path": identity,
        })
    if "image_inputs" in generation:
        generation["image_inputs"] = identities
    else:
        generation["image_paths"] = [item["path"] for item in identities]
    return value


def request_hash(request: dict[str, Any]) -> str:
    payload = json.dumps(
        canonical_request(request),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class RunStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, digest: str) -> Path:
        return self.root / digest

    def manifest_path(self, digest: str) -> Path:
        return self.run_dir(digest) / "manifest.json"

    def load(self, digest: str) -> dict[str, Any] | None:
        path = self.manifest_path(digest)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, manifest: dict[str, Any]) -> dict[str, Any]:
        digest = manifest["request_hash"]
        target = self.manifest_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest["updated_at"] = _utc_now()
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return manifest

    def prepare(self, request: dict[str, Any], provider_name: str) -> tuple[dict[str, Any], bool]:
        digest = request_hash(request)
        existing = self.load(digest)
        if existing is not None:
            return existing, False
        now = _utc_now()
        manifest = {
            "schema_version": "1.0.0",
            "run_id": digest[:20],
            "request_hash": digest,
            "status": "prepared",
            "created_at": now,
            "updated_at": now,
            "request": canonical_request(request),
            "provider": {
                "name": provider_name,
                "job_id": None,
                "status": "not_submitted",
                "submit_started": False,
                "metadata": {},
            },
            "cost": {
                "estimated_credits": request["generation"].get("estimated_credits", 0),
                "actual_credits": None,
                "ledger_recorded": False,
            },
            "artifacts": {},
            "metrics": {},
            "events": [{"at": now, "type": "prepared"}],
        }
        self.save(manifest)
        return manifest, True

    def record_cost_once(self, manifest: dict[str, Any]) -> None:
        if manifest["cost"].get("ledger_recorded"):
            return
        ledger_path = self.root / "cost-ledger.jsonl"
        entry = {
            "at": _utc_now(),
            "request_hash": manifest["request_hash"],
            "provider": manifest["provider"]["name"],
            "job_id": manifest["provider"].get("job_id"),
            "actual_credits": manifest["cost"].get("actual_credits"),
        }
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
        manifest["cost"]["ledger_recorded"] = True
        self.save(manifest)


def _apply_job(manifest: dict[str, Any], job: ProviderJob) -> None:
    manifest["provider"]["job_id"] = job.job_id
    manifest["provider"]["status"] = job.status
    manifest["provider"]["metadata"] = job.metadata or {}
    manifest["cost"]["actual_credits"] = job.actual_credits
    if job.output_path:
        manifest["artifacts"]["provider_output"] = str(job.output_path.resolve())
    if job.status == "completed":
        manifest["status"] = "provider_completed"
    elif job.status in {"failed", "cancelled"}:
        manifest["status"] = "failed"
    elif job.status in {"queued", "pending", "created"}:
        manifest["status"] = "queued"
    else:
        manifest["status"] = "running"


def execute_once(
    request: dict[str, Any],
    *,
    provider: GenerationProvider,
    store: RunStore,
) -> tuple[dict[str, Any], bool]:
    # This must run before RunStore.prepare mutates local state and before the
    # provider can estimate, inspect an account, or submit a remote job.
    guard_generation_provider_boundary(request, provider=provider)
    manifest, created = store.prepare(request, provider.name)
    provider_state = manifest["provider"]

    if manifest["status"] in {"provider_completed", "completed"}:
        return manifest, True

    if provider_state.get("job_id"):
        job = provider.get(provider_state["job_id"])
        _apply_job(manifest, job)
        manifest["events"].append({"at": _utc_now(), "type": "provider_resumed", "job_id": job.job_id})
        store.save(manifest)
        if job.status == "completed":
            store.record_cost_once(manifest)
        return manifest, True

    if provider_state.get("submit_started"):
        reconcile = getattr(provider, "find_by_idempotency_key", None)
        recovered_job = reconcile(manifest["request_hash"]) if callable(reconcile) else None
        if recovered_job is not None:
            _apply_job(manifest, recovered_job)
            manifest["events"].append(
                {
                    "at": _utc_now(),
                    "type": "provider_job_reconciled",
                    "job_id": recovered_job.job_id,
                }
            )
            store.save(manifest)
            if recovered_job.status == "completed":
                store.record_cost_once(manifest)
            return manifest, True
        raise ManualReconciliationRequired(
            "Submission started but no provider job ID was recorded. Automatic resubmission is blocked."
        )

    provider_state["submit_started"] = True
    provider_state["status"] = "submitting"
    manifest["events"].append({"at": _utc_now(), "type": "submit_started"})
    store.save(manifest)

    job = provider.submit(request, idempotency_key=manifest["request_hash"])
    _apply_job(manifest, job)
    manifest["events"].append({"at": _utc_now(), "type": "provider_job_recorded", "job_id": job.job_id})
    store.save(manifest)
    if job.status == "completed":
        store.record_cost_once(manifest)
    return manifest, not created


def execute_until_terminal(
    request: dict[str, Any],
    *,
    provider: GenerationProvider,
    store: RunStore,
    timeout_seconds: float = 1200,
    poll_interval_seconds: float = 3,
) -> tuple[dict[str, Any], bool]:
    started = time.monotonic()
    manifest, reused = execute_once(request, provider=provider, store=store)
    while manifest["status"] not in {"provider_completed", "completed", "failed"}:
        if time.monotonic() - started >= timeout_seconds:
            raise TimeoutError(f"Provider job did not finish within {timeout_seconds} seconds")
        time.sleep(poll_interval_seconds)
        manifest, resumed = execute_once(request, provider=provider, store=store)
        reused = reused or resumed
    return manifest, reused
