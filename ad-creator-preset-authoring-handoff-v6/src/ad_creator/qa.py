from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Literal, NotRequired, Sequence, TypedDict

from .jsonio import validate_json


class ProductQAMeasurements(TypedDict):
    product_id: str
    observed_product_id: str
    center_position_error: float
    width_ratio: float
    height_ratio: float
    target_bbox_iou: float
    frame_margin: float
    support_relation_match: bool
    occlusion_relation_match: bool
    active_relation_match: bool
    brand_detected: NotRequired[bool]
    generated_logo_text: NotRequired[str | None]
    reference_brand_detected: NotRequired[bool]


class ProductQAResult(TypedDict):
    product_id: str
    status: Literal["pass", "fail", "needs_review"]
    hard_failures: list[str]
    missing_measurements: list[str]
    measurements: dict[str, Any]
    brand_result: NotRequired[dict[str, Any]]
    review_reasons: NotRequired[list[str]]


class MultiProductQAReport(TypedDict):
    schema_version: Literal["1.0.0"]
    overall_status: Literal["passed", "needs_review", "rejected"]
    expected_exact_product_ids: list[str]
    observed_exact_product_ids: list[str]
    product_results: list[ProductQAResult]
    hard_failures: list[str]
    missing_measurements: list[str]


class WoodQAMeasurements(TypedDict):
    delta_e00: float
    lightness_difference: float
    chroma_difference: float
    grain_direction_difference_degrees: float
    grain_frequency_ratio: float
    surface_coverage_error: float
    swatch_boundary_detected: NotRequired[bool]
    source_object_copied: NotRequired[bool]
    source_text_copied: NotRequired[bool]
    source_layout_copied: NotRequired[bool]


class WoodQAReport(TypedDict):
    schema_version: Literal["1.0.0"]
    overall_status: Literal[
        "passed", "passed_with_warnings", "needs_review", "rejected"
    ]
    metrics: dict[str, dict[str, Any]]
    hard_failures: list[str]
    warnings: list[str]
    missing_measurements: list[str]


BASE_CHECK_CODES = (
    "beverage_identity",
    "container_policy",
    "reference_brand_leakage",
    "logo_text",
    "product_composition",
    "hand_contact",
    "wrist_exposure",
    "contact_shadow",
    "cast_shadow",
    "transmitted_light",
    "lighting_physical_consistency",
    "smartphone_naturalness",
)

SCENE_CHECK_CODES = (
    "scene_slot_adherence",
    "scene_subject_count",
    "scene_support_contact",
    "scene_relational_consistency",
)

# Backwards-compatible name for callers that construct the singleton QA contract.
CHECK_CODES = BASE_CHECK_CODES


def qa_check_codes(request: dict[str, Any]) -> tuple[str, ...]:
    return (
        BASE_CHECK_CODES + SCENE_CHECK_CODES
        if request.get("scene_graph_contract") is not None
        else BASE_CHECK_CODES
    )

REJECT_ON_FAIL = {
    "beverage_identity",
    "container_policy",
    "reference_brand_leakage",
    "scene_slot_adherence",
    "scene_subject_count",
}

AUTO_REPAIRABLE = {
    "logo_text",
    "wrist_exposure",
    "contact_shadow",
    "cast_shadow",
    "transmitted_light",
    "lighting_physical_consistency",
}

REPAIR_INSTRUCTIONS = {
    "logo_text": "Correct only the source logo spelling and mark; preserve every unrelated scene pixel semantically.",
    "wrist_exposure": "Shorten only the excessive wrist or forearm while keeping finger-to-cup contact physically connected.",
    "contact_shadow": "Restore a compact attached contact shadow at the fingers and nearest cup edge.",
    "cast_shadow": "Reduce or redirect only the physically failed cast-shadow footprint according to the selected lighting sheet.",
    "transmitted_light": "Restore believable beverage-colored transmitted light inside the transparent-container shadow.",
    "lighting_physical_consistency": "Correct only the failed shared-light relationship between highlight, reflection and shadow.",
}

PROTECTED_INVARIANTS = [
    "source beverage identity and visible liquid layers",
    "selected container policy and container construction",
    "source branding with no reference-brand leakage",
    "product position, crop and negative space",
    "hand-to-cup contact",
    "selected lighting-sheet identity",
    "ordinary smartphone capture character",
    "resolved scene slot count, support contact and depth ordering",
]


_STATUS_RANK = {"pass": 0, "warning": 1, "fail": 2}


def _normalized_logo_text(value: str) -> str:
    return "".join(value.casefold().split())


