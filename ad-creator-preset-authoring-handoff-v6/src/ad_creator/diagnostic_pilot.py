from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .generation_inputs import ordered_image_inputs
from .paid_readiness import (
    MAXIMUM_FUTURE_CLOCK_SKEW_SECONDS,
    V3_DIAGNOSTIC_AUTHORIZATION_FIELD,
    V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD,
    V3_GENERATION_REQUEST_SCHEMA_VERSION,
    V3_PROMPT_COMPILER_VERSION,
    build_provider_quote,
    guard_generation_provider_boundary,
    validate_provider_quote,
)
from .providers.base import GenerationProvider, ProviderJob
from .prompt_limits import resolve_prompt_limit_policy
from .runs import ManualReconciliationRequired, RunStore, request_hash


DIAGNOSTIC_AUTHORIZATION_SCHEMA_VERSION = "1.0.0"
DIAGNOSTIC_BUNDLE_SCHEMA_VERSION = "1.0.0"
DIAGNOSTIC_AUTHORIZATION_TYPE = "v3_diagnostic_paid_pilot_authorization"
DIAGNOSTIC_BUNDLE_TYPE = "v3_diagnostic_paid_pilot_bundle"
DIAGNOSTIC_PURPOSE = "v3_diagnostic_quality_pilot"
DIAGNOSTIC_PROVIDER = "higgsfield_cli"
EXTERNAL_UPLOAD_CONFIRMATION = (
    "I_CONFIRM_EXACT_PRODUCT_IMAGES_AND_OPTIONAL_SANITIZED_CONTROL_BOARDS_"
    "WILL_BE_UPLOADED_TO_HIGGSFIELD"
)
MAXIMUM_DIAGNOSTIC_CASES = 2
MAXIMUM_DIAGNOSTIC_TOTAL_CREDITS = 4.0
MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE = 2.0
MAXIMUM_DIAGNOSTIC_AUTHORIZATION_TTL_SECONDS = 10 * 60
DIAGNOSTIC_RESULT_DISPOSITION = "manual_review"


class DiagnosticPilotError(RuntimeError):
    """A diagnostic pilot contract or execution boundary was rejected."""


def _canonical_sha256(value: Any) -> str:
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


def _utc(value: datetime | str | None, *, field: str) -> datetime:
    if value is None:
        return _utc_now()
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


