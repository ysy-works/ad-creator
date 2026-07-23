from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .jsonio import load_json, validate_json


DEFAULT_FEATURES: dict[str, Any] = {
    "schema_version": "1.0.0",
    "features": {
        "container_choice": {
            "enabled": True,
            "fallback_when_disabled": "preserve_source",
        },
        "auto_paid_repair": {
            "enabled": True,
            "default_for_request": True,
            "minimum_trigger_confidence": 0.85,
            "maximum_attempts": 1,
            "maximum_additional_credits": 2,
        },
    },
}


def load_service_features(
    project_root: str | Path,
    path: str | Path | None = "configs/service-features.json",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if path is None:
        value = copy.deepcopy(DEFAULT_FEATURES)
    else:
        source = Path(path)
        if not source.is_absolute():
            source = root / source
        value = load_json(source)
    validate_json(value, "service-features.schema.json", project_root=root)
    return value


def resolve_container_mode(requested: str, features: dict[str, Any]) -> str:
    if requested not in {"preserve_source", "adopt_reference"}:
        raise ValueError(f"Unknown container mode: {requested}")
    policy = features["features"]["container_choice"]
    if not policy["enabled"]:
        return policy["fallback_when_disabled"]
    return requested


def resolve_auto_paid_repair(requested: bool | None, features: dict[str, Any]) -> bool:
    policy = features["features"]["auto_paid_repair"]
    if not policy["enabled"]:
        return False
    if requested is None:
        return bool(policy["default_for_request"])
    return bool(requested)


def ui_feature_state(features: dict[str, Any]) -> dict[str, bool]:
    """Return the effective controls that a research UI may expose."""
    container_policy = features["features"]["container_choice"]
    repair_policy = features["features"]["auto_paid_repair"]
    repair_enabled = bool(repair_policy["enabled"])
    return {
        "container_choice_visible": bool(container_policy["enabled"]),
        "auto_paid_repair_visible": repair_enabled,
        "auto_paid_repair_default": repair_enabled
        and bool(repair_policy["default_for_request"]),
    }
