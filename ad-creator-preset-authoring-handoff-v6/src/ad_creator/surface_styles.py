from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from PIL import Image

from .wood_materials import (
    BBoxInput,
    ImageInput,
    MATERIAL_MASK_APPROVAL_THRESHOLD,
    NormalizedBBox,
    _canonical_hash,
    _lab_percentiles,
    _load_mask,
    _load_rgb,
    _mask_hash,
    _pixel_box,
    _pixel_hash,
    _rgb_to_lab,
    _triple,
)


SURFACE_STYLE_SCHEMA_VERSION = "1.0.0"
TRANSFER_POLICIES = frozenset({"shape_only", "shape_finish", "abstract_pattern"})
MATERIAL_FAMILIES = frozenset(
    {"ceramic", "glass", "paper", "metal", "wood", "stone", "textile", "unknown"}
)
SURFACE_FINISHES = frozenset({"matte", "satin", "gloss", "translucent", "unknown"})
STRUCTURAL_TEXTURES = frozenset(
    {"smooth", "ribbed", "fluted", "rough", "embossed", "unknown"}
)
ABSTRACT_PATTERNS = frozenset(
    {"none", "speckled", "striped", "dotted", "marbled", "unknown"}
)
TEXT_BRAND_STATES = frozenset({"verified_absent", "verified_present", "uncertain"})


def _permissions(policy: str, text_brand_state: str) -> tuple[list[str], list[str]]:
    allowed = ["silhouette", "aspect_ratio", "handle_and_lid_structure"]
    if policy in {"shape_finish", "abstract_pattern"}:
        allowed.extend(["material_family", "finish", "structural_texture"])
    if policy == "abstract_pattern" and text_brand_state == "verified_absent":
        allowed.extend(["abstract_pattern_type", "pattern_scale", "pattern_density"])
    forbidden = [
        "visible_text",
        "logo",
        "illustration",
        "exact_pixel_pattern",
        "source_object_identity",
        "source_composition",
    ]
    if policy == "shape_only":
        forbidden.extend(["surface_color", "finish", "surface_pattern"])
    elif policy == "shape_finish":
        forbidden.append("surface_pattern")
    if text_brand_state != "verified_absent":
        forbidden.append("abstract_pattern_transfer")
    return allowed, sorted(set(forbidden))


