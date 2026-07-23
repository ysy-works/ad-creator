from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageOps, ImageStat


WOOD_PROFILE_SCHEMA_VERSION = "3.1.0"
LEGACY_WOOD_PROFILE_SCHEMA_VERSION = "3.0.0"
SUPPORTED_WOOD_PROFILE_SCHEMA_VERSIONS = frozenset(
    {LEGACY_WOOD_PROFILE_SCHEMA_VERSION, WOOD_PROFILE_SCHEMA_VERSION}
)
SCENE_SURFACE_OCCUPANCY_BASIS = "scene_surface_fraction"
UNAVAILABLE_SURFACE_OCCUPANCY_BASIS = "unavailable"
LEGACY_AMBIGUOUS_SURFACE_OCCUPANCY_BASIS = "legacy_ambiguous_v3_0"
SURFACE_OCCUPANCY_BASES = frozenset(
    {
        SCENE_SURFACE_OCCUPANCY_BASIS,
        UNAVAILABLE_SURFACE_OCCUPANCY_BASIS,
        LEGACY_AMBIGUOUS_SURFACE_OCCUPANCY_BASIS,
    }
)
LIGHTNESS_CLASSES = frozenset({"pale", "light", "medium", "dark"})
COLOR_FAMILIES = frozenset(
    {"neutral-gray", "honey-yellow", "orange-red", "brown", "chocolate"}
)
GRAIN_PATTERNS = frozenset(
    {
        "straight",
        "cathedral",
        "quartered",
        "figured",
        "slatted",
        "engineered",
        "indistinct",
    }
)
FINISHES = frozenset(
    {
        "raw-matte",
        "oiled-matte",
        "satin",
        "gloss",
        "painted",
        "whitewashed",
    }
)
PROFILE_STATUSES = frozenset({"draft", "published"})
MINIMUM_MATERIAL_PURITY = 0.92
DEFAULT_EXCLUSION_EXPANSION = 0.08
MATERIAL_MASK_POLICY_VERSION = "material_mask_purity_v1"
MATERIAL_MASK_APPROVAL_THRESHOLD = 128


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_number(value: float) -> float:
    return float(round(float(value), 6))


def _triple(value: Sequence[float], *, label: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{label} must contain exactly three numbers")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{label} values must be finite")
    return result  # type: ignore[return-value]


