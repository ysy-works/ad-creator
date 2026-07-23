from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .paid_readiness import (
    MAXIMUM_QUOTE_TTL_SECONDS,
    PAID_READINESS_SCHEMA_VERSION,
    require_paid_execution_readiness,
    validate_provider_quote,
)


CAMPAIGN_SCHEMA_VERSION = "1.0.0"
INITIAL_ARMS = ("structured_only", "derived_board", "masked_raw_experimental")
EXPANSION_WOOD_ARMS = ("structured_only", "derived_board")
BLOCKING_FAILURE_TOKENS = (
    "identity",
    "product",
    "generic",
    "brand",
    "logo",
    "glyph",
    "layout",
    "slot",
    "relation",
    "bbox",
    "center",
    "frame_margin",
    "occlusion",
    "support",
    "leakage",
    "material_board",
)
BLOCKING_FAILURE_CATEGORIES = (
    "identity",
    "brand",
    "layout",
    "leakage",
    "unknown",
)
MATERIAL_IMPROVEMENT_METRICS = (
    "delta_e00",
    "grain_error",
    "surface_occupancy_error",
)


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


def _case(
    *,
    case_id: str,
    phase: str,
    scene_family: str,
    product_set_id: str,
    seed: int,
    material_arm: str,
    estimated_credits: float,
    wood_family_id: str | None = None,
    lighting_family: str | None = None,
    brand_scenario: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "phase": phase,
        "scene_family": scene_family,
        "product_set_id": product_set_id,
        "wood_family_id": wood_family_id,
        "lighting_family": lighting_family,
        "seed": seed,
        "material_arm": material_arm,
        "brand_scenario": brand_scenario,
        "estimated_credits": float(estimated_credits),
        "automatic_paid_repair": False,
    }


def build_validation_campaign(
    *,
    wood_family_ids: Sequence[str],
    three_exact_product_set_id: str,
    two_exact_one_generic_product_set_id: str,
    credits_per_generation: float = 2.0,
    seed_base: int = 8300,
) -> dict[str, Any]:
    """Build the fixed 12+8 paid-validation design without submitting anything."""

    families = list(wood_family_ids)
    if len(families) < 4 or any(
        not isinstance(item, str) or not item.strip() for item in families
    ):
        raise ValueError("At least four concrete wood family IDs are required")
    if len(set(families)) != len(families):
        raise ValueError("Wood family IDs must be unique")
    if not isinstance(credits_per_generation, (int, float)) or isinstance(
        credits_per_generation, bool
    ):
        raise ValueError("credits_per_generation must be numeric")
    cost = float(credits_per_generation)
    if not math.isfinite(cost) or cost <= 0:
        raise ValueError("credits_per_generation must be positive and finite")
    product_sets = (
        ("three_exact", three_exact_product_set_id, "unbranded_adopted_container"),
        (
            "two_exact_one_generic",
            two_exact_one_generic_product_set_id,
            "fully_compatible_branded_surface",
        ),
    )
    if any(not isinstance(value, str) or not value.strip() for _, value, _ in product_sets):
        raise ValueError("Both validation product-set IDs are required")

    cases: list[dict[str, Any]] = []
    for family_index, family_id in enumerate(families[:2], start=1):
        for set_index, (set_key, set_id, brand_scenario) in enumerate(
            product_sets, start=1
        ):
            shared_seed = seed_base + family_index * 10 + set_index
            for arm in INITIAL_ARMS:
                cases.append(
                    _case(
                        case_id=f"initial-{family_index}-{set_key}-{arm}",
                        phase="initial",
                        scene_family="wood",
                        product_set_id=set_id,
                        wood_family_id=family_id,
                        seed=shared_seed,
                        material_arm=arm,
                        brand_scenario=brand_scenario,
                        estimated_credits=cost,
                    )
                )

    for family_offset, family_id in enumerate(families[2:4], start=3):
        set_key, set_id, brand_scenario = product_sets[(family_offset - 3) % 2]
        for arm in EXPANSION_WOOD_ARMS:
            cases.append(
                _case(
                    case_id=f"expansion-{family_offset}-{set_key}-{arm}",
                    phase="expansion",
                    scene_family="wood",
                    product_set_id=set_id,
                    wood_family_id=family_id,
                    seed=seed_base + family_offset * 10,
                    material_arm=arm,
                    brand_scenario=brand_scenario,
                    estimated_credits=cost,
                )
            )

    for lighting_index, lighting_family in enumerate(("direct", "diffuse"), start=1):
        for seed_offset in (1, 2):
            cases.append(
                _case(
                    case_id=f"expansion-white-{lighting_family}-seed-{seed_offset}",
                    phase="expansion",
                    scene_family="white",
                    product_set_id=three_exact_product_set_id,
                    lighting_family=lighting_family,
                    seed=seed_base + 100 + lighting_index * 10 + seed_offset,
                    material_arm="structured_only",
                    brand_scenario="unbranded_adopted_container",
                    estimated_credits=cost,
                )
            )

    plan = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "status": "planned",
        "automatic_paid_repair": False,
        "limits": {
            "initial_maximum_generations": 12,
            "initial_maximum_credits": 24.0,
            "expansion_maximum_generations": 8,
            "expansion_maximum_credits": 16.0,
            "total_maximum_generations": 20,
            "total_maximum_credits": 40.0,
        },
        "expansion_gate": {
            "requires_all_initial_results": True,
            "blocking_hard_failure_tokens": list(BLOCKING_FAILURE_TOKENS),
            "blocking_hard_failure_categories": list(BLOCKING_FAILURE_CATEGORIES),
            "unknown_hard_failure_policy": "block",
        },
        "paid_execution_gate": {
            "contract_gate_and_readiness_are_separate": True,
            "readiness_schema_version": PAID_READINESS_SCHEMA_VERSION,
            "maximum_quote_ttl_seconds": MAXIMUM_QUOTE_TTL_SECONDS,
            "requires_request_hash_binding": True,
            "requires_catalog_and_evaluator_hashes": True,
        },
        "cases": cases,
    }
    plan["campaign_sha256"] = _hash(plan)
    validate_validation_campaign(plan)
    return plan


