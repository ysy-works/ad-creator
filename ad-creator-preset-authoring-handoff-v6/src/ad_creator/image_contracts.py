from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from PIL import Image, ImageOps, ImageStat

from .serving_contracts import validate_serving_state


BRAND_STATES = {"verified_present", "verified_absent", "uncertain"}
PRODUCT_KINDS = {"beverage", "dessert"}
BRAND_TRANSFER_POLICY_VERSION = "strict_auto_v1"
TARGET_BRAND_POLICY_VERSION = BRAND_TRANSFER_POLICY_VERSION
BRAND_APPLICATION_FIELDS = (
    "material_family",
    "application_medium",
    "carrier_component",
    "surface",
)


class BrandApplicationV3(TypedDict):
    state: Literal["verified_present", "verified_absent", "uncertain"]
    material_family: str | None
    application_medium: str | None
    carrier_component: str | None
    surface: str | None
    bbox: dict[str, float] | None
    confidence: float
    main_text: NotRequired[str | None]
    visible_text: NotRequired[list[str]]
    non_text_mark: NotRequired[str | None]


class ProductAnalysisV3(TypedDict):
    schema_version: Literal["3.0.0"]
    product_kind: Literal["beverage", "dessert"]
    identity: dict[str, Any]
    brand_applications: list[BrandApplicationV3]
    source_binding: NotRequired[dict[str, Any]]


class ReferenceBrandObservation(TypedDict):
    state: Literal["verified_present", "verified_absent", "uncertain"]
    material_family: str | None
    application_medium: str | None
    carrier_component: str | None
    surface_allowed: bool | str | list[str] | dict[str, bool] | None
    confidence: float


class TargetBrandContract(TypedDict):
    state: Literal["verified_present", "verified_absent", "uncertain"]
    allowed_main_text: str | None
    placement_source: Literal["source_product", "none"]
    surface_policy: dict[str, Any]


class BrandTransferResolution(TypedDict):
    policy_version: Literal["strict_auto_v1"]
    action: Literal[
        "preserve_source_exact",
        "transfer_source_exact",
        "omit_branding",
        "block_uncertain",
    ]
    checks: dict[str, bool]
    reason_codes: list[str]


class ResolvedBrandContract(TypedDict):
    brand_transfer_resolution: BrandTransferResolution
    target_brand_contract: TargetBrandContract


def perceptual_dhash(image: Image.Image) -> str:
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    values = list(gray.get_flattened_data())
    bits = 0
    for row in range(8):
        for column in range(8):
            left = values[row * 9 + column]
            right = values[row * 9 + column + 1]
            bits = (bits << 1) | int(left > right)
    return f"{bits:016x}"


def dhash_distance(first: str, second: str) -> int:
    return (int(first, 16) ^ int(second, 16)).bit_count()