def _finite_credits(value: Any, *, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def diagnostic_base_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact provider payload with only the pilot envelope removed."""

    value = copy.deepcopy(dict(request))
    value.pop(V3_DIAGNOSTIC_AUTHORIZATION_FIELD, None)
    value.pop(V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD, None)
    return value


def diagnostic_request_hash(request: Mapping[str, Any]) -> str:
    """Bind authorization to request fields and the bytes of every input image."""

    return request_hash(diagnostic_base_request(request))


def _walk_contract_fields(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key), item
            yield from _walk_contract_fields(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_contract_fields(item)


def validate_diagnostic_base_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the narrow structured or reviewed-control-board diagnostic payload.

    The diagnostic arm accepts one to three exact product images and at most one
    final, hash-bound control board. Raw references, masked crops, repair inputs
    and any other image role remain forbidden.
    """

    value = diagnostic_base_request(request)
    if value.get("schema_version") != V3_GENERATION_REQUEST_SCHEMA_VERSION:
        raise ValueError("Diagnostic pilot requires GenerationRequestV3 schema 3.0.0")
    if value.get("prompt_compiler_version") != V3_PROMPT_COMPILER_VERSION:
        raise ValueError(
            "Diagnostic pilot requires natural_compact_v5_multi prompt compilation"
        )
    if value.get("repair_type") is not None or value.get("maximum_attempts") is not None:
        raise ValueError("Diagnostic pilot forbids paid repair requests")
    generation = value.get("generation")
    if not isinstance(generation, dict):
        raise ValueError("Diagnostic pilot request requires generation")
    if generation.get("provider") != DIAGNOSTIC_PROVIDER:
        raise ValueError("Diagnostic pilot is restricted to higgsfield_cli")
    if generation.get("job_type") != "gpt_image_2":
        raise ValueError("Diagnostic pilot is restricted to Higgsfield gpt_image_2")
    prompt = generation.get("prompt")
    prompt_policy = resolve_prompt_limit_policy(
        provider=generation.get("provider"),
        model=generation.get("job_type"),
    )
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or len(prompt) > prompt_policy.maximum_characters
    ):
        raise ValueError(
            "Diagnostic pilot prompt must contain 1.."
            f"{prompt_policy.maximum_characters} characters"
        )
    for field, expected in (
        ("prompt_character_limit", prompt_policy.maximum_characters),
        ("prompt_limit_policy_id", prompt_policy.policy_id),
        ("prompt_limit_verification_state", prompt_policy.verification_state),
    ):
        observed = generation.get(field)
        if observed is not None and observed != expected:
            raise ValueError(
                f"Diagnostic pilot generation.{field} conflicts with prompt policy"
            )
    for field in ("aspect_ratio", "resolution", "quality"):
        if not isinstance(generation.get(field), str) or not generation[field].strip():
            raise ValueError(f"Diagnostic pilot generation.{field} is required")
    estimated = _finite_credits(
        generation.get("estimated_credits"),
        field="generation.estimated_credits",
    )
    if estimated <= 0 or estimated > MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE:
        raise ValueError("Diagnostic case must cost more than 0 and no more than 2 credits")
    if "image_paths" in generation or "image_roles" in generation:
        raise ValueError("Diagnostic V3 requests cannot use legacy image arrays")

    image_inputs = ordered_image_inputs(generation, allow_legacy=False)
    if not 1 <= len(image_inputs) <= 4:
        raise ValueError("Diagnostic pilot accepts one to three products plus one board")
    board_inputs = [
        item for item in image_inputs if item["role"] == "reference_control_board"
    ]
    if len(board_inputs) > 1:
        raise ValueError("Diagnostic pilot accepts at most one control board")
    if board_inputs and image_inputs[-1]["role"] != "reference_control_board":
        raise ValueError("Diagnostic control board must be the final ordered input")
    if any(
        item["role"] not in {"product_source", "reference_control_board"}
        for item in image_inputs
    ):
        raise ValueError("Diagnostic pilot received an unsupported image role")
    product_inputs = [item for item in image_inputs if item["role"] == "product_source"]
    if not 1 <= len(product_inputs) <= 3:
        raise ValueError("Diagnostic pilot requires one to three product_source inputs")
    manifest = value.get("reference_control_board_manifest")
    if board_inputs:
        if not isinstance(manifest, Mapping):
            raise ValueError("Diagnostic control board requires a bound manifest")
        board_path = Path(board_inputs[0]["path"]).expanduser()
        from .multi_pipeline import validate_reference_control_board_binding

        validate_reference_control_board_binding(board_path, manifest)
    elif manifest is not None:
        raise ValueError("Diagnostic manifest is forbidden without a control-board input")
    product_ids = [item.get("product_id") for item in product_inputs]
    if any(not isinstance(item, str) or not item.strip() for item in product_ids):
        raise ValueError("Every diagnostic product_source requires product_id")
    if len(set(product_ids)) != len(product_ids):
        raise ValueError("Diagnostic product_source IDs must be unique")

    products = value.get("products")
    if not isinstance(products, list) or not 1 <= len(products) <= 3:
        raise ValueError("Diagnostic pilot requires one to three exact products")
    declared_ids = [item.get("product_id") if isinstance(item, Mapping) else None for item in products]
    if declared_ids != product_ids:
        raise ValueError("Diagnostic product order must match ordered image_inputs")
    for product, image_input in zip(products, product_inputs, strict=True):
        source_image = product.get("source_image")
        if source_image != image_input["path"]:
            raise ValueError("Diagnostic ProductSpec source_image must match image_inputs")
        path = Path(image_input["path"]).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Diagnostic product image does not exist: {path}")

    product_set = value.get("product_set")
    if isinstance(product_set, Mapping):
        set_products = product_set.get("products")
        if isinstance(set_products, list):
            set_ids = [
                item.get("product_id") if isinstance(item, Mapping) else None
                for item in set_products
            ]
            if set_ids != product_ids:
                raise ValueError("Diagnostic product_set differs from products")

    forbidden_truthy_keys = {
        "derived_board",
        "derived_material_board",
        "masked_raw_crop",
        "raw_crop",
        "brand_asset_image",
        "brand_mask_image",
        "repair_request",
    }
    arm_keys = {"material_arm", "material_input_mode", "wood_input_mode"}
    for key, item in _walk_contract_fields(value):
        normalized = key.lower()
        if normalized in forbidden_truthy_keys and item not in (None, False, "", [], {}):
            raise ValueError(f"Diagnostic reviewed-input arm forbids {key}")
        if normalized in arm_keys and item != "structured_only":
            raise ValueError(f"Diagnostic material arm must be structured_only, not {item!r}")
    return value


def _diagnostic_idempotency_key(
    *, pilot_id: str, case_id: str, request_sha256: str
) -> str:
    # It intentionally excludes short-lived quote/authorization timestamps.
    # Renewing an expired envelope for the same pilot cannot create a second
    # remote job after an uncertain submission.
    return _canonical_sha256(
        {
            "purpose": DIAGNOSTIC_PURPOSE,
            "pilot_id": pilot_id,
            "case_id": case_id,
            "request_sha256": request_sha256,
        }
    )