def validate_validation_campaign(plan: Mapping[str, Any]) -> None:
    if plan.get("schema_version") != CAMPAIGN_SCHEMA_VERSION:
        raise ValueError("Unsupported validation campaign schema version")
    cases = plan.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Validation campaign cases must be an array")
    initial = [item for item in cases if item.get("phase") == "initial"]
    expansion = [item for item in cases if item.get("phase") == "expansion"]
    if len(initial) != 12 or len(expansion) != 8 or len(cases) != 20:
        raise ValueError("Validation campaign must contain exactly 12 initial and 8 expansion cases")
    if len({item.get("case_id") for item in cases}) != len(cases):
        raise ValueError("Validation campaign case IDs must be unique")
    if any(item.get("automatic_paid_repair") is not False for item in cases):
        raise ValueError("Paid validation cases must disable automatic paid repair")
    limits = plan.get("limits", {})
    initial_estimate = sum(float(item.get("estimated_credits", math.inf)) for item in initial)
    expansion_estimate = sum(
        float(item.get("estimated_credits", math.inf)) for item in expansion
    )
    if initial_estimate > float(limits.get("initial_maximum_credits", -1)):
        raise ValueError("Initial validation estimate exceeds 24 credits")
    if expansion_estimate > float(limits.get("expansion_maximum_credits", -1)):
        raise ValueError("Expansion validation estimate exceeds 16 credits")
    if initial_estimate + expansion_estimate > float(
        limits.get("total_maximum_credits", -1)
    ):
        raise ValueError("Validation estimate exceeds 40 total credits")
    expected_hash = plan.get("campaign_sha256")
    without_hash = dict(plan)
    without_hash.pop("campaign_sha256", None)
    if expected_hash != _hash(without_hash):
        raise ValueError("Validation campaign hash does not match its contents")


def _failure_category(code: str) -> str:
    normalized = code.casefold()
    if any(token in normalized for token in ("brand", "logo", "glyph")):
        return "brand"
    if any(token in normalized for token in ("leakage", "material_board", "swatch")):
        return "leakage"
    if any(
        token in normalized
        for token in (
            "identity",
            "exact_product",
            "product_id",
            "product_count",
        )
    ):
        return "identity"
    if any(
        token in normalized
        for token in (
            "layout",
            "slot",
            "relation",
            "generic",
            "bbox",
            "center",
            "frame_margin",
            "occlusion",
            "support",
            "placement",
            "crop",
            "overlap",
        )
    ):
        return "layout"
    return "unknown"