def canonical_image_binding(path: str | Path) -> dict[str, Any]:
    """Return an encoding-independent fingerprint for the visible RGB pixels."""
    image_path = Path(path).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Image does not exist: {image_path}")
    with Image.open(image_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        width, height = image.size
        digest = hashlib.sha256()
        digest.update(f"RGB:{width}x{height}:".encode("ascii"))
        digest.update(image.tobytes())
        mean_rgb = [round(value / 255, 6) for value in ImageStat.Stat(image).mean]
    return {
        "pixel_sha256": digest.hexdigest(),
        "width_px": width,
        "height_px": height,
        "dhash": perceptual_dhash(image),
        "mean_rgb": mean_rgb,
    }


def bind_product_analysis(
    analysis: dict[str, Any],
    image_path: str | Path,
) -> dict[str, Any]:
    bound = deepcopy(analysis)
    bound["source_binding"] = canonical_image_binding(image_path)
    return bound


def validate_brand_contract(analysis: dict[str, Any]) -> None:
    if analysis.get("schema_version") == "3.0.0":
        validate_product_analysis_v3(analysis)
        return
    try:
        branding = analysis["identity"]["branding"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Product analysis has no branding contract") from exc

    state = branding.get("state")
    if state not in BRAND_STATES:
        raise ValueError(f"Unsupported brand state: {state!r}")
    main_text = branding.get("main_text")
    visible_text = branding.get("visible_text")
    if not isinstance(visible_text, list) or any(
        not isinstance(value, str) or not value.strip() for value in visible_text
    ):
        raise ValueError("branding.visible_text must be a list of non-empty strings")

    if state == "verified_absent":
        if main_text is not None or visible_text:
            raise ValueError(
                "verified_absent branding cannot contain main_text or visible_text"
            )
    elif state == "uncertain":
        if main_text is not None:
            raise ValueError("uncertain branding cannot assert main_text")
    elif main_text is not None and (
        not isinstance(main_text, str) or not main_text.strip()
    ):
        raise ValueError("verified brand main_text must be null or a non-empty string")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _known_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in {
        "",
        "unknown",
        "uncertain",
        "unspecified",
        "n/a",
        "none",
        "null",
    }


def _normalized_contract_value(value: Any) -> str | None:
    if not _known_string(value):
        return None
    return " ".join(
        str(value).strip().casefold().replace("_", " ").replace("-", " ").split()
    )


def _validate_normalized_bbox(value: Any, *, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a normalized bbox object or null")
    coordinates = [value.get(key) for key in ("left", "top", "right", "bottom")]
    if not all(_is_number(item) and 0 <= float(item) <= 1 for item in coordinates):
        raise ValueError(f"{field_name} coordinates must be numeric values from 0 to 1")
    left, top, right, bottom = (float(item) for item in coordinates)
    if left >= right or top >= bottom:
        raise ValueError(f"{field_name} must have positive width and height")


def validate_brand_application_v3(application: dict[str, Any]) -> None:
    """Validate one observed source-brand application without guessing unknown fields."""
    if not isinstance(application, dict):
        raise ValueError("brand application must be an object")
    state = application.get("state")
    if state not in BRAND_STATES:
        raise ValueError(f"Unsupported brand application state: {state!r}")
    confidence = application.get("confidence")
    if not _is_number(confidence) or not 0 <= float(confidence) <= 1:
        raise ValueError("brand application confidence must be between 0 and 1")
    required = {*BRAND_APPLICATION_FIELDS, "bbox"}
    missing_keys = sorted(required - application.keys())
    if missing_keys:
        raise ValueError(
            "brand application is missing required fields: " + ", ".join(missing_keys)
        )
    for field in BRAND_APPLICATION_FIELDS:
        value = application.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"brand application {field} must be a string or null")
    _validate_normalized_bbox(application.get("bbox"), field_name="brand application bbox")

    if state == "verified_absent":
        for field in ("main_text", "non_text_mark"):
            if application.get(field) not in (None, ""):
                raise ValueError(f"verified_absent brand application cannot contain {field}")
        visible_text = application.get("visible_text", [])
        if visible_text not in (None, []):
            raise ValueError("verified_absent brand application cannot contain visible_text")


def _brand_applications(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    identity = analysis.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    branding = identity.get("branding")
    branding = branding if isinstance(branding, dict) else {}
    candidates = (
        analysis.get("brand_applications"),
        identity.get("brand_applications"),
        branding.get("applications"),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate

    direct = analysis.get("brand_application") or identity.get("brand_application")
    if isinstance(direct, dict):
        return [direct]
    if any(field in branding for field in BRAND_APPLICATION_FIELDS):
        return [branding]
    return []


def validate_product_analysis_v3(analysis: ProductAnalysisV3 | dict[str, Any]) -> None:
    """Validate the v3 product and brand-application fields used at paid preflight."""
    if not isinstance(analysis, dict):
        raise ValueError("ProductAnalysisV3 must be an object")
    if analysis.get("schema_version") != "3.0.0":
        raise ValueError("ProductAnalysisV3 schema_version must be 3.0.0")
    if analysis.get("product_kind") not in PRODUCT_KINDS:
        raise ValueError("ProductAnalysisV3 product_kind must be beverage or dessert")
    if not isinstance(analysis.get("identity"), dict):
        raise ValueError("ProductAnalysisV3 identity must be an object")

    serving_state = analysis["identity"].get("serving_state")
    if serving_state is not None:
        if not isinstance(serving_state, dict):
            raise ValueError("ProductAnalysisV3 identity.serving_state must be an object")
        serving_state = validate_serving_state(serving_state)
        if analysis["product_kind"] == "dessert":
            if serving_state["temperature"] != "not_applicable":
                raise ValueError("Dessert serving_state temperature must be not_applicable")
        elif serving_state["temperature"] == "not_applicable":
            raise ValueError("Beverage serving_state temperature cannot be not_applicable")

    applications = _brand_applications(analysis)
    if not applications:
        raise ValueError("ProductAnalysisV3 requires at least one brand application")
    for application in applications:
        validate_brand_application_v3(application)

    branding = analysis["identity"].get("branding")
    if isinstance(branding, dict) and branding.get("state") in BRAND_STATES:
        observed_states = {application["state"] for application in applications}
        if "uncertain" in observed_states:
            application_state = "uncertain"
        elif "verified_present" in observed_states:
            application_state = "verified_present"
        else:
            application_state = "verified_absent"
        if branding["state"] != application_state:
            raise ValueError(
                "ProductAnalysisV3 branding state conflicts with brand applications"
            )


def _source_brand_observation(analysis: dict[str, Any]) -> dict[str, Any]:
    schema_version = analysis.get("schema_version")
    applications = _brand_applications(analysis)
    if schema_version == "3.0.0":
        validate_product_analysis_v3(analysis)
    elif not applications:
        validate_brand_contract(analysis)

    identity = analysis.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    branding = identity.get("branding")
    branding = branding if isinstance(branding, dict) else {}
    states = {application.get("state") for application in applications}
    state = branding.get("state")
    if state not in BRAND_STATES:
        if "uncertain" in states:
            state = "uncertain"
        elif "verified_present" in states:
            state = "verified_present"
        elif states == {"verified_absent"}:
            state = "verified_absent"
        else:
            raise ValueError("Product analysis has no authoritative brand state")

    present = [item for item in applications if item.get("state") == "verified_present"]
    primary = max(
        present,
        key=lambda item: (bool(item.get("primary")), float(item.get("confidence", 0))),
        default={},
    )
    main_text = branding.get("main_text")
    if main_text is None:
        main_text = primary.get("main_text")
    return {
        "state": state,
        "main_text": main_text,
        "visible_text": branding.get("visible_text", primary.get("visible_text", [])),
        "non_text_mark": branding.get("non_text_mark", primary.get("non_text_mark")),
        "application": primary,
    }


def _container_policy_mode(container_policy: str | dict[str, Any]) -> str:
    if isinstance(container_policy, str):
        mode = container_policy
    elif isinstance(container_policy, dict):
        mode = container_policy.get("container") or container_policy.get("mode")
    else:
        mode = None
    if mode not in {"preserve_source", "adopt_reference"}:
        raise ValueError(
            "container_policy must resolve to preserve_source or adopt_reference"
        )
    return mode


def _surface_is_allowed(source_surface: Any, allowed: Any) -> bool:
    source = _normalized_contract_value(source_surface)
    if source is None:
        return False
    if isinstance(allowed, bool):
        return allowed
    if isinstance(allowed, str):
        return _normalized_contract_value(allowed) == source
    if isinstance(allowed, list):
        return source in {_normalized_contract_value(item) for item in allowed}
    if isinstance(allowed, dict):
        return any(
            _normalized_contract_value(key) == source and value is True
            for key, value in allowed.items()
        )
    return False


def _unbranded_target() -> TargetBrandContract:
    return {
        "state": "verified_absent",
        "allowed_main_text": None,
        "placement_source": "none",
        "surface_policy": {
            "mode": "forbid_branding",
            "material_family": None,
            "application_medium": None,
            "carrier_component": None,
            "surface": None,
        },
    }


def _source_target(source: dict[str, Any]) -> TargetBrandContract:
    application = source.get("application", {})
    return {
        "state": "verified_present",
        "allowed_main_text": source.get("main_text"),
        "placement_source": "source_product",
        "surface_policy": {
            "mode": "source_application_only",
            **{field: application.get(field) for field in BRAND_APPLICATION_FIELDS},
        },
    }


def resolve_target_brand_contract(
    product_analysis: ProductAnalysisV3 | dict[str, Any] | None,
    container_policy: str | dict[str, Any],
    reference_brand_observation: ReferenceBrandObservation | dict[str, Any] | None = None,
    *,
    is_generic: bool = False,
    policy: str = BRAND_TRANSFER_POLICY_VERSION,
) -> ResolvedBrandContract:
    """Resolve the only brand contract generation and QA are allowed to follow.

    Reference branding is compatibility evidence only. Its text or mark is never
    copied into the target contract.
    """
    if policy != BRAND_TRANSFER_POLICY_VERSION:
        raise ValueError(f"Unsupported brand transfer policy: {policy!r}")
    mode = _container_policy_mode(container_policy)
    checks = {
        "source_state_known": False,
        "source_application_complete": False,
        "source_confidence_sufficient": False,
        "reference_verified_present": False,
        "reference_confidence_sufficient": False,
        "material_family_match": False,
        "application_medium_match": False,
        "carrier_component_match": False,
        "surface_allowed": False,
    }

    if is_generic:
        return {
            "brand_transfer_resolution": {
                "policy_version": BRAND_TRANSFER_POLICY_VERSION,
                "action": "omit_branding",
                "checks": checks,
                "reason_codes": ["generic_must_be_unbranded"],
            },
            "target_brand_contract": _unbranded_target(),
        }
    if not isinstance(product_analysis, dict):
        raise ValueError("Exact products require product_analysis")

    source = _source_brand_observation(product_analysis)
    checks["source_state_known"] = source["state"] != "uncertain"
    application = source.get("application", {})
    checks["source_application_complete"] = all(
        _known_string(application.get(field)) for field in BRAND_APPLICATION_FIELDS
    )
    source_confidence = application.get("confidence")
    checks["source_confidence_sufficient"] = bool(
        _is_number(source_confidence) and float(source_confidence) >= 0.90
    )
    if source["state"] == "uncertain":
        return {
            "brand_transfer_resolution": {
                "policy_version": BRAND_TRANSFER_POLICY_VERSION,
                "action": "block_uncertain",
                "checks": checks,
                "reason_codes": ["source_brand_uncertain", "paid_submission_blocked"],
            },
            "target_brand_contract": {
                **_unbranded_target(),
                "state": "uncertain",
            },
        }
    if source["state"] == "verified_absent":
        return {
            "brand_transfer_resolution": {
                "policy_version": BRAND_TRANSFER_POLICY_VERSION,
                "action": "omit_branding",
                "checks": checks,
                "reason_codes": ["source_verified_unbranded"],
            },
            "target_brand_contract": _unbranded_target(),
        }
    if mode == "preserve_source":
        return {
            "brand_transfer_resolution": {
                "policy_version": BRAND_TRANSFER_POLICY_VERSION,
                "action": "preserve_source_exact",
                "checks": checks,
                "reason_codes": [
                    "source_container_preserved",
                    "source_brand_verified_present",
                ],
            },
            "target_brand_contract": _source_target(source),
        }

    reference = (
        reference_brand_observation
        if isinstance(reference_brand_observation, dict)
        else {}
    )
    reference_state = reference.get("state")
    checks["reference_verified_present"] = reference_state == "verified_present"
    if not checks["reference_verified_present"]:
        return {
            "brand_transfer_resolution": {
                "policy_version": BRAND_TRANSFER_POLICY_VERSION,
                "action": "omit_branding",
                "checks": checks,
                "reason_codes": [
                    "reference_brand_not_verified_present",
                    "brand_transfer_forbidden",
                ],
            },
            "target_brand_contract": _unbranded_target(),
        }

    reference_confidence = reference.get("confidence")
    checks["reference_confidence_sufficient"] = bool(
        _is_number(reference_confidence) and float(reference_confidence) >= 0.90
    )
    for field in ("material_family", "application_medium", "carrier_component"):
        checks[f"{field}_match"] = bool(
            _normalized_contract_value(application.get(field)) is not None
            and _normalized_contract_value(application.get(field))
            == _normalized_contract_value(reference.get(field))
        )
    checks["surface_allowed"] = _surface_is_allowed(
        application.get("surface"), reference.get("surface_allowed")
    )

    compatible = all(
        checks[key]
        for key in (
            "source_application_complete",
            "source_confidence_sufficient",
            "reference_verified_present",
            "reference_confidence_sufficient",
            "material_family_match",
            "application_medium_match",
            "carrier_component_match",
            "surface_allowed",
        )
    )
    if compatible:
        return {
            "brand_transfer_resolution": {
                "policy_version": BRAND_TRANSFER_POLICY_VERSION,
                "action": "transfer_source_exact",
                "checks": checks,
                "reason_codes": [
                    "all_application_compatibility_checks_passed",
                    "reference_brand_content_never_copied",
                ],
            },
            "target_brand_contract": _source_target(source),
        }

    failed = [
        key
        for key in (
            "source_application_complete",
            "source_confidence_sufficient",
            "reference_confidence_sufficient",
            "material_family_match",
            "application_medium_match",
            "carrier_component_match",
            "surface_allowed",
        )
        if not checks[key]
    ]
    return {
        "brand_transfer_resolution": {
            "policy_version": BRAND_TRANSFER_POLICY_VERSION,
            "action": "omit_branding",
            "checks": checks,
            "reason_codes": [
                *(f"{key}_failed_or_unknown" for key in failed),
                "brand_transfer_forbidden",
            ],
        },
        "target_brand_contract": _unbranded_target(),
    }


def validate_product_analysis_binding(
    analysis: dict[str, Any],
    image_path: str | Path,
) -> dict[str, Any]:
    """Reject stale analysis before a request can reach a paid provider."""
    if analysis.get("schema_version") == "3.0.0":
        validate_product_analysis_v3(analysis)
    else:
        validate_brand_contract(analysis)
    binding = analysis.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError(
            "Product analysis is not bound to an image. Run Product Analysis again."
        )
    actual = canonical_image_binding(image_path)
    actual_exact = {
        "pixel_sha256": actual["pixel_sha256"],
        "width_px": actual["width_px"],
        "height_px": actual["height_px"],
    }
    expected = {
        "pixel_sha256": binding.get("pixel_sha256"),
        "width_px": binding.get("width_px"),
        "height_px": binding.get("height_px"),
    }
    if expected != actual_exact:
        raise ValueError(
            "Product analysis does not match the uploaded image. "
            "Run Product Analysis again before generation."
        )
    return actual


def verified_logo_text(analysis: dict[str, Any]) -> str | None:
    """Return text only when analysis explicitly verified a visible brand."""
    source = _source_brand_observation(analysis)
    if source["state"] != "verified_present":
        return None
    return source.get("main_text")


def require_generation_ready_brand_contract(analysis: dict[str, Any]) -> None:
    source = _source_brand_observation(analysis)
    if source["state"] == "uncertain":
        raise ValueError(
            "Branding is uncertain. Confirm whether the source is branded before generation."
        )
