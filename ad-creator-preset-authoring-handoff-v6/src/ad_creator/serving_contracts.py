from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any, Literal, TypedDict


ServingTemperature = Literal[
    "iced",
    "cold",
    "ambient",
    "hot",
    "unknown",
    "not_applicable",
]
ContainerTemperature = Literal["cold", "hot", "dual", "ambient", "unknown"]
CompatibilityAction = Literal["allow", "block", "review"]


class ServingState(TypedDict):
    schema_version: Literal["1.0.0"]
    temperature: ServingTemperature
    ice_presence: Literal["present", "absent", "unknown", "not_applicable"]
    straw_requirement: Literal[
        "required", "optional", "none", "unknown", "not_applicable"
    ]
    topping_requirement: Literal[
        "required", "optional", "none", "unknown", "not_applicable"
    ]
    side_visibility_requirement: Literal[
        "required", "optional", "unknown", "not_applicable"
    ]
    confidence: float
    evidence: list[str]


class ContainerServiceProfile(TypedDict):
    schema_version: Literal["1.0.0"]
    service_temperature: ContainerTemperature
    transparency: Literal["transparent", "opaque", "unknown"]
    opening: Literal["open", "narrow_or_sealed", "unknown"]
    supports_straw: bool | None
    supports_toppings: bool | None
    confidence: float
    evidence: list[str]


class ServingCompatibilityResolution(TypedDict):
    schema_version: Literal["1.0.0"]
    action: CompatibilityAction
    product_serving_state: ServingState
    target_container_service_profile: ContainerServiceProfile | None
    reason_codes: list[str]


_UNKNOWN_VALUES = {"", "unknown", "uncertain", "unspecified", "n/a", "none"}
_COLD_TERMS = (
    "iced",
    "ice cube",
    "ice sphere",
    "cold beverage",
    "cold drink",
    "smoothie",
    "sparkling",
    "frozen drink",
)
_HOT_TERMS = (
    "hot beverage",
    "hot drink",
    "steaming",
    "steam",
    "latte art",
)
_TOPPING_TERMS = (
    "topping",
    "whipped cream",
    "foam",
    "mint leaf",
    "fruit piece",
    "fruit pieces",
    "diced strawberry",
    "pulp",
    "garnish",
)
_SIDE_IDENTITY_TERMS = (
    "layer",
    "marbling",
    "marbled",
    "swirl",
    "gradient",
    "clear glass",
    "transparent",
    "milk base",
)
_TRANSPARENT_TERMS = ("glass", "clear", "transparent", "translucent", "pet")
_OPAQUE_TERMS = (
    "ceramic",
    "porcelain",
    "stoneware",
    "earthenware",
    "paper",
    "metal",
    "stone",
    "opaque",
)
_HOT_VESSEL_TERMS = (
    "ceramic cup",
    "ceramic_cup",
    "porcelain cup",
    "teacup",
    "tea cup",
    "coffee cup",
    "mug",
    "saucer",
    "teaspoon",
    "tea spoon",
    "demitasse",
)
_COLD_VESSEL_TERMS = (
    "cold cup",
    "plastic cup",
    "pet cup",
    "domed lid",
    "dome lid",
    "straw hole",
    "smoothie cup",
)
_IMMEDIATE_SUPPORT_TERMS = (
    "saucer",
    "coaster",
    "pedestal",
    "cup stand",
    "serving stand",
    "underplate",
)