@dataclass(frozen=True)
class WoodMaterialProfile:
    """Structured, provider-independent description of one observed wood surface."""

    lightness: str
    color_family: str
    grain_pattern: str
    finish: str
    lab_median: tuple[float, float, float]
    lab_p10: tuple[float, float, float]
    lab_p90: tuple[float, float, float]
    chroma: float
    grain_direction_degrees: float | None
    grain_frequency: float
    grain_contrast: float
    # Compatibility name for the *scene* surface fraction. It must never be
    # populated from extraction-mask coverage. The serialized 3.1 contract
    # makes this meaning explicit with ``surface_occupancy_basis``.
    surface_occupancy: float | None
    confidence: float
    species: str = "unknown"
    status: str = "draft"
    source_pixel_sha256: str | None = None
    artifact: dict[str, Any] | None = None
    observed_lab_median: tuple[float, float, float] | None = None
    observed_lab_p10: tuple[float, float, float] | None = None
    observed_lab_p90: tuple[float, float, float] | None = None
    measurement_evidence: dict[str, Any] | None = None
    surface_occupancy_basis: str = SCENE_SURFACE_OCCUPANCY_BASIS
    schema_version: str = WOOD_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_wood_material_profile(self, _already_profile=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WoodMaterialProfile:
        schema_version = str(value.get("schema_version", WOOD_PROFILE_SCHEMA_VERSION))
        axes = value.get("family_axes", {})
        appearance = value.get("appearance", {})
        if not isinstance(axes, Mapping) or not isinstance(appearance, Mapping):
            raise ValueError("family_axes and appearance must be objects")
        lab = appearance.get("lab", value.get("lab", {}))
        grain = value.get("grain", {})
        if not isinstance(lab, Mapping) or not isinstance(grain, Mapping):
            raise ValueError("lab and grain must be objects")
        artifact_value = value.get("artifact")
        if artifact_value is not None and not isinstance(artifact_value, Mapping):
            raise ValueError("artifact must be an object or null")
        raw_occupancy = appearance.get(
            "surface_occupancy", value.get("surface_occupancy")
        )
        if schema_version == LEGACY_WOOD_PROFILE_SCHEMA_VERSION:
            occupancy_basis = LEGACY_AMBIGUOUS_SURFACE_OCCUPANCY_BASIS
        elif "schema_version" in value:
            # Versioned 3.1 manifests must state the semantic basis. Inferring it
            # here would let malformed persisted contracts bypass the schema.
            occupancy_basis = str(appearance.get("surface_occupancy_basis", ""))
        else:
            occupancy_basis = str(
                appearance.get(
                    "surface_occupancy_basis",
                    (
                        SCENE_SURFACE_OCCUPANCY_BASIS
                        if raw_occupancy is not None
                        else UNAVAILABLE_SURFACE_OCCUPANCY_BASIS
                    ),
                )
            )
        return cls(
            schema_version=schema_version,
            lightness=str(
                axes.get(
                    "lightness", value.get("lightness", value.get("brightness", ""))
                )
            ),
            color_family=str(
                axes.get("color_family", value.get("color_family", ""))
            ),
            grain_pattern=str(
                axes.get(
                    "grain_pattern",
                    grain.get("pattern", value.get("grain_pattern", "")),
                )
            ),
            finish=str(axes.get("finish", value.get("finish", ""))),
            lab_median=_triple(
                lab.get("median", value.get("lab_median", ())),
                label="lab.median",
            ),
            lab_p10=_triple(
                lab.get("p10", value.get("lab_p10", ())),
                label="lab.p10",
            ),
            lab_p90=_triple(
                lab.get("p90", value.get("lab_p90", ())),
                label="lab.p90",
            ),
            chroma=float(appearance.get("chroma", value.get("chroma", 0.0))),
            grain_direction_degrees=(
                None
                if appearance.get(
                    "grain_direction_degrees",
                    grain.get(
                        "direction_degrees", value.get("grain_direction_degrees")
                    ),
                )
                is None
                else float(
                    appearance.get(
                        "grain_direction_degrees",
                        grain.get(
                            "direction_degrees", value.get("grain_direction_degrees")
                        ),
                    )
                )
            ),
            grain_frequency=float(
                appearance.get(
                    "grain_frequency",
                    grain.get("frequency", value.get("grain_frequency", 0.0)),
                )
            ),
            grain_contrast=float(
                appearance.get(
                    "grain_contrast",
                    grain.get("contrast", value.get("grain_contrast", 0.0)),
                )
            ),
            surface_occupancy=(
                float(raw_occupancy) if raw_occupancy is not None else None
            ),
            surface_occupancy_basis=occupancy_basis,
            confidence=float(value.get("confidence", 0.0)),
            species=str(value.get("species", "unknown")),
            status=str(value.get("status", "draft")),
            source_pixel_sha256=(
                str(value["source_pixel_sha256"])
                if value.get("source_pixel_sha256") is not None
                else None
            ),
            artifact=(
                dict(artifact_value) if isinstance(artifact_value, Mapping) else None
            ),
            observed_lab_median=(
                _triple(appearance["observed_lab"]["median"], label="observed_lab.median")
                if isinstance(appearance.get("observed_lab"), Mapping)
                else None
            ),
            observed_lab_p10=(
                _triple(appearance["observed_lab"]["p10"], label="observed_lab.p10")
                if isinstance(appearance.get("observed_lab"), Mapping)
                else None
            ),
            observed_lab_p90=(
                _triple(appearance["observed_lab"]["p90"], label="observed_lab.p90")
                if isinstance(appearance.get("observed_lab"), Mapping)
                else None
            ),
            measurement_evidence=(
                dict(value["measurement_evidence"])
                if isinstance(value.get("measurement_evidence"), Mapping)
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        appearance: dict[str, Any] = {
            "lab": {
                "median": [_normalized_number(item) for item in self.lab_median],
                "p10": [_normalized_number(item) for item in self.lab_p10],
                "p90": [_normalized_number(item) for item in self.lab_p90],
            },
            "chroma": _normalized_number(self.chroma),
            "grain_direction_degrees": (
                _normalized_number(self.grain_direction_degrees)
                if self.grain_direction_degrees is not None
                else None
            ),
            "grain_frequency": _normalized_number(self.grain_frequency),
            "grain_contrast": _normalized_number(self.grain_contrast),
            "surface_occupancy": (
                _normalized_number(self.surface_occupancy)
                if self.surface_occupancy is not None
                else None
            ),
            "observed_lab": (
                {
                    "median": [
                        _normalized_number(item) for item in self.observed_lab_median
                    ],
                    "p10": [
                        _normalized_number(item) for item in self.observed_lab_p10
                    ],
                    "p90": [
                        _normalized_number(item) for item in self.observed_lab_p90
                    ],
                }
                if self.observed_lab_median is not None
                and self.observed_lab_p10 is not None
                and self.observed_lab_p90 is not None
                else None
            ),
        }
        if self.schema_version != LEGACY_WOOD_PROFILE_SCHEMA_VERSION:
            appearance["surface_occupancy_basis"] = self.surface_occupancy_basis
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "family_axes": {
                "lightness": self.lightness,
                "color_family": self.color_family,
                "grain_pattern": self.grain_pattern,
                "finish": self.finish,
            },
            "appearance": appearance,
            "confidence": _normalized_number(self.confidence),
            "species": self.species,
            "source_pixel_sha256": self.source_pixel_sha256,
            "artifact": self.artifact,
            "measurement_evidence": self.measurement_evidence,
        }


def validate_wood_material_profile(
    value: WoodMaterialProfile | Mapping[str, Any],
    *,
    _already_profile: bool = False,
) -> WoodMaterialProfile:
    profile = value if _already_profile else (
        value if isinstance(value, WoodMaterialProfile) else WoodMaterialProfile.from_dict(value)
    )
    assert isinstance(profile, WoodMaterialProfile)
    if profile.schema_version not in SUPPORTED_WOOD_PROFILE_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported wood profile schema version: {profile.schema_version!r}"
        )
    if profile.surface_occupancy_basis not in SURFACE_OCCUPANCY_BASES:
        raise ValueError(
            "Unsupported surface_occupancy_basis: "
            f"{profile.surface_occupancy_basis!r}"
        )
    if profile.schema_version == LEGACY_WOOD_PROFILE_SCHEMA_VERSION:
        if (
            profile.surface_occupancy_basis
            != LEGACY_AMBIGUOUS_SURFACE_OCCUPANCY_BASIS
        ):
            raise ValueError(
                "Wood profile v3.0 surface_occupancy must remain legacy_ambiguous; "
                "upgrade explicitly instead of reinterpreting it"
            )
        if profile.surface_occupancy is None:
            raise ValueError("Wood profile v3.0 requires legacy surface_occupancy")
    else:
        if (
            profile.surface_occupancy_basis
            == LEGACY_AMBIGUOUS_SURFACE_OCCUPANCY_BASIS
        ):
            raise ValueError(
                "Wood profile v3.1 cannot carry ambiguous legacy occupancy semantics"
            )
        if profile.surface_occupancy is None:
            if profile.surface_occupancy_basis != UNAVAILABLE_SURFACE_OCCUPANCY_BASIS:
                raise ValueError(
                    "Missing scene surface occupancy must use the unavailable basis"
                )
        elif profile.surface_occupancy_basis != SCENE_SURFACE_OCCUPANCY_BASIS:
            raise ValueError(
                "Numeric surface_occupancy must use scene_surface_fraction basis"
            )
        if profile.status == "published" and profile.surface_occupancy is None:
            raise ValueError(
                "Published wood profile requires reviewed scene surface occupancy"
            )
    for label, actual, allowed in (
        ("lightness", profile.lightness, LIGHTNESS_CLASSES),
        ("color_family", profile.color_family, COLOR_FAMILIES),
        ("grain.pattern", profile.grain_pattern, GRAIN_PATTERNS),
        ("finish", profile.finish, FINISHES),
        ("status", profile.status, PROFILE_STATUSES),
    ):
        if actual not in allowed:
            raise ValueError(f"Unsupported {label}: {actual!r}")
    triples = {
        "lab.p10": _triple(profile.lab_p10, label="lab.p10"),
        "lab.median": _triple(profile.lab_median, label="lab.median"),
        "lab.p90": _triple(profile.lab_p90, label="lab.p90"),
    }
    observed_values = (
        profile.observed_lab_p10,
        profile.observed_lab_median,
        profile.observed_lab_p90,
    )
    if any(item is not None for item in observed_values):
        if any(item is None for item in observed_values):
            raise ValueError("Observed Lab p10, median and p90 must be provided together")
        assert all(item is not None for item in observed_values)
        triples.update(
            {
                "observed_lab.p10": _triple(profile.observed_lab_p10, label="observed_lab.p10"),
                "observed_lab.median": _triple(
                    profile.observed_lab_median, label="observed_lab.median"
                ),
                "observed_lab.p90": _triple(profile.observed_lab_p90, label="observed_lab.p90"),
            }
        )
    for label, lab_value in triples.items():
        if not 0 <= lab_value[0] <= 100:
            raise ValueError(f"{label} L* must be between 0 and 100")
        if any(not -128 <= channel <= 127 for channel in lab_value[1:]):
            raise ValueError(f"{label} a* and b* must be between -128 and 127")
    for channel in range(3):
        if not (
            profile.lab_p10[channel]
            <= profile.lab_median[channel]
            <= profile.lab_p90[channel]
        ):
            raise ValueError("Lab percentiles must satisfy p10 <= median <= p90")
        if all(item is not None for item in observed_values) and not (
            profile.observed_lab_p10[channel]  # type: ignore[index]
            <= profile.observed_lab_median[channel]  # type: ignore[index]
            <= profile.observed_lab_p90[channel]  # type: ignore[index]
        ):
            raise ValueError("Observed Lab percentiles must satisfy p10 <= median <= p90")
    numeric_ranges = (
        ("chroma", profile.chroma, 0.0, 182.0),
        ("grain.frequency", profile.grain_frequency, 0.0, 10_000.0),
        ("grain.contrast", profile.grain_contrast, 0.0, 1.0),
        ("confidence", profile.confidence, 0.0, 1.0),
    )
    for label, actual, minimum, maximum in numeric_ranges:
        if not math.isfinite(actual) or not minimum <= actual <= maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}")
    if profile.surface_occupancy is not None and (
        not math.isfinite(profile.surface_occupancy)
        or not 0 <= profile.surface_occupancy <= 1
    ):
        raise ValueError("surface_occupancy must be null or between 0 and 1")
    direction = profile.grain_direction_degrees
    if direction is not None and (
        not math.isfinite(direction) or not 0 <= direction < 180
    ):
        raise ValueError("grain.direction_degrees must be null or in [0, 180)")
    if profile.species != "unknown":
        raise ValueError("species must remain 'unknown'; wood species inference is prohibited")
    source_hash = profile.source_pixel_sha256
    if source_hash is not None and (
        len(source_hash) != 64
        or source_hash != source_hash.lower()
        or any(character not in "0123456789abcdef" for character in source_hash)
    ):
        raise ValueError("source_pixel_sha256 must be a 64-character hex digest")
    artifact = profile.artifact
    if artifact is not None:
        required = {
            "kind",
            "path",
            "pixel_sha256",
            "selection_hash",
            "purity",
            "purity_evidence",
        }
        missing = sorted(required - set(artifact))
        if missing:
            raise ValueError(f"artifact is missing required fields: {missing}")
        if artifact["kind"] not in {
            "derived_material_board",
            "masked_raw_material_crop",
        }:
            raise ValueError(f"Unsupported artifact kind: {artifact['kind']!r}")
        if not isinstance(artifact["path"], str) or not artifact["path"].strip():
            raise ValueError("artifact.path must be a non-empty string")
        for label in ("pixel_sha256", "selection_hash"):
            digest = artifact[label]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or digest != digest.lower()
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(f"artifact.{label} must be a 64-character hex digest")
        purity = artifact["purity"]
        if (
            not isinstance(purity, (int, float))
            or not math.isfinite(float(purity))
            or not MINIMUM_MATERIAL_PURITY <= float(purity) <= 1
        ):
            raise ValueError(
                f"artifact.purity must be between {MINIMUM_MATERIAL_PURITY} and 1"
            )
        purity_evidence = artifact["purity_evidence"]
        if not isinstance(purity_evidence, Mapping):
            raise ValueError("artifact.purity_evidence must be an object")
        evidence_required = {
            "policy_version",
            "source_pixel_sha256",
            "material_mask_sha256",
            "approval_threshold",
            "region_bbox",
            "approved_pixel_count",
            "total_pixel_count",
            "measured_purity",
            "measurement_sha256",
        }
        evidence_missing = sorted(evidence_required - set(purity_evidence))
        if evidence_missing:
            raise ValueError(
                f"artifact.purity_evidence is missing required fields: {evidence_missing}"
            )
        if purity_evidence["policy_version"] != MATERIAL_MASK_POLICY_VERSION:
            raise ValueError("artifact.purity_evidence has an unsupported policy_version")
        for label in ("source_pixel_sha256", "material_mask_sha256", "measurement_sha256"):
            digest = purity_evidence[label]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or digest != digest.lower()
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(
                    f"artifact.purity_evidence.{label} must be a 64-character hex digest"
                )
        approved = purity_evidence["approved_pixel_count"]
        total = purity_evidence["total_pixel_count"]
        if (
            not isinstance(approved, int)
            or isinstance(approved, bool)
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total <= 0
            or not 0 <= approved <= total
        ):
            raise ValueError("artifact.purity_evidence pixel counts are invalid")
        measured = round(approved / total, 6)
        if measured != float(purity_evidence["measured_purity"]):
            raise ValueError("artifact.purity_evidence measured_purity does not match its counts")
        if measured != round(float(purity), 6):
            raise ValueError("artifact.purity does not match measured mask evidence")
        stable_evidence = dict(purity_evidence)
        evidence_hash = stable_evidence.pop("measurement_sha256")
        if _canonical_hash(stable_evidence) != evidence_hash:
            raise ValueError("artifact.purity_evidence measurement hash is invalid")
    measurement = profile.measurement_evidence
    if measurement is not None:
        required_measurement = {
            "extractor_version",
            "source_pixel_sha256",
            "material_mask_sha256",
            "surface_bbox",
            "mask_purity_evidence",
            "analysis_sample_count",
            "analysis_size_px",
            "normalization",
            "grain_direction_concentration",
            "highlight_fraction",
            "measurement_sha256",
        }
        missing_measurement = sorted(required_measurement - set(measurement))
        if missing_measurement:
            raise ValueError(
                f"measurement_evidence is missing required fields: {missing_measurement}"
            )
        stable_measurement = dict(measurement)
        measurement_hash = stable_measurement.pop("measurement_sha256")
        if _canonical_hash(stable_measurement) != measurement_hash:
            raise ValueError("measurement_evidence hash is invalid")
        if profile.source_pixel_sha256 != measurement["source_pixel_sha256"]:
            raise ValueError("measurement_evidence source hash does not match the profile")
        if (
            not isinstance(measurement["analysis_sample_count"], int)
            or measurement["analysis_sample_count"] < 16
        ):
            raise ValueError("measurement_evidence has too few analysis samples")
        coverage_keys = {
            "safe_mask_approved_pixel_count",
            "source_pixel_count",
            "safe_mask_coverage",
        }
        available_coverage_keys = coverage_keys & set(measurement)
        if profile.schema_version == WOOD_PROFILE_SCHEMA_VERSION and (
            available_coverage_keys != coverage_keys
        ):
            raise ValueError(
                "Wood profile v3.1 measurement_evidence requires explicit safe-mask "
                "coverage counts"
            )
        if available_coverage_keys:
            if available_coverage_keys != coverage_keys:
                raise ValueError(
                    "Safe-mask coverage value and pixel counts must be provided together"
                )
            approved = measurement["safe_mask_approved_pixel_count"]
            total = measurement["source_pixel_count"]
            coverage = measurement["safe_mask_coverage"]
            if (
                not isinstance(approved, int)
                or isinstance(approved, bool)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or total <= 0
                or not 0 <= approved <= total
                or not isinstance(coverage, (int, float))
                or isinstance(coverage, bool)
                or not math.isfinite(float(coverage))
            ):
                raise ValueError("measurement_evidence safe-mask coverage is invalid")
            if round(approved / total, 6) != float(coverage):
                raise ValueError(
                    "measurement_evidence safe_mask_coverage does not match its counts"
                )
    return profile


