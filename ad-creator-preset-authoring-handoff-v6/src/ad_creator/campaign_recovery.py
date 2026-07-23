from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paid_readiness import (
    guard_generation_provider_boundary,
    require_paid_execution_readiness,
)
from .providers.base import GenerationProvider, ProviderJob
from .runs import request_hash
from .validation_campaign import validate_validation_campaign


JOURNAL_SCHEMA_VERSION = "1.0.0"
ZERO_SHA256 = "0" * 64
TERMINAL_CASE_STATUSES = {"completed", "failed", "cancelled", "skipped"}
ACTIVE_CASE_STATUSES = {"prepared", "submit_started", "running"}


class JournalIntegrityError(RuntimeError):
    """The checkpoint journal is incomplete, altered, or semantically invalid."""


class CampaignStateError(RuntimeError):
    """The requested transition is unsafe for the current campaign state."""


class ManualReviewRequired(CampaignStateError):
    """A paid submission may have happened and must not be retried automatically."""


class AuthorizationExpired(CampaignStateError):
    """No new case may be submitted with an expired phase authorization."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HashChainedCheckpointJournal:
    """Durable JSONL event journal whose records form a SHA-256 chain.

    The journal is the source of truth.  Mutable snapshots and destructive
    cleanup are deliberately excluded so recovery can always replay history.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise JournalIntegrityError("Checkpoint journal must not be a symlink")

    @contextmanager
    def _lock(self, *, exclusive: bool):
        self.lock_path.touch(exist_ok=True)
        with self.lock_path.open("r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        if not raw:
            return []
        if not raw.endswith(b"\n"):
            raise JournalIntegrityError("Checkpoint journal has a truncated final record")

        events: list[dict[str, Any]] = []
        expected_previous = ZERO_SHA256
        for expected_sequence, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JournalIntegrityError(
                    f"Checkpoint journal record {expected_sequence} is not valid JSON"
                ) from exc
            if not isinstance(event, dict):
                raise JournalIntegrityError(
                    f"Checkpoint journal record {expected_sequence} is not an object"
                )
            if event.get("schema_version") != JOURNAL_SCHEMA_VERSION:
                raise JournalIntegrityError("Unsupported checkpoint journal schema")
            if event.get("sequence") != expected_sequence:
                raise JournalIntegrityError("Checkpoint journal sequence is not contiguous")
            if event.get("previous_event_sha256") != expected_previous:
                raise JournalIntegrityError("Checkpoint journal hash chain is broken")
            recorded_hash = event.get("event_sha256")
            without_hash = dict(event)
            without_hash.pop("event_sha256", None)
            if not _is_sha256(recorded_hash) or recorded_hash != canonical_sha256(
                without_hash
            ):
                raise JournalIntegrityError("Checkpoint journal event hash does not match")
            if not isinstance(event.get("event_type"), str) or not isinstance(
                event.get("payload"), dict
            ):
                raise JournalIntegrityError("Checkpoint journal event has invalid fields")
            _parse_timestamp(event.get("at"), field="journal.at")
            events.append(event)
            expected_previous = recorded_hash
        return events

    def read(self) -> list[dict[str, Any]]:
        with self._lock(exclusive=False):
            return self._read_unlocked()

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        expected_head_sha256: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Journal event_type is required")
        if not isinstance(payload, Mapping):
            raise ValueError("Journal event payload must be an object")
        with self._lock(exclusive=True):
            events = self._read_unlocked()
            previous_hash = events[-1]["event_sha256"] if events else ZERO_SHA256
            if (
                expected_head_sha256 is not None
                and expected_head_sha256 != previous_hash
            ):
                raise CampaignStateError(
                    "Checkpoint journal changed concurrently; reload before continuing"
                )
            event: dict[str, Any] = {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "sequence": len(events) + 1,
                "at": _timestamp(at or _utc_now()),
                "event_type": event_type,
                "payload": copy.deepcopy(dict(payload)),
                "previous_event_sha256": previous_hash,
            }
            event["event_sha256"] = canonical_sha256(event)
            encoded = (
                json.dumps(
                    event,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("Checkpoint journal append made no progress")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event


def _provider_case_status(value: Any) -> str:
    normalized = str(value).strip().casefold()
    if normalized in {"completed", "succeeded", "success"}:
        return "completed"
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized in {"queued", "pending", "created", "running", "processing"}:
        return "running"
    raise JournalIntegrityError(f"Unknown provider job status in journal: {value!r}")


def replay_campaign(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify semantic transitions and derive the current active pointers."""

    if not events:
        return {
            "initialized": False,
            "campaign_status": "uninitialized",
            "event_count": 0,
            "head_sha256": ZERO_SHA256,
        }
    first = events[0]
    if first.get("event_type") != "campaign_initialized":
        raise JournalIntegrityError("First checkpoint event must initialize the campaign")
    initial = first.get("payload")
    if not isinstance(initial, Mapping):
        raise JournalIntegrityError("Campaign initialization payload is invalid")
    order = initial.get("case_order")
    bindings = initial.get("case_bindings")
    if (
        not isinstance(order, list)
        or not order
        or len(set(order)) != len(order)
        or not isinstance(bindings, Mapping)
        or set(order) != set(bindings)
    ):
        raise JournalIntegrityError("Campaign case order and bindings do not match")
    for case_id in order:
        binding = bindings[case_id]
        if not isinstance(case_id, str) or not case_id.strip() or not isinstance(
            binding, Mapping
        ):
            raise JournalIntegrityError("Campaign contains an invalid case binding")
        for field in (
            "request_sha256",
            "idempotency_key",
            "quote_sha256",
            "readiness_sha256",
            "authorization_sha256",
        ):
            if not _is_sha256(binding.get(field)):
                raise JournalIntegrityError(f"Case {case_id} has an invalid {field}")
        if binding["readiness_sha256"] != initial.get("readiness_sha256"):
            raise JournalIntegrityError("Case readiness binding differs from campaign")
        if binding["authorization_sha256"] != initial.get("authorization_sha256"):
            raise JournalIntegrityError("Case authorization binding differs from campaign")
        expected_idempotency_key = canonical_sha256(
            {
                "campaign_sha256": initial.get("campaign_sha256"),
                "case_id": case_id,
                "request_sha256": binding["request_sha256"],
                "readiness_sha256": binding["readiness_sha256"],
                "authorization_sha256": binding["authorization_sha256"],
                "quote_sha256": binding["quote_sha256"],
            }
        )
        if binding["idempotency_key"] != expected_idempotency_key:
            raise JournalIntegrityError("Case idempotency key does not match its bindings")
    for field in (
        "campaign_sha256",
        "readiness_sha256",
        "authorization_sha256",
        "request_set_sha256",
    ):
        if not _is_sha256(initial.get(field)):
            raise JournalIntegrityError(f"Campaign initialization has an invalid {field}")
    if not isinstance(initial.get("campaign_id"), str) or not initial["campaign_id"].strip():
        raise JournalIntegrityError("Campaign initialization requires campaign_id")
    if initial.get("phase") not in {"initial", "expansion"}:
        raise JournalIntegrityError("Campaign initialization has an invalid phase")
    if not isinstance(initial.get("provider"), str) or not initial["provider"].strip():
        raise JournalIntegrityError("Campaign initialization requires provider")

    state: dict[str, Any] = {
        "initialized": True,
        "campaign_id": initial.get("campaign_id"),
        "campaign_sha256": initial.get("campaign_sha256"),
        "phase": initial.get("phase"),
        "provider": initial.get("provider"),
        "readiness_sha256": initial.get("readiness_sha256"),
        "authorization_sha256": initial.get("authorization_sha256"),
        "campaign_status": "running",
        "cancel_requested": False,
        "active_case_id": None,
        "in_flight_case_id": None,
        "manual_review_case_id": None,
        "case_order": list(order),
        "cases": {
            case_id: {
                "status": "pending",
                "job_id": None,
                "provider_status": None,
                "actual_credits": None,
                "binding": copy.deepcopy(dict(bindings[case_id])),
            }
            for case_id in order
        },
        "artifact_versions": {},
        "active_artifacts": {},
        "artifact_tombstones": [],
    }

    for event in events[1:]:
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise JournalIntegrityError("Checkpoint event payload is invalid")
        if state["campaign_status"] in {"completed", "cancelled"} and event_type not in {
            "artifact_recorded",
            "artifact_rolled_back",
        }:
            raise JournalIntegrityError("Campaign changed after reaching a terminal state")

        if event_type == "campaign_initialized":
            raise JournalIntegrityError("Campaign may only be initialized once")
        if event_type == "case_prepared":
            case_id = payload.get("case_id")
            if state["active_case_id"] is not None:
                raise JournalIntegrityError("More than one campaign case became active")
            if case_id not in state["cases"] or state["cases"][case_id]["status"] != "pending":
                raise JournalIntegrityError("Prepared case is missing or not pending")
            if payload.get("binding") != state["cases"][case_id]["binding"]:
                raise JournalIntegrityError("Prepared case binding changed")
            state["cases"][case_id]["status"] = "prepared"
            state["active_case_id"] = case_id
        elif event_type == "case_submit_started":
            case_id = payload.get("case_id")
            binding = state["cases"].get(case_id, {}).get("binding", {})
            if (
                case_id != state["active_case_id"]
                or state["cases"].get(case_id, {}).get("status") != "prepared"
                or state["cancel_requested"]
                or payload.get("idempotency_key")
                != binding.get("idempotency_key")
                or payload.get("readiness_sha256") != binding.get("readiness_sha256")
                or payload.get("authorization_sha256")
                != binding.get("authorization_sha256")
                or payload.get("quote_sha256") != binding.get("quote_sha256")
            ):
                raise JournalIntegrityError("Unsafe or mismatched submit-start transition")
            if state["in_flight_case_id"] is not None:
                raise JournalIntegrityError("More than one case is in flight")
            state["cases"][case_id]["status"] = "submit_started"
            state["in_flight_case_id"] = case_id
        elif event_type in {"case_job_recorded", "case_job_observed"}:
            case_id = payload.get("case_id")
            case = state["cases"].get(case_id)
            if case is None or case_id != state["active_case_id"]:
                raise JournalIntegrityError("Provider job belongs to a non-active case")
            if event_type == "case_job_recorded" and case["status"] != "submit_started":
                raise JournalIntegrityError("Provider job was recorded before submit-start")
            if event_type == "case_job_observed" and case["status"] != "running":
                raise JournalIntegrityError("Provider job observation has no running case")
            job_id = payload.get("job_id")
            if not isinstance(job_id, str) or not job_id.strip():
                raise JournalIntegrityError("Provider job event requires job_id")
            if case["job_id"] is not None and case["job_id"] != job_id:
                raise JournalIntegrityError("Provider job_id changed during recovery")
            status = _provider_case_status(payload.get("provider_status"))
            case["job_id"] = job_id
            case["provider_status"] = payload.get("provider_status")
            actual_credits = payload.get("actual_credits")
            if actual_credits is not None:
                if (
                    not isinstance(actual_credits, (int, float))
                    or isinstance(actual_credits, bool)
                    or not math.isfinite(float(actual_credits))
                    or float(actual_credits) < 0
                ):
                    raise JournalIntegrityError("Provider actual_credits is invalid")
                case["actual_credits"] = float(actual_credits)
            case["status"] = status
            if status in TERMINAL_CASE_STATUSES:
                state["active_case_id"] = None
                state["in_flight_case_id"] = None
        elif event_type == "case_manual_review":
            case_id = payload.get("case_id")
            case = state["cases"].get(case_id)
            if (
                case is None
                or case_id != state["active_case_id"]
                or case["status"] not in {"submit_started", "running"}
            ):
                raise JournalIntegrityError("Manual-review transition has no uncertain case")
            case["status"] = "manual_review"
            case["manual_review_reason"] = payload.get("reason")
            state["active_case_id"] = None
            state["in_flight_case_id"] = None
            state["manual_review_case_id"] = case_id
            state["campaign_status"] = "manual_review"
        elif event_type == "case_abandoned_before_submit":
            case_id = payload.get("case_id")
            case = state["cases"].get(case_id)
            if (
                not state["cancel_requested"]
                or case is None
                or case_id != state["active_case_id"]
                or case["status"] != "prepared"
            ):
                raise JournalIntegrityError("Prepared case abandonment is invalid")
            case["status"] = "skipped"
            case["abandonment_reason"] = payload.get("reason")
            state["active_case_id"] = None
        elif event_type == "manual_review_resolved":
            case_id = payload.get("case_id")
            outcome = payload.get("outcome")
            if (
                case_id != state["manual_review_case_id"]
                or state["cases"].get(case_id, {}).get("status") != "manual_review"
                or outcome not in TERMINAL_CASE_STATUSES
            ):
                raise JournalIntegrityError("Manual-review resolution is invalid")
            state["cases"][case_id]["status"] = outcome
            state["cases"][case_id]["manual_review_resolution"] = payload.get("note")
            if payload.get("job_id") is not None:
                state["cases"][case_id]["job_id"] = payload["job_id"]
            state["manual_review_case_id"] = None
            state["campaign_status"] = (
                "cancel_pending" if state["cancel_requested"] else "running"
            )
        elif event_type == "cancel_requested":
            if state["cancel_requested"]:
                raise JournalIntegrityError("Campaign cancellation was requested twice")
            state["cancel_requested"] = True
            if state["campaign_status"] != "manual_review":
                state["campaign_status"] = "cancel_pending"
        elif event_type == "campaign_cancelled":
            if not state["cancel_requested"] or state["active_case_id"] is not None:
                raise JournalIntegrityError("Campaign cancelled while a case was still active")
            state["campaign_status"] = "cancelled"
        elif event_type == "campaign_completed":
            if state["active_case_id"] is not None or any(
                case["status"] not in TERMINAL_CASE_STATUSES
                for case in state["cases"].values()
            ):
                raise JournalIntegrityError("Campaign completed before every case was terminal")
            state["campaign_status"] = "completed"
        elif event_type == "artifact_recorded":
            case_id = payload.get("case_id")
            name = payload.get("artifact_name")
            version_id = payload.get("version_id")
            if case_id not in state["cases"] or not isinstance(name, str) or not name:
                raise JournalIntegrityError("Artifact event has an invalid case or name")
            if not _is_sha256(version_id) or not _is_sha256(payload.get("file_sha256")):
                raise JournalIntegrityError("Artifact event has an invalid content identity")
            if not isinstance(payload.get("path"), str) or not payload["path"]:
                raise JournalIntegrityError("Artifact event requires a path")
            key = f"{case_id}:{name}"
            versions = state["artifact_versions"].setdefault(key, [])
            if payload.get("previous_version_id") != state["active_artifacts"].get(key):
                raise JournalIntegrityError("Artifact previous-version pointer changed")
            if any(item["version_id"] == version_id for item in versions):
                raise JournalIntegrityError("Artifact version_id was reused")
            versions.append({**copy.deepcopy(dict(payload)), "tombstoned": False})
            state["active_artifacts"][key] = version_id
        elif event_type == "artifact_rolled_back":
            key = payload.get("artifact_key")
            from_version = payload.get("from_version_id")
            to_version = payload.get("active_pointer_to")
            versions = state["artifact_versions"].get(key)
            if not isinstance(versions, list) or state["active_artifacts"].get(key) != from_version:
                raise JournalIntegrityError("Artifact rollback does not match the active pointer")
            source = next(
                (item for item in versions if item["version_id"] == from_version),
                None,
            )
            target = next(
                (item for item in versions if item["version_id"] == to_version),
                None,
            ) if to_version is not None else None
            if source is None or source["tombstoned"]:
                raise JournalIntegrityError("Artifact rollback source is invalid")
            if to_version == from_version:
                raise JournalIntegrityError("Artifact cannot roll back to its active version")
            if to_version is not None and (target is None or target["tombstoned"]):
                raise JournalIntegrityError("Artifact rollback target is invalid")
            if target is not None:
                target_path = Path(target["path"])
                if not target_path.is_file():
                    raise JournalIntegrityError(
                        "Artifact rollback target file is missing"
                    )
                if _sha256_file(target_path) != target["file_sha256"]:
                    raise JournalIntegrityError(
                        "Artifact rollback target file hash does not match"
                    )
            source["tombstoned"] = True
            state["artifact_tombstones"].append(from_version)
            if to_version is None:
                state["active_artifacts"].pop(key, None)
            else:
                state["active_artifacts"][key] = to_version
        else:
            raise JournalIntegrityError(f"Unknown checkpoint event type: {event_type!r}")

    for key, active_version in state["active_artifacts"].items():
        active_record = next(
            (
                item
                for item in state["artifact_versions"].get(key, [])
                if item["version_id"] == active_version
            ),
            None,
        )
        if active_record is None or active_record["tombstoned"]:
            raise JournalIntegrityError("Active artifact pointer is missing or tombstoned")

    state["event_count"] = len(events)
    state["head_sha256"] = events[-1]["event_sha256"]
    state["pending_case_ids"] = [
        case_id
        for case_id in state["case_order"]
        if state["cases"][case_id]["status"] == "pending"
    ]
    state["terminal_case_count"] = sum(
        case["status"] in TERMINAL_CASE_STATUSES for case in state["cases"].values()
    )
    return state


def _job_payload(case_id: str, job: ProviderJob) -> dict[str, Any]:
    if not isinstance(job, ProviderJob):
        raise TypeError("Generation provider must return ProviderJob")
    payload: dict[str, Any] = {
        "case_id": case_id,
        "job_id": job.job_id,
        "provider_status": job.status,
        "actual_credits": job.actual_credits,
    }
    if job.output_path is not None:
        payload["output_path"] = str(job.output_path.resolve())
    return payload


class SequentialCampaignExecutor:
    """Crash-safe, strictly sequential validation-campaign executor.

    The executor records ``case_submit_started`` durably before the provider
    call.  If the process dies in the following uncertainty window, recovery
    only reconciles by idempotency key; it never calls ``submit`` again.
    """

    def __init__(
        self,
        *,
        journal: HashChainedCheckpointJournal,
        plan: Mapping[str, Any],
        phase: str,
        paid_readiness: Mapping[str, Any],
        authorization: Mapping[str, Any],
        requests: Mapping[str, dict[str, Any]],
        provider: GenerationProvider,
        campaign_id: str | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        validate_validation_campaign(plan)
        readiness = require_paid_execution_readiness(paid_readiness)
        if phase not in {"initial", "expansion"}:
            raise ValueError("Campaign phase must be initial or expansion")
        expected_authorization_hash = authorization.get("authorization_sha256")
        authorization_without_hash = dict(authorization)
        authorization_without_hash.pop("authorization_sha256", None)
        if (
            not _is_sha256(expected_authorization_hash)
            or expected_authorization_hash
            != canonical_sha256(authorization_without_hash)
        ):
            raise ValueError("Campaign authorization hash does not match its contents")
        if authorization.get("authorized") is not True or authorization.get("phase") != phase:
            raise ValueError("Campaign phase is not authorized")
        if authorization.get("campaign_sha256") != plan.get("campaign_sha256"):
            raise ValueError("Campaign authorization is bound to another campaign")
        if authorization.get("readiness_sha256") != readiness["readiness_sha256"]:
            raise ValueError("Campaign authorization is bound to another readiness proof")
        if authorization.get("request_set_sha256") != readiness["request_set_sha256"]:
            raise ValueError("Campaign authorization request set does not match readiness")
        for field in (
            "contract_gate_sha256",
            "catalog_contract_sha256",
            "evaluator_contract_sha256",
        ):
            if authorization.get(field) != readiness[field]:
                raise ValueError(f"Campaign authorization {field} does not match readiness")
        if authorization.get("automatic_paid_repair") is not False:
            raise ValueError("Campaign authorization must disable automatic paid repair")
        if authorization.get("provider") != getattr(provider, "name", None):
            raise ValueError("Campaign authorization is bound to another provider")

        phase_cases = [case for case in plan["cases"] if case["phase"] == phase]
        case_order = [case["case_id"] for case in phase_cases]
        if set(requests) != set(case_order):
            raise ValueError("Executor requires exactly one request for every phase case")
        quote_hashes = authorization.get("quote_hashes")
        if not isinstance(quote_hashes, Mapping) or set(quote_hashes) != set(case_order):
            raise ValueError("Authorization requires one quote hash for every phase case")
        if authorization.get("case_count") != len(case_order):
            raise ValueError("Authorization case count does not match the phase")
        if authorization.get("quote_set_sha256") != canonical_sha256(
            dict(sorted(quote_hashes.items()))
        ):
            raise ValueError("Authorization quote-set hash does not match its quote hashes")
        _parse_timestamp(
            authorization.get("quote_expires_at"),
            field="authorization.quote_expires_at",
        )

        bindings: dict[str, dict[str, str]] = {}
        for case_id in case_order:
            digest = request_hash(requests[case_id])
            if readiness["request_hashes"].get(case_id) != digest:
                raise ValueError(f"Request hash binding changed for case {case_id}")
            quote_sha256 = quote_hashes[case_id]
            if not _is_sha256(quote_sha256):
                raise ValueError(f"Authorization quote hash is invalid for case {case_id}")
            idempotency_key = canonical_sha256(
                {
                    "campaign_sha256": plan["campaign_sha256"],
                    "case_id": case_id,
                    "request_sha256": digest,
                    "readiness_sha256": readiness["readiness_sha256"],
                    "authorization_sha256": expected_authorization_hash,
                    "quote_sha256": quote_sha256,
                }
            )
            bindings[case_id] = {
                "request_sha256": digest,
                "idempotency_key": idempotency_key,
                "quote_sha256": quote_sha256,
                "readiness_sha256": readiness["readiness_sha256"],
                "authorization_sha256": expected_authorization_hash,
            }

        self.journal = journal
        self.plan = copy.deepcopy(dict(plan))
        self.phase = phase
        self.readiness = copy.deepcopy(dict(readiness))
        self.authorization = copy.deepcopy(dict(authorization))
        self.requests = copy.deepcopy(dict(requests))
        self.provider = provider
        self.clock = clock
        initialization = {
            "campaign_id": campaign_id or f"{phase}-{plan['campaign_sha256'][:16]}",
            "campaign_sha256": plan["campaign_sha256"],
            "phase": phase,
            "provider": provider.name,
            "readiness_sha256": readiness["readiness_sha256"],
            "authorization_sha256": expected_authorization_hash,
            "request_set_sha256": readiness["request_set_sha256"],
            "case_order": case_order,
            "case_bindings": bindings,
        }
        events = journal.read()
        if not events:
            journal.append(
                "campaign_initialized",
                initialization,
                expected_head_sha256=ZERO_SHA256,
            )
        elif events[0].get("payload") != initialization:
            raise JournalIntegrityError(
                "Existing checkpoint journal is bound to different campaign inputs"
            )
        self.state()

    def state(self) -> dict[str, Any]:
        return replay_campaign(self.journal.read())

    def _append(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        events = self.journal.read()
        state = replay_campaign(events)
        prospective_event = {
            "event_type": event_type,
            "payload": copy.deepcopy(dict(payload)),
            "event_sha256": ZERO_SHA256,
        }
        try:
            replay_campaign([*events, prospective_event])
        except JournalIntegrityError as exc:
            raise CampaignStateError(
                f"Unsafe campaign transition {event_type!r}: {exc}"
            ) from exc
        self.journal.append(
            event_type,
            payload,
            expected_head_sha256=state["head_sha256"],
        )
        return self.state()

    def _require_fresh_authorization(self) -> None:
        expires_at = _parse_timestamp(
            self.authorization.get("quote_expires_at"),
            field="authorization.quote_expires_at",
        )
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("Executor clock must return a timezone-aware datetime")
        if now.astimezone(timezone.utc) >= expires_at:
            raise AuthorizationExpired(
                "Phase quote authorization expired before the next submit; obtain fresh quotes"
            )

    def request_cancel(self, *, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Cancellation requires a reason")
        state = self.state()
        if state["campaign_status"] in {"completed", "cancelled"}:
            return state
        if state["cancel_requested"]:
            return state
        return self._append("cancel_requested", {"reason": reason.strip()})

    def _record_job(self, case_id: str, job: ProviderJob, *, observed: bool) -> dict[str, Any]:
        return self._append(
            "case_job_observed" if observed else "case_job_recorded",
            _job_payload(case_id, job),
        )

    def _record_submit_started(self, case_id: str) -> dict[str, Any]:
        state = self.state()
        case = state["cases"].get(case_id)
        if (
            state["cancel_requested"]
            or case is None
            or case_id != state["active_case_id"]
            or case["status"] != "prepared"
        ):
            raise CampaignStateError(
                "Submit boundary is no longer safe; reload campaign state"
            )
        binding = case["binding"]
        self.journal.append(
            "case_submit_started",
            {
                "case_id": case_id,
                "idempotency_key": binding["idempotency_key"],
                "readiness_sha256": binding["readiness_sha256"],
                "authorization_sha256": binding["authorization_sha256"],
                "quote_sha256": binding["quote_sha256"],
            },
            expected_head_sha256=state["head_sha256"],
        )
        return self.state()

    def _manual_review(self, case_id: str, reason: str) -> dict[str, Any]:
        return self._append(
            "case_manual_review",
            {
                "case_id": case_id,
                "reason": reason,
                "automatic_resubmit_blocked": True,
            },
        )

    def recover(self) -> dict[str, Any]:
        """Recover an active case without ever issuing a new submit call."""

        state = self.state()
        case_id = state.get("active_case_id")
        if case_id is None:
            return state
        case = state["cases"][case_id]
        if case["status"] == "prepared":
            return state
        if case["status"] == "submit_started":
            reconcile = getattr(self.provider, "find_by_idempotency_key", None)
            job = (
                reconcile(case["binding"]["idempotency_key"])
                if callable(reconcile)
                else None
            )
            if job is None:
                return self._manual_review(
                    case_id,
                    "unknown_paid_submit_outcome: provider job could not be reconciled",
                )
            return self._record_job(case_id, job, observed=False)
        if case["status"] == "running":
            try:
                job = self.provider.get(case["job_id"])
            except Exception as exc:
                return self._manual_review(
                    case_id,
                    f"provider_status_unknown:{type(exc).__name__}",
                )
            return self._record_job(case_id, job, observed=True)
        raise JournalIntegrityError("Active case has an invalid recovery state")

    def advance(self) -> dict[str, Any]:
        """Advance at most one case, enforcing a submit boundary between cases."""

        state = self.state()
        if state["campaign_status"] in {"completed", "cancelled"}:
            return state
        if state["campaign_status"] == "manual_review":
            raise ManualReviewRequired(
                f"Case {state['manual_review_case_id']} requires manual reconciliation"
            )
        active_case_id = state.get("active_case_id")
        if active_case_id is not None:
            active = state["cases"][active_case_id]
            if active["status"] in {"submit_started", "running"}:
                return self.recover()
            if active["status"] != "prepared":
                raise JournalIntegrityError("Campaign active-case pointer is invalid")
            case_id = active_case_id
        else:
            if state["cancel_requested"]:
                return self._append(
                    "campaign_cancelled",
                    {"reason": "cancelled_before_next_submit"},
                )
            pending = state["pending_case_ids"]
            if not pending:
                return self._append("campaign_completed", {})
            self._require_fresh_authorization()
            case_id = pending[0]
            state = self._append(
                "case_prepared",
                {
                    "case_id": case_id,
                    "binding": state["cases"][case_id]["binding"],
                },
            )

        if state["cancel_requested"]:
            # A concurrent cancel can arrive after preparation but before the
            # durable submit marker.  Prepared means no remote side effect.
            state = self._append(
                "case_abandoned_before_submit",
                {
                    "case_id": case_id,
                    "reason": "cancelled_before_submit",
                },
            )
            return self._append(
                "campaign_cancelled",
                {"reason": "cancelled_before_next_submit"},
            )
        self._require_fresh_authorization()
        request = self.requests[case_id]
        guard_generation_provider_boundary(request, provider=self.provider)
        binding = state["cases"][case_id]["binding"]
        self._record_submit_started(case_id)
        try:
            job = self.provider.submit(
                request,
                idempotency_key=binding["idempotency_key"],
            )
        except Exception as exc:
            return self._manual_review(
                case_id,
                f"unknown_paid_submit_outcome:{type(exc).__name__}",
            )
        return self._record_job(case_id, job, observed=False)

    def run_until_blocked(self, *, maximum_cases: int | None = None) -> dict[str, Any]:
        if maximum_cases is not None and (
            not isinstance(maximum_cases, int)
            or isinstance(maximum_cases, bool)
            or maximum_cases < 1
        ):
            raise ValueError("maximum_cases must be a positive integer")
        started_terminal = self.state().get("terminal_case_count", 0)
        while True:
            state = self.advance()
            if state["campaign_status"] in {"completed", "cancelled", "manual_review"}:
                return state
            if state.get("active_case_id") is not None:
                # Queued/running jobs are polled by a later invocation.  This
                # prevents a local tight loop from hiding the cancel boundary.
                return state
            if (
                maximum_cases is not None
                and state["terminal_case_count"] - started_terminal >= maximum_cases
            ):
                return state

    def resolve_manual_review(
        self,
        *,
        case_id: str,
        outcome: str,
        note: str,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        state = self.state()
        if state.get("manual_review_case_id") != case_id:
            raise CampaignStateError("The selected case is not awaiting manual review")
        if outcome not in TERMINAL_CASE_STATUSES:
            raise ValueError("Manual outcome must be completed, failed, cancelled, or skipped")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("Manual review resolution requires an audit note")
        return self._append(
            "manual_review_resolved",
            {
                "case_id": case_id,
                "outcome": outcome,
                "note": note.strip(),
                "job_id": job_id,
            },
        )

    def record_artifact(
        self,
        *,
        case_id: str,
        artifact_name: str,
        path: str | Path,
    ) -> dict[str, Any]:
        state = self.state()
        if case_id not in state["cases"]:
            raise ValueError("Artifact case_id is not part of this campaign")
        if not isinstance(artifact_name, str) or not artifact_name.strip():
            raise ValueError("Artifact name is required")
        artifact_path = Path(path).resolve()
        if not artifact_path.is_file():
            raise FileNotFoundError(f"Artifact does not exist: {artifact_path}")
        digest = _sha256_file(artifact_path)
        key = f"{case_id}:{artifact_name.strip()}"
        previous = state["active_artifacts"].get(key)
        version_id = canonical_sha256(
            {
                "artifact_key": key,
                "path": str(artifact_path),
                "file_sha256": digest,
                "previous_version_id": previous,
                "journal_head_sha256": state["head_sha256"],
            }
        )
        return self._append(
            "artifact_recorded",
            {
                "case_id": case_id,
                "artifact_name": artifact_name.strip(),
                "path": str(artifact_path),
                "file_sha256": digest,
                "version_id": version_id,
                "previous_version_id": previous,
            },
        )

    def rollback_artifact(
        self,
        *,
        case_id: str,
        artifact_name: str,
        reason: str,
        to_version_id: str | None = None,
    ) -> dict[str, Any]:
        state = self.state()
        if not isinstance(artifact_name, str) or not artifact_name.strip():
            raise ValueError("Artifact name is required")
        key = f"{case_id}:{artifact_name.strip()}"
        active = state["active_artifacts"].get(key)
        versions = state["artifact_versions"].get(key, [])
        if active is None:
            raise CampaignStateError("Artifact has no active version to roll back")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Artifact rollback requires a reason")
        if to_version_id is None:
            candidates = [
                item["version_id"]
                for item in versions
                if item["version_id"] != active and not item["tombstoned"]
            ]
            target = candidates[-1] if candidates else None
        else:
            target = to_version_id
            if target == active:
                raise CampaignStateError(
                    "Artifact rollback target must differ from the active version"
                )
            if not any(
                item["version_id"] == target and not item["tombstoned"]
                for item in versions
            ):
                raise CampaignStateError("Requested rollback target is unavailable")
        if target is not None:
            target_record = next(
                item for item in versions if item["version_id"] == target
            )
            target_path = Path(target_record["path"])
            if not target_path.is_file():
                raise CampaignStateError(
                    "Artifact rollback target file is missing"
                )
            if _sha256_file(target_path) != target_record["file_sha256"]:
                raise CampaignStateError(
                    "Artifact rollback target file hash no longer matches the journal"
                )
        return self._append(
            "artifact_rolled_back",
            {
                "artifact_key": key,
                "from_version_id": active,
                "active_pointer_to": target,
                "tombstone": True,
                "reason": reason.strip(),
                "files_deleted": False,
            },
        )