def build_diagnostic_pilot_authorization(
    *,
    pilot_id: str,
    requests: Mapping[str, Mapping[str, Any]],
    provider_quotes: Mapping[str, Mapping[str, Any]],
    external_upload_confirmed: bool,
    confirmation_statement: str = EXTERNAL_UPLOAD_CONFIRMATION,
    issued_at: datetime | str | None = None,
    ttl_seconds: int = MAXIMUM_DIAGNOSTIC_AUTHORIZATION_TTL_SECONDS,
) -> dict[str, Any]:
    if not isinstance(pilot_id, str) or not pilot_id.strip():
        raise ValueError("Diagnostic pilot_id is required")
    if not 1 <= len(requests) <= MAXIMUM_DIAGNOSTIC_CASES:
        raise ValueError("Diagnostic pilot permits one or two cases only")
    if set(requests) != set(provider_quotes):
        raise ValueError("Every diagnostic case requires exactly one provider quote")
    if external_upload_confirmed is not True:
        raise ValueError("Diagnostic pilot requires explicit external-upload confirmation")
    if confirmation_statement != EXTERNAL_UPLOAD_CONFIRMATION:
        raise ValueError("External-upload confirmation statement does not match")
    if (
        not isinstance(ttl_seconds, int)
        or isinstance(ttl_seconds, bool)
        or not 1 <= ttl_seconds <= MAXIMUM_DIAGNOSTIC_AUTHORIZATION_TTL_SECONDS
    ):
        raise ValueError("Diagnostic authorization TTL must be between 1 and 600 seconds")

    issued = _utc(issued_at, field="issued_at")
    expires = issued + timedelta(seconds=ttl_seconds)
    cases: list[dict[str, Any]] = []
    total = 0.0
    for case_id, request in requests.items():
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Every diagnostic case requires case_id")
        validate_diagnostic_base_request(request)
        digest = diagnostic_request_hash(request)
        quote = validate_provider_quote(provider_quotes[case_id], now=issued)
        if quote["case_id"] != case_id:
            raise ValueError("Provider quote case_id differs from diagnostic case")
        if quote["request_sha256"] != digest:
            raise ValueError("Provider quote is bound to another diagnostic request")
        if quote["provider"] != DIAGNOSTIC_PROVIDER:
            raise ValueError("Diagnostic quote is bound to another provider")
        credits = float(quote["quoted_credits"])
        if credits <= 0 or credits > MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE:
            raise ValueError("Every diagnostic provider quote must be within (0, 2] credits")
        estimated = float(request["generation"]["estimated_credits"])
        if abs(estimated - credits) > 1e-9:
            raise ValueError("Diagnostic request estimate must equal its fresh provider quote")
        quote_expiry = _utc(quote["expires_at"], field="quote.expires_at")
        if quote_expiry < expires:
            raise ValueError("Provider quote expires before diagnostic authorization")
        total += credits
        cases.append(
            {
                "case_id": case_id,
                "request_sha256": digest,
                "quote": copy.deepcopy(quote),
                "quote_sha256": quote["quote_sha256"],
                "idempotency_key": _diagnostic_idempotency_key(
                    pilot_id=pilot_id,
                    case_id=case_id,
                    request_sha256=digest,
                ),
            }
        )
    if total > MAXIMUM_DIAGNOSTIC_TOTAL_CREDITS:
        raise ValueError("Diagnostic provider quotes exceed the 4-credit pilot cap")

    request_hashes = {case["case_id"]: case["request_sha256"] for case in cases}
    quote_hashes = {case["case_id"]: case["quote_sha256"] for case in cases}
    authorization: dict[str, Any] = {
        "schema_version": DIAGNOSTIC_AUTHORIZATION_SCHEMA_VERSION,
        "artifact_type": DIAGNOSTIC_AUTHORIZATION_TYPE,
        "purpose": DIAGNOSTIC_PURPOSE,
        "pilot_id": pilot_id,
        "authorized": True,
        "provider": DIAGNOSTIC_PROVIDER,
        "issued_at": _timestamp(issued),
        "expires_at": _timestamp(expires),
        "ttl_seconds": ttl_seconds,
        "external_upload_confirmation": {
            "confirmed": True,
            "statement": EXTERNAL_UPLOAD_CONFIRMATION,
            "confirmed_at": _timestamp(issued),
            "request_set_sha256": _canonical_sha256(request_hashes),
        },
        "execution_policy": {
            "maximum_cases": MAXIMUM_DIAGNOSTIC_CASES,
            "maximum_total_credits": MAXIMUM_DIAGNOSTIC_TOTAL_CREDITS,
            "maximum_credits_per_case": MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE,
            "automatic_paid_repair": False,
            "maximum_auto_repairs": 0,
            "material_arm": "structured_or_reviewed_control_board",
            "result_disposition": DIAGNOSTIC_RESULT_DISPOSITION,
            "production_readiness_eligible": False,
        },
        "case_count": len(cases),
        "quoted_credits": total,
        "request_set_sha256": _canonical_sha256(request_hashes),
        "quote_set_sha256": _canonical_sha256(quote_hashes),
        "cases": cases,
    }
    authorization["authorization_sha256"] = _canonical_sha256(authorization)
    validate_diagnostic_pilot_authorization(authorization, now=issued)
    return authorization