def evaluate_target_brand_qa(
    target_brand_contract: dict[str, Any],
    measurements: dict[str, Any],
    *,
    brand_transfer_resolution: dict[str, Any] | None = None,
    product_count: int = 1,
) -> dict[str, Any]:
    """Apply deterministic brand QA against the resolved target, never the reference."""
    target_state = target_brand_contract.get("state")
    action = (brand_transfer_resolution or {}).get("action")
    reference_brand_detected = measurements.get("reference_brand_detected")
    if reference_brand_detected is True:
        return {
            "status": "fail",
            "decision": "reject",
            "repairable": False,
            "reason_code": "reference_brand_leakage",
        }

    observed_text = measurements.get("generated_logo_text")
    no_brand_sentinel = isinstance(observed_text, str) and observed_text.strip().casefold() in {
        "",
        "none",
        "null",
        "absent",
        "unbranded",
        "no logo",
        "no text",
    }
    if no_brand_sentinel:
        observed_text = None
        measurements["generated_logo_text"] = None
        measurements["brand_detected"] = False
    brand_detected = measurements.get("brand_detected")
    if not isinstance(brand_detected, bool) and isinstance(observed_text, str):
        brand_detected = bool(observed_text.strip())

    if target_state == "verified_absent":
        if not isinstance(brand_detected, bool):
            return {
                "status": "needs_review",
                "decision": "manual_review",
                "repairable": False,
                "reason_code": "brand_presence_measurement_missing",
            }
        if brand_detected:
            return {
                "status": "fail",
                "decision": "reject",
                "repairable": False,
                "reason_code": "forbidden_brand_detected",
            }
        return {
            "status": "pass",
            "decision": "no_action",
            "repairable": False,
            "reason_code": "verified_unbranded_target_satisfied",
        }

    if target_state == "uncertain":
        return {
            "status": "needs_review",
            "decision": "manual_review",
            "repairable": False,
            "reason_code": "target_brand_contract_uncertain",
        }
    if target_state != "verified_present":
        raise ValueError(f"Unsupported target brand state: {target_state!r}")

    expected = target_brand_contract.get("allowed_main_text")
    if not isinstance(expected, str) or not expected.strip():
        target_non_text_mark = target_brand_contract.get("non_text_mark")
        visual_identity = measurements.get("non_text_visual_identity")
        if not isinstance(target_non_text_mark, str) or not target_non_text_mark.strip():
            return {
                "status": "needs_review",
                "decision": "manual_review",
                "repairable": False,
                "reason_code": "non_text_brand_contract_missing",
            }
        if not isinstance(visual_identity, dict):
            return {
                "status": "needs_review",
                "decision": "manual_review",
                "repairable": False,
                "reason_code": "non_text_visual_identity_measurement_missing",
            }
        detector = visual_identity.get("detector")
        confidence = visual_identity.get("confidence")
        matched = visual_identity.get("matched")
        matcher_ready = (
            visual_identity.get("target_non_text_mark") == target_non_text_mark
            and isinstance(detector, dict)
            and all(
                isinstance(detector.get(field), str) and detector[field].strip()
                for field in ("name", "version")
            )
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and 0 <= float(confidence) <= 1
            and isinstance(matched, bool)
        )
        if not matcher_ready:
            return {
                "status": "needs_review",
                "decision": "manual_review",
                "repairable": False,
                "reason_code": "non_text_visual_identity_evidence_invalid",
            }
        if float(confidence) < 0.90:
            return {
                "status": "needs_review",
                "decision": "manual_review",
                "repairable": False,
                "reason_code": "non_text_visual_identity_confidence_below_0_90",
            }
        if isinstance(matched, bool):
            return {
                "status": "pass" if matched else "fail",
                "decision": "no_action" if matched else "reject",
                "repairable": False,
                "reason_code": (
                    "verified_non_text_brand_present"
                    if matched
                    else "required_non_text_brand_missing"
                ),
            }
    if not isinstance(observed_text, str):
        return {
            "status": "needs_review",
            "decision": "manual_review",
            "repairable": False,
            "reason_code": "generated_logo_text_measurement_missing",
        }
    if _normalized_logo_text(observed_text) == _normalized_logo_text(expected):
        return {
            "status": "pass",
            "decision": "no_action",
            "repairable": False,
            "reason_code": "target_logo_exact_match",
        }

    if product_count > 1:
        return {
            "status": "needs_review",
            "decision": "manual_review",
            "repairable": False,
            "reason_code": "multi_product_logo_mismatch",
        }
    repair_assets_ready = (
        measurements.get("brand_asset_available") is True
        and measurements.get("brand_mask_available") is True
    )
    if action == "preserve_source_exact" and not repair_assets_ready:
        return {
            "status": "fail",
            "decision": "reject",
            "repairable": False,
            "reason_code": "preserved_source_logo_glyph_mismatch",
        }
    return {
        "status": "fail" if repair_assets_ready else "needs_review",
        "decision": "repair" if repair_assets_ready else "manual_review",
        "repairable": repair_assets_ready,
        "reason_code": (
            "single_product_logo_repair_allowed"
            if repair_assets_ready
            else "logo_repair_assets_missing"
        ),
    }


