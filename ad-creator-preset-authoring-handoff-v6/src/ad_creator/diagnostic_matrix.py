from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .diagnostic_pilot import (
    DIAGNOSTIC_PROVIDER,
    MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE,
    _canonical_sha256,
    _finite_credits,
    _is_sha256,
    _timestamp,
    _utc,
    validate_diagnostic_base_request,
)
from .generation_inputs import ordered_image_inputs
from .paid_readiness import (
    MAXIMUM_FUTURE_CLOCK_SKEW_SECONDS,
    V3_DIAGNOSTIC_AUTHORIZATION_FIELD,
    V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD,
    build_provider_quote,
    guard_generation_provider_boundary,
    validate_provider_quote,
)
from .providers.base import GenerationProvider, ProviderJob
from .runs import request_hash


MATRIX_AUTHORIZATION_SCHEMA_VERSION = "1.0.0"
MATRIX_BUNDLE_SCHEMA_VERSION = "1.0.0"
MATRIX_EXECUTION_SCHEMA_VERSION = "1.0.0"
MATRIX_AUTHORIZATION_TYPE = "v3_diagnostic_paid_matrix_authorization"
MATRIX_BUNDLE_TYPE = "v3_diagnostic_paid_matrix_bundle"
MATRIX_EXECUTION_TYPE = "v3_diagnostic_paid_matrix_execution_state"
MATRIX_RESULT_TYPE = "v3_diagnostic_paid_matrix_execution_result"
MATRIX_PURPOSE = "v3_diagnostic_4_product_x_5_reference_quality_matrix"
MATRIX_EXTERNAL_UPLOAD_CONFIRMATION = (
    "I_CONFIRM_4_EXACT_PRODUCT_IMAGES_X_5_REFERENCE_CONTRACTS_WILL_CREATE_"
    "20_HIGGSFIELD_JOBS_MAX_40_CREDITS"
)
MATRIX_PRODUCT_COUNT = 4
MATRIX_REFERENCE_COUNT = 5
MATRIX_CASE_COUNT = MATRIX_PRODUCT_COUNT * MATRIX_REFERENCE_COUNT
MATRIX_MAXIMUM_TOTAL_CREDITS = 40.0
MATRIX_MAXIMUM_CREDITS_PER_CASE = MAXIMUM_DIAGNOSTIC_CREDITS_PER_CASE
MATRIX_MAXIMUM_AUTHORIZATION_TTL_SECONDS = 15 * 60
MATRIX_RESULT_DISPOSITION = "manual_review"


class DiagnosticMatrixError(RuntimeError):
    """A 4x5 diagnostic matrix contract or execution was rejected."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def diagnostic_matrix_base_request(request: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(request))
    value.pop(V3_DIAGNOSTIC_AUTHORIZATION_FIELD, None)
    value.pop(V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD, None)
    return value


def diagnostic_matrix_request_hash(request: Mapping[str, Any]) -> str:
    """Hash canonical request fields plus the exact bytes of its product image."""

    return request_hash(diagnostic_matrix_base_request(request))


def validate_diagnostic_matrix_base_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Require one exact product image and metadata-only reference control."""

    value = diagnostic_matrix_base_request(request)
    validate_diagnostic_base_request(value)
    generation = value["generation"]
    image_inputs = ordered_image_inputs(generation, allow_legacy=False)
    if len(image_inputs) != 1 or image_inputs[0]["role"] != "product_source":
        raise ValueError(
            "Matrix diagnostic requires exactly one product_source provider input"
        )
    products = value.get("products")
    if not isinstance(products, list) or len(products) != 1:
        raise ValueError("Matrix diagnostic requires exactly one exact product")
    product = products[0]
    if not isinstance(product, Mapping):
        raise ValueError("Matrix diagnostic product must be an object")
    product_id = product.get("product_id")
    if product_id != image_inputs[0].get("product_id"):
        raise ValueError("Matrix diagnostic product_id differs from image input")
    source_path = Path(image_inputs[0]["path"]).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"Matrix product image does not exist: {source_path}")
    if product.get("source_image") != image_inputs[0]["path"]:
        raise ValueError("Matrix ProductSpec source_image must match image input")

    reference = value.get("reference_analysis_contract")
    if not isinstance(reference, Mapping):
        raise ValueError("Matrix diagnostic requires reference_analysis_contract")
    reference_id = reference.get("asset_id")
    contract_sha256 = reference.get("sha256")
    if not isinstance(reference_id, str) or not reference_id.strip():
        raise ValueError("Matrix reference asset_id is required")
    if not _is_sha256(contract_sha256):
        raise ValueError("Matrix reference contract sha256 is invalid")
    if reference.get("status") not in {"draft", "published"}:
        raise ValueError("Matrix reference status must be draft or published")

    scene_graph = value.get("scene_graph_contract")
    if not isinstance(scene_graph, Mapping) or scene_graph.get("asset_id") != reference_id:
        raise ValueError("Matrix scene graph is bound to another reference")
    if scene_graph.get("runtime_reference_pixels_submitted") is not False:
        raise ValueError("Matrix diagnostic forbids runtime reference pixels")
    resolved = value.get("resolved_visual_contract")
    if not isinstance(resolved, Mapping):
        raise ValueError("Matrix diagnostic requires resolved_visual_contract")
    if resolved.get("reference_asset_id") != reference_id:
        raise ValueError("Matrix resolved visual contract uses another reference")
    if resolved.get("reference_contract_sha256") != contract_sha256:
        raise ValueError("Matrix resolved visual contract hash differs from reference")

    if value.get("reference_control_board_manifest") is not None:
        raise ValueError("Matrix diagnostic forbids reference control boards")
    if any(item["role"] != "product_source" for item in image_inputs):
        raise ValueError("Matrix diagnostic forbids reference images and material boards")
    return value