def _blocking_failures(result: Mapping[str, Any]) -> list[str]:
    values = result.get("hard_failures", [])
    if not isinstance(values, list):
        raise ValueError("Validation result hard_failures must be an array")
    blockers: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            raw_code = value.get("code", value.get("check", value.get("failure")))
            if not isinstance(raw_code, str) or not raw_code.strip():
                raise ValueError("Typed hard failure requires a non-empty code")
            raw_category = value.get("category")
            category = (
                raw_category
                if isinstance(raw_category, str)
                and raw_category in BLOCKING_FAILURE_CATEGORIES
                else _failure_category(raw_code)
            )
            blockers.append(f"{category}:{raw_code}")
        else:
            code = str(value).strip()
            if not code:
                raise ValueError("Validation hard failure codes must be non-empty")
            blockers.append(f"{_failure_category(code)}:{code}")

    raw_categories = result.get("hard_failure_categories", [])
    if isinstance(raw_categories, Mapping):
        raw_categories = list(raw_categories.values())
    if not isinstance(raw_categories, list):
        raise ValueError("hard_failure_categories must be an array or object")
    for category in raw_categories:
        if not isinstance(category, str) or category not in BLOCKING_FAILURE_CATEGORIES:
            raise ValueError("Validation result has an unsupported hard-failure category")
        marker = f"{category}:typed_category"
        if marker not in blockers:
            blockers.append(marker)
    # A value explicitly placed in hard_failures is blocking even when its code
    # is new. Unknown failures must not silently authorize paid expansion.
    return blockers