def _guard_target_brand_contract(
    logo_check: dict[str, Any],
    reference_check: dict[str, Any],
    *,
    request: dict[str, Any],
) -> bool:
    target = request.get("target_brand_contract")
    if not isinstance(target, dict) and isinstance(
        request.get("brand_transfer_resolution"), dict
    ):
        target = request.get("brand_contract")
    if not isinstance(target, dict):
        return False
    measurements = logo_check.setdefault("measurements", {})
    if "generated_logo_text" not in measurements:
        observed_alias = measurements.get("observed")
        if isinstance(observed_alias, str):
            measurements["generated_logo_text"] = observed_alias
    if "reference_brand_detected" not in measurements:
        reference_measurements = reference_check.get("measurements", {})
        if isinstance(reference_measurements, dict):
            detected = reference_measurements.get("reference_brand_detected")
            if isinstance(detected, bool):
                measurements["reference_brand_detected"] = detected
    products = request.get("products")
    product_count = len(products) if isinstance(products, list) else 1
    result = evaluate_target_brand_qa(
        target,
        measurements,
        brand_transfer_resolution=request.get("brand_transfer_resolution"),
        product_count=max(1, product_count),
    )
    measurements["target_brand_contract_state"] = target.get("state")
    measurements["deterministic_guard"] = result["reason_code"]
    measurements["brand_qa_decision"] = result["decision"]
    if isinstance(target.get("allowed_main_text"), str):
        measurements["contract_logo_text"] = target["allowed_main_text"]

    if result["status"] == "pass":
        logo_check["status"] = "pass"
        logo_check["confidence"] = max(float(logo_check["confidence"]), 0.90)
    elif result["status"] == "fail":
        logo_check["status"] = "fail"
        logo_check["confidence"] = max(float(logo_check["confidence"]), 0.97)
    else:
        logo_check["status"] = "fail"
        logo_check["confidence"] = min(float(logo_check["confidence"]), 0.70)
    logo_check["repairable"] = bool(result["repairable"])
    logo_check["evidence"].append(
        f"Target brand guard: {result['reason_code']}."
    )

    if result["reason_code"] == "reference_brand_leakage":
        reference_check["status"] = "fail"
        reference_check["confidence"] = max(
            float(reference_check["confidence"]), 0.99
        )
        reference_check.setdefault("measurements", {})[
            "deterministic_guard"
        ] = "reference_brand_leakage"
        reference_check["evidence"].append(
            "Target brand guard: reference branding appeared in the generated image."
        )
    return True


def _guard_verified_logo_contract(
    check: dict[str, Any],
    *,
    request: dict[str, Any],
) -> None:
    branding = request.get("product_analysis", {}).get("identity", {}).get("branding", {})
    if branding.get("state") != "verified_present":
        return
    expected = branding.get("main_text")
    observed = check.get("measurements", {}).get("generated_logo_text")
    if not isinstance(expected, str) or not expected.strip() or not isinstance(observed, str):
        return

    measurements = check["measurements"]
    measurements["contract_logo_text"] = expected
    if _normalized_logo_text(observed) == _normalized_logo_text(expected):
        check["status"] = "pass"
        check["confidence"] = max(float(check["confidence"]), 0.90)
        measurements["deterministic_guard"] = "verified_contract_match"
        check["evidence"].append(
            "Verified logo guard: generated_logo_text exactly matches the authoritative contract."
        )
        return

    check["status"] = "fail"
    check["confidence"] = max(float(check["confidence"]), 0.95)
    measurements["deterministic_guard"] = "verified_contract_mismatch"
    check["evidence"].append(
        f'Verified logo guard: generated_logo_text="{observed}" does not match "{expected}".'
    )


def _effective_container_material(request: dict[str, Any]) -> str:
    if request.get("identity_policy", {}).get("container") == "adopt_reference":
        material = request.get("container_design", {}).get("design", {}).get("material")
    else:
        material = (
            request.get("product_analysis", {})
            .get("identity", {})
            .get("container", {})
            .get("material")
        )
    return str(material or "").casefold()


def _requires_transmitted_light(request: dict[str, Any]) -> bool:
    material = _effective_container_material(request)
    if any(token in material for token in ("ceramic", "porcelain", "paper", "metal", "stone")):
        return False
    return any(token in material for token in ("glass", "clear", "transparent", "pet"))


def _guard_opaque_transmission(
    check: dict[str, Any],
    *,
    request: dict[str, Any],
) -> None:
    if _requires_transmitted_light(request):
        return
    check["status"] = "pass"
    check["confidence"] = max(float(check["confidence"]), 0.90)
    check["measurements"]["deterministic_guard"] = "opaque_container_not_applicable"
    check["evidence"].append(
        "Material guard: the selected opaque container requires no through-body transmitted light."
    )


def _escalate_ratio_check(
    check: dict[str, Any],
    *,
    measurement_name: str,
    target_range: list[float],
    upper_only: bool = False,
    aliases: tuple[str, ...] = (),
) -> None:
    measurements = check.get("measurements", {})
    measured = measurements.get(measurement_name)
    if not isinstance(measured, (int, float)):
        for alias in aliases:
            candidate = measurements.get(alias)
            if isinstance(candidate, (int, float)):
                measured = candidate
                measurements[measurement_name] = candidate
                break
    if not isinstance(measured, (int, float)):
        return
    lower, upper = (float(target_range[0]), float(target_range[1]))
    check["measurements"]["target_range"] = [lower, upper]
    outside = measured > upper or (not upper_only and measured < lower)
    if not outside:
        return

    severe = measured > upper * 1.25 or (
        not upper_only and measured < lower * 0.75
    )
    status = "fail" if severe else "warning"
    if _STATUS_RANK[status] <= _STATUS_RANK[check["status"]]:
        return
    check["status"] = status
    check["confidence"] = max(float(check["confidence"]), 0.90 if severe else 0.80)
    check["evidence"].append(
        f"Deterministic ratio guard: {measurement_name}={measured:.3f} is outside "
        f"the selected lighting-sheet range {lower:.3f}..{upper:.3f}."
    )
    check["measurements"]["deterministic_guard"] = "severe" if severe else "minor"


