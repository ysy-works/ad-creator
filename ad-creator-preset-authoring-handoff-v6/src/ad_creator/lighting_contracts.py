from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


LIGHTING_CONTRACT_SCHEMA_VERSION = "3.0.0"
LIGHTING_FAMILIES = frozenset({"direct", "diffuse"})
DELTA_LIMITS = MappingProxyType(
    {
        "hardness": 0.15,
        "shadow_density": 0.10,
        "exposure_ev": 0.20,
        "white_balance_mired": 20.0,
    }
)
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: Any, *, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _normalized_number(value: float) -> float:
    return float(round(float(value), 6))


def _hex_digest(value: str | None, *, label: str) -> None:
    if value is None:
        return
    if len(value) != 64 or value != value.lower() or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a 64-character hex digest")


@dataclass(frozen=True)
class WhiteLightingBase:
    """Immutable numeric base for either direct or diffuse white lighting."""

    base_id: str
    family: str
    direction_degrees: float
    elevation_degrees: float
    hardness: float
    shadow_density: float
    exposure_ev: float
    white_balance_mired: float
    schema_version: str = LIGHTING_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_white_lighting_base(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WhiteLightingBase:
        signature = value.get("signature", value)
        if not isinstance(signature, Mapping):
            raise ValueError("lighting base signature must be an object")
        return cls(
            schema_version=str(
                value.get("schema_version", LIGHTING_CONTRACT_SCHEMA_VERSION)
            ),
            base_id=str(value.get("base_id", "")),
            family=str(value.get("family", "")),
            direction_degrees=_finite(
                signature.get("direction_degrees"), label="direction_degrees"
            ),
            elevation_degrees=_finite(
                signature.get("elevation_degrees"), label="elevation_degrees"
            ),
            hardness=_finite(signature.get("hardness"), label="hardness"),
            shadow_density=_finite(
                signature.get("shadow_density"), label="shadow_density"
            ),
            exposure_ev=_finite(
                signature.get("exposure_ev"), label="exposure_ev"
            ),
            white_balance_mired=_finite(
                signature.get("white_balance_mired"),
                label="white_balance_mired",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "base_id": self.base_id,
            "family": self.family,
            "signature": {
                "direction_degrees": _normalized_number(self.direction_degrees),
                "elevation_degrees": _normalized_number(self.elevation_degrees),
                "hardness": _normalized_number(self.hardness),
                "shadow_density": _normalized_number(self.shadow_density),
                "exposure_ev": _normalized_number(self.exposure_ev),
                "white_balance_mired": _normalized_number(
                    self.white_balance_mired
                ),
            },
        }

    @property
    def base_hash(self) -> str:
        return _canonical_hash(self.to_dict())


def validate_white_lighting_base(
    value: WhiteLightingBase | Mapping[str, Any],
) -> WhiteLightingBase:
    base = value if isinstance(value, WhiteLightingBase) else WhiteLightingBase.from_dict(value)
    if base.schema_version != LIGHTING_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported lighting base schema version: {base.schema_version!r}"
        )
    if not _IDENTIFIER.fullmatch(base.base_id):
        raise ValueError("base_id must contain only lowercase letters, numbers, _ or -")
    if base.family not in LIGHTING_FAMILIES:
        raise ValueError(f"Unsupported lighting family: {base.family!r}")
    ranges = (
        ("direction_degrees", base.direction_degrees, 0.0, 360.0, False),
        ("elevation_degrees", base.elevation_degrees, 0.0, 90.0, True),
        ("hardness", base.hardness, 0.0, 1.0, True),
        ("shadow_density", base.shadow_density, 0.0, 1.0, True),
        ("exposure_ev", base.exposure_ev, -3.0, 3.0, True),
        ("white_balance_mired", base.white_balance_mired, 100.0, 500.0, True),
    )
    for label, actual, minimum, maximum, inclusive_maximum in ranges:
        valid = minimum <= actual <= maximum if inclusive_maximum else minimum <= actual < maximum
        if not math.isfinite(actual) or not valid:
            boundary = "]" if inclusive_maximum else ")"
            raise ValueError(f"{label} must be in [{minimum}, {maximum}{boundary}")
    return base


@dataclass(frozen=True)
class ReferenceLightingDelta:
    reference_id: str
    base_id: str
    direction_delta_degrees: float = 0.0
    elevation_delta_degrees: float = 0.0
    hardness_delta: float = 0.0
    shadow_density_delta: float = 0.0
    exposure_delta_ev: float = 0.0
    white_balance_delta_mired: float = 0.0
    confidence: float = 1.0
    source_pixel_sha256: str | None = None
    schema_version: str = LIGHTING_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_reference_lighting_delta(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReferenceLightingDelta:
        delta = value.get("delta", value)
        if not isinstance(delta, Mapping):
            raise ValueError("reference lighting delta must be an object")
        return cls(
            schema_version=str(
                value.get("schema_version", LIGHTING_CONTRACT_SCHEMA_VERSION)
            ),
            reference_id=str(value.get("reference_id", "")),
            base_id=str(value.get("base_id", "")),
            direction_delta_degrees=_finite(
                delta.get("direction_degrees", delta.get("direction_delta_degrees", 0)),
                label="direction_delta_degrees",
            ),
            elevation_delta_degrees=_finite(
                delta.get("elevation_degrees", delta.get("elevation_delta_degrees", 0)),
                label="elevation_delta_degrees",
            ),
            hardness_delta=_finite(
                delta.get("hardness", delta.get("hardness_delta", 0)),
                label="hardness_delta",
            ),
            shadow_density_delta=_finite(
                delta.get(
                    "shadow_density", delta.get("shadow_density_delta", 0)
                ),
                label="shadow_density_delta",
            ),
            exposure_delta_ev=_finite(
                delta.get("exposure_ev", delta.get("exposure_delta_ev", 0)),
                label="exposure_delta_ev",
            ),
            white_balance_delta_mired=_finite(
                delta.get(
                    "white_balance_mired",
                    delta.get("white_balance_delta_mired", 0),
                ),
                label="white_balance_delta_mired",
            ),
            confidence=_finite(value.get("confidence", 1), label="confidence"),
            source_pixel_sha256=(
                str(value["source_pixel_sha256"])
                if value.get("source_pixel_sha256") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reference_id": self.reference_id,
            "base_id": self.base_id,
            "source_pixel_sha256": self.source_pixel_sha256,
            "confidence": _normalized_number(self.confidence),
            "delta": {
                "direction_degrees": _normalized_number(
                    self.direction_delta_degrees
                ),
                "elevation_degrees": _normalized_number(
                    self.elevation_delta_degrees
                ),
                "hardness": _normalized_number(self.hardness_delta),
                "shadow_density": _normalized_number(
                    self.shadow_density_delta
                ),
                "exposure_ev": _normalized_number(self.exposure_delta_ev),
                "white_balance_mired": _normalized_number(
                    self.white_balance_delta_mired
                ),
            },
        }


def validate_reference_lighting_delta(
    value: ReferenceLightingDelta | Mapping[str, Any],
    *,
    require_policy_bounds: bool = False,
) -> ReferenceLightingDelta:
    delta = (
        value
        if isinstance(value, ReferenceLightingDelta)
        else ReferenceLightingDelta.from_dict(value)
    )
    if delta.schema_version != LIGHTING_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported lighting delta schema version: {delta.schema_version!r}"
        )
    for label, identifier in (
        ("reference_id", delta.reference_id),
        ("base_id", delta.base_id),
    ):
        if not _IDENTIFIER.fullmatch(identifier):
            raise ValueError(
                f"{label} must contain only lowercase letters, numbers, _ or -"
            )
    numeric = {
        "direction_degrees": delta.direction_delta_degrees,
        "elevation_degrees": delta.elevation_delta_degrees,
        "hardness": delta.hardness_delta,
        "shadow_density": delta.shadow_density_delta,
        "exposure_ev": delta.exposure_delta_ev,
        "white_balance_mired": delta.white_balance_delta_mired,
        "confidence": delta.confidence,
    }
    if any(not math.isfinite(item) for item in numeric.values()):
        raise ValueError("Lighting delta values must be finite")
    if not 0 <= delta.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    _hex_digest(delta.source_pixel_sha256, label="source_pixel_sha256")
    if require_policy_bounds:
        bounded = {
            "hardness": delta.hardness_delta,
            "shadow_density": delta.shadow_density_delta,
            "exposure_ev": delta.exposure_delta_ev,
            "white_balance_mired": delta.white_balance_delta_mired,
        }
        for label, actual in bounded.items():
            if abs(actual) > DELTA_LIMITS[label]:
                raise ValueError(
                    f"delta.{label} exceeds policy limit +/-{DELTA_LIMITS[label]}"
                )
    return delta


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def clamp_reference_lighting_delta(
    value: ReferenceLightingDelta | Mapping[str, Any],
) -> tuple[dict[str, float], list[str]]:
    delta = validate_reference_lighting_delta(value)
    raw = {
        "direction_degrees": delta.direction_delta_degrees,
        "elevation_degrees": delta.elevation_delta_degrees,
        "hardness": delta.hardness_delta,
        "shadow_density": delta.shadow_density_delta,
        "exposure_ev": delta.exposure_delta_ev,
        "white_balance_mired": delta.white_balance_delta_mired,
    }
    applied = dict(raw)
    applied["direction_degrees"] = ((raw["direction_degrees"] + 180) % 360) - 180
    applied["elevation_degrees"] = _clamp(raw["elevation_degrees"], -90, 90)
    for field in ("hardness", "shadow_density", "exposure_ev", "white_balance_mired"):
        limit = DELTA_LIMITS[field]
        applied[field] = _clamp(raw[field], -limit, limit)
    clamped = [
        f"delta.{field}"
        for field in raw
        if not math.isclose(raw[field], applied[field], abs_tol=1e-12)
    ]
    return applied, clamped


@dataclass(frozen=True)
class ResolvedLightingContract:
    effective_lighting_id: str
    effective_lighting_hash: str
    base_id: str
    base_hash: str
    reference_id: str
    source_pixel_sha256: str | None
    family: str
    direction_degrees: float
    elevation_degrees: float
    hardness: float
    shadow_density: float
    exposure_ev: float
    white_balance_mired: float
    applied_delta: dict[str, float]
    clamped_fields: tuple[str, ...]
    schema_version: str = LIGHTING_CONTRACT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "effective_lighting_id": self.effective_lighting_id,
            "effective_lighting_hash": self.effective_lighting_hash,
            "base_id": self.base_id,
            "base_hash": self.base_hash,
            "reference_id": self.reference_id,
            "source_pixel_sha256": self.source_pixel_sha256,
            "family": self.family,
            "signature": {
                "direction_degrees": self.direction_degrees,
                "elevation_degrees": self.elevation_degrees,
                "hardness": self.hardness,
                "shadow_density": self.shadow_density,
                "exposure_ev": self.exposure_ev,
                "white_balance_mired": self.white_balance_mired,
            },
            "applied_delta": dict(self.applied_delta),
            "clamped_fields": list(self.clamped_fields),
        }


def resolve_lighting_contract(
    base_value: WhiteLightingBase | Mapping[str, Any],
    delta_value: ReferenceLightingDelta | Mapping[str, Any],
) -> ResolvedLightingContract:
    base = validate_white_lighting_base(base_value)
    delta = validate_reference_lighting_delta(delta_value)
    if delta.base_id != base.base_id:
        raise ValueError(
            f"Lighting delta targets {delta.base_id!r}, not base {base.base_id!r}"
        )
    applied, clamped = clamp_reference_lighting_delta(delta)
    raw_effective = {
        "direction_degrees": (base.direction_degrees + applied["direction_degrees"])
        % 360,
        "elevation_degrees": base.elevation_degrees + applied["elevation_degrees"],
        "hardness": base.hardness + applied["hardness"],
        "shadow_density": base.shadow_density + applied["shadow_density"],
        "exposure_ev": base.exposure_ev + applied["exposure_ev"],
        "white_balance_mired": base.white_balance_mired
        + applied["white_balance_mired"],
    }
    effective = {
        "direction_degrees": raw_effective["direction_degrees"],
        "elevation_degrees": _clamp(raw_effective["elevation_degrees"], 0, 90),
        "hardness": _clamp(raw_effective["hardness"], 0, 1),
        "shadow_density": _clamp(raw_effective["shadow_density"], 0, 1),
        "exposure_ev": _clamp(raw_effective["exposure_ev"], -3, 3),
        "white_balance_mired": _clamp(
            raw_effective["white_balance_mired"], 100, 500
        ),
    }
    clamped.extend(
        f"effective.{field}"
        for field in raw_effective
        if not math.isclose(raw_effective[field], effective[field], abs_tol=1e-12)
    )
    effective = {
        field: _normalized_number(number) for field, number in effective.items()
    }
    applied = {field: _normalized_number(number) for field, number in applied.items()}
    hash_payload = {
        "schema_version": LIGHTING_CONTRACT_SCHEMA_VERSION,
        "base_id": base.base_id,
        "base_hash": base.base_hash,
        "reference_id": delta.reference_id,
        "source_pixel_sha256": delta.source_pixel_sha256,
        "family": base.family,
        "signature": effective,
        "applied_delta": applied,
    }
    effective_hash = _canonical_hash(hash_payload)
    return ResolvedLightingContract(
        effective_lighting_id=f"lighting_{effective_hash[:20]}",
        effective_lighting_hash=effective_hash,
        base_id=base.base_id,
        base_hash=base.base_hash,
        reference_id=delta.reference_id,
        source_pixel_sha256=delta.source_pixel_sha256,
        family=base.family,
        applied_delta=applied,
        clamped_fields=tuple(sorted(set(clamped))),
        **effective,
    )


DEFAULT_DIFFUSE_WHITE_BASE = WhiteLightingBase(
    base_id="white_diffuse_base_v1",
    family="diffuse",
    direction_degrees=315.0,
    elevation_degrees=42.0,
    hardness=0.28,
    shadow_density=0.17,
    exposure_ev=0.02,
    white_balance_mired=185.0,
)
DEFAULT_DIRECT_WHITE_BASE = WhiteLightingBase(
    base_id="white_direct_base_v1",
    family="direct",
    direction_degrees=45.0,
    elevation_degrees=34.0,
    hardness=0.75,
    shadow_density=0.37,
    exposure_ev=-0.14,
    white_balance_mired=196.0,
)
DEFAULT_WHITE_LIGHTING_BASES = MappingProxyType(
    {
        "diffuse": DEFAULT_DIFFUSE_WHITE_BASE,
        "direct": DEFAULT_DIRECT_WHITE_BASE,
    }
)