def validate_diagnostic_pilot_authorization(
    authorization: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(authorization, Mapping):
        raise ValueError("Diagnostic authorization must be an object")
    value = copy.deepcopy(dict(authorization))
    expected_authorization_fields = {
        "schema_version",
        "artifact_type",
        "purpose",
        "pilot_id",
        "authorized",
        "provider",
        "issued_at",
        "expires_at",
        "ttl_seconds",
        "external_upload_confirmation",
        "execution_policy",
        "case_count",
        "quoted_credits",
        "request_set_sha256",
        "quote_set_sha256",
        "cases",
        "authorization_sha256",
    }
    if set(value) != expected_authorization_fields:
        raise ValueError("Diagnostic authorization has unknown or missing fields")
    if value.get("schema_version") != DIAGNOSTIC_AUTHORIZATION_SCHEMA_VERSION:
        raise ValueError("Unsupported diagnostic authorization schema")
    if value.get("artifact_type") != DIAGNOSTIC_AUTHORIZATION_TYPE:
        raise ValueError("Diagnostic authorization has wrong artifact_type")
    if value.get("purpose") != DIAGNOSTIC_PURPOSE or value.get("authorized") is not True:
        raise ValueError("Diagnostic pilot was not explicitly authorized")
    if value.get("provider") != DIAGNOSTIC_PROVIDER:
        raise ValueError("Diagnostic pilot is restricted to higgsfield_cli")
    if not isinstance(value.get("pilot_id"), str) or not value["pilot_id"].strip():
        raise ValueError("Diagnostic authorization requires pilot_id")
    declared_hash = value.get("authorization_sha256")
    stable = copy.deepcopy(value)
    stable.pop("authorization_sha256", None)
    if not _is_sha256(declared_hash) or declared_hash != _canonical_sha256(stable):
        raise ValueError("Diagnostic authorization hash does not match its contents")

    ttl = value.get("ttl_seconds")
    if (
        not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or not 1 <= ttl <= MAXIMUM_DIAGNOSTIC_AUTHORIZATION_TTL_SECONDS
    ):
        raise ValueError("Diagnostic authorization TTL is outside 1..600 seconds")
    issued = _utc(value.get("issued_at"), field="authorization.issued_at")
    expires = _utc(value.get("expires_at"), field="authorization.expires_at")
    if expires != issued + timedelta(seconds=ttl):
        raise ValueError("Diagnostic authorization expiry differs from TTL")
    current = _utc(now, field="now")
    if issued > current + timedelta(seconds=MAXIMUM_FUTURE_CLOCK_SKEW_SECONDS):
        raise ValueError("Diagnostic authorization was issued in the future")
    if require_fresh and current >= expires:
        raise ValueError("Diagnostic authorization has expired")

    policy = value.get("execution_policy")
    expected_policy = {
        "maximum_cases": MAXIMUM_DIAGNOSTIC_CASES,
        "maximum_total_credits": MAXIMUM_DIAGNOSTIC_TOTAL_CREDITS,
        "maximum_credits_per_case": MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE,
        "automatic_paid_repair": False,
        "maximum_auto_repairs": 0,
        "material_arm": "structured_or_reviewed_control_board",
        "result_disposition": DIAGNOSTIC_RESULT_DISPOSITION,
        "production_readiness_eligible": False,
    }
    if policy != expected_policy:
        raise ValueError("Diagnostic execution policy was altered")

    cases = value.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAXIMUM_DIAGNOSTIC_CASES:
        raise ValueError("Diagnostic authorization permits one or two cases only")
    if value.get("case_count") != len(cases):
        raise ValueError("Diagnostic authorization case_count differs from cases")
    request_hashes: dict[str, str] = {}
    quote_hashes: dict[str, str] = {}
    total = 0.0
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("Diagnostic case authorization must be an object")
        if set(case) != {
            "case_id",
            "request_sha256",
            "quote",
            "quote_sha256",
            "idempotency_key",
        }:
            raise ValueError("Diagnostic case has unknown or missing fields")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in request_hashes:
            raise ValueError("Diagnostic case IDs must be non-empty and unique")
        request_sha256 = case.get("request_sha256")
        if not _is_sha256(request_sha256):
            raise ValueError("Diagnostic case request_sha256 is invalid")
        expected_idempotency = _diagnostic_idempotency_key(
            pilot_id=value["pilot_id"],
            case_id=case_id,
            request_sha256=request_sha256,
        )
        if case.get("idempotency_key") != expected_idempotency:
            raise ValueError("Diagnostic idempotency binding was altered")
        # Once a submit marker/job exists, reconciliation must remain possible
        # after authorization expiry.  The quote still has to have been valid
        # at authorization issuance and all hashes/policies remain enforced.
        quote = validate_provider_quote(
            case.get("quote", {}),
            now=current if require_fresh else issued,
        )
        if (
            quote["case_id"] != case_id
            or quote["request_sha256"] != request_sha256
            or quote["provider"] != DIAGNOSTIC_PROVIDER
            or case.get("quote_sha256") != quote["quote_sha256"]
        ):
            raise ValueError("Diagnostic case and provider quote bindings differ")
        credits = float(quote["quoted_credits"])
        if credits <= 0 or credits > MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE:
            raise ValueError("Diagnostic case quote exceeds the 2-credit cap")
        total += credits
        request_hashes[case_id] = request_sha256
        quote_hashes[case_id] = quote["quote_sha256"]
    if total > MAXIMUM_DIAGNOSTIC_TOTAL_CREDITS:
        raise ValueError("Diagnostic authorization exceeds the 4-credit cap")
    if abs(total - _finite_credits(value.get("quoted_credits"), field="quoted_credits")) > 1e-9:
        raise ValueError("Diagnostic quoted_credits differs from case quotes")
    request_set_sha256 = _canonical_sha256(request_hashes)
    if value.get("request_set_sha256") != request_set_sha256:
        raise ValueError("Diagnostic request-set hash differs from cases")
    if value.get("quote_set_sha256") != _canonical_sha256(quote_hashes):
        raise ValueError("Diagnostic quote-set hash differs from cases")

    confirmation = value.get("external_upload_confirmation")
    expected_confirmation = {
        "confirmed": True,
        "statement": EXTERNAL_UPLOAD_CONFIRMATION,
        "confirmed_at": value["issued_at"],
        "request_set_sha256": request_set_sha256,
    }
    if confirmation != expected_confirmation:
        raise ValueError("External-upload confirmation is absent or altered")
    return value


def _case_by_request_hash(
    authorization: Mapping[str, Any], request_sha256: str
) -> dict[str, Any]:
    matches = [
        dict(case)
        for case in authorization["cases"]
        if case.get("request_sha256") == request_sha256
    ]
    if len(matches) != 1:
        raise ValueError("Diagnostic request is not uniquely authorized")
    return matches[0]


def validate_diagnostic_pilot_request(
    request: Mapping[str, Any],
    *,
    provider_name: str,
    now: datetime | str | None = None,
    require_fresh: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if provider_name != DIAGNOSTIC_PROVIDER:
        raise ValueError("Diagnostic authorization cannot be used with another provider")
    if V3_DIAGNOSTIC_AUTHORIZATION_FIELD not in request:
        raise ValueError("Diagnostic request has no authorization envelope")
    base = validate_diagnostic_base_request(request)
    authorization = validate_diagnostic_pilot_authorization(
        request[V3_DIAGNOSTIC_AUTHORIZATION_FIELD],
        now=now,
        require_fresh=require_fresh,
    )
    digest = request_hash(base)
    case = _case_by_request_hash(authorization, digest)
    estimated = float(base["generation"]["estimated_credits"])
    if abs(estimated - float(case["quote"]["quoted_credits"])) > 1e-9:
        raise ValueError("Diagnostic request cost differs from its authorized quote")
    return authorization, case


def attach_diagnostic_pilot_authorization(
    request: Mapping[str, Any], authorization: Mapping[str, Any]
) -> dict[str, Any]:
    value = diagnostic_base_request(request)
    validated = validate_diagnostic_pilot_authorization(authorization)
    _case_by_request_hash(validated, request_hash(value))
    value[V3_DIAGNOSTIC_AUTHORIZATION_FIELD] = copy.deepcopy(validated)
    return value


def build_diagnostic_pilot_bundle(
    *,
    requests: Mapping[str, Mapping[str, Any]],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_diagnostic_pilot_authorization(authorization)
    expected_ids = [case["case_id"] for case in validated["cases"]]
    if list(requests) != expected_ids:
        raise ValueError("Diagnostic bundle request order differs from authorization")
    entries = []
    for case_id, request in requests.items():
        attached = attach_diagnostic_pilot_authorization(request, validated)
        _, case = validate_diagnostic_pilot_request(
            attached,
            provider_name=DIAGNOSTIC_PROVIDER,
        )
        if case["case_id"] != case_id:
            raise ValueError("Diagnostic request is stored under another case_id")
        entries.append({"case_id": case_id, "request": attached})
    bundle: dict[str, Any] = {
        "schema_version": DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
        "artifact_type": DIAGNOSTIC_BUNDLE_TYPE,
        "pilot_id": validated["pilot_id"],
        "authorization_sha256": validated["authorization_sha256"],
        "requests": entries,
    }
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    return validate_diagnostic_pilot_bundle(bundle)


def validate_diagnostic_pilot_bundle(
    bundle: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(bundle, Mapping):
        raise ValueError("Diagnostic bundle must be an object")
    value = copy.deepcopy(dict(bundle))
    if set(value) != {
        "schema_version",
        "artifact_type",
        "pilot_id",
        "authorization_sha256",
        "requests",
        "bundle_sha256",
    }:
        raise ValueError("Diagnostic bundle has unknown or missing fields")
    if value.get("schema_version") != DIAGNOSTIC_BUNDLE_SCHEMA_VERSION:
        raise ValueError("Unsupported diagnostic bundle schema")
    if value.get("artifact_type") != DIAGNOSTIC_BUNDLE_TYPE:
        raise ValueError("Diagnostic bundle has wrong artifact_type")
    declared = value.get("bundle_sha256")
    stable = copy.deepcopy(value)
    stable.pop("bundle_sha256", None)
    if not _is_sha256(declared) or declared != _canonical_sha256(stable):
        raise ValueError("Diagnostic bundle hash does not match its contents")
    entries = value.get("requests")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAXIMUM_DIAGNOSTIC_CASES:
        raise ValueError("Diagnostic bundle requires one or two requests")

    authorization: dict[str, Any] | None = None
    expected_ids: list[str] | None = None
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("request"), Mapping):
            raise ValueError("Diagnostic bundle request entry is invalid")
        if set(entry) != {"case_id", "request"}:
            raise ValueError("Diagnostic bundle request has unknown or missing fields")
        request = entry["request"]
        candidate, case = validate_diagnostic_pilot_request(
            request,
            provider_name=DIAGNOSTIC_PROVIDER,
            now=now,
            require_fresh=require_fresh,
        )
        if entry.get("case_id") != case["case_id"]:
            raise ValueError("Diagnostic bundle case_id differs from authorization")
        if authorization is None:
            authorization = candidate
            expected_ids = [item["case_id"] for item in candidate["cases"]]
        elif candidate["authorization_sha256"] != authorization["authorization_sha256"]:
            raise ValueError("Diagnostic bundle contains different authorizations")
    observed_ids = [entry["case_id"] for entry in entries]
    if observed_ids != expected_ids:
        raise ValueError("Diagnostic bundle is incomplete or reordered")
    if value.get("pilot_id") != authorization["pilot_id"]:
        raise ValueError("Diagnostic bundle pilot_id differs from authorization")
    if value.get("authorization_sha256") != authorization["authorization_sha256"]:
        raise ValueError("Diagnostic bundle authorization hash differs")
    return value


def preflight_diagnostic_pilot(
    *,
    pilot_id: str,
    requests: Mapping[str, Mapping[str, Any]],
    provider: Any,
    external_upload_confirmed: bool,
    issued_at: datetime | str | None = None,
    ttl_seconds: int = MAXIMUM_DIAGNOSTIC_AUTHORIZATION_TTL_SECONDS,
) -> dict[str, Any]:
    """Fetch provider estimates and build the short-lived execution bundle.

    ``estimate_cost`` is the only provider operation used here.  No generation
    submission or automatic repair is performed by preflight.
    """

    if getattr(provider, "name", None) != DIAGNOSTIC_PROVIDER:
        raise ValueError("Diagnostic preflight requires HiggsfieldProvider")
    for request in requests.values():
        validate_diagnostic_base_request(request)
    issued = _utc(issued_at, field="issued_at")
    quotes: dict[str, dict[str, Any]] = {}
    for case_id, request in requests.items():
        quoted = _finite_credits(
            provider.estimate_cost(diagnostic_base_request(request)),
            field=f"provider quote for {case_id}",
        )
        quotes[case_id] = build_provider_quote(
            case_id=case_id,
            request_sha256=diagnostic_request_hash(request),
            provider=DIAGNOSTIC_PROVIDER,
            quoted_credits=quoted,
            quoted_at=issued,
            ttl_seconds=ttl_seconds,
        )
    authorization = build_diagnostic_pilot_authorization(
        pilot_id=pilot_id,
        requests=requests,
        provider_quotes=quotes,
        external_upload_confirmed=external_upload_confirmed,
        issued_at=issued,
        ttl_seconds=ttl_seconds,
    )
    return build_diagnostic_pilot_bundle(
        requests=requests,
        authorization=authorization,
    )


def _apply_job(manifest: dict[str, Any], job: ProviderJob) -> None:
    if not isinstance(job, ProviderJob):
        raise TypeError("Diagnostic provider must return ProviderJob")
    provider = manifest["provider"]
    provider["job_id"] = job.job_id
    provider["status"] = job.status
    provider["metadata"] = job.metadata or {}
    manifest["cost"]["actual_credits"] = job.actual_credits
    if job.output_path is not None:
        manifest["artifacts"]["provider_output"] = str(job.output_path.resolve())
    if job.status == "completed":
        manifest["status"] = "provider_completed"
    elif job.status in {"failed", "cancelled"}:
        manifest["status"] = "failed"
    elif job.status in {"queued", "pending", "created"}:
        manifest["status"] = "queued"
    else:
        manifest["status"] = "running"


def _mark_manual_review(
    manifest: dict[str, Any],
    *,
    store: RunStore,
    authorization: Mapping[str, Any],
    case: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    provider_terminal_status = manifest.get("status")
    diagnostic = {
        "pilot_id": authorization["pilot_id"],
        "case_id": case["case_id"],
        "authorization_sha256": authorization["authorization_sha256"],
        "quote_sha256": case["quote_sha256"],
        "request_sha256": case["request_sha256"],
        "result_disposition": DIAGNOSTIC_RESULT_DISPOSITION,
        "production_readiness_eligible": False,
        "automatic_paid_repair_attempts": 0,
        "provider_terminal_status": provider_terminal_status,
        "reason": reason,
    }
    manifest.setdefault("metrics", {})["diagnostic_pilot"] = diagnostic
    manifest["status"] = "manual_review"
    manifest.setdefault("events", []).append(
        {
            "at": _timestamp(_utc_now()),
            "type": "diagnostic_manual_review_required",
            "case_id": case["case_id"],
            "reason": reason,
            "production_readiness_eligible": False,
        }
    )
    store.save(manifest)
    return manifest


def execute_diagnostic_pilot_case(
    request: dict[str, Any],
    *,
    provider: GenerationProvider,
    store: RunStore,
    timeout_seconds: float = 1200,
    poll_interval_seconds: float = 3,
    clock: Callable[[], datetime] = _utc_now,
) -> tuple[dict[str, Any], bool]:
    """Execute or reconcile one case; never convert its result into a pass."""

    if timeout_seconds <= 0 or poll_interval_seconds < 0:
        raise ValueError("Diagnostic timeout must be positive and poll interval non-negative")
    authorization, case = validate_diagnostic_pilot_request(
        request,
        provider_name=str(getattr(provider, "name", "")),
        now=clock(),
        require_fresh=False,
    )
    manifest, created = store.prepare(request, provider.name)
    existing_diagnostic = manifest.get("metrics", {}).get("diagnostic_pilot")
    if manifest.get("status") == "manual_review" and isinstance(existing_diagnostic, Mapping):
        if (
            existing_diagnostic.get("pilot_id") != authorization["pilot_id"]
            or existing_diagnostic.get("case_id") != case["case_id"]
        ):
            raise DiagnosticPilotError("Existing RunStore result belongs to another pilot")
        return manifest, True

    provider_state = manifest["provider"]
    diagnostic_binding = manifest.setdefault("diagnostic_pilot_binding", {})
    expected_binding = {
        "pilot_id": authorization["pilot_id"],
        "case_id": case["case_id"],
        "request_sha256": case["request_sha256"],
        "authorization_sha256": authorization["authorization_sha256"],
        "quote_sha256": case["quote_sha256"],
        "idempotency_key": case["idempotency_key"],
    }
    if diagnostic_binding and diagnostic_binding != expected_binding:
        raise DiagnosticPilotError("RunStore diagnostic binding changed")
    if not diagnostic_binding:
        manifest["diagnostic_pilot_binding"] = copy.deepcopy(expected_binding)
        store.save(manifest)

    started = time.monotonic()
    while True:
        provider_state = manifest["provider"]
        if provider_state.get("job_id"):
            job = provider.get(provider_state["job_id"])
            _apply_job(manifest, job)
            manifest["events"].append(
                {
                    "at": _timestamp(clock()),
                    "type": "diagnostic_provider_resumed",
                    "job_id": job.job_id,
                }
            )
            store.save(manifest)
        elif provider_state.get("submit_started"):
            reconcile = getattr(provider, "find_by_idempotency_key", None)
            recovered = (
                reconcile(case["idempotency_key"])
                if callable(reconcile)
                else None
            )
            if recovered is None:
                raise ManualReconciliationRequired(
                    "Diagnostic submission started without a recorded job ID. "
                    "Automatic resubmission is blocked; reconcile the provider job manually."
                )
            _apply_job(manifest, recovered)
            manifest["events"].append(
                {
                    "at": _timestamp(clock()),
                    "type": "diagnostic_provider_job_reconciled",
                    "job_id": recovered.job_id,
                }
            )
            store.save(manifest)
        else:
            # Freshness is required only immediately before a possible paid
            # submit.  Expired envelopes may still poll/reconcile an existing
            # job, but can never start a new one.
            validate_diagnostic_pilot_request(
                request,
                provider_name=provider.name,
                now=clock(),
                require_fresh=True,
            )
            guard_generation_provider_boundary(request, provider=provider)
            provider_state["submit_started"] = True
            provider_state["status"] = "submitting"
            provider_state["idempotency_key"] = case["idempotency_key"]
            manifest["events"].append(
                {
                    "at": _timestamp(clock()),
                    "type": "diagnostic_submit_started",
                    "case_id": case["case_id"],
                    "idempotency_key": case["idempotency_key"],
                }
            )
            store.save(manifest)
            job = provider.submit(request, idempotency_key=case["idempotency_key"])
            _apply_job(manifest, job)
            manifest["events"].append(
                {
                    "at": _timestamp(clock()),
                    "type": "diagnostic_provider_job_recorded",
                    "job_id": job.job_id,
                }
            )
            store.save(manifest)

        if manifest["status"] in {"provider_completed", "failed"}:
            if manifest["status"] == "provider_completed":
                store.record_cost_once(manifest)
            return (
                _mark_manual_review(
                    manifest,
                    store=store,
                    authorization=authorization,
                    case=case,
                    reason="diagnostic_outputs_require_human_quality_review",
                ),
                not created,
            )
        if time.monotonic() - started >= timeout_seconds:
            raise TimeoutError(
                f"Diagnostic provider job did not finish within {timeout_seconds} seconds"
            )
        time.sleep(poll_interval_seconds)


def execute_diagnostic_pilot_bundle(
    bundle: Mapping[str, Any],
    *,
    provider: GenerationProvider,
    store: RunStore,
    timeout_seconds: float = 1200,
    poll_interval_seconds: float = 3,
    clock: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """Execute at most two cases sequentially with zero automatic repair."""

    if getattr(provider, "name", None) != DIAGNOSTIC_PROVIDER:
        raise ValueError("Diagnostic execution requires HiggsfieldProvider")
    validated = validate_diagnostic_pilot_bundle(
        bundle,
        now=clock(),
        require_fresh=False,
    )
    results: list[dict[str, Any]] = []
    spent_or_reserved = 0.0
    for entry in validated["requests"]:
        request = entry["request"]
        authorization, case = validate_diagnostic_pilot_request(
            request,
            provider_name=provider.name,
            now=clock(),
            require_fresh=False,
        )
        quoted = float(case["quote"]["quoted_credits"])
        if spent_or_reserved + quoted > MAXIMUM_DIAGNOSTIC_TOTAL_CREDITS:
            raise DiagnosticPilotError("Next case would exceed the 4-credit diagnostic cap")
        manifest, reused = execute_diagnostic_pilot_case(
            request,
            provider=provider,
            store=store,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            clock=clock,
        )
        actual = manifest["cost"].get("actual_credits")
        charged = quoted if actual is None else _finite_credits(
            actual, field=f"actual credits for {case['case_id']}"
        )
        spent_or_reserved += charged
        budget_violation = (
            charged > MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE
            or spent_or_reserved > MAXIMUM_DIAGNOSTIC_TOTAL_CREDITS
        )
        if budget_violation:
            manifest["metrics"]["diagnostic_pilot"]["reason"] = (
                "provider_cost_exceeded_diagnostic_authorization"
            )
            store.save(manifest)
        results.append(
            {
                "case_id": case["case_id"],
                "run_request_hash": manifest["request_hash"],
                "provider_job_id": manifest["provider"].get("job_id"),
                "provider_status": manifest["provider"].get("status"),
                "actual_or_reserved_credits": charged,
                "reused": reused,
                "result_disposition": DIAGNOSTIC_RESULT_DISPOSITION,
                "production_readiness_eligible": False,
            }
        )
        if budget_violation:
            break
    return {
        "schema_version": "1.0.0",
        "artifact_type": "v3_diagnostic_paid_pilot_execution_result",
        "pilot_id": validated["pilot_id"],
        "authorization_sha256": validated["authorization_sha256"],
        "case_results": results,
        "case_count": len(results),
        "actual_or_reserved_credits": spent_or_reserved,
        "automatic_paid_repair_attempts": 0,
        "result_disposition": DIAGNOSTIC_RESULT_DISPOSITION,
        "production_readiness_eligible": False,
    }