def _guard_adopted_container_ratio(
    check: dict[str, Any],
    *,
    target_range: list[float],
) -> None:
    measurements = check.get("measurements", {})
    measured = measurements.get("generated_height_to_width_ratio")
    for alias in (
        "generated_container_height_to_width_ratio",
        "container_height_to_width_ratio",
    ):
        if isinstance(measured, (int, float)):
            break
        candidate = measurements.get(alias)
        if isinstance(candidate, (int, float)):
            measured = candidate
            measurements["generated_height_to_width_ratio"] = candidate

    lower, upper = float(target_range[0]), float(target_range[1])
    measurements["target_height_to_width_ratio"] = [lower, upper]
    if not isinstance(measured, (int, float)):
        if check["status"] != "fail":
            check["status"] = "fail"
            check["confidence"] = min(float(check["confidence"]), 0.70)
            check["evidence"].append(
                "Container ratio guard: adopt_reference cannot pass without a measured "
                "generated cup height-to-width ratio."
            )
            measurements["deterministic_guard"] = "measurement_missing"
        return

    if lower <= measured <= upper:
        return
    severe = measured < lower * 0.90 or measured > upper * 1.10
    status = "fail" if severe else "warning"
    if _STATUS_RANK[status] <= _STATUS_RANK[check["status"]]:
        return
    check["status"] = status
    check["confidence"] = max(float(check["confidence"]), 0.90 if severe else 0.80)
    check["evidence"].append(
        f"Container ratio guard: generated_height_to_width_ratio={measured:.3f} is "
        f"outside the adopted range {lower:.3f}..{upper:.3f}."
    )
    measurements["deterministic_guard"] = "severe" if severe else "minor"


def normalize_qa_report(
    payload: dict[str, Any],
    *,
    evaluator: dict[str, str],
    evaluated_image: str | Path,
    request: dict[str, Any],
    lighting_sheet: dict[str, Any],
    project_root: str | Path,
) -> dict[str, Any]:
    checks = copy.deepcopy(payload.get("checks"))
    if not isinstance(checks, dict):
        raise ValueError("Evaluator response must contain a checks object")
    expected_codes = qa_check_codes(request)
    missing = [code for code in expected_codes if code not in checks]
    extra = [code for code in checks if code not in expected_codes]
    if missing or extra:
        raise ValueError(f"Evaluator check mismatch; missing={missing}, extra={extra}")

    for code, check in checks.items():
        if not isinstance(check, dict):
            raise ValueError(f"QA check must be an object: {code}")
        check["repairable"] = code in AUTO_REPAIRABLE

    target_guard_applied = _guard_target_brand_contract(
        checks["logo_text"],
        checks["reference_brand_leakage"],
        request=request,
    )
    if not target_guard_applied:
        _guard_verified_logo_contract(checks["logo_text"], request=request)

    if request["identity_policy"]["container"] == "adopt_reference":
        design = request.get("container_design", {}).get("design", {})
        target_ratio = design.get("height_to_width_ratio")
        if not (
            isinstance(target_ratio, list)
            and len(target_ratio) == 2
            and all(isinstance(value, (int, float)) for value in target_ratio)
        ):
            raise ValueError(
                "adopt_reference QA requires a numeric container height-to-width range"
            )
        _guard_adopted_container_ratio(
            checks["container_policy"],
            target_range=target_ratio,
        )

    qa_ratios = lighting_sheet["shadow_contract"]["qa_ratios"]
    _escalate_ratio_check(
        checks["wrist_exposure"],
        measurement_name="wrist_length_to_cup_height",
        target_range=qa_ratios["wrist_length_to_cup_height"],
        upper_only=True,
        aliases=("wrist_length_to_cup_height_ratio",),
    )
    _escalate_ratio_check(
        checks["cast_shadow"],
        measurement_name="cast_area_to_cup_bbox",
        target_range=qa_ratios["cast_area_to_cup_bbox"],
    )
    if _requires_transmitted_light(request):
        _escalate_ratio_check(
            checks["transmitted_light"],
            measurement_name="transparent_lift_inside_shadow",
            target_range=qa_ratios["transparent_lift_inside_shadow"],
        )
    else:
        _guard_opaque_transmission(checks["transmitted_light"], request=request)

    hard_failures = [
        code for code in expected_codes if checks[code]["status"] == "fail"
    ]
    warnings = [
        code for code in expected_codes if checks[code]["status"] == "warning"
    ]
    if hard_failures:
        overall = "needs_review"
    elif warnings:
        overall = "passed_with_warnings"
    else:
        overall = "passed"

    report = {
        "schema_version": "1.0.0",
        "evaluator": evaluator,
        "evaluated_image": str(Path(evaluated_image)),
        "lighting_sheet_id": lighting_sheet["lighting_sheet_id"],
        "container_mode": request["identity_policy"]["container"],
        "overall_status": overall,
        "checks": checks,
        "hard_failures": hard_failures,
        "warnings": warnings,
    }
    validate_json(report, "qa-report.schema.json", project_root=project_root)
    return report