def wood_material_profile_hash(
    value: WoodMaterialProfile | Mapping[str, Any],
) -> str:
    return _canonical_hash(validate_wood_material_profile(value).to_dict())


def delta_e_ciede2000(
    first: Sequence[float],
    second: Sequence[float],
) -> float:
    """Calculate CIEDE2000 color distance for two CIE Lab triples."""

    l1, a1, b1 = _triple(first, label="first Lab")
    l2, a2, b2 = _triple(second, label="second Lab")
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    mean_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(mean_c**7 / (mean_c**7 + 25**7)))
    a1_prime = (1 + g) * a1
    a2_prime = (1 + g) * a2
    c1_prime = math.hypot(a1_prime, b1)
    c2_prime = math.hypot(a2_prime, b2)

    def hue(a_value: float, b_value: float) -> float:
        if a_value == 0 and b_value == 0:
            return 0.0
        return math.degrees(math.atan2(b_value, a_value)) % 360

    h1_prime = hue(a1_prime, b1)
    h2_prime = hue(a2_prime, b2)
    delta_l = l2 - l1
    delta_c = c2_prime - c1_prime
    if c1_prime * c2_prime == 0:
        delta_h_degrees = 0.0
    elif abs(h2_prime - h1_prime) <= 180:
        delta_h_degrees = h2_prime - h1_prime
    elif h2_prime <= h1_prime:
        delta_h_degrees = h2_prime - h1_prime + 360
    else:
        delta_h_degrees = h2_prime - h1_prime - 360
    delta_h = 2 * math.sqrt(c1_prime * c2_prime) * math.sin(
        math.radians(delta_h_degrees / 2)
    )
    mean_l = (l1 + l2) / 2
    mean_c_prime = (c1_prime + c2_prime) / 2
    if c1_prime * c2_prime == 0:
        mean_h = h1_prime + h2_prime
    elif abs(h1_prime - h2_prime) <= 180:
        mean_h = (h1_prime + h2_prime) / 2
    elif h1_prime + h2_prime < 360:
        mean_h = (h1_prime + h2_prime + 360) / 2
    else:
        mean_h = (h1_prime + h2_prime - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(mean_h - 30))
        + 0.24 * math.cos(math.radians(2 * mean_h))
        + 0.32 * math.cos(math.radians(3 * mean_h + 6))
        - 0.20 * math.cos(math.radians(4 * mean_h - 63))
    )
    s_l = 1 + 0.015 * (mean_l - 50) ** 2 / math.sqrt(20 + (mean_l - 50) ** 2)
    s_c = 1 + 0.045 * mean_c_prime
    s_h = 1 + 0.015 * mean_c_prime * t
    delta_theta = 30 * math.exp(-((mean_h - 275) / 25) ** 2)
    r_c = 2 * math.sqrt(mean_c_prime**7 / (mean_c_prime**7 + 25**7))
    r_t = -r_c * math.sin(math.radians(2 * delta_theta))
    l_term = delta_l / s_l
    c_term = delta_c / s_c
    h_term = delta_h / s_h
    return math.sqrt(
        l_term**2 + c_term**2 + h_term**2 + r_t * c_term * h_term
    )


