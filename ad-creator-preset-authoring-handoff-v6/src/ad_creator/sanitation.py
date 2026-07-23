from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .brand_restoration import canonical_raster_hash
from .control_board import create_control_board_sanitation_evidence
from .image_contracts import canonical_image_binding
from .vision_ocr import VISION_OCR_VERSION, VisionOCRUnavailable, run_vision_ocr
from .wood_materials import (
    build_derived_material_board,
    build_masked_raw_material_crop,
    measure_material_mask_purity,
)


SANITATION_RUNNER_VERSION = "local_control_board_sanitation_v1"
MINIMUM_WOOD_PURITY = 0.92
OBJECTNESS_CONFIDENCE_THRESHOLD = 0.55
OBJECTNESS_AREA_THRESHOLD = 0.01
REQUIRED_COPY_EXCLUSIONS = frozenset(
    {"objects", "composition", "visible_text", "branding", "lighting"}
)

VisionHook = Callable[..., Mapping[str, Any]]
LayoutComparisonHook = Callable[..., Mapping[str, Any]]


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


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _full_frame_finding(label: str, confidence: float = 1.0) -> dict[str, Any]:
    return {
        "label": label,
        "confidence": confidence,
        "bbox": {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0},
    }


def _validate_wood_artifact_provenance(
    image_path: Path,
    manifest: Mapping[str, Any],
    *,
    provenance_source_path: str | Path | None,
    provenance_mask_path: str | Path | None,
) -> tuple[bool, str, str]:
    """Recompute the material artifact's hash chain rather than trust flags."""

    binding = canonical_image_binding(image_path)
    artifact_kind = manifest.get("artifact_kind")
    if artifact_kind not in {"derived_material_board", "masked_raw_material_crop"}:
        return False, "unsupported_artifact_kind", "unknown"
    if manifest.get("available") is not True or manifest.get("material_mask_applied") is not True:
        return False, "material_mask_not_applied", str(artifact_kind)
    if manifest.get("artifact_pixel_sha256") != binding["pixel_sha256"]:
        return False, "artifact_pixel_hash_mismatch", str(artifact_kind)
    if provenance_source_path is None or provenance_mask_path is None:
        return False, "source_or_mask_file_missing", str(artifact_kind)
    source_path = Path(provenance_source_path).expanduser().resolve()
    mask_path = Path(provenance_mask_path).expanduser().resolve()
    if not source_path.is_file() or not mask_path.is_file():
        return False, "source_or_mask_file_missing", str(artifact_kind)
    try:
        source_binding = canonical_image_binding(source_path)
        with Image.open(source_path) as opened:
            source_image = ImageOps.exif_transpose(opened).convert("RGB")
        with Image.open(mask_path) as opened:
            material_mask = ImageOps.exif_transpose(opened).convert("L")
    except (FileNotFoundError, OSError, ValueError):
        return False, "source_or_mask_file_unreadable", str(artifact_kind)
    if material_mask.size != source_image.size:
        return False, "source_mask_dimensions_mismatch", str(artifact_kind)
    source_pixel_sha256 = source_binding["pixel_sha256"]
    material_mask_sha256 = canonical_raster_hash(material_mask, "L")
    if manifest.get("source_pixel_sha256") != source_pixel_sha256:
        return False, "source_pixel_hash_mismatch", str(artifact_kind)
    if manifest.get("material_mask_sha256") != material_mask_sha256:
        return False, "material_mask_hash_mismatch", str(artifact_kind)
    purity = manifest.get("measured_purity")
    minimum = manifest.get("minimum_purity")
    if (
        not isinstance(purity, (int, float))
        or isinstance(purity, bool)
        or not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or float(purity) < max(float(minimum), MINIMUM_WOOD_PURITY)
    ):
        return False, "material_purity_below_gate", str(artifact_kind)
    evidence = manifest.get("purity_evidence")
    if not isinstance(evidence, Mapping):
        return False, "purity_evidence_missing", str(artifact_kind)
    safe_bbox = manifest.get("safe_material_bbox")
    if not isinstance(safe_bbox, Mapping):
        return False, "safe_material_bbox_missing", str(artifact_kind)
    try:
        recomputed_evidence = measure_material_mask_purity(
            source_path,
            mask_path,
            region_bbox=safe_bbox,
        )
    except (FileNotFoundError, OSError, ValueError):
        return False, "purity_recomputation_failed", str(artifact_kind)
    if dict(evidence) != recomputed_evidence:
        return False, "purity_evidence_recomputation_mismatch", str(artifact_kind)
    evidence_hash = recomputed_evidence["measurement_sha256"]
    if float(recomputed_evidence["measured_purity"]) != float(purity):
        return False, "purity_evidence_binding_mismatch", str(artifact_kind)
    selection = {
        "source_pixel_sha256": source_pixel_sha256,
        "material_mask_sha256": material_mask_sha256,
        "material_mask_applied": True,
        "safe_material_bbox": manifest.get("safe_material_bbox"),
        "expanded_exclusion_bboxes": manifest.get("expanded_exclusion_bboxes"),
        "minimum_purity": manifest.get("minimum_purity"),
        "measured_purity": manifest.get("measured_purity"),
        "purity_evidence_sha256": evidence_hash,
        "artifact_kind": artifact_kind,
    }
    try:
        recomputed_selection_hash = _hash(selection)
    except (TypeError, ValueError):
        return False, "artifact_selection_invalid", str(artifact_kind)
    if manifest.get("selection_hash") != recomputed_selection_hash:
        return False, "artifact_selection_hash_mismatch", str(artifact_kind)
    copy_exclusions = manifest.get("copy_exclusions")
    if not isinstance(copy_exclusions, list) or not REQUIRED_COPY_EXCLUSIONS.issubset(
        set(copy_exclusions)
    ):
        return False, "copy_exclusions_incomplete", str(artifact_kind)
    try:
        if artifact_kind == "derived_material_board":
            reproduced = build_derived_material_board(
                source_path,
                surface_bbox=safe_bbox,
                material_mask=mask_path,
                minimum_purity=float(minimum),
                board_size=(binding["width_px"], binding["height_px"]),
                minimum_side_px=1,
            )
        else:
            maximum_frame_area = manifest.get("maximum_frame_area")
            if not isinstance(maximum_frame_area, (int, float)) or isinstance(
                maximum_frame_area, bool
            ):
                return False, "maximum_frame_area_missing", str(artifact_kind)
            reproduced = build_masked_raw_material_crop(
                source_path,
                surface_bbox=safe_bbox,
                material_mask=mask_path,
                minimum_purity=float(minimum),
                maximum_frame_area=float(maximum_frame_area),
                maximum_edge_px=max(binding["width_px"], binding["height_px"]),
                minimum_side_px=1,
            )
    except (OSError, ValueError):
        return False, "artifact_reproduction_failed", str(artifact_kind)
    if reproduced.image is None:
        return False, "artifact_reproduction_unavailable", str(artifact_kind)
    if canonical_raster_hash(reproduced.image, "RGB") != binding["pixel_sha256"]:
        return False, "artifact_reproduction_hash_mismatch", str(artifact_kind)
    return True, "verified", str(artifact_kind)