def route_repair(
    report: dict[str, Any],
    *,
    request: dict[str, Any],
    project_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = copy.deepcopy(report)
    policy = request["repair_policy"]
    enabled = bool(policy["auto_paid_repair"])
    threshold = float(policy["minimum_trigger_confidence"])
    expected_codes = qa_check_codes(request)
    failures = [
        code
        for code in expected_codes
        if report["checks"][code]["status"] == "fail"
    ]
    high_confidence = [
        code
        for code in failures
        if float(report["checks"][code]["confidence"]) >= threshold
    ]
    low_confidence = [code for code in failures if code not in high_confidence]
    rejected = [code for code in high_confidence if code in REJECT_ON_FAIL]
    logo_measurements = report["checks"]["logo_text"].get("measurements", {})
    if (
        "logo_text" in high_confidence
        and logo_measurements.get("brand_qa_decision") == "reject"
        and "logo_text" not in rejected
    ):
        rejected.append("logo_text")
    repairable = [code for code in high_confidence if code in AUTO_REPAIRABLE]
    unsupported = [
        code for code in high_confidence if code not in REJECT_ON_FAIL | AUTO_REPAIRABLE
    ]
    if (
        "logo_text" in high_confidence
        and logo_measurements.get("brand_qa_decision") == "manual_review"
    ):
        repairable = [code for code in repairable if code != "logo_text"]
        unsupported.append("logo_text")

    if rejected:
        decision = "reject"
        report["overall_status"] = "rejected"
        reason = f"Protected identity policy failed: {', '.join(rejected)}"
        issues: list[dict[str, Any]] = []
    elif repairable and enabled and not unsupported and not low_confidence:
        decision = "repair"
        report["overall_status"] = "repair_required"
        reason = "High-confidence, allowlisted hard failures require one conditional repair."
        issues = [
            {
                "check": code,
                "confidence": report["checks"][code]["confidence"],
                "instruction": REPAIR_INSTRUCTIONS[code],
            }
            for code in repairable
        ]
    elif failures:
        decision = "needs_review"
        report["overall_status"] = "needs_review"
        reasons = []
        if not enabled:
            reasons.append("automatic paid repair is disabled")
        if low_confidence:
            reasons.append(f"below-threshold failures: {', '.join(low_confidence)}")
        if unsupported:
            reasons.append(f"non-automatic failures: {', '.join(unsupported)}")
        if repairable and enabled and (unsupported or low_confidence):
            reasons.append("mixed failure set requires human review")
        reason = "; ".join(reasons) or "Hard failure requires human review."
        issues = []
    else:
        decision = "no_repair"
        reason = "No hard failure qualifies for paid repair."
        issues = []

    plan = {
        "schema_version": "1.0.0",
        "decision": decision,
        "reason": reason,
        "auto_paid_repair_enabled": enabled,
        "minimum_trigger_confidence": threshold,
        "container_mode": request["identity_policy"]["container"],
        "issues": issues,
        "protected_invariants": PROTECTED_INVARIANTS,
        "estimated_credits": (
            float(policy["maximum_additional_credits"]) if decision == "repair" else 0
        ),
        "maximum_attempts": int(policy["maximum_attempts"]) if decision == "repair" else 0,
    }
    validate_json(report, "qa-report.schema.json", project_root=project_root)
    validate_json(plan, "repair-plan.schema.json", project_root=project_root)
    return report, plan


_PRODUCT_MEASUREMENT_ALIASES = {
    "observed_product_id": ("exact_product_id", "matched_product_id"),
    "center_position_error": ("center_error", "center_error_ratio"),
    "width_ratio": ("width_ratio_to_expected", "generated_width_to_expected"),
    "height_ratio": ("height_ratio_to_expected", "generated_height_to_expected"),
    "target_bbox_iou": ("bbox_iou", "slot_bbox_iou"),
    "frame_margin": ("minimum_frame_margin", "frame_margin_ratio"),
    "support_relation_match": ("support_match", "support_contact_match"),
    "occlusion_relation_match": ("occlusion_match",),
    "active_relation_match": ("active_relations_match", "relation_set_match"),
}


def _measurement_value(
    measurements: dict[str, Any],
    name: str,
) -> Any:
    if name in measurements:
        return measurements[name]
    for alias in _PRODUCT_MEASUREMENT_ALIASES.get(name, ()):
        if alias in measurements:
            measurements[name] = measurements[alias]
            return measurements[name]
    if name in {
        "support_relation_match",
        "occlusion_relation_match",
        "active_relation_match",
    } and isinstance(measurements.get("relations_match"), bool):
        measurements[name] = measurements["relations_match"]
        return measurements[name]
    return None


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _product_id(spec: dict[str, Any]) -> str | None:
    for key in ("product_id", "id", "input_product_id"):
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_generic_product(spec: dict[str, Any]) -> bool:
    return bool(spec.get("is_generic")) or spec.get("role") == "generic" or spec.get(
        "source_type"
    ) == "generic"


def evaluate_multi_product_qa(
    product_measurements: Sequence[dict[str, Any]],
    *,
    expected_product_ids: Sequence[str] | None = None,
    product_specs: Sequence[dict[str, Any]] | None = None,
    observed_exact_product_ids: Sequence[str] | None = None,
    observed_exact_product_count: int | None = None,
) -> MultiProductQAReport:
    """Evaluate one-to-three exact products with fail-closed typed measurements."""
    if not isinstance(product_measurements, Sequence) or isinstance(
        product_measurements, (str, bytes)
    ):
        raise ValueError("product_measurements must be an array")
    records = [copy.deepcopy(item) for item in product_measurements]
    if any(not isinstance(item, dict) for item in records):
        raise ValueError("each product measurement must be an object")

    specs = [copy.deepcopy(item) for item in (product_specs or [])]
    if any(not isinstance(item, dict) for item in specs):
        raise ValueError("each product spec must be an object")
    exact_specs = [item for item in specs if not _is_generic_product(item)]
    if expected_product_ids is None:
        expected = [_product_id(item) for item in exact_specs]
        if not exact_specs:
            expected = [
                item.get("product_id")
                for item in records
                if isinstance(item.get("product_id"), str)
            ]
    else:
        expected = list(expected_product_ids)
    if not expected or any(not isinstance(item, str) or not item.strip() for item in expected):
        raise ValueError("expected_product_ids must contain one to three non-empty IDs")
    if len(expected) > 3:
        raise ValueError("multi-product QA supports at most three exact products")
    if len(set(expected)) != len(expected):
        raise ValueError("expected_product_ids must be unique")

    specs_by_id = {
        product_id: spec
        for spec in exact_specs
        if (product_id := _product_id(spec)) is not None
    }
    records_by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        expected_id = record.get("product_id", record.get("expected_product_id"))
        if isinstance(expected_id, str) and expected_id not in records_by_id:
            records_by_id[expected_id] = record

    global_missing: list[str] = []
    explicit_observed_ids = observed_exact_product_ids is not None
    if observed_exact_product_ids is None:
        observed = []
        for record in records:
            value = _measurement_value(record, "observed_product_id")
            if isinstance(value, str) and value.strip():
                observed.append(value)
    else:
        observed = list(observed_exact_product_ids)
    observed_ids_valid = not any(
        not isinstance(item, str) or not item.strip() for item in observed
    )
    if not observed_ids_valid:
        global_missing.append("observed_exact_product_ids")
    observed = [item for item in observed if isinstance(item, str) and item.strip()]

    hard_failures: list[str] = []
    count_is_measured = (
        isinstance(observed_exact_product_count, int)
        and not isinstance(observed_exact_product_count, bool)
        and observed_exact_product_count >= 0
    )
    if observed_exact_product_count is not None and not count_is_measured:
        global_missing.append("observed_exact_product_count")
    if count_is_measured and observed_exact_product_count != len(expected):
        hard_failures.append("exact_product_count_mismatch")
    elif explicit_observed_ids and observed_ids_valid and len(observed) != len(expected):
        hard_failures.append("exact_product_count_mismatch")
    elif not explicit_observed_ids and not count_is_measured:
        if len(records) == len(expected) and len(observed) == len(records):
            pass
        elif len(records) > len(expected) and len(observed) == len(records):
            hard_failures.append("exact_product_count_mismatch")
        else:
            global_missing.append("observed_exact_product_count")
    ids_are_measured = (explicit_observed_ids and observed_ids_valid) or (
        len(records) == len(expected) and len(observed) == len(records)
    )
    if ids_are_measured and sorted(observed) != sorted(expected):
        hard_failures.append("exact_product_id_mismatch")

    required_numeric = (
        "center_position_error",
        "width_ratio",
        "height_ratio",
        "target_bbox_iou",
        "frame_margin",
    )
    required_boolean = (
        "support_relation_match",
        "occlusion_relation_match",
        "active_relation_match",
    )
    product_results: list[ProductQAResult] = []
    all_missing: list[str] = list(dict.fromkeys(global_missing))

    for expected_id in expected:
        record = records_by_id.get(expected_id)
        if record is None:
            missing = [*required_numeric, *required_boolean, "product_record"]
            qualified = [f"{expected_id}.{name}" for name in missing]
            all_missing.extend(qualified)
            product_results.append(
                {
                    "product_id": expected_id,
                    "status": "needs_review",
                    "hard_failures": [],
                    "missing_measurements": missing,
                    "measurements": {},
                }
            )
            continue

        failures: list[str] = []
        missing = []
        review_reasons: list[str] = []
        observed_id = _measurement_value(record, "observed_product_id")
        if not isinstance(observed_id, str) or not observed_id.strip():
            missing.append("observed_product_id")
        elif observed_id != expected_id:
            failures.append("exact_product_id_mismatch")

        for field in required_numeric:
            if not _finite_number(_measurement_value(record, field)):
                missing.append(field)
        for field in required_boolean:
            if not isinstance(_measurement_value(record, field), bool):
                missing.append(field)

        if "center_position_error" not in missing and float(
            record["center_position_error"]
        ) > 0.03:
            failures.append("center_position_error_exceeds_0_03")
        if "width_ratio" not in missing and not 0.80 <= float(record["width_ratio"]) <= 1.20:
            failures.append("width_ratio_outside_0_80_1_20")
        if "height_ratio" not in missing and not 0.80 <= float(record["height_ratio"]) <= 1.20:
            failures.append("height_ratio_outside_0_80_1_20")
        if "target_bbox_iou" not in missing and float(record["target_bbox_iou"]) < 0.55:
            failures.append("target_bbox_iou_below_0_55")
        if "frame_margin" not in missing and float(record["frame_margin"]) < 0.06:
            failures.append("frame_margin_below_0_06")
        for field in required_boolean:
            if field not in missing and record[field] is False:
                failures.append(f"{field}_failed")

        spec = specs_by_id.get(expected_id, {})
        target = spec.get("target_brand_contract")
        if isinstance(target, dict):
            brand_measurements = record.get("brand_measurements")
            if not isinstance(brand_measurements, dict):
                brand_measurements = record
            brand_result = evaluate_target_brand_qa(
                target,
                brand_measurements,
                brand_transfer_resolution=spec.get("brand_transfer_resolution"),
                product_count=len(expected),
            )
            if brand_result["status"] == "fail":
                failures.append(brand_result["reason_code"])
            elif brand_result["status"] == "needs_review":
                review_reasons.append(brand_result["reason_code"])
        else:
            brand_result = None

        serving_resolution = spec.get("serving_compatibility_resolution")
        if isinstance(serving_resolution, dict):
            expected_serving = serving_resolution.get("product_serving_state")
            expected_serving = (
                expected_serving if isinstance(expected_serving, dict) else {}
            )
            expected_container = serving_resolution.get(
                "target_container_service_profile"
            )
            expected_container = (
                expected_container if isinstance(expected_container, dict) else {}
            )
            observed_temperature = _measurement_value(
                record, "observed_temperature"
            )
            observed_ice = _measurement_value(record, "observed_ice_presence")
            observed_container_temperature = _measurement_value(
                record, "observed_container_service_temperature"
            )
            expected_temperature = expected_serving.get("temperature")
            if expected_temperature != "not_applicable":
                if not isinstance(observed_temperature, str):
                    missing.append("observed_temperature")
                elif expected_temperature == "iced" and observed_temperature not in {
                    "iced",
                    "cold",
                }:
                    failures.append("serving_temperature_mismatch")
                elif expected_temperature != "iced" and observed_temperature != expected_temperature:
                    failures.append("serving_temperature_mismatch")
                if not isinstance(observed_ice, str):
                    missing.append("observed_ice_presence")
                elif expected_serving.get("ice_presence") in {"present", "absent"} and (
                    observed_ice != expected_serving["ice_presence"]
                ):
                    failures.append("ice_presence_mismatch")
            expected_container_temperature = expected_container.get(
                "service_temperature"
            )
            if expected_container_temperature in {"cold", "hot", "dual", "ambient"}:
                if not isinstance(observed_container_temperature, str):
                    missing.append("observed_container_service_temperature")
                elif (
                    expected_container_temperature != "dual"
                    and observed_container_temperature != expected_container_temperature
                ):
                    failures.append("container_service_temperature_mismatch")

        qualified = [f"{expected_id}.{name}" for name in missing]
        all_missing.extend(qualified)
        if failures:
            status: Literal["pass", "fail", "needs_review"] = "fail"
        elif missing or review_reasons:
            status = "needs_review"
        else:
            status = "pass"
        result: ProductQAResult = {
            "product_id": expected_id,
            "status": status,
            "hard_failures": failures,
            "missing_measurements": missing,
            "measurements": record,
        }
        if brand_result is not None:
            result["brand_result"] = brand_result
        if review_reasons:
            result["review_reasons"] = review_reasons
        product_results.append(result)
        hard_failures.extend(f"{expected_id}.{failure}" for failure in failures)

    if hard_failures:
        overall: Literal["passed", "needs_review", "rejected"] = "rejected"
    elif all_missing or any(item["status"] == "needs_review" for item in product_results):
        overall = "needs_review"
    else:
        overall = "passed"
    return {
        "schema_version": "1.0.0",
        "overall_status": overall,
        "expected_exact_product_ids": expected,
        "observed_exact_product_ids": observed,
        "product_results": product_results,
        "hard_failures": hard_failures,
        "missing_measurements": all_missing,
    }


def normalize_multi_product_qa(
    payload: dict[str, Any] | Sequence[dict[str, Any]],
    *,
    request: dict[str, Any],
) -> MultiProductQAReport:
    """Normalize evaluator payload variants into the typed multi-product QA gate."""
    if isinstance(payload, dict):
        product_measurements = payload.get("product_measurements", payload.get("products"))
        observed = payload.get("observed_exact_product_ids")
        observed_count = payload.get(
            "observed_exact_product_count", payload.get("exact_product_count")
        )
    else:
        product_measurements = payload
        observed = None
        observed_count = None
    if not isinstance(product_measurements, Sequence) or isinstance(
        product_measurements, (str, bytes)
    ):
        raise ValueError("Multi-product QA payload requires product_measurements")
    products = request.get("products")
    if not isinstance(products, list):
        raise ValueError("GenerationRequestV3 products must be an array")
    exact_ids = [
        product_id
        for product in products
        if isinstance(product, dict)
        and not _is_generic_product(product)
        and (product_id := _product_id(product)) is not None
    ]
    return evaluate_multi_product_qa(
        product_measurements,
        expected_product_ids=exact_ids,
        product_specs=products,
        observed_exact_product_ids=observed,
        observed_exact_product_count=observed_count,
    )


_WOOD_METRIC_ALIASES = {
    "delta_e00": ("delta_e_00", "delta_e"),
    "lightness_difference": ("delta_l", "lightness_delta"),
    "chroma_difference": ("delta_chroma", "chroma_delta"),
    "grain_direction_difference_degrees": (
        "grain_direction_delta",
        "grain_direction_delta_degrees",
    ),
    "grain_frequency_ratio": ("frequency_ratio",),
    "surface_coverage_error": ("surface_occupancy_error", "coverage_error"),
}


def _wood_value(measurements: dict[str, Any], name: str) -> Any:
    if name in measurements:
        return measurements[name]
    for alias in _WOOD_METRIC_ALIASES[name]:
        if alias in measurements:
            return measurements[alias]
    return None


def _upper_bound_metric(value: float, pass_limit: float, warning_limit: float) -> str:
    absolute = abs(value)
    if absolute <= pass_limit:
        return "pass"
    if absolute <= warning_limit:
        return "warning"
    return "fail"


def _frequency_metric(value: float) -> str:
    if 0.65 <= value <= 1.55:
        return "pass"
    if 0.50 <= value <= 2.00:
        return "warning"
    return "fail"


def evaluate_wood_material_qa(measurements: dict[str, Any]) -> WoodQAReport:
    """Apply the published wood fidelity thresholds and leakage hard gate."""
    if not isinstance(measurements, dict):
        raise ValueError("wood QA measurements must be an object")
    thresholds = {
        "delta_e00": (8.0, 12.0),
        "lightness_difference": (8.0, 12.0),
        "chroma_difference": (6.0, 10.0),
        "grain_direction_difference_degrees": (15.0, 25.0),
        "surface_coverage_error": (0.12, 0.20),
    }
    metrics: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []
    for name, (pass_limit, warning_limit) in thresholds.items():
        raw = _wood_value(measurements, name)
        if not _finite_number(raw):
            missing.append(name)
            continue
        value = float(raw)
        status = _upper_bound_metric(value, pass_limit, warning_limit)
        metrics[name] = {
            "value": value,
            "status": status,
            "pass_limit": pass_limit,
            "warning_limit": warning_limit,
        }
        if status == "fail":
            failures.append(name)
        elif status == "warning":
            warnings.append(name)

    frequency = _wood_value(measurements, "grain_frequency_ratio")
    if not _finite_number(frequency):
        missing.append("grain_frequency_ratio")
    else:
        frequency_value = float(frequency)
        frequency_status = _frequency_metric(frequency_value)
        metrics["grain_frequency_ratio"] = {
            "value": frequency_value,
            "status": frequency_status,
            "pass_range": [0.65, 1.55],
            "warning_range": [0.50, 2.00],
        }
        if frequency_status == "fail":
            failures.append("grain_frequency_ratio")
        elif frequency_status == "warning":
            warnings.append("grain_frequency_ratio")

    leakage_flags = []
    for name in (
        "swatch_boundary_detected",
        "source_object_copied",
        "source_text_copied",
        "source_layout_copied",
    ):
        if measurements.get(name) is True:
            leakage_flags.append(name)
    explicit_leakage = measurements.get("material_board_leakage")
    if explicit_leakage is True:
        leakage_flags.append("material_board_leakage")
    elif isinstance(explicit_leakage, (list, dict)) and bool(explicit_leakage):
        leakage_flags.append("material_board_leakage")
    if leakage_flags:
        failures.append("material_board_leakage")
        metrics["material_board_leakage"] = {
            "status": "fail",
            "detected": sorted(set(leakage_flags)),
        }

    if failures:
        overall: Literal[
            "passed", "passed_with_warnings", "needs_review", "rejected"
        ] = "rejected"
    elif missing:
        overall = "needs_review"
    elif warnings:
        overall = "passed_with_warnings"
    else:
        overall = "passed"
    return {
        "schema_version": "1.0.0",
        "overall_status": overall,
        "metrics": metrics,
        "hard_failures": failures,
        "warnings": warnings,
        "missing_measurements": missing,
    }


def normalize_wood_material_qa(measurements: dict[str, Any]) -> WoodQAReport:
    """Backwards-friendly name for the deterministic wood QA gate."""
    return evaluate_wood_material_qa(measurements)