def _metric_status(
    value: float,
    *,
    pass_test: bool,
    warning_test: bool,
) -> str:
    del value
    if pass_test:
        return "pass"
    if warning_test:
        return "warning"
    return "fail"


def _grain_angle_difference(first: float, second: float) -> float:
    difference = abs(first - second) % 180
    return min(difference, 180 - difference)


def evaluate_wood_material_qa(
    expected: WoodMaterialProfile | Mapping[str, Any],
    observed: WoodMaterialProfile | Mapping[str, Any],
    *,
    leakage_flags: Iterable[str] = (),
) -> dict[str, Any]:
    target = validate_wood_material_profile(expected)
    actual = validate_wood_material_profile(observed)
    delta_e = delta_e_ciede2000(target.lab_median, actual.lab_median)
    lightness_difference = abs(target.lab_median[0] - actual.lab_median[0])
    chroma_difference = abs(target.chroma - actual.chroma)
    occupancy_authoritative = (
        target.surface_occupancy_basis == SCENE_SURFACE_OCCUPANCY_BASIS
        and actual.surface_occupancy_basis == SCENE_SURFACE_OCCUPANCY_BASIS
        and target.surface_occupancy is not None
        and actual.surface_occupancy is not None
    )
    occupancy_difference = (
        abs(target.surface_occupancy - actual.surface_occupancy)
        if occupancy_authoritative
        and target.surface_occupancy is not None
        and actual.surface_occupancy is not None
        else None
    )
    if (
        target.grain_direction_degrees is None
        or actual.grain_direction_degrees is None
    ):
        direction_difference: float | None = None
    else:
        direction_difference = _grain_angle_difference(
            target.grain_direction_degrees,
            actual.grain_direction_degrees,
        )
    if target.grain_frequency == 0:
        frequency_ratio = 1.0 if actual.grain_frequency == 0 else math.inf
    else:
        frequency_ratio = actual.grain_frequency / target.grain_frequency

    metrics: dict[str, dict[str, Any]] = {
        "delta_e_00": {
            "value": round(delta_e, 6),
            "status": _metric_status(
                delta_e, pass_test=delta_e <= 8, warning_test=delta_e <= 12
            ),
            "pass_max": 8,
            "warning_max": 12,
        },
        "lightness_difference": {
            "value": round(lightness_difference, 6),
            "status": _metric_status(
                lightness_difference,
                pass_test=lightness_difference <= 8,
                warning_test=lightness_difference <= 12,
            ),
            "pass_max": 8,
            "warning_max": 12,
        },
        "chroma_difference": {
            "value": round(chroma_difference, 6),
            "status": _metric_status(
                chroma_difference,
                pass_test=chroma_difference <= 6,
                warning_test=chroma_difference <= 10,
            ),
            "pass_max": 6,
            "warning_max": 10,
        },
        "grain_frequency_ratio": {
            "value": frequency_ratio,
            "status": _metric_status(
                frequency_ratio,
                pass_test=0.65 <= frequency_ratio <= 1.55,
                warning_test=0.5 <= frequency_ratio <= 2.0,
            ),
            "pass_range": [0.65, 1.55],
            "warning_range": [0.5, 2.0],
        },
        "surface_occupancy_difference": (
            {
                "value": round(occupancy_difference, 6),
                "status": _metric_status(
                    occupancy_difference,
                    pass_test=occupancy_difference <= 0.12,
                    warning_test=occupancy_difference <= 0.20,
                ),
                "pass_max": 0.12,
                "warning_max": 0.20,
                "expected_basis": target.surface_occupancy_basis,
                "observed_basis": actual.surface_occupancy_basis,
            }
            if occupancy_difference is not None
            else {
                "value": None,
                "status": "needs_review",
                "pass_max": 0.12,
                "warning_max": 0.20,
                "expected_basis": target.surface_occupancy_basis,
                "observed_basis": actual.surface_occupancy_basis,
            }
        ),
    }
    metrics["grain_direction_difference_degrees"] = (
        {
            "value": None,
            "status": "not_applicable"
            if target.grain_pattern == actual.grain_pattern == "indistinct"
            else "needs_review",
            "pass_max": 15,
            "warning_max": 25,
        }
        if direction_difference is None
        else {
            "value": round(direction_difference, 6),
            "status": _metric_status(
                direction_difference,
                pass_test=direction_difference <= 15,
                warning_test=direction_difference <= 25,
            ),
            "pass_max": 15,
            "warning_max": 25,
        }
    )

    leakage = sorted({str(item) for item in leakage_flags if str(item).strip()})
    reason_codes = [
        f"wood_{name}_{metric['status']}"
        for name, metric in metrics.items()
        if metric["status"] in {"warning", "fail", "needs_review"}
    ]
    if leakage:
        reason_codes.insert(0, "material_board_leakage")
        status = "fail"
    else:
        states = {metric["status"] for metric in metrics.values()}
        status = (
            "fail"
            if "fail" in states
            else "needs_review"
            if "needs_review" in states
            else "warning"
            if "warning" in states
            else "pass"
        )
    return {
        "policy_version": "wood_material_qa_v2",
        "status": status,
        "metrics": metrics,
        "leakage_flags": leakage,
        "reason_codes": reason_codes,
    }


@dataclass(frozen=True)
class NormalizedBBox:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        coordinates = (self.left, self.top, self.right, self.bottom)
        if not all(math.isfinite(item) for item in coordinates) or not (
            0 <= self.left < self.right <= 1
            and 0 <= self.top < self.bottom <= 1
        ):
            raise ValueError("Normalized bbox coordinates must be ordered within [0, 1]")

    @classmethod
    def from_value(
        cls,
        value: NormalizedBBox | Mapping[str, Any] | Sequence[float],
    ) -> NormalizedBBox:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            nested = value.get("bbox")
            if nested is not None:
                return cls.from_value(nested)
            coordinates = (
                value.get("left"),
                value.get("top"),
                value.get("right"),
                value.get("bottom"),
            )
        else:
            if isinstance(value, (str, bytes)) or len(value) != 4:
                raise ValueError("A normalized bbox must contain four coordinates")
            coordinates = tuple(value)
        try:
            result = cls(*(float(item) for item in coordinates))
        except (TypeError, ValueError) as exc:
            raise ValueError("A normalized bbox must contain four numbers") from exc
        if not (
            0 <= result.left < result.right <= 1
            and 0 <= result.top < result.bottom <= 1
        ):
            raise ValueError("Normalized bbox coordinates must be ordered within [0, 1]")
        return result

    @property
    def area(self) -> float:
        return (self.right - self.left) * (self.bottom - self.top)

    def to_dict(self) -> dict[str, float]:
        return {
            "left": round(self.left, 6),
            "top": round(self.top, 6),
            "right": round(self.right, 6),
            "bottom": round(self.bottom, 6),
        }