def _matrix_idempotency_key(
    *, matrix_id: str, case_id: str, request_sha256: str
) -> str:
    # Quote and authorization timestamps are intentionally excluded so a
    # renewed short-lived bundle can reconcile, never duplicate, a prior job.
    return _canonical_sha256(
        {
            "purpose": MATRIX_PURPOSE,
            "matrix_id": matrix_id,
            "case_id": case_id,
            "request_sha256": request_sha256,
        }
    )


def _request_case_record(case_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    value = validate_diagnostic_matrix_base_request(request)
    product = value["products"][0]
    source_path = Path(value["generation"]["image_inputs"][0]["path"]).expanduser()
    reference = value["reference_analysis_contract"]
    return {
        "case_id": case_id,
        "product_id": product["product_id"],
        "product_source_sha256": _sha256_file(source_path),
        "reference_id": reference["asset_id"],
        "reference_contract_sha256": reference["sha256"],
        "request_sha256": diagnostic_matrix_request_hash(value),
        "prompt_sha256": _prompt_sha256(value["generation"]["prompt"]),
    }


def analyze_diagnostic_matrix(
    requests: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(requests, Mapping) or len(requests) != MATRIX_CASE_COUNT:
        raise ValueError("Matrix diagnostic requires exactly 20 requests")
    records: list[dict[str, Any]] = []
    for case_id, request in requests.items():
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Every matrix case requires a non-empty case_id")
        records.append(_request_case_record(case_id, request))

    products: dict[str, dict[str, str]] = {}
    product_ids: dict[str, str] = {}
    references: dict[str, dict[str, str]] = {}
    pairs: set[tuple[str, str]] = set()
    for record in records:
        source_sha = record["product_source_sha256"]
        product_id = record["product_id"]
        previous_source = product_ids.get(product_id)
        if previous_source is not None and previous_source != source_sha:
            raise ValueError("One matrix product_id is bound to different source bytes")
        product_ids[product_id] = source_sha
        existing_product = products.get(source_sha)
        descriptor = {"product_id": product_id, "source_sha256": source_sha}
        if existing_product is not None and existing_product != descriptor:
            raise ValueError("One product source is bound to different product IDs")
        products.setdefault(source_sha, descriptor)

        reference_id = record["reference_id"]
        reference_sha = record["reference_contract_sha256"]
        descriptor_ref = {
            "reference_id": reference_id,
            "contract_sha256": reference_sha,
        }
        existing_reference = references.get(reference_id)
        if existing_reference is not None and existing_reference != descriptor_ref:
            raise ValueError("One matrix reference_id has different contract hashes")
        references.setdefault(reference_id, descriptor_ref)
        pair = (source_sha, reference_id)
        if pair in pairs:
            raise ValueError("Matrix contains a duplicate product/reference pair")
        pairs.add(pair)

    if len(products) != MATRIX_PRODUCT_COUNT:
        raise ValueError("Matrix diagnostic requires four distinct product source images")
    if len(references) != MATRIX_REFERENCE_COUNT:
        raise ValueError("Matrix diagnostic requires five distinct reference contracts")
    expected_pairs = {
        (source_sha, reference_id)
        for source_sha in products
        for reference_id in references
    }
    if pairs != expected_pairs:
        raise ValueError("Matrix requests must be the complete 4x5 cross product")

    product_rows = list(products.values())
    reference_rows = list(references.values())
    matrix_contract: dict[str, Any] = {
        "product_count": MATRIX_PRODUCT_COUNT,
        "reference_count": MATRIX_REFERENCE_COUNT,
        "case_count": MATRIX_CASE_COUNT,
        "products": product_rows,
        "references": reference_rows,
        "case_order": [record["case_id"] for record in records],
        "pairs": [
            {
                "case_id": record["case_id"],
                "product_source_sha256": record["product_source_sha256"],
                "reference_id": record["reference_id"],
            }
            for record in records
        ],
    }
    matrix_contract["matrix_sha256"] = _canonical_sha256(matrix_contract)
    return matrix_contract, records


def _expected_execution_policy() -> dict[str, Any]:
    return {
        "product_count": MATRIX_PRODUCT_COUNT,
        "reference_count": MATRIX_REFERENCE_COUNT,
        "maximum_cases": MATRIX_CASE_COUNT,
        "maximum_total_credits": MATRIX_MAXIMUM_TOTAL_CREDITS,
        "maximum_credits_per_case": MATRIX_MAXIMUM_CREDITS_PER_CASE,
        "inputs_per_case": 1,
        "input_roles": ["product_source"],
        "reference_pixels_submitted": False,
        "control_boards_submitted": False,
        "raw_crops_submitted": False,
        "automatic_paid_repair": False,
        "maximum_auto_repairs": 0,
        "material_arm": "structured_only",
        "execution_order": "sequential",
        "stop_on_provider_failure": True,
        "stop_on_actual_cost_overrun": True,
        "result_disposition": MATRIX_RESULT_DISPOSITION,
        "production_readiness_eligible": False,
    }


def build_diagnostic_matrix_authorization(
    *,
    matrix_id: str,
    requests: Mapping[str, Mapping[str, Any]],
    provider_quotes: Mapping[str, Mapping[str, Any]],
    external_upload_confirmed: bool,
    confirmation_statement: str = MATRIX_EXTERNAL_UPLOAD_CONFIRMATION,
    issued_at: datetime | str | None = None,
    ttl_seconds: int = MATRIX_MAXIMUM_AUTHORIZATION_TTL_SECONDS,
) -> dict[str, Any]:
    if not isinstance(matrix_id, str) or not matrix_id.strip():
        raise ValueError("Matrix diagnostic matrix_id is required")
    matrix_contract, records = analyze_diagnostic_matrix(requests)
    if set(requests) != set(provider_quotes):
        raise ValueError("Every matrix case requires exactly one provider quote")
    if external_upload_confirmed is not True:
        raise ValueError("Matrix diagnostic requires explicit external-upload confirmation")
    if confirmation_statement != MATRIX_EXTERNAL_UPLOAD_CONFIRMATION:
        raise ValueError("Matrix external-upload confirmation statement does not match")
    if (
        not isinstance(ttl_seconds, int)
        or isinstance(ttl_seconds, bool)
        or not 1 <= ttl_seconds <= MATRIX_MAXIMUM_AUTHORIZATION_TTL_SECONDS
    ):
        raise ValueError("Matrix authorization TTL must be between 1 and 900 seconds")

    issued = _utc(issued_at, field="issued_at")
    expires = issued + timedelta(seconds=ttl_seconds)
    cases: list[dict[str, Any]] = []
    total = 0.0
    for record in records:
        case_id = record["case_id"]
        quote = validate_provider_quote(provider_quotes[case_id], now=issued)
        if quote["case_id"] != case_id:
            raise ValueError("Provider quote case_id differs from matrix case")
        if quote["request_sha256"] != record["request_sha256"]:
            raise ValueError("Provider quote is bound to another matrix request")
        if quote["provider"] != DIAGNOSTIC_PROVIDER:
            raise ValueError("Matrix quote is bound to another provider")
        credits = float(quote["quoted_credits"])
        if credits <= 0 or credits > MATRIX_MAXIMUM_CREDITS_PER_CASE:
            raise ValueError("Every matrix quote must be within (0, 2] credits")
        estimated = float(requests[case_id]["generation"]["estimated_credits"])
        if abs(estimated - credits) > 1e-9:
            raise ValueError("Matrix request estimate must equal its fresh provider quote")
        if _utc(quote["expires_at"], field="quote.expires_at") < expires:
            raise ValueError("Provider quote expires before matrix authorization")
        total += credits
        cases.append(
            {
                **record,
                "quote": copy.deepcopy(quote),
                "quote_sha256": quote["quote_sha256"],
                "idempotency_key": _matrix_idempotency_key(
                    matrix_id=matrix_id,
                    case_id=case_id,
                    request_sha256=record["request_sha256"],
                ),
            }
        )
    if total > MATRIX_MAXIMUM_TOTAL_CREDITS:
        raise ValueError("Matrix provider quotes exceed the 40-credit cap")

    request_hashes = {case["case_id"]: case["request_sha256"] for case in cases}
    prompt_hashes = {case["case_id"]: case["prompt_sha256"] for case in cases}
    quote_hashes = {case["case_id"]: case["quote_sha256"] for case in cases}
    authorization: dict[str, Any] = {
        "schema_version": MATRIX_AUTHORIZATION_SCHEMA_VERSION,
        "artifact_type": MATRIX_AUTHORIZATION_TYPE,
        "purpose": MATRIX_PURPOSE,
        "matrix_id": matrix_id,
        "authorized": True,
        "provider": DIAGNOSTIC_PROVIDER,
        "issued_at": _timestamp(issued),
        "expires_at": _timestamp(expires),
        "ttl_seconds": ttl_seconds,
        "external_upload_confirmation": {
            "confirmed": True,
            "statement": MATRIX_EXTERNAL_UPLOAD_CONFIRMATION,
            "confirmed_at": _timestamp(issued),
            "request_set_sha256": _canonical_sha256(request_hashes),
            "matrix_sha256": matrix_contract["matrix_sha256"],
        },
        "execution_policy": _expected_execution_policy(),
        "matrix_contract": matrix_contract,
        "case_count": len(cases),
        "quoted_credits": total,
        "request_set_sha256": _canonical_sha256(request_hashes),
        "prompt_set_sha256": _canonical_sha256(prompt_hashes),
        "quote_set_sha256": _canonical_sha256(quote_hashes),
        "cases": cases,
    }
    authorization["authorization_sha256"] = _canonical_sha256(authorization)
    validate_diagnostic_matrix_authorization(authorization, now=issued)
    return authorization


def validate_diagnostic_matrix_authorization(
    authorization: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(authorization, Mapping):
        raise ValueError("Matrix authorization must be an object")
    value = copy.deepcopy(dict(authorization))
    expected_fields = {
        "schema_version",
        "artifact_type",
        "purpose",
        "matrix_id",
        "authorized",
        "provider",
        "issued_at",
        "expires_at",
        "ttl_seconds",
        "external_upload_confirmation",
        "execution_policy",
        "matrix_contract",
        "case_count",
        "quoted_credits",
        "request_set_sha256",
        "prompt_set_sha256",
        "quote_set_sha256",
        "cases",
        "authorization_sha256",
    }
    if set(value) != expected_fields:
        raise ValueError("Matrix authorization has unknown or missing fields")
    if value.get("schema_version") != MATRIX_AUTHORIZATION_SCHEMA_VERSION:
        raise ValueError("Unsupported matrix authorization schema")
    if value.get("artifact_type") != MATRIX_AUTHORIZATION_TYPE:
        raise ValueError("Matrix authorization has wrong artifact_type")
    if value.get("purpose") != MATRIX_PURPOSE or value.get("authorized") is not True:
        raise ValueError("Matrix diagnostic was not explicitly authorized")
    if value.get("provider") != DIAGNOSTIC_PROVIDER:
        raise ValueError("Matrix diagnostic is restricted to higgsfield_cli")
    if not isinstance(value.get("matrix_id"), str) or not value["matrix_id"].strip():
        raise ValueError("Matrix authorization requires matrix_id")
    declared_hash = value.get("authorization_sha256")
    stable = copy.deepcopy(value)
    stable.pop("authorization_sha256", None)
    if not _is_sha256(declared_hash) or declared_hash != _canonical_sha256(stable):
        raise ValueError("Matrix authorization hash does not match its contents")

    ttl = value.get("ttl_seconds")
    if (
        not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or not 1 <= ttl <= MATRIX_MAXIMUM_AUTHORIZATION_TTL_SECONDS
    ):
        raise ValueError("Matrix authorization TTL is outside 1..900 seconds")
    issued = _utc(value.get("issued_at"), field="authorization.issued_at")
    expires = _utc(value.get("expires_at"), field="authorization.expires_at")
    if expires != issued + timedelta(seconds=ttl):
        raise ValueError("Matrix authorization expiry differs from TTL")
    current = _utc(now, field="now")
    if issued > current + timedelta(seconds=MAXIMUM_FUTURE_CLOCK_SKEW_SECONDS):
        raise ValueError("Matrix authorization was issued in the future")
    if require_fresh and current >= expires:
        raise ValueError("Matrix authorization has expired")
    if value.get("execution_policy") != _expected_execution_policy():
        raise ValueError("Matrix execution policy was altered")

    matrix_contract = value.get("matrix_contract")
    if not isinstance(matrix_contract, Mapping):
        raise ValueError("Matrix contract must be an object")
    if set(matrix_contract) != {
        "product_count",
        "reference_count",
        "case_count",
        "products",
        "references",
        "case_order",
        "pairs",
        "matrix_sha256",
    }:
        raise ValueError("Matrix contract has unknown or missing fields")
    declared_matrix_hash = matrix_contract.get("matrix_sha256")
    stable_matrix = copy.deepcopy(dict(matrix_contract))
    stable_matrix.pop("matrix_sha256", None)
    if not _is_sha256(declared_matrix_hash) or declared_matrix_hash != _canonical_sha256(
        stable_matrix
    ):
        raise ValueError("Matrix contract hash does not match its contents")
    if (
        matrix_contract.get("product_count") != MATRIX_PRODUCT_COUNT
        or matrix_contract.get("reference_count") != MATRIX_REFERENCE_COUNT
        or matrix_contract.get("case_count") != MATRIX_CASE_COUNT
    ):
        raise ValueError("Matrix contract must describe exactly 4x5=20 cases")
    products = matrix_contract.get("products")
    references = matrix_contract.get("references")
    pairs = matrix_contract.get("pairs")
    case_order = matrix_contract.get("case_order")
    if not isinstance(products, list) or len(products) != MATRIX_PRODUCT_COUNT:
        raise ValueError("Matrix contract requires four products")
    if not isinstance(references, list) or len(references) != MATRIX_REFERENCE_COUNT:
        raise ValueError("Matrix contract requires five references")
    if not isinstance(pairs, list) or len(pairs) != MATRIX_CASE_COUNT:
        raise ValueError("Matrix contract requires twenty pairs")
    if not isinstance(case_order, list) or len(case_order) != MATRIX_CASE_COUNT:
        raise ValueError("Matrix contract requires twenty ordered case IDs")

    product_sources: set[str] = set()
    product_ids: set[str] = set()
    for product in products:
        if not isinstance(product, Mapping) or set(product) != {
            "product_id",
            "source_sha256",
        }:
            raise ValueError("Matrix product descriptor is invalid")
        if not isinstance(product["product_id"], str) or not product["product_id"].strip():
            raise ValueError("Matrix product_id is invalid")
        if not _is_sha256(product["source_sha256"]):
            raise ValueError("Matrix product source hash is invalid")
        product_ids.add(product["product_id"])
        product_sources.add(product["source_sha256"])
    if len(product_ids) != MATRIX_PRODUCT_COUNT or len(product_sources) != MATRIX_PRODUCT_COUNT:
        raise ValueError("Matrix products must have distinct IDs and source bytes")

    reference_ids: set[str] = set()
    for reference in references:
        if not isinstance(reference, Mapping) or set(reference) != {
            "reference_id",
            "contract_sha256",
        }:
            raise ValueError("Matrix reference descriptor is invalid")
        if not isinstance(reference["reference_id"], str) or not reference["reference_id"].strip():
            raise ValueError("Matrix reference_id is invalid")
        if not _is_sha256(reference["contract_sha256"]):
            raise ValueError("Matrix reference contract hash is invalid")
        reference_ids.add(reference["reference_id"])
    if len(reference_ids) != MATRIX_REFERENCE_COUNT:
        raise ValueError("Matrix reference IDs must be distinct")

    observed_pairs: set[tuple[str, str]] = set()
    observed_pair_ids: list[str] = []
    for pair in pairs:
        if not isinstance(pair, Mapping) or set(pair) != {
            "case_id",
            "product_source_sha256",
            "reference_id",
        }:
            raise ValueError("Matrix pair descriptor is invalid")
        if pair["product_source_sha256"] not in product_sources:
            raise ValueError("Matrix pair uses an unknown product")
        if pair["reference_id"] not in reference_ids:
            raise ValueError("Matrix pair uses an unknown reference")
        observed_pairs.add((pair["product_source_sha256"], pair["reference_id"]))
        observed_pair_ids.append(pair["case_id"])
    expected_pairs = {
        (source_sha, reference_id)
        for source_sha in product_sources
        for reference_id in reference_ids
    }
    if observed_pairs != expected_pairs or observed_pair_ids != case_order:
        raise ValueError("Matrix contract is not the ordered complete cross product")

    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != MATRIX_CASE_COUNT:
        raise ValueError("Matrix authorization requires exactly twenty cases")
    if value.get("case_count") != MATRIX_CASE_COUNT:
        raise ValueError("Matrix authorization case_count must be twenty")
    request_hashes: dict[str, str] = {}
    prompt_hashes: dict[str, str] = {}
    quote_hashes: dict[str, str] = {}
    total = 0.0
    reference_sha_by_id = {
        item["reference_id"]: item["contract_sha256"] for item in references
    }
    product_id_by_sha = {item["source_sha256"]: item["product_id"] for item in products}
    for expected_case_id, case in zip(case_order, cases, strict=True):
        if not isinstance(case, Mapping) or set(case) != {
            "case_id",
            "product_id",
            "product_source_sha256",
            "reference_id",
            "reference_contract_sha256",
            "request_sha256",
            "prompt_sha256",
            "quote",
            "quote_sha256",
            "idempotency_key",
        }:
            raise ValueError("Matrix case authorization is invalid")
        case_id = case.get("case_id")
        if case_id != expected_case_id or case_id in request_hashes:
            raise ValueError("Matrix case order or uniqueness differs from contract")
        if case.get("product_id") != product_id_by_sha.get(
            case.get("product_source_sha256")
        ):
            raise ValueError("Matrix case product binding differs from contract")
        if case.get("reference_contract_sha256") != reference_sha_by_id.get(
            case.get("reference_id")
        ):
            raise ValueError("Matrix case reference binding differs from contract")
        if not _is_sha256(case.get("request_sha256")) or not _is_sha256(
            case.get("prompt_sha256")
        ):
            raise ValueError("Matrix case request/prompt hash is invalid")
        expected_idempotency = _matrix_idempotency_key(
            matrix_id=value["matrix_id"],
            case_id=case_id,
            request_sha256=case["request_sha256"],
        )
        if case.get("idempotency_key") != expected_idempotency:
            raise ValueError("Matrix idempotency binding was altered")
        quote = validate_provider_quote(
            case.get("quote", {}),
            now=current if require_fresh else issued,
        )
        if (
            quote["case_id"] != case_id
            or quote["request_sha256"] != case["request_sha256"]
            or quote["provider"] != DIAGNOSTIC_PROVIDER
            or case.get("quote_sha256") != quote["quote_sha256"]
        ):
            raise ValueError("Matrix case and provider quote bindings differ")
        credits = float(quote["quoted_credits"])
        if credits <= 0 or credits > MATRIX_MAXIMUM_CREDITS_PER_CASE:
            raise ValueError("Matrix case quote exceeds the 2-credit cap")
        total += credits
        request_hashes[case_id] = case["request_sha256"]
        prompt_hashes[case_id] = case["prompt_sha256"]
        quote_hashes[case_id] = quote["quote_sha256"]
    if total > MATRIX_MAXIMUM_TOTAL_CREDITS:
        raise ValueError("Matrix authorization exceeds the 40-credit cap")
    if abs(total - _finite_credits(value.get("quoted_credits"), field="quoted_credits")) > 1e-9:
        raise ValueError("Matrix quoted_credits differs from case quotes")
    request_set_sha256 = _canonical_sha256(request_hashes)
    if value.get("request_set_sha256") != request_set_sha256:
        raise ValueError("Matrix request-set hash differs from cases")
    if value.get("prompt_set_sha256") != _canonical_sha256(prompt_hashes):
        raise ValueError("Matrix prompt-set hash differs from cases")
    if value.get("quote_set_sha256") != _canonical_sha256(quote_hashes):
        raise ValueError("Matrix quote-set hash differs from cases")
    expected_confirmation = {
        "confirmed": True,
        "statement": MATRIX_EXTERNAL_UPLOAD_CONFIRMATION,
        "confirmed_at": value["issued_at"],
        "request_set_sha256": request_set_sha256,
        "matrix_sha256": declared_matrix_hash,
    }
    if value.get("external_upload_confirmation") != expected_confirmation:
        raise ValueError("Matrix external-upload confirmation is absent or altered")
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
        raise ValueError("Matrix request is not uniquely authorized")
    return matches[0]


def validate_diagnostic_matrix_request(
    request: Mapping[str, Any],
    *,
    provider_name: str,
    now: datetime | str | None = None,
    require_fresh: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if provider_name != DIAGNOSTIC_PROVIDER:
        raise ValueError("Matrix authorization cannot be used with another provider")
    if V3_DIAGNOSTIC_AUTHORIZATION_FIELD in request:
        raise ValueError("A request cannot combine pilot and matrix authorizations")
    if V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD not in request:
        raise ValueError("Matrix request has no authorization envelope")
    base = validate_diagnostic_matrix_base_request(request)
    authorization = validate_diagnostic_matrix_authorization(
        request[V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD],
        now=now,
        require_fresh=require_fresh,
    )
    case = _case_by_request_hash(authorization, request_hash(base))
    observed = _request_case_record(case["case_id"], base)
    for field in (
        "product_id",
        "product_source_sha256",
        "reference_id",
        "reference_contract_sha256",
        "request_sha256",
        "prompt_sha256",
    ):
        if observed[field] != case[field]:
            raise ValueError(f"Matrix request {field} differs from authorization")
    estimated = float(base["generation"]["estimated_credits"])
    if abs(estimated - float(case["quote"]["quoted_credits"])) > 1e-9:
        raise ValueError("Matrix request cost differs from its authorized quote")
    return authorization, case


def attach_diagnostic_matrix_authorization(
    request: Mapping[str, Any], authorization: Mapping[str, Any]
) -> dict[str, Any]:
    value = diagnostic_matrix_base_request(request)
    validated = validate_diagnostic_matrix_authorization(authorization)
    case = _case_by_request_hash(validated, request_hash(value))
    observed = _request_case_record(case["case_id"], value)
    if observed["prompt_sha256"] != case["prompt_sha256"]:
        raise ValueError("Matrix prompt bytes differ from authorization")
    value[V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD] = copy.deepcopy(validated)
    return value


def build_diagnostic_matrix_bundle(
    *,
    requests: Mapping[str, Mapping[str, Any]],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_diagnostic_matrix_authorization(authorization)
    expected_ids = [case["case_id"] for case in validated["cases"]]
    if list(requests) != expected_ids:
        raise ValueError("Matrix bundle request order differs from authorization")
    entries: list[dict[str, Any]] = []
    for case_id, request in requests.items():
        attached = attach_diagnostic_matrix_authorization(request, validated)
        _, case = validate_diagnostic_matrix_request(
            attached,
            provider_name=DIAGNOSTIC_PROVIDER,
        )
        if case["case_id"] != case_id:
            raise ValueError("Matrix request is stored under another case_id")
        entries.append({"case_id": case_id, "request": attached})
    bundle: dict[str, Any] = {
        "schema_version": MATRIX_BUNDLE_SCHEMA_VERSION,
        "artifact_type": MATRIX_BUNDLE_TYPE,
        "matrix_id": validated["matrix_id"],
        "matrix_sha256": validated["matrix_contract"]["matrix_sha256"],
        "authorization_sha256": validated["authorization_sha256"],
        "requests": entries,
    }
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    return validate_diagnostic_matrix_bundle(bundle)


def validate_diagnostic_matrix_bundle(
    bundle: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(bundle, Mapping):
        raise ValueError("Matrix bundle must be an object")
    value = copy.deepcopy(dict(bundle))
    if set(value) != {
        "schema_version",
        "artifact_type",
        "matrix_id",
        "matrix_sha256",
        "authorization_sha256",
        "requests",
        "bundle_sha256",
    }:
        raise ValueError("Matrix bundle has unknown or missing fields")
    if value.get("schema_version") != MATRIX_BUNDLE_SCHEMA_VERSION:
        raise ValueError("Unsupported matrix bundle schema")
    if value.get("artifact_type") != MATRIX_BUNDLE_TYPE:
        raise ValueError("Matrix bundle has wrong artifact_type")
    declared_hash = value.get("bundle_sha256")
    stable = copy.deepcopy(value)
    stable.pop("bundle_sha256", None)
    if not _is_sha256(declared_hash) or declared_hash != _canonical_sha256(stable):
        raise ValueError("Matrix bundle hash does not match its contents")
    entries = value.get("requests")
    if not isinstance(entries, list) or len(entries) != MATRIX_CASE_COUNT:
        raise ValueError("Matrix bundle requires exactly twenty requests")

    authorization: dict[str, Any] | None = None
    expected_ids: list[str] | None = None
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"case_id", "request"}:
            raise ValueError("Matrix bundle request entry is invalid")
        if not isinstance(entry.get("request"), Mapping):
            raise ValueError("Matrix bundle request must be an object")
        candidate, case = validate_diagnostic_matrix_request(
            entry["request"],
            provider_name=DIAGNOSTIC_PROVIDER,
            now=now,
            require_fresh=require_fresh,
        )
        if entry.get("case_id") != case["case_id"]:
            raise ValueError("Matrix bundle case_id differs from authorization")
        if authorization is None:
            authorization = candidate
            expected_ids = [item["case_id"] for item in candidate["cases"]]
        elif candidate["authorization_sha256"] != authorization["authorization_sha256"]:
            raise ValueError("Matrix bundle contains different authorizations")
    observed_ids = [entry["case_id"] for entry in entries]
    if observed_ids != expected_ids:
        raise ValueError("Matrix bundle is incomplete or reordered")
    assert authorization is not None
    if value.get("matrix_id") != authorization["matrix_id"]:
        raise ValueError("Matrix bundle matrix_id differs from authorization")
    if value.get("matrix_sha256") != authorization["matrix_contract"]["matrix_sha256"]:
        raise ValueError("Matrix bundle contract hash differs")
    if value.get("authorization_sha256") != authorization["authorization_sha256"]:
        raise ValueError("Matrix bundle authorization hash differs")
    return value


def preflight_diagnostic_matrix(
    *,
    matrix_id: str,
    requests: Mapping[str, Mapping[str, Any]],
    provider: Any,
    external_upload_confirmed: bool,
    issued_at: datetime | str | None = None,
    ttl_seconds: int = MATRIX_MAXIMUM_AUTHORIZATION_TTL_SECONDS,
) -> dict[str, Any]:
    """Quote all twenty cases; no generation or repair call occurs here."""

    if getattr(provider, "name", None) != DIAGNOSTIC_PROVIDER:
        raise ValueError("Matrix preflight requires HiggsfieldProvider")
    analyze_diagnostic_matrix(requests)
    issued = _utc(issued_at, field="issued_at")
    quotes: dict[str, dict[str, Any]] = {}
    for case_id, request in requests.items():
        quoted = _finite_credits(
            provider.estimate_cost(diagnostic_matrix_base_request(request)),
            field=f"provider quote for {case_id}",
        )
        quotes[case_id] = build_provider_quote(
            case_id=case_id,
            request_sha256=diagnostic_matrix_request_hash(request),
            provider=DIAGNOSTIC_PROVIDER,
            quoted_credits=quoted,
            quoted_at=issued,
            ttl_seconds=ttl_seconds,
        )
    authorization = build_diagnostic_matrix_authorization(
        matrix_id=matrix_id,
        requests=requests,
        provider_quotes=quotes,
        external_upload_confirmed=external_upload_confirmed,
        issued_at=issued,
        ttl_seconds=ttl_seconds,
    )
    return build_diagnostic_matrix_bundle(
        requests=requests,
        authorization=authorization,
    )


class MatrixExecutionStore:
    """Atomic, exclusively locked state used to resume the sequential matrix."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "matrix-state.json"
        self.lock_path = self.root / "matrix-state.lock"

    @contextmanager
    def exclusive(self):
        self.lock_path.touch(exist_ok=True)
        with self.lock_path.open("r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def load(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise DiagnosticMatrixError("Matrix execution state must be an object")
        declared = value.get("state_sha256")
        stable = copy.deepcopy(value)
        stable.pop("state_sha256", None)
        if not _is_sha256(declared) or declared != _canonical_sha256(stable):
            raise DiagnosticMatrixError("Matrix execution state hash does not match")
        return value

    def save(self, state: Mapping[str, Any]) -> None:
        value = copy.deepcopy(dict(state))
        value.pop("state_sha256", None)
        value["updated_at"] = _timestamp(_utc_now())
        value["state_sha256"] = _canonical_sha256(value)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)


def _new_execution_state(authorization: Mapping[str, Any]) -> dict[str, Any]:
    now = _timestamp(_utc_now())
    cases = {
        case["case_id"]: {
            "case_id": case["case_id"],
            "request_sha256": case["request_sha256"],
            "prompt_sha256": case["prompt_sha256"],
            "product_id": case["product_id"],
            "product_source_sha256": case["product_source_sha256"],
            "reference_id": case["reference_id"],
            "reference_contract_sha256": case["reference_contract_sha256"],
            "idempotency_key": case["idempotency_key"],
            "status": "pending",
            "provider_job_id": None,
            "provider_status": "not_submitted",
            "provider_output": None,
            "actual_or_reserved_credits": None,
            "reason": None,
        }
        for case in authorization["cases"]
    }
    return {
        "schema_version": MATRIX_EXECUTION_SCHEMA_VERSION,
        "artifact_type": MATRIX_EXECUTION_TYPE,
        "matrix_id": authorization["matrix_id"],
        "matrix_sha256": authorization["matrix_contract"]["matrix_sha256"],
        "request_set_sha256": authorization["request_set_sha256"],
        "provider": DIAGNOSTIC_PROVIDER,
        "case_order": [case["case_id"] for case in authorization["cases"]],
        "cases": cases,
        "authorization_history": [authorization["authorization_sha256"]],
        "actual_or_reserved_credits": 0.0,
        "automatic_paid_repair_attempts": 0,
        "result_disposition": MATRIX_RESULT_DISPOSITION,
        "production_readiness_eligible": False,
        "stop_reason": None,
        "created_at": now,
        "updated_at": now,
    }


def _bind_or_resume_state(
    state: dict[str, Any] | None, authorization: Mapping[str, Any]
) -> dict[str, Any]:
    if state is None:
        return _new_execution_state(authorization)
    expected = {
        "matrix_id": authorization["matrix_id"],
        "matrix_sha256": authorization["matrix_contract"]["matrix_sha256"],
        "request_set_sha256": authorization["request_set_sha256"],
        "provider": DIAGNOSTIC_PROVIDER,
        "case_order": [case["case_id"] for case in authorization["cases"]],
    }
    for field, value in expected.items():
        if state.get(field) != value:
            raise DiagnosticMatrixError(
                f"Existing matrix execution state has different {field}"
            )
    if state.get("automatic_paid_repair_attempts") != 0:
        raise DiagnosticMatrixError("Matrix execution state recorded a paid repair")
    history = state.setdefault("authorization_history", [])
    if authorization["authorization_sha256"] not in history:
        history.append(authorization["authorization_sha256"])
    if state.get("stop_reason") in {"authorization_expired", "provider_timeout"}:
        state["stop_reason"] = None
    return state


def _apply_provider_job(case_state: dict[str, Any], job: ProviderJob) -> None:
    if not isinstance(job, ProviderJob):
        raise TypeError("Matrix provider must return ProviderJob")
    case_state["provider_job_id"] = job.job_id
    case_state["provider_status"] = job.status
    if job.output_path is not None:
        case_state["provider_output"] = str(job.output_path.resolve())
    normalized = str(job.status).strip().casefold()
    if normalized in {"completed", "succeeded", "success"}:
        case_state["status"] = "provider_completed"
    elif normalized in {"failed", "error", "cancelled", "canceled"}:
        case_state["status"] = "provider_failed"
    elif normalized in {
        "queued",
        "pending",
        "created",
        "running",
        "in_progress",
        "processing",
    }:
        case_state["status"] = "running"
    else:
        raise DiagnosticMatrixError(f"Unsupported provider status: {job.status!r}")
    case_state["reported_actual_credits"] = job.actual_credits


def _case_result(case_state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(case_state.get(key))
        for key in (
            "case_id",
            "product_id",
            "reference_id",
            "status",
            "provider_job_id",
            "provider_status",
            "provider_output",
            "actual_or_reserved_credits",
            "reason",
        )
    }


def _execution_result(state: Mapping[str, Any]) -> dict[str, Any]:
    cases = [state["cases"][case_id] for case_id in state["case_order"]]
    generated = sum(
        case.get("status") == "manual_review"
        and case.get("provider_status") in {"completed", "succeeded", "success"}
        for case in cases
    )
    return {
        "schema_version": "1.0.0",
        "artifact_type": MATRIX_RESULT_TYPE,
        "matrix_id": state["matrix_id"],
        "matrix_sha256": state["matrix_sha256"],
        "case_results": [_case_result(case) for case in cases],
        "case_count": MATRIX_CASE_COUNT,
        "generated_case_count": generated,
        "remaining_case_count": sum(case.get("status") == "pending" for case in cases),
        "actual_or_reserved_credits": state["actual_or_reserved_credits"],
        "automatic_paid_repair_attempts": 0,
        "result_disposition": MATRIX_RESULT_DISPOSITION,
        "production_readiness_eligible": False,
        "stop_reason": state.get("stop_reason"),
    }


def execute_diagnostic_matrix_bundle(
    bundle: Mapping[str, Any],
    *,
    provider: GenerationProvider,
    store: MatrixExecutionStore,
    timeout_seconds: float = 1200,
    poll_interval_seconds: float = 3,
    clock: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """Run/reconcile the 20 cases in order; never repair or mark them passed."""

    if getattr(provider, "name", None) != DIAGNOSTIC_PROVIDER:
        raise ValueError("Matrix execution requires HiggsfieldProvider")
    if timeout_seconds <= 0 or poll_interval_seconds < 0:
        raise ValueError("Matrix timeout must be positive and poll interval non-negative")
    validated = validate_diagnostic_matrix_bundle(
        bundle,
        now=clock(),
        require_fresh=False,
    )
    authorization = validated["requests"][0]["request"][
        V3_MATRIX_DIAGNOSTIC_AUTHORIZATION_FIELD
    ]
    auth_by_case = {case["case_id"]: case for case in authorization["cases"]}
    request_by_case = {
        entry["case_id"]: entry["request"] for entry in validated["requests"]
    }

    with store.exclusive():
        state = _bind_or_resume_state(store.load(), authorization)
        store.save(state)
        permanent_stops = {
            "actual_cost_overrun",
            "provider_failed",
        }
        if state.get("stop_reason") in permanent_stops:
            return _execution_result(state)

        for case_id in state["case_order"]:
            case_state = state["cases"][case_id]
            if case_state["status"] == "manual_review":
                continue
            request = request_by_case[case_id]
            authorized_case = auth_by_case[case_id]
            quoted = float(authorized_case["quote"]["quoted_credits"])

            if case_state["status"] in {"submit_started", "submit_unknown"}:
                reconcile = getattr(provider, "find_by_idempotency_key", None)
                recovered = (
                    reconcile(case_state["idempotency_key"])
                    if callable(reconcile)
                    else None
                )
                if recovered is None:
                    case_state["status"] = "submit_unknown"
                    case_state["reason"] = "unknown_paid_submit_outcome"
                    state["stop_reason"] = "unknown_submit_outcome"
                    store.save(state)
                    return _execution_result(state)
                _apply_provider_job(case_state, recovered)
                store.save(state)

            if case_state["status"] == "pending":
                try:
                    validate_diagnostic_matrix_request(
                        request,
                        provider_name=provider.name,
                        now=clock(),
                        require_fresh=True,
                    )
                except ValueError as exc:
                    if "expired" in str(exc).casefold():
                        state["stop_reason"] = "authorization_expired"
                        store.save(state)
                        return _execution_result(state)
                    raise
                if (
                    state["actual_or_reserved_credits"] + quoted
                    > MATRIX_MAXIMUM_TOTAL_CREDITS
                ):
                    state["stop_reason"] = "actual_cost_overrun"
                    store.save(state)
                    return _execution_result(state)
                guard_generation_provider_boundary(request, provider=provider)
                case_state["status"] = "submit_started"
                case_state["reason"] = None
                store.save(state)
                try:
                    job = provider.submit(
                        request,
                        idempotency_key=case_state["idempotency_key"],
                    )
                except Exception as exc:
                    case_state["status"] = "submit_unknown"
                    case_state["reason"] = (
                        f"unknown_paid_submit_outcome:{type(exc).__name__}"
                    )
                    state["stop_reason"] = "unknown_submit_outcome"
                    store.save(state)
                    return _execution_result(state)
                _apply_provider_job(case_state, job)
                store.save(state)

            started = time.monotonic()
            while case_state["status"] == "running":
                if time.monotonic() - started >= timeout_seconds:
                    case_state["reason"] = "provider_poll_timeout"
                    state["stop_reason"] = "provider_timeout"
                    store.save(state)
                    return _execution_result(state)
                time.sleep(poll_interval_seconds)
                try:
                    job = provider.get(case_state["provider_job_id"])
                except Exception as exc:
                    case_state["reason"] = f"provider_status_unknown:{type(exc).__name__}"
                    state["stop_reason"] = "unknown_submit_outcome"
                    store.save(state)
                    return _execution_result(state)
                _apply_provider_job(case_state, job)
                store.save(state)

            reported_actual = case_state.pop("reported_actual_credits", None)
            if reported_actual is None:
                charged = quoted
            else:
                charged = _finite_credits(
                    reported_actual,
                    field=f"actual credits for {case_id}",
                )
                if charged < 0:
                    raise DiagnosticMatrixError("Provider actual credits cannot be negative")
            if case_state.get("actual_or_reserved_credits") is None:
                case_state["actual_or_reserved_credits"] = charged
                state["actual_or_reserved_credits"] += charged

            provider_failed = case_state["status"] == "provider_failed"
            overrun = (
                charged > MATRIX_MAXIMUM_CREDITS_PER_CASE
                or state["actual_or_reserved_credits"] > MATRIX_MAXIMUM_TOTAL_CREDITS
            )
            case_state["status"] = "manual_review"
            if provider_failed:
                case_state["reason"] = "provider_failed_stop_remaining_cases"
                state["stop_reason"] = "provider_failed"
            elif overrun:
                case_state["reason"] = "provider_cost_exceeded_matrix_authorization"
                state["stop_reason"] = "actual_cost_overrun"
            else:
                case_state["reason"] = "diagnostic_output_requires_human_quality_review"
                state["stop_reason"] = None
            store.save(state)
            if provider_failed or overrun:
                return _execution_result(state)

        state["stop_reason"] = "all_cases_generated_manual_review_required"
        store.save(state)
        return _execution_result(state)