def authorize_campaign_phase(
    plan: Mapping[str, Any],
    *,
    phase: str,
    quoted_credits: Mapping[str, Mapping[str, Any]],
    paid_readiness: Mapping[str, Any] | None = None,
    initial_results: Mapping[str, Mapping[str, Any]] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Authorize a phase only from one ready proof and unexpired bound quotes."""

    validate_validation_campaign(plan)
    if paid_readiness is None:
        raise ValueError("Campaign authorization requires a paid-readiness proof")
    readiness = require_paid_execution_readiness(paid_readiness)
    if phase not in {"initial", "expansion"}:
        raise ValueError("phase must be initial or expansion")
    cases = [item for item in plan["cases"] if item["phase"] == phase]
    expected_ids = {item["case_id"] for item in cases}
    if set(quoted_credits) != expected_ids:
        raise ValueError("Every case in the phase must have one fresh provider quote")

    request_hashes = readiness["request_hashes"]
    missing_request_hashes = expected_ids - set(request_hashes)
    if missing_request_hashes:
        raise ValueError(
            "Paid readiness is missing campaign request hashes: "
            f"{sorted(missing_request_hashes)}"
        )
    quotes: dict[str, dict[str, Any]] = {}
    for case_id, raw_quote in quoted_credits.items():
        if not isinstance(raw_quote, Mapping):
            raise ValueError(
                "Provider quotes must include request hash, timestamps, TTL and quote hash"
            )
        quote = validate_provider_quote(raw_quote, now=now)
        if quote["case_id"] != case_id:
            raise ValueError("Provider quote case_id does not match its campaign case")
        if quote["request_sha256"] != request_hashes[case_id]:
            raise ValueError("Provider quote is bound to a different generation request")
        quotes[case_id] = quote
    providers = {quote["provider"] for quote in quotes.values()}
    if len(providers) != 1:
        raise ValueError("Every case in one campaign phase must use the same provider")
    quoted_total = sum(float(quote["quoted_credits"]) for quote in quotes.values())
    phase_cap = float(plan["limits"][f"{phase}_maximum_credits"])
    if quoted_total > phase_cap:
        raise ValueError(f"Fresh provider quote exceeds the {phase_cap:g}-credit {phase} cap")

    blockers: dict[str, list[str]] = {}
    initial_actual_total = 0.0
    if phase == "expansion":
        initial_cases = [item for item in plan["cases"] if item["phase"] == "initial"]
        expected_initial = {item["case_id"] for item in initial_cases}
        if initial_results is None or set(initial_results) != expected_initial:
            raise ValueError("Expansion requires all 12 initial results")
        for case_id, result in initial_results.items():
            blocking = _blocking_failures(result)
            if blocking:
                blockers[case_id] = blocking
            actual = result.get("actual_credits")
            if (
                not isinstance(actual, (int, float))
                or isinstance(actual, bool)
                or not math.isfinite(float(actual))
                or float(actual) < 0
            ):
                raise ValueError("Every initial result requires non-negative actual_credits")
            initial_actual_total += float(actual)
        if blockers:
            raise ValueError("Expansion blocked by initial identity/brand/layout/leakage failure")
        if initial_actual_total + quoted_total > float(
            plan["limits"]["total_maximum_credits"]
        ):
            raise ValueError("Fresh quotes would exceed the 40-credit campaign cap")

    quote_hashes = {
        case_id: quote["quote_sha256"] for case_id, quote in sorted(quotes.items())
    }
    authorization = {
        "authorized": True,
        "phase": phase,
        "case_count": len(cases),
        "quoted_credits": quoted_total,
        "provider": next(iter(providers)),
        "quote_expires_at": min(quote["expires_at"] for quote in quotes.values()),
        "quote_hashes": quote_hashes,
        "quote_set_sha256": _hash(quote_hashes),
        "initial_actual_credits": initial_actual_total,
        "maximum_total_credits": plan["limits"]["total_maximum_credits"],
        "automatic_paid_repair": False,
        "campaign_sha256": plan["campaign_sha256"],
        "readiness_sha256": readiness["readiness_sha256"],
        "contract_gate_sha256": readiness["contract_gate_sha256"],
        "catalog_contract_sha256": readiness["catalog_contract_sha256"],
        "evaluator_contract_sha256": readiness["evaluator_contract_sha256"],
        "request_set_sha256": readiness["request_set_sha256"],
    }
    authorization["authorization_sha256"] = _hash(authorization)
    return authorization


def _metrics(result: Mapping[str, Any]) -> dict[str, float]:
    raw = result.get("metrics")
    if not isinstance(raw, Mapping):
        raise ValueError("Material arm result requires metrics")
    values: dict[str, float] = {}
    for name in MATERIAL_IMPROVEMENT_METRICS:
        value = raw.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"Material arm result requires numeric {name}")
        values[name] = float(value)
    return values


def decide_material_input_policy(
    results_by_product_set: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Apply the family-level derived-board and masked-raw activation rules."""

    if len(results_by_product_set) < 2:
        raise ValueError("A family decision requires both validation product sets")
    derived_eligible = True
    raw_eligible = True
    comparisons: dict[str, Any] = {}
    for product_set_id, arms in results_by_product_set.items():
        missing = set(INITIAL_ARMS) - set(arms)
        if missing:
            raise ValueError(f"Product set {product_set_id} is missing arms: {sorted(missing)}")
        structured = _metrics(arms["structured_only"])
        derived = _metrics(arms["derived_board"])
        masked = _metrics(arms["masked_raw_experimental"])
        derived_improved = [
            name
            for name in MATERIAL_IMPROVEMENT_METRICS
            if derived[name] < structured[name]
        ]
        raw_improved_ten_percent = [
            name
            for name in MATERIAL_IMPROVEMENT_METRICS
            if derived[name] > 0 and (derived[name] - masked[name]) / derived[name] >= 0.10
        ]
        derived_failures = _blocking_failures(arms["derived_board"])
        raw_failures = _blocking_failures(arms["masked_raw_experimental"])
        if arms["derived_board"].get("leakage_flags"):
            derived_failures.append("material_board_leakage")
        if arms["masked_raw_experimental"].get("leakage_flags"):
            raw_failures.append("material_board_leakage")
        derived_set_pass = len(derived_improved) >= 2 and not derived_failures
        raw_set_pass = len(raw_improved_ten_percent) >= 2 and not raw_failures
        derived_eligible = derived_eligible and derived_set_pass
        raw_eligible = raw_eligible and raw_set_pass
        comparisons[product_set_id] = {
            "derived_improved_metrics": derived_improved,
            "derived_blocking_failures": derived_failures,
            "masked_raw_improved_by_at_least_10_percent": raw_improved_ten_percent,
            "masked_raw_blocking_failures": raw_failures,
        }

    return {
        "default_material_input": (
            "derived_board" if derived_eligible else "structured_only"
        ),
        "masked_raw_fallback_allowed": bool(derived_eligible and raw_eligible),
        "comparisons": comparisons,
    }
