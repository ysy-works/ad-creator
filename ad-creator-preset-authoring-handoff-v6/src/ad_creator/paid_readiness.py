from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any


PAID_READINESS_SCHEMA_VERSION = "1.0.0"
PROVIDER_QUOTE_SCHEMA_VERSION = "1.0.0"
WOOD_CATALOG_READINESS_SCHEMA_VERSION = "1.0.0"
CONTACT_SHEET_REVIEW_SCHEMA_VERSION = "1.0.0"
CONTACT_SHEET_REVIEW_ARTIFACT_TYPE = "wood_cohort_contact_sheet_review"
CONTACT_SHEET_REVIEW_STATUSES = frozenset({"approved", "pending", "rejected"})
CONTACT_SHEET_REVIEW_SHA256_DEFINITION = (
    "sha256(canonical-json-without-top-level-sha256;utf-8;ensure_ascii=true;"
    "sort_keys=true;separators=(',',':');allow_nan=false)"
)
MAXIMUM_QUOTE_TTL_SECONDS = 15 * 60
MAXIMUM_FUTURE_CLOCK_SKEW_SECONDS = 30
REQUIRED_WOOD_PROFILE_COUNT = 100
V3_GENERATION_REQUEST_SCHEMA_VERSION = "3.0.0"
V3_PROMPT_COMPILER_VERSION = "natural_compact_v5_multi"
V3_DIAGNOSTIC_AUTHORIZATION_FIELD = "diagnostic_pilot_authorization"
V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD = "diagnostic_matrix_authorization"
REQUIRED_EVALUATOR_CAPABILITIES = {
    "product_region_detector_ready",
    "brand_ocr_ready",
    "leakage_detectors_ready",
    "wood_measurement_ready",
}


class V3PaidExecutionDisabled(RuntimeError):
    """Raised before a V3 request can reach a paid provider boundary."""


def _hash(value: Mapping[str, Any]) -> str:
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


def _non_negative_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _utc_datetime(value: datetime | str | None, *, field: str) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _catalog_count(catalog: Mapping[str, Any], *names: str) -> int:
    counts = catalog.get("counts")
    if isinstance(counts, Mapping):
        for name in names:
            if name in counts:
                return _non_negative_int(
                    counts[name],
                    field=f"catalog_contract.counts.{name}",
                )
    for name in names:
        if name in catalog:
            return _non_negative_int(catalog[name], field=f"catalog_contract.{name}")
    return 0