def expand_normalized_bbox(
    value: NormalizedBBox | Mapping[str, Any] | Sequence[float],
    fraction: float = DEFAULT_EXCLUSION_EXPANSION,
) -> NormalizedBBox:
    if not math.isfinite(fraction) or fraction < 0:
        raise ValueError("BBox expansion fraction must be a non-negative number")
    box = NormalizedBBox.from_value(value)
    horizontal = (box.right - box.left) * fraction
    vertical = (box.bottom - box.top) * fraction
    return NormalizedBBox(
        max(0.0, box.left - horizontal),
        max(0.0, box.top - vertical),
        min(1.0, box.right + horizontal),
        min(1.0, box.bottom + vertical),
    )


@dataclass
class MaterialArtifactResult:
    image: Image.Image | None
    manifest: dict[str, Any]

    @property
    def available(self) -> bool:
        return self.image is not None

    def save(self, path: str | Path) -> Path:
        if self.image is None:
            raise ValueError("No material artifact is available; use structured values only")
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(destination)
        self.manifest["path"] = str(destination)
        return destination

    def profile_artifact(self, path: str | Path | None = None) -> dict[str, Any] | None:
        if not self.available:
            return None
        artifact_path = str(path) if path is not None else self.manifest.get("path")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            raise ValueError("Save the artifact or provide its path before embedding it")
        return {
            "kind": self.manifest["artifact_kind"],
            "path": artifact_path,
            "pixel_sha256": self.manifest["artifact_pixel_sha256"],
            "selection_hash": self.manifest["selection_hash"],
            "purity": self.manifest["measured_purity"],
            "purity_evidence": self.manifest["purity_evidence"],
        }


ImageInput = str | Path | Image.Image
BBoxInput = NormalizedBBox | Mapping[str, Any] | Sequence[float]


def _load_rgb(value: ImageInput) -> Image.Image:
    if isinstance(value, Image.Image):
        return ImageOps.exif_transpose(value).convert("RGB")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Image does not exist: {path}")
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _load_mask(value: ImageInput, expected_size: tuple[int, int]) -> Image.Image:
    if isinstance(value, Image.Image):
        mask = ImageOps.exif_transpose(value).convert("L")
    else:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Material mask does not exist: {path}")
        with Image.open(path) as opened:
            mask = ImageOps.exif_transpose(opened).convert("L")
    if mask.size != expected_size:
        raise ValueError("Material mask dimensions must match the source image")
    return mask


def _pixel_hash(image: Image.Image) -> str:
    converted = image.convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"RGB:{converted.width}x{converted.height}:".encode("ascii"))
    digest.update(converted.tobytes())
    return digest.hexdigest()


def _mask_hash(mask: Image.Image) -> str:
    converted = mask.convert("L")
    digest = hashlib.sha256()
    digest.update(f"L:{converted.width}x{converted.height}:".encode("ascii"))
    digest.update(converted.tobytes())
    return digest.hexdigest()


def _intersects(first: NormalizedBBox, second: NormalizedBBox) -> bool:
    return not (
        first.right <= second.left
        or second.right <= first.left
        or first.bottom <= second.top
        or second.bottom <= first.top
    )


def _carve_candidate(
    candidate: NormalizedBBox,
    exclusion: NormalizedBBox,
) -> list[NormalizedBBox]:
    if not _intersects(candidate, exclusion):
        return [candidate]
    intersection_left = max(candidate.left, exclusion.left)
    intersection_top = max(candidate.top, exclusion.top)
    intersection_right = min(candidate.right, exclusion.right)
    intersection_bottom = min(candidate.bottom, exclusion.bottom)
    values = [
        (candidate.left, candidate.top, intersection_left, candidate.bottom),
        (intersection_right, candidate.top, candidate.right, candidate.bottom),
        (candidate.left, candidate.top, candidate.right, intersection_top),
        (candidate.left, intersection_bottom, candidate.right, candidate.bottom),
    ]
    return [
        NormalizedBBox(*value)
        for value in values
        if value[2] - value[0] > 1e-9 and value[3] - value[1] > 1e-9
    ]


def _prune_candidates(values: Iterable[NormalizedBBox]) -> list[NormalizedBBox]:
    unique = {
        (
            round(value.left, 9),
            round(value.top, 9),
            round(value.right, 9),
            round(value.bottom, 9),
        ): value
        for value in values
    }
    candidates = sorted(
        unique.values(),
        key=lambda item: (-item.area, item.top, item.left, item.bottom, item.right),
    )
    result: list[NormalizedBBox] = []
    for candidate in candidates:
        contained = any(
            existing.left <= candidate.left
            and existing.top <= candidate.top
            and existing.right >= candidate.right
            and existing.bottom >= candidate.bottom
            for existing in result
        )
        if not contained:
            result.append(candidate)
    return result


def _pixel_box(
    box: NormalizedBBox,
    size: tuple[int, int],
) -> tuple[int, int, int, int]:
    width, height = size
    return (
        max(0, min(width, math.ceil(box.left * width))),
        max(0, min(height, math.ceil(box.top * height))),
        max(0, min(width, math.floor(box.right * width))),
        max(0, min(height, math.floor(box.bottom * height))),
    )


def _measure_material_mask_region(
    candidate: NormalizedBBox,
    *,
    size: tuple[int, int],
    material_mask: Image.Image,
    source_pixel_sha256: str,
) -> dict[str, Any]:
    """Measure mask-approved coverage without trusting caller declarations."""

    pixels = _pixel_box(candidate, size)
    if pixels[2] <= pixels[0] or pixels[3] <= pixels[1]:
        approved = 0
        total = 0
    else:
        histogram = material_mask.crop(pixels).histogram()
        approved = sum(histogram[MATERIAL_MASK_APPROVAL_THRESHOLD:])
        total = sum(histogram)
    purity = approved / total if total else 0.0
    evidence = {
        "policy_version": MATERIAL_MASK_POLICY_VERSION,
        "source_pixel_sha256": source_pixel_sha256,
        "material_mask_sha256": _mask_hash(material_mask),
        "approval_threshold": MATERIAL_MASK_APPROVAL_THRESHOLD,
        "region_bbox": candidate.to_dict(),
        "approved_pixel_count": approved,
        "total_pixel_count": total,
        "measured_purity": round(purity, 6),
    }
    evidence["measurement_sha256"] = _canonical_hash(evidence)
    return evidence


def measure_material_mask_purity(
    source: ImageInput,
    material_mask: ImageInput,
    *,
    region_bbox: BBoxInput,
) -> dict[str, Any]:
    """Return independently reproducible pixel evidence for a material mask region."""

    image = _load_rgb(source)
    mask = _load_mask(material_mask, image.size)
    return _measure_material_mask_region(
        NormalizedBBox.from_value(region_bbox),
        size=image.size,
        material_mask=mask,
        source_pixel_sha256=_pixel_hash(image),
    )


def _sanitized_crop(
    image: Image.Image,
    box: tuple[int, int, int, int],
    material_mask: Image.Image | None,
) -> Image.Image:
    crop = image.crop(box)
    if material_mask is None:
        return crop
    mask = material_mask.crop(box).point(lambda value: 255 if value >= 128 else 0)
    if not mask.getbbox():
        raise ValueError("Selected material region contains no mask-approved pixels")
    median = tuple(round(value) for value in ImageStat.Stat(crop, mask).median)
    background = Image.new("RGB", crop.size, median)
    return Image.composite(crop, background, mask)