def _validate_layout_comparison(
    evidence: Mapping[str, Any],
    *,
    artifact_pixel_sha256: str,
    source_pixel_sha256: str,
) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
    if evidence.get("artifact_pixel_sha256") != artifact_pixel_sha256 or evidence.get(
        "source_pixel_sha256"
    ) != source_pixel_sha256:
        raise ValueError("Layout comparison evidence belongs to different pixels")
    detector = evidence.get("detector")
    if not isinstance(detector, Mapping) or any(
        not isinstance(detector.get(key), str) or not detector[key].strip()
        for key in ("name", "version")
    ):
        raise ValueError("Layout comparison evidence requires detector identity")
    copied = evidence.get("layout_copied")
    confidence = evidence.get("confidence")
    bboxes = evidence.get("bboxes")
    if not isinstance(copied, bool):
        raise ValueError("Layout comparison evidence requires layout_copied")
    if not (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and 0 <= float(confidence) <= 1
    ):
        raise ValueError("Layout comparison evidence requires confidence in 0..1")
    if not isinstance(bboxes, list):
        raise ValueError("Layout comparison evidence requires bboxes")
    findings: list[dict[str, Any]] = []
    for raw_bbox in bboxes:
        if not isinstance(raw_bbox, Mapping):
            raise ValueError("Layout comparison bbox must be an object")
        try:
            bbox = {
                key: float(raw_bbox[key])
                for key in ("left", "top", "right", "bottom")
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Layout comparison bbox is invalid") from exc
        if not (
            all(0 <= value <= 1 for value in bbox.values())
            and bbox["left"] < bbox["right"]
            and bbox["top"] < bbox["bottom"]
        ):
            raise ValueError("Layout comparison bbox is invalid")
        findings.append(
            {
                "label": "source_layout_copied",
                "confidence": float(confidence),
                "bbox": bbox,
            }
        )
    if copied and not findings:
        raise ValueError("Copied layout evidence requires at least one bbox")
    return ("fail" if copied else "pass"), findings, dict(detector)


def _validate_container_artifact_provenance(
    artifact_path: Path,
    manifest: Mapping[str, Any],
    *,
    provenance_source_path: str | Path | None,
    provenance_mask_path: str | Path | None,
) -> tuple[bool, str, str | None]:
    artifact_binding = canonical_image_binding(artifact_path)
    if (
        manifest.get("artifact_kind") != "deidentified_container_surface"
        or manifest.get("artifact_pixel_sha256") != artifact_binding["pixel_sha256"]
        or manifest.get("brand_mask_applied") is not True
        or manifest.get("scene_context_removed") is not True
    ):
        return False, "container_deidentification_provenance_missing", None
    if provenance_source_path is None or provenance_mask_path is None:
        return False, "container_source_or_mask_file_missing", None
    source_path = Path(provenance_source_path).expanduser().resolve()
    mask_path = Path(provenance_mask_path).expanduser().resolve()
    if not source_path.is_file() or not mask_path.is_file():
        return False, "container_source_or_mask_file_missing", None
    try:
        source_binding = canonical_image_binding(source_path)
        with Image.open(source_path) as opened:
            source_size = ImageOps.exif_transpose(opened).size
        with Image.open(mask_path) as opened:
            brand_mask = ImageOps.exif_transpose(opened).convert("L")
    except (FileNotFoundError, OSError, ValueError):
        return False, "container_source_or_mask_file_unreadable", None
    if brand_mask.size != source_size:
        return False, "container_source_mask_dimensions_mismatch", None
    if manifest.get("source_pixel_sha256") != source_binding["pixel_sha256"]:
        return False, "container_source_pixel_hash_mismatch", None
    if manifest.get("brand_mask_sha256") != canonical_raster_hash(brand_mask, "L"):
        return False, "container_brand_mask_hash_mismatch", None
    return True, "verified", source_binding["pixel_sha256"]


def _vision_findings(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    regions = result.get("regions")
    if not isinstance(regions, Mapping) or not isinstance(regions.get("full_image"), Mapping):
        raise VisionOCRUnavailable("Vision sanitation output has no full_image region")
    text_region = regions["full_image"]
    text_findings: list[dict[str, Any]] = []
    text = str(text_region.get("text") or "visible_text")[:80]
    confidence = float(text_region.get("confidence") or 0)
    for bbox in text_region.get("bboxes", []):
        text_findings.append(
            {"label": f"visible_text:{text}", "confidence": confidence, "bbox": dict(bbox)}
        )

    objectness = result.get("objectness")
    if not isinstance(objectness, Mapping) or objectness.get("status") != "available":
        raise VisionOCRUnavailable("Vision objectness detector is unavailable")
    object_findings: list[dict[str, Any]] = []
    for item in objectness.get("objects", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("bbox"), Mapping):
            continue
        bbox = item["bbox"]
        area = (float(bbox["right"]) - float(bbox["left"])) * (
            float(bbox["bottom"]) - float(bbox["top"])
        )
        confidence = float(item.get("confidence") or 0)
        if confidence >= OBJECTNESS_CONFIDENCE_THRESHOLD and area >= OBJECTNESS_AREA_THRESHOLD:
            object_findings.append(
                {
                    "label": "salient_object_requires_review",
                    "confidence": confidence,
                    "bbox": dict(bbox),
                }
            )
    return text_findings, object_findings


def run_local_control_board_sanitation(
    source_path: str | Path,
    *,
    role: str,
    artifact_manifest: Mapping[str, Any],
    vision_hook: VisionHook = run_vision_ocr,
    provenance_source_path: str | Path | None = None,
    provenance_mask_path: str | Path | None = None,
    layout_comparison_hook: LayoutComparisonHook | None = None,
) -> dict[str, Any]:
    """Produce exact-image-bound sanitation evidence from real local detectors.

    A detector outage, unknown artifact provenance, raw scene crop, or ambiguous
    salient object becomes ``needs_review``/``fail``. It never becomes a clean pass.
    """

    source = Path(source_path).expanduser().resolve()
    if role not in {"wood_material", "container_surface"}:
        raise ValueError(f"Unsupported control-board role: {role!r}")
    binding = canonical_image_binding(source)
    vision_error: str | None = None
    vision: Mapping[str, Any] | None = None
    text_findings: list[dict[str, Any]] = []
    object_findings: list[dict[str, Any]] = []
    try:
        vision = vision_hook(source, include_objectness=True)
        if vision.get("input_pixel_sha256") != binding["pixel_sha256"]:
            raise VisionOCRUnavailable("Vision detector output belongs to different pixels")
        text_findings, object_findings = _vision_findings(vision)
    except (VisionOCRUnavailable, FileNotFoundError, OSError, ValueError) as exc:
        vision_error = type(exc).__name__

    if vision is not None and isinstance(vision.get("detector"), Mapping):
        text_detector = dict(vision["detector"])
    else:
        text_detector = {"name": "apple_vision_text_recognizer", "version": VISION_OCR_VERSION}
    objectness = vision.get("objectness") if isinstance(vision, Mapping) else None
    if isinstance(objectness, Mapping) and isinstance(objectness.get("detector"), Mapping):
        object_detector = dict(objectness["detector"])
    else:
        object_detector = {
            "name": "apple_vision_objectness_saliency",
            "version": SANITATION_RUNNER_VERSION,
        }

    checks: list[dict[str, Any]] = []
    if vision_error:
        checks.append(
            {
                "check_id": "visible_text",
                "detector": text_detector,
                "status": "needs_review",
                "findings": [_full_frame_finding(f"detector_unavailable:{vision_error}")],
            }
        )
    else:
        checks.append(
            {
                "check_id": "visible_text",
                "detector": text_detector,
                "status": "fail" if text_findings else "pass",
                "findings": text_findings,
            }
        )

    if vision_error:
        brand_status = "needs_review"
        brand_findings = [_full_frame_finding("brand_detector_unavailable")]
    elif text_findings:
        brand_status = "fail"
        brand_findings = [
            {**item, "label": item["label"].replace("visible_text:", "text_brand_mark:")}
            for item in text_findings
        ]
    elif object_findings:
        brand_status = "needs_review"
        brand_findings = [
            {**item, "label": "possible_non_text_brand_mark"} for item in object_findings
        ]
    else:
        brand_status = "pass"
        brand_findings = []
    checks.append(
        {
            "check_id": "brand_mark",
            "detector": {
                "name": "apple_vision_text_plus_objectness",
                "version": SANITATION_RUNNER_VERSION,
            },
            "status": brand_status,
            "findings": brand_findings,
        }
    )

    if vision_error:
        object_status = "needs_review"
        forbidden_findings = [_full_frame_finding("object_detector_unavailable")]
    elif role == "wood_material" and object_findings:
        object_status = "needs_review"
        forbidden_findings = object_findings
    else:
        # A single deidentified container silhouette is expected in a container panel.
        object_status = "pass"
        forbidden_findings = []
    checks.append(
        {
            "check_id": "forbidden_object",
            "detector": object_detector,
            "status": object_status,
            "findings": forbidden_findings,
        }
    )

    if role == "wood_material":
        provenance_ok, reason, artifact_kind = _validate_wood_artifact_provenance(
            source,
            artifact_manifest,
            provenance_source_path=provenance_source_path,
            provenance_mask_path=provenance_mask_path,
        )
        if not provenance_ok:
            layout_status = "fail"
            layout_findings = [_full_frame_finding(reason)]
            layout_detector = {
                "name": "material_artifact_provenance_verifier",
                "version": SANITATION_RUNNER_VERSION,
            }
        elif layout_comparison_hook is None:
            layout_status = "needs_review"
            layout_findings = [_full_frame_finding("layout_comparison_evidence_missing")]
            layout_detector = {
                "name": "layout_comparison_required",
                "version": SANITATION_RUNNER_VERSION,
            }
        else:
            try:
                comparison = layout_comparison_hook(
                    source,
                    source_path=Path(provenance_source_path).expanduser().resolve(),
                )
                layout_status, layout_findings, layout_detector = (
                    _validate_layout_comparison(
                        comparison,
                        artifact_pixel_sha256=binding["pixel_sha256"],
                        source_pixel_sha256=str(artifact_manifest["source_pixel_sha256"]),
                    )
                )
            except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
                layout_status = "needs_review"
                layout_findings = [
                    _full_frame_finding(
                        f"layout_comparison_unavailable:{type(exc).__name__}"
                    )
                ]
                layout_detector = {
                    "name": "layout_comparison_required",
                    "version": SANITATION_RUNNER_VERSION,
                }
    else:
        provenance_ok, reason, source_pixel_sha256 = (
            _validate_container_artifact_provenance(
                source,
                artifact_manifest,
                provenance_source_path=provenance_source_path,
                provenance_mask_path=provenance_mask_path,
            )
        )
        if not provenance_ok:
            layout_status = "needs_review"
            layout_findings = [_full_frame_finding(reason)]
            layout_detector = {
                "name": "material_artifact_provenance_verifier",
                "version": SANITATION_RUNNER_VERSION,
            }
        elif layout_comparison_hook is None:
            layout_status = "needs_review"
            layout_findings = [_full_frame_finding("layout_comparison_evidence_missing")]
            layout_detector = {
                "name": "layout_comparison_required",
                "version": SANITATION_RUNNER_VERSION,
            }
        else:
            try:
                comparison = layout_comparison_hook(
                    source,
                    source_path=Path(provenance_source_path).expanduser().resolve(),
                )
                layout_status, layout_findings, layout_detector = (
                    _validate_layout_comparison(
                        comparison,
                        artifact_pixel_sha256=binding["pixel_sha256"],
                        source_pixel_sha256=str(source_pixel_sha256),
                    )
                )
            except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
                layout_status = "needs_review"
                layout_findings = [
                    _full_frame_finding(
                        f"layout_comparison_unavailable:{type(exc).__name__}"
                    )
                ]
                layout_detector = {
                    "name": "layout_comparison_required",
                    "version": SANITATION_RUNNER_VERSION,
                }
    provenance_hash = _hash(dict(artifact_manifest))
    checks.append(
        {
            "check_id": "scene_layout",
            "detector": {
                **layout_detector,
                "version": (
                    f"{layout_detector['version']};{provenance_hash[:16]};{reason}"
                ),
            },
            "status": layout_status,
            "findings": layout_findings,
        }
    )
    return create_control_board_sanitation_evidence(source, checks)