def validate_contact_sheet_review_artifact(
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the self-hashed review artifact embedded in paid readiness.

    ``sha256`` is the SHA-256 digest of the canonical JSON object after removing
    only its top-level ``sha256`` field.  The exact canonicalization is declared
    by ``sha256_definition`` and must match the constant above.
    """

    if not isinstance(artifact, Mapping):
        raise ValueError("Wood contact-sheet review must be an object")
    if artifact.get("schema_version") != CONTACT_SHEET_REVIEW_SCHEMA_VERSION:
        raise ValueError("Wood contact-sheet review has an unsupported schema")
    if artifact.get("artifact_type") != CONTACT_SHEET_REVIEW_ARTIFACT_TYPE:
        raise ValueError("Wood contact-sheet review has the wrong artifact type")
    status = artifact.get("status")
    if status not in CONTACT_SHEET_REVIEW_STATUSES:
        raise ValueError("Wood contact-sheet review has an invalid status")
    if artifact.get("sha256_definition") != CONTACT_SHEET_REVIEW_SHA256_DEFINITION:
        raise ValueError("Wood contact-sheet review has an unknown sha256 definition")
    declared_hash = artifact.get("sha256")
    if not _is_sha256(declared_hash):
        raise ValueError("Wood contact-sheet review requires sha256")
    stable = deepcopy(dict(artifact))
    stable.pop("sha256", None)
    if declared_hash != _hash(stable):
        raise ValueError("Wood contact-sheet review sha256 does not match its contents")

    publication_authorized = artifact.get("publication_authorized")
    if not isinstance(publication_authorized, bool):
        raise ValueError("Wood contact-sheet review requires publication_authorized")
    if publication_authorized is not (status == "approved"):
        raise ValueError(
            "Wood contact-sheet publication authorization does not match review status"
        )
    cohort = artifact.get("cohort")
    if not isinstance(cohort, Mapping):
        raise ValueError("Wood contact-sheet review requires cohort evidence")
    cohort_count = _non_negative_int(
        cohort.get("canonical_reference_count"),
        field="contact_sheet_review.cohort.canonical_reference_count",
    )
    if cohort_count == 0:
        raise ValueError("Wood contact-sheet cohort cannot be empty")
    sheets = artifact.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        raise ValueError("Wood contact-sheet review requires sheet evidence")
    expected_offset = 0
    seen_paths: set[str] = set()
    for index, sheet in enumerate(sheets):
        if not isinstance(sheet, Mapping):
            raise ValueError(f"Wood contact sheet {index} must be an object")
        path = sheet.get("path")
        if not isinstance(path, str) or not path.strip() or path in seen_paths:
            raise ValueError(f"Wood contact sheet {index} has an invalid or duplicate path")
        seen_paths.add(path)
        offset = _non_negative_int(
            sheet.get("offset"), field=f"contact_sheet_review.sheets[{index}].offset"
        )
        count = _non_negative_int(
            sheet.get("count"), field=f"contact_sheet_review.sheets[{index}].count"
        )
        if count == 0 or offset != expected_offset:
            raise ValueError("Wood contact-sheet offsets/counts are not contiguous")
        if not _is_sha256(sheet.get("sha256")):
            raise ValueError(f"Wood contact sheet {index} requires sha256")
        expected_offset += count
    if expected_offset != cohort_count:
        raise ValueError("Wood contact-sheet counts do not match the cohort")
    if not isinstance(artifact.get("review"), Mapping):
        raise ValueError("Wood contact-sheet review requires review details")
    return dict(artifact)


def build_contact_sheet_review_artifact(
    *,
    status: str,
    cohort: Mapping[str, Any],
    sheets: Sequence[Mapping[str, Any]],
    review: Mapping[str, Any],
    publication_authorized: bool | None = None,
) -> dict[str, Any]:
    """Build a deterministic contact-sheet review that paid readiness can embed."""

    if status not in CONTACT_SHEET_REVIEW_STATUSES:
        raise ValueError("Wood contact-sheet review has an invalid status")
    authorized = (
        status == "approved"
        if publication_authorized is None
        else publication_authorized
    )
    artifact: dict[str, Any] = {
        "schema_version": CONTACT_SHEET_REVIEW_SCHEMA_VERSION,
        "artifact_type": CONTACT_SHEET_REVIEW_ARTIFACT_TYPE,
        "status": status,
        "sha256_definition": CONTACT_SHEET_REVIEW_SHA256_DEFINITION,
        "cohort": deepcopy(dict(cohort)),
        "sheets": [deepcopy(dict(sheet)) for sheet in sheets],
        "review": deepcopy(dict(review)),
        "publication_authorized": authorized,
    }
    artifact["sha256"] = _hash(artifact)
    return validate_contact_sheet_review_artifact(artifact)


def build_wood_catalog_readiness_contract(
    *,
    analyzer_version: str,
    input_catalog_sha256: str,
    mask_model: Mapping[str, Any],
    published_profiles: Sequence[Mapping[str, Any]],
    contact_sheet_review: Mapping[str, Any],
    expected_profile_count: int = REQUIRED_WOOD_PROFILE_COUNT,
    draft_profile_count: int = 0,
    pending_profile_count: int = 0,
    profile_schema_version: str = "3.0.0",
) -> dict[str, Any]:
    """Create the exact catalog evidence consumed by paid readiness."""

    if not isinstance(analyzer_version, str) or not analyzer_version.strip():
        raise ValueError("Wood catalog readiness requires analyzer_version")
    if not _is_sha256(input_catalog_sha256):
        raise ValueError("Wood catalog readiness requires input_catalog_sha256")
    if profile_schema_version != "3.0.0":
        raise ValueError("Wood catalog readiness requires profile schema 3.0.0")
    expected = _non_negative_int(
        expected_profile_count,
        field="expected_profile_count",
    )
    draft = _non_negative_int(draft_profile_count, field="draft_profile_count")
    pending = _non_negative_int(pending_profile_count, field="pending_profile_count")
    if not isinstance(mask_model, Mapping):
        raise ValueError("Wood catalog readiness requires mask_model evidence")
    for field in ("name", "version"):
        if not isinstance(mask_model.get(field), str) or not mask_model[field].strip():
            raise ValueError(f"Wood catalog mask_model requires {field}")
    if not _is_sha256(mask_model.get("sha256")):
        raise ValueError("Wood catalog mask_model requires sha256")
    if not isinstance(contact_sheet_review, Mapping):
        raise ValueError("Wood catalog readiness requires contact_sheet_review")
    validated_contact_sheet_review = validate_contact_sheet_review_artifact(
        contact_sheet_review
    )

    profile_evidence: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_profile in enumerate(published_profiles):
        if not isinstance(raw_profile, Mapping):
            raise ValueError(f"Published wood profile {index} must be an object")
        profile_id = raw_profile.get("reference_id", raw_profile.get("asset_id"))
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError(f"Published wood profile {index} requires reference_id")
        if profile_id in seen_ids:
            raise ValueError(f"Duplicate published wood profile: {profile_id}")
        seen_ids.add(profile_id)
        if raw_profile.get("status") != "published":
            raise ValueError(f"Wood profile {profile_id} is not published")
        if raw_profile.get("schema_version") != profile_schema_version:
            raise ValueError(f"Wood profile {profile_id} has the wrong schema version")
        source_hash = raw_profile.get("source_pixel_sha256")
        if not _is_sha256(source_hash):
            raise ValueError(f"Wood profile {profile_id} has no source pixel hash")
        measurement = raw_profile.get("measurement_evidence")
        if not isinstance(measurement, Mapping) or not _is_sha256(
            measurement.get("measurement_sha256")
        ):
            raise ValueError(f"Wood profile {profile_id} has no measurement evidence hash")
        profile_hash = raw_profile.get("profile_sha256")
        if not _is_sha256(profile_hash):
            raise ValueError(f"Wood profile {profile_id} has no valid profile hash")
        profile_evidence.append(
            {
                "reference_id": profile_id,
                "schema_version": profile_schema_version,
                "status": "published",
                "source_pixel_sha256": source_hash,
                "measurement_sha256": measurement["measurement_sha256"],
                "profile_sha256": profile_hash,
            }
        )

    published = len(profile_evidence)
    if published + draft + pending != expected:
        raise ValueError(
            "Wood catalog expected count must equal published + draft + pending"
        )
    is_published = (
        expected > 0
        and published == expected
        and draft == 0
        and pending == 0
        and validated_contact_sheet_review.get("status") == "approved"
    )
    catalog: dict[str, Any] = {
        "schema_version": WOOD_CATALOG_READINESS_SCHEMA_VERSION,
        "status": "published" if is_published else "draft",
        "analyzer_version": analyzer_version,
        "input_catalog_sha256": input_catalog_sha256,
        "mask_model": deepcopy(dict(mask_model)),
        "profile_schema_version": profile_schema_version,
        "counts": {
            "expected_profile_count": expected,
            "published_profile_count": published,
            "draft_profile_count": draft,
            "pending_profile_count": pending,
        },
        "contact_sheet_review": deepcopy(validated_contact_sheet_review),
        "published_profiles": profile_evidence,
    }
    catalog["catalog_sha256"] = _hash(catalog)
    validate_wood_catalog_readiness_contract(catalog)
    return catalog


def validate_wood_catalog_readiness_contract(
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    if catalog.get("schema_version") != WOOD_CATALOG_READINESS_SCHEMA_VERSION:
        raise ValueError("Unsupported wood-catalog readiness schema version")
    contact_sheet_review = catalog.get("contact_sheet_review")
    if not isinstance(contact_sheet_review, Mapping):
        raise ValueError("Wood-catalog readiness requires contact-sheet review evidence")
    validate_contact_sheet_review_artifact(contact_sheet_review)
    expected_hash = catalog.get("catalog_sha256")
    without_hash = dict(catalog)
    without_hash.pop("catalog_sha256", None)
    if expected_hash != _hash(without_hash):
        raise ValueError("Wood-catalog readiness hash does not match its contents")
    counts = catalog.get("counts")
    if not isinstance(counts, Mapping):
        raise ValueError("Wood-catalog readiness requires counts")
    if not isinstance(catalog.get("analyzer_version"), str) or not catalog[
        "analyzer_version"
    ].strip():
        raise ValueError("Wood-catalog readiness requires analyzer_version")
    if not _is_sha256(catalog.get("input_catalog_sha256")):
        raise ValueError("Wood-catalog readiness requires input_catalog_sha256")
    if catalog.get("profile_schema_version") != "3.0.0":
        raise ValueError("Wood-catalog readiness requires profile schema 3.0.0")
    mask_model = catalog.get("mask_model")
    if not isinstance(mask_model, Mapping):
        raise ValueError("Wood-catalog readiness requires mask_model evidence")
    if any(
        not isinstance(mask_model.get(field), str) or not mask_model[field].strip()
        for field in ("name", "version")
    ) or not _is_sha256(mask_model.get("sha256")):
        raise ValueError("Wood-catalog readiness mask_model evidence is incomplete")
    contact_sheet = catalog.get("contact_sheet_review")
    if (
        not isinstance(contact_sheet, Mapping)
        or contact_sheet.get("status") not in {"approved", "pending", "rejected"}
        or not _is_sha256(contact_sheet.get("sha256"))
    ):
        raise ValueError("Wood-catalog contact-sheet evidence is incomplete")
    expected = _catalog_count(catalog, "expected_profile_count")
    published = _catalog_count(catalog, "published_profile_count")
    draft = _catalog_count(catalog, "draft_profile_count")
    pending = _catalog_count(catalog, "pending_profile_count")
    profiles = catalog.get("published_profiles")
    if not isinstance(profiles, list) or len(profiles) != published:
        raise ValueError("Wood-catalog published count does not match its evidence")
    if published + draft + pending != expected:
        raise ValueError(
            "Wood-catalog counts must sum to the expected profile count"
        )
    if len({item.get("reference_id") for item in profiles if isinstance(item, Mapping)}) != len(
        profiles
    ):
        raise ValueError("Wood-catalog profile evidence IDs must be unique")
    for item in profiles:
        if not isinstance(item, Mapping):
            raise ValueError("Wood-catalog profile evidence must be an object")
        if item.get("schema_version") != catalog.get("profile_schema_version"):
            raise ValueError("Wood-catalog profile evidence has the wrong schema")
        if item.get("status") != "published":
            raise ValueError("Wood-catalog profile evidence is not published")
        if not isinstance(item.get("reference_id"), str) or not item[
            "reference_id"
        ].strip():
            raise ValueError("Wood-catalog profile evidence requires reference_id")
        for field in ("source_pixel_sha256", "measurement_sha256", "profile_sha256"):
            if not _is_sha256(item.get(field)):
                raise ValueError(f"Wood-catalog profile evidence requires {field}")
    should_be_published = (
        expected > 0
        and published == expected
        and draft == 0
        and pending == 0
        and contact_sheet.get("status") == "approved"
    )
    if (catalog.get("status") == "published") is not should_be_published:
        raise ValueError("Wood-catalog status does not match its evidence counts")
    return dict(catalog)


def validate_evaluator_readiness_contract(
    evaluator: Mapping[str, Any],
) -> dict[str, Any]:
    expected_hash = evaluator.get("contract_sha256")
    without_hash = dict(evaluator)
    without_hash.pop("contract_sha256", None)
    if expected_hash != _hash(without_hash):
        raise ValueError("Evaluator readiness hash does not match its contents")
    version = evaluator.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Evaluator readiness requires a version")
    capabilities = evaluator.get("capabilities")
    if not isinstance(capabilities, Mapping) or not capabilities:
        raise ValueError("Evaluator readiness requires capabilities")
    if set(capabilities) != REQUIRED_EVALUATOR_CAPABILITIES:
        raise ValueError("Evaluator readiness capabilities are incomplete or unsupported")
    if any(not isinstance(value, bool) for value in capabilities.values()):
        raise ValueError("Evaluator readiness capabilities must be booleans")
    complete = all(capabilities.values())
    if evaluator.get("required_measurements_complete") is not complete:
        raise ValueError("Evaluator readiness does not match its capabilities")
    regression_status = evaluator.get("regression_status")
    if not isinstance(regression_status, str) or not regression_status:
        raise ValueError("Evaluator readiness requires regression_status")
    should_be_ready = complete and regression_status == "pass"
    if (evaluator.get("status") == "ready") is not should_be_ready:
        raise ValueError("Evaluator readiness status does not match its evidence")
    return dict(evaluator)


def _derive_paid_execution_readiness(
    *,
    contract_gate: Mapping[str, Any],
    catalog_contract: Mapping[str, Any],
    evaluator_contract: Mapping[str, Any],
    request_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Derive readiness exclusively from the embedded source contracts.

    A contract gate may pass while this proof remains not ready.  Missing or
    unfinished operational evidence is represented by stable blocker codes,
    not silently folded into the contract result.
    """

    if not all(isinstance(value, Mapping) for value in (
        contract_gate,
        catalog_contract,
        evaluator_contract,
        request_hashes,
    )):
        raise ValueError("Paid readiness inputs must be mappings")
    catalog = validate_wood_catalog_readiness_contract(catalog_contract)
    evaluator = validate_evaluator_readiness_contract(evaluator_contract)

    normalized_request_hashes: dict[str, str] = {}
    invalid_request_ids: list[str] = []
    for case_id, digest in sorted(request_hashes.items()):
        if not isinstance(case_id, str) or not case_id.strip() or not _is_sha256(digest):
            invalid_request_ids.append(str(case_id))
            continue
        normalized_request_hashes[case_id] = digest

    hard_failures = _non_negative_int(
        contract_gate.get("hard_failure_count", 0),
        field="contract_gate.hard_failure_count",
    )
    pending_checks = _non_negative_int(
        contract_gate.get("pending_check_count", 0),
        field="contract_gate.pending_check_count",
    )
    wood_analysis_pending = _non_negative_int(
        contract_gate.get("wood_analysis_pending_count", 0),
        field="contract_gate.wood_analysis_pending_count",
    )
    contract_status = contract_gate.get("contract_status", contract_gate.get("status"))

    expected_profiles = _catalog_count(
        catalog,
        "expected_wood_profile_count",
        "expected_profile_count",
    )
    published_profiles = _catalog_count(
        catalog,
        "published_wood_profile_count",
        "published_profile_count",
    )
    draft_profiles = _catalog_count(
        catalog,
        "draft_wood_profile_count",
        "draft_profile_count",
    )
    pending_profiles = _catalog_count(
        catalog,
        "pending_wood_profile_count",
        "pending_profile_count",
    )
    catalog_status = catalog.get("status")
    contact_sheet = catalog.get("contact_sheet_review")

    evaluator_status = evaluator.get("status")
    measurements_ready = evaluator.get("required_measurements_complete") is True
    regression_status = evaluator.get("regression_status")
    evaluator_version = evaluator.get("version")

    blockers: list[str] = []
    if contract_status != "pass":
        blockers.append("contract_gate_not_passed")
    if hard_failures:
        blockers.append(f"contract_hard_failures:{hard_failures}")
    if pending_checks:
        blockers.append(f"contract_pending_checks:{pending_checks}")
    if wood_analysis_pending:
        blockers.append(f"wood_analysis_pending:{wood_analysis_pending}")
    if catalog_status != "published":
        blockers.append("wood_catalog_not_published")
    if expected_profiles != REQUIRED_WOOD_PROFILE_COUNT:
        blockers.append(
            f"wood_profile_expected_count:{expected_profiles}/"
            f"{REQUIRED_WOOD_PROFILE_COUNT}"
        )
    if published_profiles != expected_profiles:
        blockers.append(
            f"wood_profiles_published:{published_profiles}/{expected_profiles}"
        )
    if draft_profiles:
        blockers.append(f"wood_profiles_draft:{draft_profiles}")
    if pending_profiles:
        blockers.append(f"wood_profiles_pending:{pending_profiles}")
    if not isinstance(contact_sheet, Mapping) or contact_sheet.get("status") != "approved":
        blockers.append("wood_contact_sheet_not_approved")
    elif not _is_sha256(contact_sheet.get("sha256")):
        blockers.append("wood_contact_sheet_hash_missing")
    if evaluator_status != "ready":
        blockers.append("v3_evaluator_unavailable")
    if not isinstance(evaluator_version, str) or not evaluator_version.strip():
        blockers.append("v3_evaluator_version_missing")
    if not measurements_ready:
        blockers.append("v3_evaluator_measurements_incomplete")
    if regression_status != "pass":
        blockers.append("v3_evaluator_regression_not_passed")
    if invalid_request_ids:
        blockers.append("invalid_request_hashes:" + ",".join(sorted(invalid_request_ids)))
    if not normalized_request_hashes:
        blockers.append("campaign_request_hashes_missing")

    proof: dict[str, Any] = {
        "schema_version": PAID_READINESS_SCHEMA_VERSION,
        "contract_status": contract_status,
        "paid_execution_ready": not blockers,
        "blocking_reasons": blockers,
        "contract_gate_sha256": _hash(contract_gate),
        "catalog_contract_sha256": catalog["catalog_sha256"],
        "evaluator_contract_sha256": evaluator["contract_sha256"],
        "request_hashes": normalized_request_hashes,
        "request_set_sha256": _hash(normalized_request_hashes),
        "evidence": {
            "contract_hard_failure_count": hard_failures,
            "contract_pending_check_count": pending_checks,
            "wood_analysis_pending_count": wood_analysis_pending,
            "expected_wood_profile_count": expected_profiles,
            "published_wood_profile_count": published_profiles,
            "draft_wood_profile_count": draft_profiles,
            "pending_wood_profile_count": pending_profiles,
            "evaluator_status": evaluator_status,
            "evaluator_version": evaluator_version,
            "required_measurements_complete": measurements_ready,
            "regression_status": regression_status,
        },
        "source_contracts": {
            "contract_gate": deepcopy(dict(contract_gate)),
            "catalog_contract": deepcopy(dict(catalog)),
            "evaluator_contract": deepcopy(dict(evaluator)),
        },
    }
    return proof


def build_paid_execution_readiness(
    *,
    contract_gate: Mapping[str, Any],
    catalog_contract: Mapping[str, Any],
    evaluator_contract: Mapping[str, Any],
    request_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Build a self-contained proof without authorizing a paid call.

    The raw catalog, evaluator, and contract-gate inputs are embedded so a
    consumer can re-run their validators.  A summary plus a caller-computed
    outer hash is not accepted as readiness evidence.
    """

    proof = _derive_paid_execution_readiness(
        contract_gate=contract_gate,
        catalog_contract=catalog_contract,
        evaluator_contract=evaluator_contract,
        request_hashes=request_hashes,
    )
    proof["readiness_sha256"] = _hash(proof)
    validate_paid_execution_readiness(proof)
    return proof


def validate_paid_execution_readiness(proof: Mapping[str, Any]) -> dict[str, Any]:
    if proof.get("schema_version") != PAID_READINESS_SCHEMA_VERSION:
        raise ValueError("Unsupported paid-readiness schema version")
    expected_hash = proof.get("readiness_sha256")
    without_hash = dict(proof)
    without_hash.pop("readiness_sha256", None)
    if expected_hash != _hash(without_hash):
        raise ValueError("Paid-readiness hash does not match its contents")
    request_hashes = proof.get("request_hashes")
    if not isinstance(request_hashes, Mapping):
        raise ValueError("Paid readiness request_hashes must be an object")
    if any(
        not isinstance(case_id, str)
        or not case_id.strip()
        or not _is_sha256(digest)
        for case_id, digest in request_hashes.items()
    ):
        raise ValueError("Paid readiness contains an invalid request hash binding")
    source_contracts = proof.get("source_contracts")
    if not isinstance(source_contracts, Mapping):
        raise ValueError("Paid readiness requires embedded source_contracts")
    contract_gate = source_contracts.get("contract_gate")
    catalog_contract = source_contracts.get("catalog_contract")
    evaluator_contract = source_contracts.get("evaluator_contract")
    if not all(
        isinstance(value, Mapping)
        for value in (contract_gate, catalog_contract, evaluator_contract)
    ):
        raise ValueError("Paid readiness source contracts are incomplete")
    expected = _derive_paid_execution_readiness(
        contract_gate=contract_gate,
        catalog_contract=catalog_contract,
        evaluator_contract=evaluator_contract,
        request_hashes=request_hashes,
    )
    if without_hash != expected:
        raise ValueError(
            "Paid-readiness summary does not match its validated source contracts"
        )
    return dict(proof)


def require_paid_execution_readiness(proof: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_paid_execution_readiness(proof)
    if not validated["paid_execution_ready"]:
        reasons = ", ".join(validated["blocking_reasons"]) or "unknown"
        raise ValueError(f"V3 paid execution is not ready: {reasons}")
    return validated


def build_provider_quote(
    *,
    case_id: str,
    request_sha256: str,
    provider: str,
    quoted_credits: float,
    ttl_seconds: int = MAXIMUM_QUOTE_TTL_SECONDS,
    quoted_at: datetime | str | None = None,
) -> dict[str, Any]:
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("Provider quote requires a case_id")
    if not _is_sha256(request_sha256):
        raise ValueError("Provider quote requires a valid request_sha256")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("Provider quote requires a provider")
    if (
        not isinstance(quoted_credits, (int, float))
        or isinstance(quoted_credits, bool)
        or not math.isfinite(float(quoted_credits))
        or float(quoted_credits) < 0
    ):
        raise ValueError("Provider quote credits must be non-negative and finite")
    if (
        not isinstance(ttl_seconds, int)
        or isinstance(ttl_seconds, bool)
        or not 1 <= ttl_seconds <= MAXIMUM_QUOTE_TTL_SECONDS
    ):
        raise ValueError(
            f"Provider quote TTL must be between 1 and {MAXIMUM_QUOTE_TTL_SECONDS} seconds"
        )
    issued = _utc_datetime(quoted_at, field="quoted_at")
    quote: dict[str, Any] = {
        "schema_version": PROVIDER_QUOTE_SCHEMA_VERSION,
        "case_id": case_id,
        "request_sha256": request_sha256,
        "provider": provider,
        "quoted_credits": float(quoted_credits),
        "quoted_at": _timestamp(issued),
        "expires_at": _timestamp(issued + timedelta(seconds=ttl_seconds)),
        "ttl_seconds": ttl_seconds,
    }
    quote["quote_sha256"] = _hash(quote)
    validate_provider_quote(quote, now=issued)
    return quote


def validate_provider_quote(
    quote: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    if quote.get("schema_version") != PROVIDER_QUOTE_SCHEMA_VERSION:
        raise ValueError("Unsupported provider-quote schema version")
    expected_hash = quote.get("quote_sha256")
    without_hash = dict(quote)
    without_hash.pop("quote_sha256", None)
    if expected_hash != _hash(without_hash):
        raise ValueError("Provider-quote hash does not match its contents")
    if not isinstance(quote.get("case_id"), str) or not quote["case_id"].strip():
        raise ValueError("Provider quote requires a case_id")
    if not _is_sha256(quote.get("request_sha256")):
        raise ValueError("Provider quote requires a valid request_sha256")
    if not isinstance(quote.get("provider"), str) or not quote["provider"].strip():
        raise ValueError("Provider quote requires a provider")
    credits = quote.get("quoted_credits")
    if (
        not isinstance(credits, (int, float))
        or isinstance(credits, bool)
        or not math.isfinite(float(credits))
        or float(credits) < 0
    ):
        raise ValueError("Provider quote credits must be non-negative and finite")
    ttl_seconds = quote.get("ttl_seconds")
    if (
        not isinstance(ttl_seconds, int)
        or isinstance(ttl_seconds, bool)
        or not 1 <= ttl_seconds <= MAXIMUM_QUOTE_TTL_SECONDS
    ):
        raise ValueError("Provider quote TTL is outside the allowed range")
    issued = _utc_datetime(quote.get("quoted_at"), field="quoted_at")
    expires = _utc_datetime(quote.get("expires_at"), field="expires_at")
    if expires != issued + timedelta(seconds=ttl_seconds):
        raise ValueError("Provider quote expiry does not match its TTL")
    current = _utc_datetime(now, field="now")
    if issued > current + timedelta(seconds=MAXIMUM_FUTURE_CLOCK_SKEW_SECONDS):
        raise ValueError("Provider quote was issued in the future")
    if current >= expires:
        raise ValueError("Provider quote has expired")
    return dict(quote)


def is_v3_generation_request(request: Mapping[str, Any]) -> bool:
    """Recognize V3 by version *or* by V3-only contract features.

    Paid boundaries must not turn a malformed/downgraded V3 payload into a
    legacy request merely because ``schema_version`` was lost or edited.
    """

    schema_version = request.get("schema_version")
    if schema_version == V3_GENERATION_REQUEST_SCHEMA_VERSION:
        return True
    if isinstance(schema_version, str) and (
        schema_version == "3" or schema_version.startswith("3.")
    ):
        return True
    generation = request.get("generation")
    if isinstance(generation, Mapping) and "image_inputs" in generation:
        return True
    if (
        "products" in request
        or "product_set" in request
        or V3_DIAGNOSTIC_AUTHORIZATION_FIELD in request
        or V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD in request
    ):
        return True
    if request.get("prompt_compiler_version") == V3_PROMPT_COMPILER_VERSION:
        return True
    return any(
        field in request
        for field in (
            "resolved_visual_contract",
            "reference_analysis_contract",
            "target_brand_contract",
        )
    )


def require_v3_paid_submission_allowed(
    request: Mapping[str, Any],
    *,
    provider_name: str,
    idempotency_key: str | None = None,
) -> None:
    """Emergency fail-closed guard for production V3 generation.

    Production readiness and campaign authorization are deliberately not
    accepted as an implicit bypass here.  The only non-zero-credit exception is
    separately reviewed diagnostic envelopes.  The ordinary pilot remains
    capped at two cases/four credits.  A distinct 4x5 matrix purpose is capped
    at twenty cases/forty credits; neither output can establish production
    readiness.
    """

    if not is_v3_generation_request(request):
        return
    has_pilot_authorization = V3_DIAGNOSTIC_AUTHORIZATION_FIELD in request
    has_matrix_authorization = V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD in request
    if has_pilot_authorization and has_matrix_authorization:
        raise V3PaidExecutionDisabled(
            "v3_diagnostic_authorization_ambiguous: a request cannot carry both "
            "pilot and matrix diagnostic authorizations"
        )
    if has_pilot_authorization:
        try:
            # Lazy import avoids a module cycle: diagnostic_pilot uses the
            # canonical request hashing implemented by runs.py.
            from .diagnostic_pilot import validate_diagnostic_pilot_request

            _, diagnostic_case = validate_diagnostic_pilot_request(
                request,
                provider_name=provider_name,
            )
            if (
                idempotency_key is not None
                and idempotency_key != diagnostic_case["idempotency_key"]
            ):
                raise ValueError(
                    "Diagnostic submit idempotency key differs from its authorization"
                )
        except Exception as exc:
            raise V3PaidExecutionDisabled(
                "v3_diagnostic_paid_pilot_invalid: the diagnostic authorization "
                f"was rejected before paid provider {provider_name!r}: {exc}"
            ) from exc
        return
    if has_matrix_authorization:
        try:
            # The 4x5 matrix is a distinct, explicitly authorized diagnostic
            # purpose.  Its hard caps are not inherited from or able to widen
            # the two-case pilot contract above.
            from .diagnostic_matrix import validate_diagnostic_matrix_request

            _, diagnostic_case = validate_diagnostic_matrix_request(
                request,
                provider_name=provider_name,
            )
            if (
                idempotency_key is not None
                and idempotency_key != diagnostic_case["idempotency_key"]
            ):
                raise ValueError(
                    "Matrix diagnostic submit idempotency key differs from its authorization"
                )
        except Exception as exc:
            raise V3PaidExecutionDisabled(
                "v3_diagnostic_paid_matrix_invalid: the matrix authorization "
                f"was rejected before paid provider {provider_name!r}: {exc}"
            ) from exc
        return
    raise V3PaidExecutionDisabled(
        "v3_paid_execution_disabled: GenerationRequestV3 cannot be submitted "
        f"to paid provider {provider_name!r}; use the zero-credit fake provider "
        "until the emergency guard is explicitly released"
    )


def guard_generation_provider_boundary(
    request: Mapping[str, Any],
    *,
    provider: Any,
) -> None:
    """Permit V3 only through providers explicitly marked zero-credit."""

    if not is_v3_generation_request(request):
        return
    if getattr(provider, "is_zero_credit", False) is True:
        return
    require_v3_paid_submission_allowed(
        request,
        provider_name=str(getattr(provider, "name", type(provider).__name__)),
    )