@dataclass(frozen=True)
class SurfaceStyleProfile:
    profile_id: str
    material_family: str
    transfer_policy: str
    observed_lab_median: tuple[float, float, float]
    observed_lab_p10: tuple[float, float, float]
    observed_lab_p90: tuple[float, float, float]
    normalized_lab_median: tuple[float, float, float]
    normalized_lab_p10: tuple[float, float, float]
    normalized_lab_p90: tuple[float, float, float]
    finish: str
    structural_texture: str
    abstract_pattern: str
    pattern_density: float
    text_brand_state: str
    confidence: float
    source_pixel_sha256: str
    material_mask_sha256: str
    surface_bbox: dict[str, float]
    measurement_evidence: dict[str, Any]
    schema_version: str = SURFACE_STYLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_surface_style_profile(self, _already_profile=True)

    def to_dict(self) -> dict[str, Any]:
        allowed, forbidden = _permissions(self.transfer_policy, self.text_brand_state)
        return {
            "schema_version": self.schema_version,
            "profile_type": "surface_style",
            "profile_id": self.profile_id,
            "material_family": self.material_family,
            "transfer_policy": self.transfer_policy,
            "appearance": {
                "observed_lab": {
                    "median": list(self.observed_lab_median),
                    "p10": list(self.observed_lab_p10),
                    "p90": list(self.observed_lab_p90),
                },
                "normalized_material_lab": {
                    "median": list(self.normalized_lab_median),
                    "p10": list(self.normalized_lab_p10),
                    "p90": list(self.normalized_lab_p90),
                },
                "finish": self.finish,
                "structural_texture": self.structural_texture,
                "abstract_pattern": self.abstract_pattern,
                "pattern_density": round(self.pattern_density, 6),
            },
            "text_brand_state": self.text_brand_state,
            "transfer_permissions": allowed,
            "transfer_prohibitions": forbidden,
            "confidence": round(self.confidence, 6),
            "source_pixel_sha256": self.source_pixel_sha256,
            "material_mask_sha256": self.material_mask_sha256,
            "surface_bbox": self.surface_bbox,
            "measurement_evidence": self.measurement_evidence,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurfaceStyleProfile":
        appearance = value.get("appearance")
        if not isinstance(appearance, Mapping):
            raise ValueError("Surface style appearance must be an object")
        observed = appearance.get("observed_lab")
        normalized = appearance.get("normalized_material_lab")
        if not isinstance(observed, Mapping) or not isinstance(normalized, Mapping):
            raise ValueError("Surface style requires observed and normalized Lab values")
        return cls(
            schema_version=str(value.get("schema_version", SURFACE_STYLE_SCHEMA_VERSION)),
            profile_id=str(value.get("profile_id", "")),
            material_family=str(value.get("material_family", "")),
            transfer_policy=str(value.get("transfer_policy", "")),
            observed_lab_median=_triple(observed.get("median", ()), label="observed_lab.median"),
            observed_lab_p10=_triple(observed.get("p10", ()), label="observed_lab.p10"),
            observed_lab_p90=_triple(observed.get("p90", ()), label="observed_lab.p90"),
            normalized_lab_median=_triple(
                normalized.get("median", ()), label="normalized_material_lab.median"
            ),
            normalized_lab_p10=_triple(
                normalized.get("p10", ()), label="normalized_material_lab.p10"
            ),
            normalized_lab_p90=_triple(
                normalized.get("p90", ()), label="normalized_material_lab.p90"
            ),
            finish=str(appearance.get("finish", "")),
            structural_texture=str(appearance.get("structural_texture", "")),
            abstract_pattern=str(appearance.get("abstract_pattern", "")),
            pattern_density=float(appearance.get("pattern_density", -1)),
            text_brand_state=str(value.get("text_brand_state", "")),
            confidence=float(value.get("confidence", -1)),
            source_pixel_sha256=str(value.get("source_pixel_sha256", "")),
            material_mask_sha256=str(value.get("material_mask_sha256", "")),
            surface_bbox=dict(value.get("surface_bbox", {})),
            measurement_evidence=dict(value.get("measurement_evidence", {})),
        )


def validate_surface_style_profile(
    value: SurfaceStyleProfile | Mapping[str, Any],
    *,
    _already_profile: bool = False,
) -> SurfaceStyleProfile:
    profile = value if _already_profile else (
        value if isinstance(value, SurfaceStyleProfile) else SurfaceStyleProfile.from_dict(value)
    )
    assert isinstance(profile, SurfaceStyleProfile)
    if profile.schema_version != SURFACE_STYLE_SCHEMA_VERSION:
        raise ValueError("Unsupported SurfaceStyleProfile schema version")
    if not profile.profile_id.strip():
        raise ValueError("SurfaceStyleProfile requires profile_id")
    for label, actual, allowed in (
        ("material_family", profile.material_family, MATERIAL_FAMILIES),
        ("transfer_policy", profile.transfer_policy, TRANSFER_POLICIES),
        ("finish", profile.finish, SURFACE_FINISHES),
        ("structural_texture", profile.structural_texture, STRUCTURAL_TEXTURES),
        ("abstract_pattern", profile.abstract_pattern, ABSTRACT_PATTERNS),
        ("text_brand_state", profile.text_brand_state, TEXT_BRAND_STATES),
    ):
        if actual not in allowed:
            raise ValueError(f"Unsupported surface style {label}: {actual!r}")
    if (
        profile.transfer_policy == "abstract_pattern"
        and profile.text_brand_state != "verified_absent"
    ):
        raise ValueError("Abstract pattern transfer requires verified-absent text and branding")
    if not 0 <= profile.pattern_density <= 1 or not 0 <= profile.confidence <= 1:
        raise ValueError("Surface pattern density and confidence must be between 0 and 1")
    for digest in (profile.source_pixel_sha256, profile.material_mask_sha256):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("Surface style hashes must be lowercase SHA-256 digests")
    box = NormalizedBBox.from_value(profile.surface_bbox)
    normalized_bbox = {
        key: round(float(value), 6) for key, value in profile.surface_bbox.items()
    }
    if box.to_dict() != normalized_bbox:
        raise ValueError("Surface style bbox must use normalized coordinates")
    for prefix, p10, median, p90 in (
        (
            "observed",
            profile.observed_lab_p10,
            profile.observed_lab_median,
            profile.observed_lab_p90,
        ),
        (
            "normalized",
            profile.normalized_lab_p10,
            profile.normalized_lab_median,
            profile.normalized_lab_p90,
        ),
    ):
        for channel in range(3):
            if not p10[channel] <= median[channel] <= p90[channel]:
                raise ValueError(f"{prefix} Lab percentiles must satisfy p10 <= median <= p90")
    evidence = dict(profile.measurement_evidence)
    evidence_hash = evidence.pop("measurement_sha256", None)
    if evidence_hash != _canonical_hash(evidence):
        raise ValueError("Surface style measurement evidence hash is invalid")
    if evidence.get("source_pixel_sha256") != profile.source_pixel_sha256:
        raise ValueError("Surface style measurement source hash mismatch")
    if evidence.get("material_mask_sha256") != profile.material_mask_sha256:
        raise ValueError("Surface style measurement mask hash mismatch")
    return profile


def extract_surface_style_profile(
    source: ImageInput,
    material_mask: ImageInput,
    *,
    profile_id: str,
    surface_bbox: BBoxInput,
    material_family: str = "unknown",
    transfer_policy: str = "shape_only",
    text_brand_state: str = "uncertain",
    lighting_lab_offset: Sequence[float] = (0.0, 0.0, 0.0),
    finish_hint: str | None = None,
    structural_texture_hint: str | None = None,
    abstract_pattern_hint: str | None = None,
    extractor_version: str = "surface_style_extractor_local_v1",
) -> SurfaceStyleProfile:
    """Extract surface appearance while keeping transfer authority fail-closed."""

    if material_family not in MATERIAL_FAMILIES:
        raise ValueError(f"Unsupported material family: {material_family!r}")
    if transfer_policy not in TRANSFER_POLICIES:
        raise ValueError(f"Unsupported transfer policy: {transfer_policy!r}")
    if text_brand_state not in TEXT_BRAND_STATES:
        raise ValueError(f"Unsupported text/brand state: {text_brand_state!r}")
    if transfer_policy == "abstract_pattern" and text_brand_state != "verified_absent":
        raise ValueError("Abstract pattern transfer requires verified-absent text and branding")
    offset = _triple(lighting_lab_offset, label="lighting_lab_offset")
    image = _load_rgb(source)
    mask = _load_mask(material_mask, image.size)
    bbox = NormalizedBBox.from_value(surface_bbox)
    pixel_box = _pixel_box(bbox, image.size)
    crop = image.crop(pixel_box)
    crop_mask = mask.crop(pixel_box)
    if max(crop.size) > 256:
        scale = 256 / max(crop.size)
        target = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        crop = crop.resize(target, Image.Resampling.LANCZOS)
        crop_mask = crop_mask.resize(target, Image.Resampling.NEAREST)
    mask_values = list(crop_mask.get_flattened_data())
    rgb_values = [
        rgb
        for rgb, approved in zip(
            crop.get_flattened_data(), mask_values, strict=True
        )
        if approved >= MATERIAL_MASK_APPROVAL_THRESHOLD
    ]
    if len(rgb_values) < 16:
        raise ValueError("Surface style mask has too few approved pixels")
    observed_values = [_rgb_to_lab(rgb) for rgb in rgb_values]
    observed_p10, observed_median, observed_p90 = _lab_percentiles(observed_values)
    normalized_values = [
        (
            max(0.0, min(100.0, item[0] - offset[0])),
            max(-128.0, min(127.0, item[1] - offset[1])),
            max(-128.0, min(127.0, item[2] - offset[2])),
        )
        for item in observed_values
    ]
    normalized_p10, normalized_median, normalized_p90 = _lab_percentiles(normalized_values)
    gray_values = [sum(rgb) / 3 for rgb in rgb_values]
    mean = sum(gray_values) / len(gray_values)
    deviation = math.sqrt(sum((item - mean) ** 2 for item in gray_values) / len(gray_values))
    outlier_count = sum(
        abs(item - mean) > 1.5 * max(deviation, 1) for item in gray_values
    )
    pattern_density = min(1.0, outlier_count / len(gray_values))
    highlights = sum(max(rgb) >= 242 for rgb in rgb_values) / len(rgb_values)
    inferred_finish = (
        "translucent"
        if material_family == "glass"
        else "gloss"
        if highlights >= 0.08
        else "satin"
        if highlights >= 0.025
        else "matte"
    )
    finish = finish_hint or inferred_finish
    texture = structural_texture_hint or ("smooth" if deviation < 18 else "rough")
    pattern = abstract_pattern_hint or ("none" if pattern_density < 0.03 else "speckled")
    if (
        finish not in SURFACE_FINISHES
        or texture not in STRUCTURAL_TEXTURES
        or pattern not in ABSTRACT_PATTERNS
    ):
        raise ValueError("Unsupported surface style hint")
    measurement = {
        "extractor_version": extractor_version,
        "source_pixel_sha256": _pixel_hash(image),
        "material_mask_sha256": _mask_hash(mask),
        "surface_bbox": bbox.to_dict(),
        "analysis_sample_count": len(rgb_values),
        "normalization": {"method": "explicit_lab_offset_v1", "lab_offset": list(offset)},
        "highlight_fraction": round(highlights, 6),
        "luminance_deviation": round(deviation, 6),
    }
    measurement["measurement_sha256"] = _canonical_hash(measurement)
    confidence = min(0.95, 0.72 + 0.23 * min(1, len(rgb_values) / 4096))
    return SurfaceStyleProfile(
        profile_id=profile_id,
        material_family=material_family,
        transfer_policy=transfer_policy,
        observed_lab_median=observed_median,
        observed_lab_p10=observed_p10,
        observed_lab_p90=observed_p90,
        normalized_lab_median=normalized_median,
        normalized_lab_p10=normalized_p10,
        normalized_lab_p90=normalized_p90,
        finish=finish,
        structural_texture=texture,
        abstract_pattern=pattern,
        pattern_density=pattern_density,
        text_brand_state=text_brand_state,
        confidence=confidence,
        source_pixel_sha256=_pixel_hash(image),
        material_mask_sha256=_mask_hash(mask),
        surface_bbox=bbox.to_dict(),
        measurement_evidence=measurement,
    )


def surface_style_profile_hash(value: SurfaceStyleProfile | Mapping[str, Any]) -> str:
    profile = validate_surface_style_profile(value)
    return hashlib.sha256(
        json.dumps(profile.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