def _select_safe_region(
    image: Image.Image,
    *,
    surface_bbox: BBoxInput,
    exclusion_bboxes: Iterable[BBoxInput],
    material_mask: Image.Image,
    minimum_purity: float,
    exclusion_expansion: float,
    minimum_side_px: int,
) -> tuple[NormalizedBBox | None, float, list[NormalizedBBox], dict[str, Any] | None]:
    if not 0 <= minimum_purity <= 1:
        raise ValueError("minimum_purity must be between 0 and 1")
    if minimum_side_px < 1:
        raise ValueError("minimum_side_px must be positive")
    surface = NormalizedBBox.from_value(surface_bbox)
    exclusions = [
        expand_normalized_bbox(value, exclusion_expansion)
        for value in exclusion_bboxes
    ]
    candidates = [surface]
    for exclusion in exclusions:
        candidates = _prune_candidates(
            carved
            for candidate in candidates
            for carved in _carve_candidate(candidate, exclusion)
        )
        if not candidates:
            break
    best_purity = 0.0
    best_evidence: dict[str, Any] | None = None
    source_hash = _pixel_hash(image)
    for candidate in candidates:
        pixel_box = _pixel_box(candidate, image.size)
        if (
            pixel_box[2] - pixel_box[0] < minimum_side_px
            or pixel_box[3] - pixel_box[1] < minimum_side_px
        ):
            continue
        purity_evidence = _measure_material_mask_region(
            candidate,
            size=image.size,
            material_mask=material_mask,
            source_pixel_sha256=source_hash,
        )
        purity = float(purity_evidence["measured_purity"])
        if purity > best_purity or best_evidence is None:
            best_evidence = purity_evidence
        best_purity = max(best_purity, purity)
        if purity >= minimum_purity:
            return candidate, purity, exclusions, purity_evidence
    return None, best_purity, exclusions, best_evidence


def _unavailable_manifest(
    *,
    artifact_kind: str,
    source_hash: str,
    mask_hash: str | None,
    surface_bbox: NormalizedBBox,
    exclusions: list[NormalizedBBox],
    purity: float,
    minimum_purity: float,
    purity_evidence: Mapping[str, Any] | None,
    declared_purity: float | None,
) -> dict[str, Any]:
    selection = {
        "source_pixel_sha256": source_hash,
        "material_mask_sha256": mask_hash,
        "surface_bbox": surface_bbox.to_dict(),
        "expanded_exclusion_bboxes": [item.to_dict() for item in exclusions],
        "minimum_purity": minimum_purity,
        "measured_purity": round(purity, 6),
        "purity_evidence_sha256": (
            purity_evidence.get("measurement_sha256") if purity_evidence else None
        ),
        "artifact_kind": artifact_kind,
    }
    return {
        "schema_version": "1.0.0",
        "artifact_kind": artifact_kind,
        "available": False,
        "fallback": "structured_only",
        "reason_code": "no_safe_material_region",
        "measured_purity": round(purity, 6),
        "declared_purity": declared_purity,
        "declaration_used_as_authority": False,
        "purity_evidence": dict(purity_evidence) if purity_evidence else None,
        "minimum_purity": minimum_purity,
        "selection_hash": _canonical_hash(selection),
        **selection,
    }


def _artifact_result(
    image: Image.Image,
    artifact: Image.Image,
    *,
    artifact_kind: str,
    safe_bbox: NormalizedBBox,
    exclusions: list[NormalizedBBox],
    purity: float,
    minimum_purity: float,
    material_mask: Image.Image,
    purity_evidence: Mapping[str, Any],
    declared_purity: float | None,
    experimental: bool,
) -> MaterialArtifactResult:
    source_hash = _pixel_hash(image)
    mask_digest = _mask_hash(material_mask)
    selection = {
        "source_pixel_sha256": source_hash,
        "material_mask_sha256": mask_digest,
        "material_mask_applied": True,
        "safe_material_bbox": safe_bbox.to_dict(),
        "expanded_exclusion_bboxes": [item.to_dict() for item in exclusions],
        "minimum_purity": minimum_purity,
        "measured_purity": round(purity, 6),
        "purity_evidence_sha256": purity_evidence["measurement_sha256"],
        "artifact_kind": artifact_kind,
    }
    manifest = {
        "schema_version": "1.0.0",
        "artifact_kind": artifact_kind,
        "available": True,
        "experimental": experimental,
        "source_pixel_sha256": source_hash,
        "material_mask_sha256": mask_digest,
        "material_mask_applied": True,
        "artifact_pixel_sha256": _pixel_hash(artifact),
        "selection_hash": _canonical_hash(selection),
        "safe_material_bbox": safe_bbox.to_dict(),
        "safe_area_fraction": round(safe_bbox.area, 6),
        "expanded_exclusion_bboxes": [item.to_dict() for item in exclusions],
        "measured_purity": round(purity, 6),
        "declared_purity": declared_purity,
        "declaration_used_as_authority": False,
        "purity_evidence": dict(purity_evidence),
        "minimum_purity": minimum_purity,
        "width_px": artifact.width,
        "height_px": artifact.height,
        "copy_permissions": ["wood_color", "wood_chroma", "wood_grain", "wood_finish"],
        "copy_exclusions": [
            "objects",
            "composition",
            "visible_text",
            "branding",
            "lighting",
        ],
    }
    return MaterialArtifactResult(artifact, manifest)