def _normalized_text(values: list[Any]) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().casefold().replace("_", " "))
        elif isinstance(value, list):
            parts.extend(
                item.strip().casefold().replace("_", " ")
                for item in value
                if isinstance(item, str) and item.strip()
            )
    return " ".join(parts)


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _validated_confidence(value: Any, *, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return default


def validate_serving_state(value: Mapping[str, Any]) -> ServingState:
    required = {
        "schema_version",
        "temperature",
        "ice_presence",
        "straw_requirement",
        "topping_requirement",
        "side_visibility_requirement",
        "confidence",
        "evidence",
    }
    if set(value) != required or value.get("schema_version") != "1.0.0":
        raise ValueError("serving_state must use the complete 1.0.0 contract")
    allowed = {
        "temperature": {"iced", "cold", "ambient", "hot", "unknown", "not_applicable"},
        "ice_presence": {"present", "absent", "unknown", "not_applicable"},
        "straw_requirement": {"required", "optional", "none", "unknown", "not_applicable"},
        "topping_requirement": {"required", "optional", "none", "unknown", "not_applicable"},
        "side_visibility_requirement": {"required", "optional", "unknown", "not_applicable"},
    }
    for field, choices in allowed.items():
        if value.get(field) not in choices:
            raise ValueError(f"serving_state.{field} is invalid")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= float(confidence) <= 1:
        raise ValueError("serving_state.confidence must be between zero and one")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or any(
        not isinstance(item, str) or not item.strip() for item in evidence
    ):
        raise ValueError("serving_state.evidence must contain non-empty strings")
    return copy.deepcopy(dict(value))  # type: ignore[return-value]


def resolve_product_serving_state(
    product_analysis: Mapping[str, Any] | None,
    *,
    product_kind: str,
    description: str | None = None,
) -> ServingState:
    """Return an explicit state, or conservatively derive one for legacy V3 analyses."""

    if product_kind == "dessert":
        return {
            "schema_version": "1.0.0",
            "temperature": "not_applicable",
            "ice_presence": "not_applicable",
            "straw_requirement": "not_applicable",
            "topping_requirement": "not_applicable",
            "side_visibility_requirement": "not_applicable",
            "confidence": 1.0,
            "evidence": ["product_kind=dessert"],
        }
    analysis = product_analysis if isinstance(product_analysis, Mapping) else {}
    identity = analysis.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    explicit = identity.get("serving_state")
    if isinstance(explicit, Mapping):
        return validate_serving_state(explicit)

    geometry = analysis.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    straw = geometry.get("straw")
    straw = straw if isinstance(straw, Mapping) else {}
    must_preserve = identity.get("must_preserve")
    text = _normalized_text(
        [
            description,
            analysis.get("product_summary"),
            identity.get("product"),
            identity.get("beverage"),
            must_preserve if isinstance(must_preserve, list) else [],
        ]
    )
    has_ice = bool(re.search(r"\bice\b|\biced\b", text))
    cold = _contains(text, _COLD_TERMS) or has_ice or bool(re.search(r"\bcold\b", text))
    hot = _contains(text, _HOT_TERMS) or bool(re.search(r"\bhot\b", text))
    evidence: list[str] = ["legacy_product_analysis_text_derivation"]
    if cold and hot:
        temperature: ServingTemperature = "unknown"
        evidence.append("conflicting_hot_and_cold_cues")
    elif has_ice:
        temperature = "iced"
        evidence.append("visible_or_declared_ice")
    elif cold:
        temperature = "cold"
        evidence.append("cold_service_cue")
    elif hot:
        temperature = "hot"
        evidence.append("hot_service_cue")
    else:
        temperature = "unknown"
        evidence.append("temperature_not_observed")

    preserve_text = _normalized_text(
        [must_preserve if isinstance(must_preserve, list) else []]
    )
    straw_present = straw.get("present") is True
    straw_required = "straw" in preserve_text
    topping_required = _contains(text, _TOPPING_TERMS)
    side_required = _contains(text, _SIDE_IDENTITY_TERMS)
    return {
        "schema_version": "1.0.0",
        "temperature": temperature,
        "ice_presence": "present" if has_ice else "absent" if hot else "unknown",
        "straw_requirement": (
            "required" if straw_required else "optional" if straw_present else "none"
        ),
        "topping_requirement": "required" if topping_required else "none",
        "side_visibility_requirement": "required" if side_required else "optional",
        "confidence": 0.88 if temperature not in {"unknown"} else 0.45,
        "evidence": evidence,
    }


def derive_container_service_profile(
    scene_object: Mapping[str, Any] | None,
) -> ContainerServiceProfile | None:
    if not isinstance(scene_object, Mapping):
        return None
    container = scene_object.get("container")
    if not isinstance(container, Mapping):
        return None
    components = container.get("components")
    components = components if isinstance(components, list) else []
    straw = scene_object.get("straw")
    straw = straw if isinstance(straw, Mapping) else {}
    description = _normalized_text([scene_object.get("description")])
    vessel_components = [
        item
        for item in components
        if not _contains(str(item).lower(), _IMMEDIATE_SUPPORT_TERMS)
    ]
    vessel_text = _normalized_text(
        [
            container.get("class"),
            container.get("material"),
            container.get("silhouette"),
            vessel_components,
        ]
    )
    combined = f"{description} {vessel_text}".strip()
    explicit_cold = _contains(description, _COLD_TERMS) or bool(
        re.search(r"\bice\b|\biced\b", description)
    )
    explicit_hot = _contains(description, _HOT_TERMS)
    cold_vessel = _contains(vessel_text, _COLD_VESSEL_TERMS) or straw.get("present") is True
    hot_vessel = _contains(vessel_text, _HOT_VESSEL_TERMS)
    has_transparent_body = _contains(vessel_text, _TRANSPARENT_TERMS)
    has_opaque_material = _contains(vessel_text, _OPAQUE_TERMS)
    partial_opaque_sleeve = (
        has_transparent_body
        and "sleeve" in vessel_text
        and _contains(vessel_text, ("clear cup", "clear cold-drink cup", "clear plastic"))
    )
    transparent = has_transparent_body and (
        not has_opaque_material or partial_opaque_sleeve
    )
    opaque = _contains(vessel_text, _OPAQUE_TERMS) and not transparent
    evidence: list[str] = []

    if explicit_cold:
        service_temperature: ContainerTemperature = "cold"
        evidence.append("reference_observed_cold_service")
    elif explicit_hot:
        service_temperature = "hot"
        evidence.append("reference_observed_hot_service")
    elif cold_vessel and not hot_vessel:
        service_temperature = "cold"
        evidence.append("cold_service_container_components")
    elif hot_vessel and not cold_vessel:
        service_temperature = "hot"
        evidence.append("hot_service_container_components")
    elif transparent:
        service_temperature = "dual"
        evidence.append("neutral_transparent_open_vessel")
    else:
        service_temperature = "unknown"
        evidence.append("container_service_temperature_unresolved")

    narrow_or_sealed = _contains(
        combined,
        (
            "sealed lid",
            "closed lid",
            "flat lid",
            "bottle",
            "narrow neck",
            "cork stopper",
            "cork",
            "stopper",
        ),
    )
    domed = _contains(combined, ("domed lid", "dome lid"))
    lidded_cold_cup = (
        service_temperature == "cold"
        and _contains(combined, ("flat lid", "flat clear lid"))
        and straw.get("present") is True
    )
    if partial_opaque_sleeve:
        evidence.append("transparent_body_with_partial_opaque_sleeve")
    if lidded_cold_cup:
        evidence.append("lidded_cold_cup_supports_contained_ice")
    visibly_open = _contains(
        combined,
        ("open glass", "open cup", "tumbler", "rim", "lidless"),
    ) or (transparent and not narrow_or_sealed)
    if service_temperature == "hot":
        supports_straw: bool | None = False
    elif straw.get("present") is True or (transparent and not narrow_or_sealed) or domed:
        supports_straw = True
    elif narrow_or_sealed:
        supports_straw = False
    else:
        supports_straw = None
    supports_toppings: bool | None = False if narrow_or_sealed and not domed else True
    return {
        "schema_version": "1.0.0",
        "service_temperature": service_temperature,
        "transparency": "transparent" if transparent else "opaque" if opaque else "unknown",
        "opening": (
            "narrow_or_sealed"
            if narrow_or_sealed
            else "open"
            if visibly_open
            else "unknown"
        ),
        "supports_straw": supports_straw,
        "supports_toppings": supports_toppings,
        "confidence": 0.95 if explicit_cold or explicit_hot else 0.88 if service_temperature != "unknown" else 0.45,
        "evidence": evidence,
    }


def _source_container_object(analysis: Mapping[str, Any]) -> dict[str, Any] | None:
    identity = analysis.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    container = identity.get("container")
    if not isinstance(container, Mapping):
        return None
    geometry = analysis.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    return {
        "description": _normalized_text(
            [analysis.get("product_summary"), identity.get("product"), identity.get("beverage")]
        ),
        "container": {
            "class": container.get("class"),
            "material": container.get("material"),
            "silhouette": container.get("geometry"),
            "components": container.get("components", []),
        },
        "straw": geometry.get("straw", {}),
    }


def resolve_serving_compatibility(
    *,
    product_analysis: Mapping[str, Any] | None,
    product_kind: str,
    description: str | None,
    container_mode: str,
    target_scene_object: Mapping[str, Any] | None = None,
) -> ServingCompatibilityResolution:
    state = resolve_product_serving_state(
        product_analysis,
        product_kind=product_kind,
        description=description,
    )
    if product_kind == "dessert":
        return {
            "schema_version": "1.0.0",
            "action": "allow",
            "product_serving_state": state,
            "target_container_service_profile": None,
            "reason_codes": ["dessert_container_compatibility_not_applicable"],
        }
    analysis = product_analysis if isinstance(product_analysis, Mapping) else {}
    profile = derive_container_service_profile(
        _source_container_object(analysis)
        if container_mode == "preserve_source"
        else target_scene_object
    )
    if state["temperature"] == "unknown":
        return {
            "schema_version": "1.0.0",
            "action": "review",
            "product_serving_state": state,
            "target_container_service_profile": profile,
            "reason_codes": ["product_serving_temperature_unknown"],
        }
    if container_mode == "preserve_source":
        return {
            "schema_version": "1.0.0",
            "action": "allow",
            "product_serving_state": state,
            "target_container_service_profile": profile,
            "reason_codes": ["preserve_observed_source_container_and_serving_state"],
        }
    if profile is None or profile["service_temperature"] == "unknown":
        return {
            "schema_version": "1.0.0",
            "action": "review",
            "product_serving_state": state,
            "target_container_service_profile": profile,
            "reason_codes": ["target_container_service_profile_unknown"],
        }

    failures: list[str] = []
    product_temperature = state["temperature"]
    target_temperature = profile["service_temperature"]
    if product_temperature in {"iced", "cold"} and target_temperature not in {
        "cold",
        "dual",
    }:
        failures.append("cold_product_in_hot_service_container")
    if product_temperature == "hot" and target_temperature not in {"hot", "dual"}:
        failures.append("hot_product_in_cold_service_container")
    if state["straw_requirement"] == "required" and profile["supports_straw"] is not True:
        failures.append("required_straw_not_supported")
    if state["topping_requirement"] == "required" and profile["supports_toppings"] is not True:
        failures.append("required_toppings_not_supported")
    if (
        state["ice_presence"] == "present"
        and profile["opening"] == "narrow_or_sealed"
        and "lidded_cold_cup_supports_contained_ice" not in profile["evidence"]
    ):
        failures.append("visible_ice_not_supported_by_target_opening")
    if (
        state["side_visibility_requirement"] == "required"
        and profile["transparency"] != "transparent"
    ):
        failures.append("identity_requires_side_visibility_but_container_is_opaque")
    return {
        "schema_version": "1.0.0",
        "action": "block" if failures else "allow",
        "product_serving_state": state,
        "target_container_service_profile": profile,
        "reason_codes": failures or ["serving_and_container_contracts_compatible"],
    }


def require_serving_compatibility_ready(
    product_id: str,
    resolution: Mapping[str, Any] | None,
) -> None:
    if not isinstance(resolution, Mapping):
        raise ValueError(
            f"Product {product_id} has no serving compatibility resolution; generation is blocked"
        )
    action = resolution.get("action")
    if action != "allow":
        reasons = resolution.get("reason_codes")
        reason_text = ", ".join(str(item) for item in reasons) if isinstance(reasons, list) else str(action)
        raise ValueError(
            f"Product {product_id} serving/container compatibility is {action}; "
            f"generation is blocked: {reason_text}"
        )


def serving_prompt_summary(resolution: Mapping[str, Any]) -> str:
    state = resolution.get("product_serving_state")
    state = state if isinstance(state, Mapping) else {}
    profile = resolution.get("target_container_service_profile")
    profile = profile if isinstance(profile, Mapping) else {}
    reasons = resolution.get("reason_codes")
    reason = ",".join(str(item) for item in reasons) if isinstance(reasons, list) else "none"
    return (
        "serving-contract={"
        f"temperature={state.get('temperature', 'unknown')}, "
        f"ice={state.get('ice_presence', 'unknown')}, "
        f"straw={state.get('straw_requirement', 'unknown')}, "
        f"toppings={state.get('topping_requirement', 'unknown')}, "
        f"side-visibility={state.get('side_visibility_requirement', 'unknown')}"
        "}; container-service={"
        f"temperature={profile.get('service_temperature', 'not-applicable')}, "
        f"transparency={profile.get('transparency', 'not-applicable')}, "
        f"opening={profile.get('opening', 'not-applicable')}"
        "}; compatibility="
        f"{resolution.get('action', 'review')}({reason})"
    )
