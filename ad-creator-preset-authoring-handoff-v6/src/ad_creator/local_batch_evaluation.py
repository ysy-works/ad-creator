from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contact_sheet import render_labeled_contact_sheet
from .image_contracts import canonical_image_binding
from .jsonio import load_json
from .runs import request_hash
from .v3_evaluator import (
    V3ImageMeasurementExtractor,
    validate_v3_image_evaluation_report,
)
from .vision_ocr import run_vision_ocr


LOCAL_BATCH_EVALUATION_SCHEMA_VERSION = "1.0.0"
LOCAL_BATCH_EVALUATOR_VERSION = "v3_local_output_batch_v2"
REQUIRED_CASE_COUNT = 20
GRID_COLUMNS = 5
GRID_ROWS = 4
MEASUREMENT_CATEGORIES = (
    "exact_product_count",
    "brand",
    "container",
    "material",
    "layout",
)
OCR_FAILURE_TOKENS = (
    "brand",
    "logo",
    "glyph",
    "pseudotext",
)
OCR_CONCLUSIVE_CONFIDENCE = 0.90
OCR_TARGET_BBOX_MARGIN = 0.15
LAYOUT_MEASUREMENT_NAMES = (
    "observed_product_id",
    "center_position_error",
    "width_ratio",
    "height_ratio",
    "target_bbox_iou",
    "frame_margin",
    "support_relation_match",
    "occlusion_relation_match",
    "active_relation_match",
    "product_record",
)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _local_path(value: Any, *, base: Path, field: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(f"{field} requires a local filesystem path")
    text = str(value).strip()
    if "://" in text or text.casefold().startswith(("data:", "file:")):
        raise ValueError(f"{field} must not be a URL or URI")
    path = Path(text).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _object_or_json_path(value: Any, *, base: Path, field: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = _local_path(value, base=base, field=field)
    if not path.is_file():
        raise FileNotFoundError(f"{field} does not exist: {path}")
    return load_json(path)


def _is_generic(product: Mapping[str, Any]) -> bool:
    return bool(product.get("is_generic")) or product.get("role") == "generic" or (
        product.get("source_type") == "generic"
    )


def _exact_product_ids(request: Mapping[str, Any]) -> list[str]:
    products = request.get("products")
    if not isinstance(products, list):
        raise ValueError("GenerationRequestV3 products must be an array")
    result = [
        product.get("product_id")
        for product in products
        if isinstance(product, Mapping) and not _is_generic(product)
    ]
    if not 1 <= len(result) <= 3 or any(
        not isinstance(product_id, str) or not product_id.strip()
        for product_id in result
    ):
        raise ValueError("Each case requires one to three exact product IDs")
    if len(set(result)) != len(result):
        raise ValueError("Exact product IDs must be unique")
    return [str(product_id) for product_id in result]


def _constant_evidence_hook(evidence: Mapping[str, Any]):
    frozen = copy.deepcopy(dict(evidence))

    def hook(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return copy.deepcopy(frozen)

    return hook


def _redacted_evaluation_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Remove every transport image path before the evaluator hashes a request.

    ``runs.request_hash`` normally fingerprints provider input bytes.  Post-run
    local evaluation must not reopen user originals, references, control
    boards, or raw crops, so this copy retains roles and product IDs while all
    transport paths become non-filesystem virtual identities.
    """

    value = copy.deepcopy(dict(request))
    generation = value.get("generation")
    if isinstance(generation, dict):
        image_inputs = generation.get("image_inputs")
        if isinstance(image_inputs, list):
            for index, image_input in enumerate(image_inputs):
                if isinstance(image_input, dict) and "path" in image_input:
                    role = str(image_input.get("role") or "unspecified")
                    image_input["path"] = (
                        f"redacted-local-evaluation/{index:02d}/{role}"
                    )
        image_paths = generation.get("image_paths")
        if isinstance(image_paths, list):
            generation["image_paths"] = [
                f"redacted-local-evaluation/{index:02d}/legacy"
                for index, _item in enumerate(image_paths)
            ]
    products = value.get("products")
    if isinstance(products, list):
        for product in products:
            if isinstance(product, dict) and "source_image" in product:
                product["source_image"] = "redacted-local-evaluation/product-source"
    return value


def _load_case(
    raw_case: Mapping[str, Any],
    *,
    manifest_base: Path,
) -> dict[str, Any]:
    case_id = raw_case.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("Every local evaluation case requires case_id")

    run_manifest = None
    run_manifest_value = raw_case.get("run_manifest", raw_case.get("manifest"))
    if run_manifest_value is not None:
        run_manifest_path = _local_path(
            run_manifest_value,
            base=manifest_base,
            field=f"cases[{case_id}].run_manifest",
        )
        if not run_manifest_path.is_file():
            raise FileNotFoundError(f"Run manifest does not exist: {run_manifest_path}")
        run_manifest = load_json(run_manifest_path)

    request_value = raw_case.get("request", raw_case.get("request_path"))
    if request_value is None and isinstance(run_manifest, Mapping):
        request_value = run_manifest.get("request")
    if request_value is None:
        raise ValueError(f"Case {case_id} requires a V3 request or run manifest")
    request = _object_or_json_path(
        request_value,
        base=manifest_base,
        field=f"cases[{case_id}].request",
    )
    if request.get("schema_version") != "3.0.0":
        raise ValueError(f"Case {case_id} requires GenerationRequestV3")
    _exact_product_ids(request)

    output_value = raw_case.get("output_path")
    if output_value is None and isinstance(run_manifest, Mapping):
        artifacts = run_manifest.get("artifacts")
        if isinstance(artifacts, Mapping):
            output_value = artifacts.get("provider_output")
    output_path = _local_path(
        output_value,
        base=manifest_base,
        field=f"cases[{case_id}].output_path",
    )
    if not output_path.is_file():
        raise FileNotFoundError(f"Generated output does not exist: {output_path}")

    raw_evidence = raw_case.get("local_evidence", {})
    if not isinstance(raw_evidence, Mapping):
        raise ValueError(f"Case {case_id} local_evidence must be an object")
    evidence: dict[str, dict[str, Any]] = {}
    for field in (
        "product_region",
        "brand_ocr",
        "ocr_full_image",
        "wood_region",
        "leakage",
        "container",
    ):
        if raw_evidence.get(field) is not None:
            evidence[field] = _object_or_json_path(
                raw_evidence[field],
                base=manifest_base,
                field=f"cases[{case_id}].local_evidence.{field}",
            )
    return {
        "case_id": case_id.strip(),
        "output_path": output_path,
        "request": request,
        "evidence": evidence,
    }


def _container_result(
    evidence: Mapping[str, Any] | None,
    *,
    pixel_sha256: str,
    expected_product_ids: list[str],
) -> dict[str, Any]:
    if evidence is None:
        return {
            "state": "missing",
            "available": False,
            "missing_measurements": [
                f"{product_id}.container_match" for product_id in expected_product_ids
            ],
            "hard_failures": [],
            "detector": None,
        }
    if evidence.get("input_pixel_sha256") != pixel_sha256:
        raise ValueError("Container evidence is not bound to the evaluated image pixels")
    detector = evidence.get("detector")
    if not isinstance(detector, Mapping) or any(
        not isinstance(detector.get(field), str) or not detector[field].strip()
        for field in ("name", "version")
    ):
        raise ValueError("Container evidence requires detector name and version")
    products = evidence.get("products")
    if not isinstance(products, list):
        raise ValueError("Container evidence products must be an array")
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in products:
        if not isinstance(item, Mapping):
            raise ValueError("Container evidence product must be an object")
        product_id = item.get("product_id")
        if not isinstance(product_id, str) or product_id in by_id:
            raise ValueError("Container evidence product IDs must be unique strings")
        by_id[product_id] = item
    missing: list[str] = []
    failures: list[str] = []
    measurements: list[dict[str, Any]] = []
    for product_id in expected_product_ids:
        item = by_id.get(product_id)
        if item is None or not isinstance(item.get("matched"), bool):
            missing.append(f"{product_id}.container_match")
            continue
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not (
            0 <= float(confidence) <= 1
        ):
            missing.append(f"{product_id}.container_confidence")
            continue
        measurements.append(
            {
                "product_id": product_id,
                "matched": item["matched"],
                "confidence": float(confidence),
            }
        )
        if item["matched"] is False:
            failures.append(f"{product_id}.container_mismatch")
    return {
        "state": "missing" if missing else "available",
        "available": not missing,
        "missing_measurements": missing,
        "hard_failures": failures,
        "detector": copy.deepcopy(dict(detector)),
        "measurements": measurements,
    }


def _normalized_ocr_text(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _ocr_words(value: str) -> list[str]:
    return [
        token.casefold()
        for token in re.findall(r"[^\W_]+", value, flags=re.UNICODE)
        if token
    ]


def _normalized_bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, float] = {}
    for field in ("left", "top", "right", "bottom"):
        coordinate = value.get(field)
        if (
            not isinstance(coordinate, (int, float))
            or isinstance(coordinate, bool)
        ):
            return None
        result[field] = float(coordinate)
    if not (
        0 <= result["left"] < result["right"] <= 1
        and 0 <= result["top"] < result["bottom"] <= 1
    ):
        return None
    return result


def _target_product_bboxes(request: Mapping[str, Any]) -> list[dict[str, float]]:
    scene_graph = request.get("scene_graph_contract")
    slot_plan = scene_graph.get("slot_plan") if isinstance(scene_graph, Mapping) else None
    bindings = slot_plan.get("bindings") if isinstance(slot_plan, Mapping) else None
    if not isinstance(bindings, list):
        return []
    result: list[dict[str, float]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping):
            continue
        bbox = _normalized_bbox(binding.get("target_bbox"))
        if bbox is not None:
            result.append(bbox)
    return result


def _bbox_near_any_target(
    bboxes: list[dict[str, float]],
    targets: list[dict[str, float]],
) -> bool:
    for bbox in bboxes:
        center_x = (bbox["left"] + bbox["right"]) / 2
        center_y = (bbox["top"] + bbox["bottom"]) / 2
        for target in targets:
            if (
                max(0.0, target["left"] - OCR_TARGET_BBOX_MARGIN)
                <= center_x
                <= min(1.0, target["right"] + OCR_TARGET_BBOX_MARGIN)
                and max(0.0, target["top"] - OCR_TARGET_BBOX_MARGIN)
                <= center_y
                <= min(1.0, target["bottom"] + OCR_TARGET_BBOX_MARGIN)
            ):
                return True
    return False


def _comparable_logo_candidates(expected: str, observed: str) -> list[str]:
    """Return OCR spans with the same token count and glyph counts as a logo.

    This intentionally treats ``n.u.m.`` and ``m.u.m.`` as comparable while
    refusing to turn a clipped ``OSOME PLACE`` reading into proof that the
    rendered ``ATWOSOME PLACE`` glyphs are wrong.
    """

    expected_words = _ocr_words(expected)
    observed_words = _ocr_words(observed)
    if not expected_words or len(observed_words) < len(expected_words):
        return []
    signature = tuple(len(token) for token in expected_words)
    candidates: list[str] = []
    width = len(expected_words)
    for start in range(len(observed_words) - width + 1):
        window = observed_words[start : start + width]
        if tuple(len(token) for token in window) == signature:
            candidates.append("".join(window))
    return candidates


def _ocr_observations(
    regions: Mapping[str, Any],
    *,
    source_scope: str,
    request: Mapping[str, Any],
) -> list[dict[str, Any]]:
    targets = _target_product_bboxes(request)
    observations: list[dict[str, Any]] = []
    for region_id, region in regions.items():
        if not isinstance(region, Mapping):
            raise ValueError("OCR evidence region must be an object")
        if region.get("detected") is not True:
            continue
        text = region.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Detected OCR region requires text")
        raw_confidence = region.get("confidence")
        confidence = (
            float(raw_confidence)
            if isinstance(raw_confidence, (int, float))
            and not isinstance(raw_confidence, bool)
            and 0 <= float(raw_confidence) <= 1
            else None
        )
        raw_bboxes = region.get("bboxes")
        bboxes = (
            [bbox for item in raw_bboxes if (bbox := _normalized_bbox(item))]
            if isinstance(raw_bboxes, list)
            else []
        )
        bbox_evidence_complete = bool(bboxes) and (
            isinstance(raw_bboxes, list) and len(bboxes) == len(raw_bboxes)
        )
        if source_scope == "product_regions":
            target_location_supported = bbox_evidence_complete
        else:
            target_location_supported = bbox_evidence_complete and bool(targets) and (
                _bbox_near_any_target(bboxes, targets)
            )
        observations.append(
            {
                "region_id": str(region_id),
                "text": text.strip(),
                "normalized_text": _normalized_ocr_text(text),
                "confidence": confidence,
                "bboxes": bboxes,
                "bbox_evidence_complete": bbox_evidence_complete,
                "target_location_supported": target_location_supported,
            }
        )
    return observations


def _verified_logo_ocr_decision(
    allowed_logo_texts: list[str],
    observations: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    hard_failures: list[str] = []
    review_reasons: list[str] = []
    comparisons: list[dict[str, Any]] = []
    for expected in allowed_logo_texts:
        expected_normalized = _normalized_ocr_text(expected)
        exact: list[dict[str, Any]] = []
        conflicting: list[dict[str, Any]] = []
        for observation in observations:
            candidates = _comparable_logo_candidates(expected, observation["text"])
            conclusive = bool(
                observation["bbox_evidence_complete"]
                and observation["target_location_supported"]
                and isinstance(observation["confidence"], float)
                and observation["confidence"] >= OCR_CONCLUSIVE_CONFIDENCE
            )
            comparison = {
                "expected_text": expected,
                "region_id": observation["region_id"],
                "candidates": candidates,
                "confidence": observation["confidence"],
                "bbox_evidence_complete": observation["bbox_evidence_complete"],
                "target_location_supported": observation[
                    "target_location_supported"
                ],
                "conclusive": conclusive,
            }
            comparisons.append(comparison)
            for candidate in candidates:
                record = {**comparison, "candidate": candidate}
                if candidate == expected_normalized:
                    exact.append(record)
                else:
                    conflicting.append(record)

        if any(item["conclusive"] for item in exact):
            continue
        if exact:
            review_reasons.append("ocr.logo_text_evidence_inconclusive")
            continue
        if any(item["conclusive"] for item in conflicting):
            hard_failures.append("ocr.logo_or_pseudotext_mismatch")
            continue
        if conflicting:
            review_reasons.append("ocr.logo_text_evidence_inconclusive")
        elif observations:
            review_reasons.append("ocr.partial_or_noncomparable_logo_text")
        else:
            review_reasons.append("ocr.required_logo_not_detected")
    return (
        list(dict.fromkeys(hard_failures)),
        list(dict.fromkeys(review_reasons)),
        comparisons,
    )


def _ocr_policy_result(
    evidence: Mapping[str, Any] | None,
    *,
    output_path: Path,
    pixel_sha256: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    source_scope = "full_image"
    raw = copy.deepcopy(dict(evidence)) if isinstance(evidence, Mapping) else None
    if raw is None:
        try:
            raw = run_vision_ocr(output_path)
        except Exception as exc:
            return {
                "state": "missing",
                "available": False,
                "scope": source_scope,
                "detector": None,
                "observed_texts": [],
                "allowed_logo_texts": [],
                "hard_failures": [],
                "missing_measurements": ["full_image_ocr"],
                "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        source_scope = str(raw.pop("_batch_scope", "product_regions"))
    if raw.get("input_pixel_sha256") != pixel_sha256:
        raise ValueError("OCR evidence is not bound to the evaluated image pixels")
    detector = raw.get("detector")
    if not isinstance(detector, Mapping) or any(
        not isinstance(detector.get(field), str) or not detector[field].strip()
        for field in ("name", "version")
    ):
        raise ValueError("OCR evidence requires detector name and version")
    regions = raw.get("regions")
    if not isinstance(regions, Mapping):
        raise ValueError("OCR evidence regions must be an object")
    observations = _ocr_observations(
        regions,
        source_scope=source_scope,
        request=request,
    )
    observed_texts = [item["text"] for item in observations]

    products = request.get("products")
    products = products if isinstance(products, list) else []
    allowed_logo_texts = []
    for product in products:
        if not isinstance(product, Mapping) or _is_generic(product):
            continue
        target = product.get("target_brand_contract")
        if not isinstance(target, Mapping):
            continue
        allowed = target.get("allowed_main_text")
        if target.get("state") == "verified_present" and isinstance(allowed, str) and allowed.strip():
            allowed_logo_texts.append(allowed.strip())
    failures: list[str] = []
    review_reasons: list[str] = []
    comparisons: list[dict[str, Any]] = []
    if observations and not allowed_logo_texts:
        # Unbranded targets stay strict: any detected logo-like or pseudo-text
        # remains a hard failure even when OCR confidence is low.  A low score
        # cannot authorize invented markings on a verified-unbranded product.
        failures.append("ocr.forbidden_logo_or_pseudotext_detected")
    elif allowed_logo_texts:
        failures, review_reasons, comparisons = _verified_logo_ocr_decision(
            allowed_logo_texts,
            observations,
        )
    decision = (
        "reject"
        if failures
        else "manual_review"
        if review_reasons
        else "pass"
    )
    return {
        "state": "available",
        "available": True,
        "scope": source_scope,
        "detector": copy.deepcopy(dict(detector)),
        "observed_texts": observed_texts,
        "observations": observations,
        "allowed_logo_texts": allowed_logo_texts,
        "hard_failures": failures,
        "needs_review_reasons": review_reasons,
        "comparisons": comparisons,
        "decision": decision,
        "missing_measurements": [],
    }


def _batch_ocr_evidence(evidence: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if isinstance(evidence.get("ocr_full_image"), Mapping):
        value = copy.deepcopy(dict(evidence["ocr_full_image"]))
        value["_batch_scope"] = "full_image"
        return value
    brand = evidence.get("brand_ocr")
    if isinstance(brand, Mapping):
        value = copy.deepcopy(dict(brand))
        value["_batch_scope"] = "product_regions"
        return value
    return None


def _measurement_availability(
    report: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    container: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    missing = [str(item) for item in report.get("missing_measurements", [])]
    versions = report.get("evidence_versions")
    versions = versions if isinstance(versions, Mapping) else {}
    multi = report.get("qa", {}).get("multi_product", {})
    multi_missing = [str(item) for item in multi.get("missing_measurements", [])]

    count_missing = any(
        item == "observed_exact_product_count" for item in multi_missing
    )
    exact_available = isinstance(versions.get("product_region"), Mapping) and not count_missing
    brand_available = isinstance(versions.get("brand_ocr"), Mapping) and not any(
        item.startswith("brand_ocr.") for item in missing
    )
    brand_results = multi.get("product_results", [])
    if not isinstance(brand_results, list) or any(
        not isinstance(item, Mapping) or not isinstance(item.get("brand_result"), Mapping)
        for item in brand_results
    ):
        brand_available = False
    layout_missing = [
        item
        for item in multi_missing
        if item == "observed_exact_product_count"
        or any(item == name or item.endswith(f".{name}") for name in LAYOUT_MEASUREMENT_NAMES)
    ]
    layout_available = isinstance(versions.get("product_region"), Mapping) and not layout_missing

    wood_profile = request.get("wood_material_profile")
    wood_report = report.get("qa", {}).get("wood")
    if not isinstance(wood_profile, Mapping):
        material = {
            "state": "not_applicable",
            "available": True,
            "missing_measurements": [],
        }
    else:
        wood_missing = (
            [str(item) for item in wood_report.get("missing_measurements", [])]
            if isinstance(wood_report, Mapping)
            else ["wood_report"]
        )
        material = {
            "state": "missing" if wood_missing else "available",
            "available": not wood_missing,
            "missing_measurements": wood_missing,
        }

    return {
        "exact_product_count": {
            "state": "available" if exact_available else "missing",
            "available": exact_available,
            "missing_measurements": (
                [] if exact_available else ["observed_exact_product_count"]
            ),
        },
        "brand": {
            "state": "available" if brand_available else "missing",
            "available": brand_available,
            "missing_measurements": [] if brand_available else ["brand_ocr"],
        },
        "container": copy.deepcopy(dict(container)),
        "material": material,
        "layout": {
            "state": "available" if layout_available else "missing",
            "available": layout_available,
            "missing_measurements": layout_missing or (
                [] if layout_available else ["product_region_detector"]
            ),
        },
    }


def _evaluate_case(
    case: Mapping[str, Any],
    *,
    project_root: Path,
    reports_dir: Path,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    output_path = Path(case["output_path"])
    request = case["request"]
    evaluation_request = _redacted_evaluation_request(request)
    evidence = case["evidence"]
    binding = canonical_image_binding(output_path)
    extractor = V3ImageMeasurementExtractor(
        product_region_hook=(
            _constant_evidence_hook(evidence["product_region"])
            if "product_region" in evidence
            else None
        ),
        brand_evidence_hook=(
            _constant_evidence_hook(evidence["brand_ocr"])
            if "brand_ocr" in evidence
            else None
        ),
        wood_region_hook=(
            _constant_evidence_hook(evidence["wood_region"])
            if "wood_region" in evidence
            else None
        ),
        leakage_evidence_hook=(
            _constant_evidence_hook(evidence["leakage"])
            if "leakage" in evidence
            else None
        ),
        use_system_ocr=not (
            "brand_ocr" in evidence or "ocr_full_image" in evidence
        ),
    )
    report = extractor.extract(
        output_path,
        request=evaluation_request,
        project_root=project_root,
    )
    report_path = reports_dir / f"{case_id}.json"
    _write_json_atomic(report_path, report)

    container = _container_result(
        evidence.get("container"),
        pixel_sha256=binding["pixel_sha256"],
        expected_product_ids=_exact_product_ids(request),
    )
    ocr_result = _ocr_policy_result(
        _batch_ocr_evidence(evidence),
        output_path=output_path,
        pixel_sha256=binding["pixel_sha256"],
        request=evaluation_request,
    )
    availability = _measurement_availability(
        report,
        request=evaluation_request,
        container=container,
    )
    if ocr_result["state"] == "missing":
        availability["brand"] = {
            "state": "missing",
            "available": False,
            "missing_measurements": list(ocr_result["missing_measurements"]),
        }
    evaluator_failures = [str(item) for item in report.get("hard_failures", [])]
    container_failures = [str(item) for item in container.get("hard_failures", [])]
    hard_failures = list(
        dict.fromkeys(
            [
                *evaluator_failures,
                *container_failures,
                *[str(item) for item in ocr_result["hard_failures"]],
            ]
        )
    )
    ocr_failures = [
        item
        for item in hard_failures
        if any(token in item.casefold() for token in OCR_FAILURE_TOKENS)
    ]
    missing_categories = [
        category
        for category, item in availability.items()
        if item.get("state") == "missing"
    ]
    if hard_failures:
        status = "fail"
    elif report.get("overall_status") == "rejected":
        status = "fail"
    elif ocr_result.get("needs_review_reasons") or report.get(
        "missing_measurements"
    ) or missing_categories or (
        report.get("overall_status") == "needs_review"
    ):
        status = "needs_review"
    else:
        status = "pass"
    return {
        "case_id": case_id,
        "status": status,
        "output_path": str(output_path),
        "output_pixel_sha256": binding["pixel_sha256"],
        "generation_request_sha256": report["generation_request_sha256"],
        "generation_request_hash_scope": "paths_redacted_no_source_pixels",
        "v3_evaluation_report": str(report_path.resolve()),
        "v3_evaluation_report_sha256": report["report_sha256"],
        "ocr_evidence": ocr_result,
        "measurement_availability": availability,
        "missing_measurement_categories": missing_categories,
        "hard_failures": hard_failures,
        "ocr_logo_or_pseudotext_hard_failures": ocr_failures,
        "warnings": copy.deepcopy(
            report.get("qa", {}).get("wood", {}).get("warnings", [])
            if isinstance(report.get("qa", {}).get("wood"), Mapping)
            else []
        ),
    }


def _error_case(case: Mapping[str, Any], exc: Exception) -> dict[str, Any]:
    output_path = Path(case["output_path"])
    binding = canonical_image_binding(output_path)
    availability = {
        category: {
            "state": "missing",
            "available": False,
            "missing_measurements": [f"evaluation_error:{type(exc).__name__}"],
        }
        for category in MEASUREMENT_CATEGORIES
    }
    return {
        "case_id": case["case_id"],
        "status": "needs_review",
        "output_path": str(output_path),
        "output_pixel_sha256": binding["pixel_sha256"],
        "generation_request_sha256": request_hash(
            _redacted_evaluation_request(case["request"])
        ),
        "generation_request_hash_scope": "paths_redacted_no_source_pixels",
        "v3_evaluation_report": None,
        "v3_evaluation_report_sha256": None,
        "ocr_evidence": {
            "state": "missing",
            "available": False,
            "hard_failures": [],
            "missing_measurements": ["evaluation_error"],
        },
        "measurement_availability": availability,
        "missing_measurement_categories": list(MEASUREMENT_CATEGORIES),
        "hard_failures": [],
        "ocr_logo_or_pseudotext_hard_failures": [],
        "warnings": [],
        "evaluation_error": f"{type(exc).__name__}: {exc}",
    }


def _evidence_by_case(value: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if value is None:
        return {}
    raw = value.get("local_evidence_by_case")
    if isinstance(raw, Mapping):
        result: dict[str, Mapping[str, Any]] = {}
        for case_id, evidence in raw.items():
            if not isinstance(case_id, str) or not isinstance(evidence, Mapping):
                raise ValueError("Local evidence map must bind case IDs to objects")
            result[case_id] = evidence
        return result
    cases = value.get("cases")
    if isinstance(cases, list):
        result = {}
        for item in cases:
            if not isinstance(item, Mapping):
                raise ValueError("Local evidence case must be an object")
            case_id = item.get("case_id")
            evidence = item.get("local_evidence", {})
            if not isinstance(case_id, str) or not isinstance(evidence, Mapping):
                raise ValueError("Local evidence case requires case_id and local_evidence")
            result[case_id] = evidence
        return result
    result = {}
    for case_id, evidence in value.items():
        if case_id in {"schema_version", "batch_id"}:
            continue
        if not isinstance(case_id, str) or not isinstance(evidence, Mapping):
            raise ValueError("Local evidence map must bind case IDs to objects")
        result[case_id] = evidence
    return result


def _diagnostic_result_cases(
    result: Mapping[str, Any],
    *,
    request_bundle: Mapping[str, Any] | None,
    evidence_manifest: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if request_bundle is None:
        raise ValueError(
            "Diagnostic matrix results require the matching request bundle"
        )
    if request_bundle.get("artifact_type") != "v3_diagnostic_paid_matrix_bundle":
        raise ValueError("Diagnostic request bundle has the wrong artifact_type")
    bundle_hash = request_bundle.get("bundle_sha256")
    stable_bundle = copy.deepcopy(dict(request_bundle))
    stable_bundle.pop("bundle_sha256", None)
    if bundle_hash != _canonical_hash(stable_bundle):
        raise ValueError("Diagnostic request bundle hash does not match its contents")
    if result.get("matrix_id") != request_bundle.get("matrix_id") or result.get(
        "matrix_sha256"
    ) != request_bundle.get("matrix_sha256"):
        raise ValueError("Diagnostic result and request bundle describe different matrices")
    result_cases = result.get("case_results")
    requests = request_bundle.get("requests")
    if (
        not isinstance(result_cases, list)
        or not isinstance(requests, list)
        or len(result_cases) != REQUIRED_CASE_COUNT
        or len(requests) != REQUIRED_CASE_COUNT
    ):
        raise ValueError("Diagnostic result and bundle must each contain 20 cases")
    request_by_id = {
        item.get("case_id"): item.get("request")
        for item in requests
        if isinstance(item, Mapping)
    }
    if len(request_by_id) != REQUIRED_CASE_COUNT:
        raise ValueError("Diagnostic request bundle case IDs are incomplete or duplicated")
    evidence_by_id = _evidence_by_case(evidence_manifest)
    cases: list[dict[str, Any]] = []
    for item in result_cases:
        if not isinstance(item, Mapping):
            raise ValueError("Diagnostic result case must be an object")
        case_id = item.get("case_id")
        output_path = item.get("provider_output")
        if not isinstance(case_id, str) or case_id not in request_by_id:
            raise ValueError("Diagnostic result case has no matching request")
        if not isinstance(output_path, str) or not output_path.strip():
            raise ValueError(
                f"Diagnostic case {case_id} has no completed provider output"
            )
        cases.append(
            {
                "case_id": case_id,
                "output_path": output_path,
                "request": request_by_id[case_id],
                "local_evidence": copy.deepcopy(dict(evidence_by_id.get(case_id, {}))),
            }
        )
    if [item.get("case_id") for item in requests] != [
        item["case_id"] for item in cases
    ]:
        raise ValueError("Diagnostic result order differs from the request bundle")
    return cases


def evaluate_local_output_batch(
    manifest: str | Path | Mapping[str, Any],
    *,
    output_dir: str | Path,
    project_root: str | Path | None = None,
    request_bundle: str | Path | Mapping[str, Any] | None = None,
    local_evidence_manifest: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate exactly 20 generated outputs without generation or network access."""

    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else Path.cwd().resolve()
    )
    if isinstance(manifest, Mapping):
        manifest_value = copy.deepcopy(dict(manifest))
        manifest_base = root
        manifest_sha256 = _canonical_hash(manifest_value)
        manifest_path = None
    else:
        manifest_path = _local_path(manifest, base=root, field="manifest")
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Batch manifest does not exist: {manifest_path}")
        manifest_value = load_json(manifest_path)
        manifest_base = manifest_path.parent
        manifest_sha256 = _file_sha256(manifest_path)

    input_artifact_hashes = {"output_manifest": manifest_sha256}
    request_bundle_value = None
    if request_bundle is not None:
        request_bundle_value = _object_or_json_path(
            request_bundle,
            base=manifest_base,
            field="request_bundle",
        )
        input_artifact_hashes["request_bundle"] = _canonical_hash(
            request_bundle_value
        )
    evidence_manifest_value = None
    if local_evidence_manifest is not None:
        evidence_manifest_value = _object_or_json_path(
            local_evidence_manifest,
            base=manifest_base,
            field="local_evidence_manifest",
        )
        input_artifact_hashes["local_evidence_manifest"] = _canonical_hash(
            evidence_manifest_value
        )

    if manifest_value.get("artifact_type") == (
        "v3_diagnostic_paid_matrix_execution_result"
    ):
        cases_value = _diagnostic_result_cases(
            manifest_value,
            request_bundle=request_bundle_value,
            evidence_manifest=evidence_manifest_value,
        )
    else:
        cases_value = manifest_value.get("cases")
    if not isinstance(cases_value, list) or len(cases_value) != REQUIRED_CASE_COUNT:
        raise ValueError("Local output batch must contain exactly 20 cases")
    if any(not isinstance(item, Mapping) for item in cases_value):
        raise ValueError("Local output batch cases must be objects")
    cases = [
        _load_case(item, manifest_base=manifest_base)
        for item in cases_value
    ]
    case_ids = [case["case_id"] for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Local output batch case IDs must be unique")
    destination = Path(output_dir).expanduser()
    destination = destination.resolve() if destination.is_absolute() else (root / destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    reports_dir = destination / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            results.append(
                _evaluate_case(case, project_root=root, reports_dir=reports_dir)
            )
        except Exception as exc:
            # Detector absence, invalid local evidence, and OCR unavailability
            # can never become a pass.  Keep the full 20-case review surface.
            results.append(_error_case(case, exc))

    sheet_cells = [
        {
            "case_id": result["case_id"],
            "status": result["status"],
            "image_path": result["output_path"],
            "output_pixel_sha256": result["output_pixel_sha256"],
            "detail": (
                f"hard={len(result['hard_failures'])} "
                f"missing={len(result['missing_measurement_categories'])}"
            ),
        }
        for result in results
    ]
    contact_sheet = render_labeled_contact_sheet(
        sheet_cells,
        destination / "contact-sheet-5x4.jpg",
        columns=GRID_COLUMNS,
        rows=GRID_ROWS,
    )
    status_counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("pass", "needs_review", "fail")
    }
    availability_counts = {
        category: {
            state: sum(
                result["measurement_availability"][category]["state"] == state
                for result in results
            )
            for state in ("available", "missing", "not_applicable")
        }
        for category in MEASUREMENT_CATEGORIES
    }
    summary: dict[str, Any] = {
        "schema_version": LOCAL_BATCH_EVALUATION_SCHEMA_VERSION,
        "evaluator_version": LOCAL_BATCH_EVALUATOR_VERSION,
        "batch_id": str(manifest_value.get("batch_id") or "local-v3-output-batch"),
        "input_manifest": str(manifest_path) if manifest_path is not None else None,
        "input_manifest_sha256": manifest_sha256,
        "input_artifact_hashes": input_artifact_hashes,
        "input_contract_sha256": _canonical_hash(input_artifact_hashes),
        "case_count": len(results),
        "status_counts": status_counts,
        "measurement_availability_counts": availability_counts,
        "ocr_logo_or_pseudotext_hard_failure_count": sum(
            bool(result["ocr_logo_or_pseudotext_hard_failures"])
            for result in results
        ),
        "grid": contact_sheet,
        "cases": results,
        "privacy": {
            "execution": "local_only",
            "network_access": False,
            "generation_performed": False,
            "source_or_reference_images_read": False,
            "evaluated_artifact_roles": [
                "generated_output",
                "generation_request_contract",
                "local_detector_evidence",
            ],
        },
    }
    summary["summary_sha256"] = _canonical_hash(summary)
    validate_local_batch_evaluation_summary(summary)
    _write_json_atomic(destination / "summary.json", summary)
    return summary


def validate_local_batch_evaluation_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(summary))
    expected_hash = value.pop("summary_sha256", None)
    if expected_hash != _canonical_hash(value):
        raise ValueError("Local batch evaluation summary hash does not match")
    if value.get("schema_version") != LOCAL_BATCH_EVALUATION_SCHEMA_VERSION:
        raise ValueError("Unsupported local batch evaluation schema")
    if value.get("case_count") != REQUIRED_CASE_COUNT:
        raise ValueError("Local batch evaluation must contain 20 cases")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != REQUIRED_CASE_COUNT:
        raise ValueError("Local batch evaluation cases are incomplete")
    if any(
        not isinstance(case, Mapping)
        or case.get("status") not in {"pass", "needs_review", "fail"}
        for case in cases
    ):
        raise ValueError("Local batch evaluation has an invalid case status")
    expected_status_counts = {
        status: sum(case.get("status") == status for case in cases)
        for status in ("pass", "needs_review", "fail")
    }
    if value.get("status_counts") != expected_status_counts:
        raise ValueError("Local batch evaluation status counts do not match cases")
    expected_availability_counts = {
        category: {
            state: sum(
                isinstance(case.get("measurement_availability"), Mapping)
                and isinstance(
                    case["measurement_availability"].get(category), Mapping
                )
                and case["measurement_availability"][category].get("state") == state
                for case in cases
            )
            for state in ("available", "missing", "not_applicable")
        }
        for category in MEASUREMENT_CATEGORIES
    }
    if value.get("measurement_availability_counts") != expected_availability_counts:
        raise ValueError(
            "Local batch evaluation availability counts do not match cases"
        )
    grid = value.get("grid")
    if not isinstance(grid, Mapping) or (
        grid.get("columns") != GRID_COLUMNS or grid.get("rows") != GRID_ROWS
    ):
        raise ValueError("Local batch evaluation grid must be 5x4")
    grid_cells = grid.get("cells")
    if not isinstance(grid_cells, list) or len(grid_cells) != REQUIRED_CASE_COUNT:
        raise ValueError("Local batch evaluation grid cells are incomplete")
    for index, (cell, case) in enumerate(zip(grid_cells, cases, strict=True)):
        if not isinstance(cell, Mapping) or any(
            (
                cell.get("index") != index,
                cell.get("row") != index // GRID_COLUMNS,
                cell.get("column") != index % GRID_COLUMNS,
                cell.get("case_id") != case.get("case_id"),
                cell.get("status") != case.get("status"),
                cell.get("output_pixel_sha256")
                != case.get("output_pixel_sha256"),
            )
        ):
            raise ValueError("Local batch evaluation grid metadata differs from cases")
    grid_path = Path(str(grid.get("path", ""))).expanduser()
    if not grid_path.is_file():
        raise ValueError("Local batch evaluation contact sheet is missing")
    if grid.get("file_sha256") != _file_sha256(grid_path):
        raise ValueError("Local batch evaluation contact sheet file hash differs")
    grid_binding = canonical_image_binding(grid_path)
    if any(
        grid.get(field) != grid_binding[binding_field]
        for field, binding_field in (
            ("pixel_sha256", "pixel_sha256"),
            ("width_px", "width_px"),
            ("height_px", "height_px"),
        )
    ):
        raise ValueError("Local batch evaluation contact sheet pixels differ")
    for case in cases:
        report_path_value = case.get("v3_evaluation_report")
        if report_path_value is None:
            if case.get("status") == "pass":
                raise ValueError("Passing local case requires a V3 evaluation report")
            continue
        report_path = Path(str(report_path_value)).expanduser()
        if not report_path.is_file():
            raise ValueError("Local batch V3 evaluation report is missing")
        report = validate_v3_image_evaluation_report(load_json(report_path))
        if report.get("report_sha256") != case.get("v3_evaluation_report_sha256"):
            raise ValueError("Local batch V3 report hash differs from case metadata")
    privacy = value.get("privacy")
    if not isinstance(privacy, Mapping) or any(
        privacy.get(field) is not False
        for field in ("network_access", "generation_performed", "source_or_reference_images_read")
    ):
        raise ValueError("Local batch evaluation privacy contract is invalid")
    value["summary_sha256"] = expected_hash
    return value