def build_derived_material_board(
    source: ImageInput,
    *,
    surface_bbox: BBoxInput,
    exclusion_bboxes: Iterable[BBoxInput] = (),
    material_purity: float | None = None,
    material_mask: ImageInput | None = None,
    minimum_purity: float = MINIMUM_MATERIAL_PURITY,
    exclusion_expansion: float = DEFAULT_EXCLUSION_EXPANSION,
    board_size: tuple[int, int] = (512, 256),
    minimum_side_px: int = 24,
) -> MaterialArtifactResult:
    """Build a color-swatch + grain board only from a verified clean wood region."""

    image = _load_rgb(source)
    if material_mask is None:
        raise ValueError(
            "material_mask is required; declared material_purity cannot authorize a material board"
        )
    if material_purity is not None and (
        not math.isfinite(material_purity) or not 0 <= material_purity <= 1
    ):
        raise ValueError("material_purity must be between 0 and 1")
    mask = _load_mask(material_mask, image.size)
    surface = NormalizedBBox.from_value(surface_bbox)
    safe_bbox, purity, exclusions, purity_evidence = _select_safe_region(
        image,
        surface_bbox=surface,
        exclusion_bboxes=exclusion_bboxes,
        material_mask=mask,
        minimum_purity=minimum_purity,
        exclusion_expansion=exclusion_expansion,
        minimum_side_px=minimum_side_px,
    )
    if safe_bbox is None:
        return MaterialArtifactResult(
            None,
            _unavailable_manifest(
                artifact_kind="derived_material_board",
                source_hash=_pixel_hash(image),
                mask_hash=_mask_hash(mask) if mask is not None else None,
                surface_bbox=surface,
                exclusions=exclusions,
                purity=purity,
                minimum_purity=minimum_purity,
                purity_evidence=purity_evidence,
                declared_purity=material_purity,
            ),
        )
    width, height = board_size
    if width < 64 or height < 64:
        raise ValueError("Material board dimensions must each be at least 64 pixels")
    crop = _sanitized_crop(image, _pixel_box(safe_bbox, image.size), mask)
    median = tuple(round(channel) for channel in ImageStat.Stat(crop).median)
    swatch_width = max(1, width // 3)
    board = Image.new("RGB", (width, height), median)
    texture = ImageOps.fit(
        crop,
        (width - swatch_width, height),
        method=Image.Resampling.LANCZOS,
    )
    board.paste(texture, (swatch_width, 0))
    return _artifact_result(
        image,
        board,
        artifact_kind="derived_material_board",
        safe_bbox=safe_bbox,
        exclusions=exclusions,
        purity=purity,
        minimum_purity=minimum_purity,
        material_mask=mask,
        purity_evidence=purity_evidence,
        declared_purity=material_purity,
        experimental=False,
    )


def _limit_bbox_area(box: NormalizedBBox, maximum_area: float) -> NormalizedBBox:
    if box.area <= maximum_area:
        return box
    scale = math.sqrt(maximum_area / box.area)
    width = (box.right - box.left) * scale
    height = (box.bottom - box.top) * scale
    center_x = (box.left + box.right) / 2
    center_y = (box.top + box.bottom) / 2
    return NormalizedBBox(
        center_x - width / 2,
        center_y - height / 2,
        center_x + width / 2,
        center_y + height / 2,
    )


def build_masked_raw_material_crop(
    source: ImageInput,
    *,
    surface_bbox: BBoxInput,
    exclusion_bboxes: Iterable[BBoxInput] = (),
    material_purity: float | None = None,
    material_mask: ImageInput | None = None,
    minimum_purity: float = MINIMUM_MATERIAL_PURITY,
    exclusion_expansion: float = DEFAULT_EXCLUSION_EXPANSION,
    maximum_frame_area: float = 0.5,
    maximum_edge_px: int = 512,
    minimum_side_px: int = 24,
) -> MaterialArtifactResult:
    """Create the opt-in raw-crop experiment without ever forwarding a full scene."""

    if not 0 < maximum_frame_area < 1:
        raise ValueError("maximum_frame_area must be greater than 0 and less than 1")
    if maximum_edge_px < minimum_side_px:
        raise ValueError("maximum_edge_px must be at least minimum_side_px")
    image = _load_rgb(source)
    if material_mask is None:
        raise ValueError(
            "material_mask is required; declared material_purity cannot authorize a raw crop"
        )
    if material_purity is not None and (
        not math.isfinite(material_purity) or not 0 <= material_purity <= 1
    ):
        raise ValueError("material_purity must be between 0 and 1")
    mask = _load_mask(material_mask, image.size)
    surface = NormalizedBBox.from_value(surface_bbox)
    safe_bbox, purity, exclusions, purity_evidence = _select_safe_region(
        image,
        surface_bbox=surface,
        exclusion_bboxes=exclusion_bboxes,
        material_mask=mask,
        minimum_purity=minimum_purity,
        exclusion_expansion=exclusion_expansion,
        minimum_side_px=minimum_side_px,
    )
    if safe_bbox is None:
        return MaterialArtifactResult(
            None,
            _unavailable_manifest(
                artifact_kind="masked_raw_material_crop",
                source_hash=_pixel_hash(image),
                mask_hash=_mask_hash(mask) if mask is not None else None,
                surface_bbox=surface,
                exclusions=exclusions,
                purity=purity,
                minimum_purity=minimum_purity,
                purity_evidence=purity_evidence,
                declared_purity=material_purity,
            ),
        )
    safe_bbox = _limit_bbox_area(safe_bbox, maximum_frame_area)
    purity_evidence = _measure_material_mask_region(
        safe_bbox,
        size=image.size,
        material_mask=mask,
        source_pixel_sha256=_pixel_hash(image),
    )
    purity = float(purity_evidence["measured_purity"])
    pixel_box = _pixel_box(safe_bbox, image.size)
    if (
        purity < minimum_purity
        or pixel_box[2] - pixel_box[0] < minimum_side_px
        or pixel_box[3] - pixel_box[1] < minimum_side_px
    ):
        return MaterialArtifactResult(
            None,
            _unavailable_manifest(
                artifact_kind="masked_raw_material_crop",
                source_hash=_pixel_hash(image),
                mask_hash=_mask_hash(mask) if mask is not None else None,
                surface_bbox=surface,
                exclusions=exclusions,
                purity=purity,
                minimum_purity=minimum_purity,
                purity_evidence=purity_evidence,
                declared_purity=material_purity,
            ),
        )
    crop = _sanitized_crop(image, pixel_box, mask)
    if max(crop.size) > maximum_edge_px:
        crop.thumbnail(
            (maximum_edge_px, maximum_edge_px),
            Image.Resampling.LANCZOS,
        )
    result = _artifact_result(
        image,
        crop,
        artifact_kind="masked_raw_material_crop",
        safe_bbox=safe_bbox,
        exclusions=exclusions,
        purity=purity,
        minimum_purity=minimum_purity,
        material_mask=mask,
        purity_evidence=purity_evidence,
        declared_purity=material_purity,
        experimental=True,
    )
    result.manifest["maximum_frame_area"] = maximum_frame_area
    return result


def _srgb_channel_to_linear(value: int) -> float:
    channel = value / 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _rgb_to_lab(rgb: Sequence[int]) -> tuple[float, float, float]:
    red, green, blue = (_srgb_channel_to_linear(int(item)) for item in rgb)
    x = (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047
    y = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue
    z = (0.0193339 * red + 0.1191920 * green + 0.9503041 * blue) / 1.08883

    def pivot(value: float) -> float:
        delta = 6 / 29
        return value ** (1 / 3) if value > delta**3 else value / (3 * delta**2) + 4 / 29

    fx, fy, fz = pivot(x), pivot(y), pivot(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a percentile from an empty sample")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _lab_percentiles(
    values: Sequence[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    channels = [[value[index] for value in values] for index in range(3)]
    p10 = tuple(_percentile(channel, 0.10) for channel in channels)
    median = tuple(_percentile(channel, 0.50) for channel in channels)
    p90 = tuple(_percentile(channel, 0.90) for channel in channels)
    return p10, median, p90  # type: ignore[return-value]


def _classify_lightness(lightness: float) -> str:
    if lightness >= 78:
        return "pale"
    if lightness >= 64:
        return "light"
    if lightness >= 43:
        return "medium"
    return "dark"


def _classify_color_family(lab: Sequence[float]) -> str:
    lightness, a_star, b_star = lab
    chroma = math.hypot(a_star, b_star)
    if chroma < 8:
        return "neutral-gray"
    if a_star >= 18 and b_star >= 14:
        return "orange-red"
    if b_star >= 20 and a_star < 18:
        return "honey-yellow"
    if lightness < 42:
        return "chocolate"
    return "brown"


def _grain_measurements(
    image: Image.Image,
    mask: Image.Image,
) -> tuple[float | None, float, float, float]:
    gray = image.convert("L")
    pixels = gray.load()
    approved = mask.load()
    width, height = gray.size
    gradients: list[tuple[float, float]] = []
    luminance: list[float] = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            if approved[x, y] < MATERIAL_MASK_APPROVAL_THRESHOLD:
                continue
            luminance.append(float(pixels[x, y]))
            if (
                approved[x - 1, y] >= MATERIAL_MASK_APPROVAL_THRESHOLD
                and approved[x + 1, y] >= MATERIAL_MASK_APPROVAL_THRESHOLD
                and approved[x, y - 1] >= MATERIAL_MASK_APPROVAL_THRESHOLD
                and approved[x, y + 1] >= MATERIAL_MASK_APPROVAL_THRESHOLD
            ):
                gradients.append(
                    (
                        float(pixels[x + 1, y]) - float(pixels[x - 1, y]),
                        float(pixels[x, y + 1]) - float(pixels[x, y - 1]),
                    )
                )
    if len(luminance) < 16:
        return None, 0.0, 0.0, 0.0
    mean = sum(luminance) / len(luminance)
    standard_deviation = math.sqrt(
        sum((item - mean) ** 2 for item in luminance) / len(luminance)
    )
    contrast = min(1.0, standard_deviation / 64)
    if not gradients or contrast < 0.025:
        return None, 0.0, contrast, 0.0
    doubled_cos = 0.0
    doubled_sin = 0.0
    gradient_total = 0.0
    derivative_total = 0.0
    for gx, gy in gradients:
        magnitude = math.hypot(gx, gy)
        if magnitude <= 1e-9:
            continue
        angle = math.atan2(gy, gx)
        doubled_cos += magnitude * math.cos(2 * angle)
        doubled_sin += magnitude * math.sin(2 * angle)
        gradient_total += magnitude
        derivative_total += magnitude
    if gradient_total <= 1e-9:
        return None, 0.0, contrast, 0.0
    gradient_direction = math.degrees(0.5 * math.atan2(doubled_sin, doubled_cos)) % 180
    grain_direction = (gradient_direction + 90) % 180
    concentration = math.hypot(doubled_cos, doubled_sin) / gradient_total
    frequency = min(10_000.0, derivative_total / len(gradients) / 255 * 100)
    return grain_direction, frequency, contrast, concentration


def extract_wood_material_profile(
    source: ImageInput,
    material_mask: ImageInput,
    *,
    surface_bbox: BBoxInput,
    lighting_lab_offset: Sequence[float] = (0.0, 0.0, 0.0),
    grain_pattern_hint: str | None = None,
    finish_hint: str | None = None,
    scene_surface_occupancy: float | None = None,
    status: str = "draft",
    extractor_version: str = "wood_material_extractor_local_v2",
    maximum_analysis_edge_px: int = 256,
) -> WoodMaterialProfile:
    """Extract a deterministic draft profile from an exact source and full-size mask.

    The canonical ``appearance.lab`` values are lighting-normalized using the
    explicit Lab offset. The observed values are retained separately so that a
    caller cannot silently bake lighting color into the material contract.

    ``scene_surface_occupancy`` is an optional, independently reviewed scene
    composition measurement. The material mask is used only to calculate
    ``measurement_evidence.safe_mask_coverage`` and is never promoted to scene
    occupancy.
    """

    if status != "draft":
        raise ValueError("Local extraction produces draft profiles only; publish after review")
    if maximum_analysis_edge_px < 32:
        raise ValueError("maximum_analysis_edge_px must be at least 32")
    if scene_surface_occupancy is not None and (
        not math.isfinite(scene_surface_occupancy)
        or not 0 <= scene_surface_occupancy <= 1
    ):
        raise ValueError("scene_surface_occupancy must be null or between 0 and 1")
    if grain_pattern_hint is not None and grain_pattern_hint not in GRAIN_PATTERNS:
        raise ValueError(f"Unsupported grain pattern hint: {grain_pattern_hint!r}")
    if finish_hint is not None and finish_hint not in FINISHES:
        raise ValueError(f"Unsupported finish hint: {finish_hint!r}")
    lab_offset = _triple(lighting_lab_offset, label="lighting_lab_offset")
    image = _load_rgb(source)
    mask = _load_mask(material_mask, image.size)
    surface = NormalizedBBox.from_value(surface_bbox)
    purity_evidence = _measure_material_mask_region(
        surface,
        size=image.size,
        material_mask=mask,
        source_pixel_sha256=_pixel_hash(image),
    )
    if not purity_evidence["total_pixel_count"] or not purity_evidence["approved_pixel_count"]:
        raise ValueError("Wood surface mask contains no approved pixels")
    pixel_box = _pixel_box(surface, image.size)
    crop = image.crop(pixel_box)
    crop_mask = mask.crop(pixel_box)
    if max(crop.size) > maximum_analysis_edge_px:
        scale = maximum_analysis_edge_px / max(crop.size)
        target = (
            max(1, round(crop.width * scale)),
            max(1, round(crop.height * scale)),
        )
        crop = crop.resize(target, Image.Resampling.LANCZOS)
        crop_mask = crop_mask.resize(target, Image.Resampling.NEAREST)
    rgb_pixels = list(crop.get_flattened_data())
    mask_pixels = list(crop_mask.get_flattened_data())
    observed_lab_values = [
        _rgb_to_lab(rgb)
        for rgb, mask_value in zip(rgb_pixels, mask_pixels, strict=True)
        if mask_value >= MATERIAL_MASK_APPROVAL_THRESHOLD
    ]
    if len(observed_lab_values) < 16:
        raise ValueError("Wood surface mask has too few approved analysis pixels")
    observed_p10, observed_median, observed_p90 = _lab_percentiles(observed_lab_values)
    normalized_lab_values = [
        (
            max(0.0, min(100.0, value[0] - lab_offset[0])),
            max(-128.0, min(127.0, value[1] - lab_offset[1])),
            max(-128.0, min(127.0, value[2] - lab_offset[2])),
        )
        for value in observed_lab_values
    ]
    normalized_p10, normalized_median, normalized_p90 = _lab_percentiles(
        normalized_lab_values
    )
    direction, frequency, grain_contrast, direction_concentration = _grain_measurements(
        crop, crop_mask
    )
    chroma = math.hypot(normalized_median[1], normalized_median[2])
    if grain_pattern_hint is not None:
        grain_pattern = grain_pattern_hint
    elif direction is None:
        grain_pattern = "indistinct"
    elif direction_concentration >= 0.58:
        grain_pattern = "straight"
    else:
        grain_pattern = "figured"
    grayscale = crop.convert("L")
    approved_luminance = [
        value
        for value, mask_value in zip(
            grayscale.get_flattened_data(), mask_pixels, strict=True
        )
        if mask_value >= MATERIAL_MASK_APPROVAL_THRESHOLD
    ]
    highlight_fraction = sum(value >= 242 for value in approved_luminance) / len(
        approved_luminance
    )
    if finish_hint is not None:
        finish = finish_hint
    elif highlight_fraction >= 0.08:
        finish = "gloss"
    elif highlight_fraction >= 0.025:
        finish = "satin"
    elif chroma >= 14:
        finish = "oiled-matte"
    else:
        finish = "raw-matte"
    full_histogram = mask.histogram()
    approved_full = sum(full_histogram[MATERIAL_MASK_APPROVAL_THRESHOLD:])
    source_pixel_count = image.width * image.height
    safe_mask_coverage = approved_full / source_pixel_count
    sample_factor = min(1.0, len(observed_lab_values) / 4096)
    confidence = min(
        0.95,
        max(0.0, float(purity_evidence["measured_purity"]))
        * (0.72 + 0.23 * sample_factor),
    )
    measurement = {
        "extractor_version": extractor_version,
        "source_pixel_sha256": _pixel_hash(image),
        "material_mask_sha256": _mask_hash(mask),
        "surface_bbox": surface.to_dict(),
        "mask_purity_evidence": purity_evidence,
        "analysis_sample_count": len(observed_lab_values),
        "analysis_size_px": {"width": crop.width, "height": crop.height},
        "normalization": {
            "method": "explicit_lab_offset_v1",
            "lab_offset": [_normalized_number(item) for item in lab_offset],
        },
        "grain_direction_concentration": _normalized_number(direction_concentration),
        "highlight_fraction": _normalized_number(highlight_fraction),
        "safe_mask_approved_pixel_count": approved_full,
        "source_pixel_count": source_pixel_count,
        "safe_mask_coverage": _normalized_number(safe_mask_coverage),
    }
    measurement["measurement_sha256"] = _canonical_hash(measurement)
    return WoodMaterialProfile(
        lightness=_classify_lightness(normalized_median[0]),
        color_family=_classify_color_family(normalized_median),
        grain_pattern=grain_pattern,
        finish=finish,
        lab_median=normalized_median,
        lab_p10=normalized_p10,
        lab_p90=normalized_p90,
        chroma=chroma,
        grain_direction_degrees=direction,
        grain_frequency=frequency,
        grain_contrast=grain_contrast,
        surface_occupancy=scene_surface_occupancy,
        surface_occupancy_basis=(
            SCENE_SURFACE_OCCUPANCY_BASIS
            if scene_surface_occupancy is not None
            else UNAVAILABLE_SURFACE_OCCUPANCY_BASIS
        ),
        confidence=confidence,
        status="draft",
        source_pixel_sha256=_pixel_hash(image),
        observed_lab_median=observed_median,
        observed_lab_p10=observed_p10,
        observed_lab_p90=observed_p90,
        measurement_evidence=measurement,
    )


# Readable aliases for callers that use the plan terminology.
derive_safe_material_board = build_derived_material_board
build_masked_raw_experimental_arm = build_masked_raw_material_crop
