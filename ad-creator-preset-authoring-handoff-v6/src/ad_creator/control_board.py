from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image, ImageOps


CONTROL_BOARD_SIZE = 1024
CONTROL_BOARD_MAX_PANELS = 4
CONTROL_BOARD_GUTTER = 16
CONTROL_BOARD_ROLES = {"container_surface", "wood_material"}
CONTROL_BOARD_SANITATION_SCHEMA_VERSION = "1.0.0"
REQUIRED_SANITATION_CHECKS = frozenset(
    {"visible_text", "brand_mark", "forbidden_object", "scene_layout"}
)
SANITATION_STATUSES = frozenset({"pass", "fail", "needs_review"})


def _content_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pixel_sha256(path: Path) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"RGB:{image.width}x{image.height}:".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def create_control_board_sanitation_evidence(
    source_path: str | Path,
    checks: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create auditable evidence from independent sanitation detector outputs.

    This function never performs OCR or object detection itself.  It binds the
    outputs of those independent detectors to the exact source bytes and pixels,
    and fails closed unless every mandatory check produced a conclusive pass.
    """

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Sanitation source does not exist: {source}")
    reports = [dict(item) for item in checks]
    check_ids = [str(item.get("check_id", "")) for item in reports]
    if len(check_ids) != len(set(check_ids)):
        raise ValueError("Sanitation check_id values must be unique")
    missing = sorted(REQUIRED_SANITATION_CHECKS - set(check_ids))
    unknown = sorted(set(check_ids) - REQUIRED_SANITATION_CHECKS)
    if missing or unknown:
        raise ValueError(
            f"Sanitation evidence checks are incomplete (missing={missing}, unknown={unknown})"
        )
    normalized: list[dict[str, Any]] = []
    for report in sorted(reports, key=lambda item: str(item["check_id"])):
        detector = report.get("detector")
        if not isinstance(detector, Mapping):
            raise ValueError("Each sanitation check requires detector metadata")
        name = detector.get("name")
        version = detector.get("version")
        if (
            not isinstance(name, str)
            or not name.strip()
            or name.strip().lower() in {"caller_attestation", "self_report", "unknown"}
            or not isinstance(version, str)
            or not version.strip()
        ):
            raise ValueError("Sanitation detectors require a concrete name and version")
        status = report.get("status")
        if status not in SANITATION_STATUSES:
            raise ValueError(f"Unsupported sanitation status: {status!r}")
        findings = report.get("findings")
        if not isinstance(findings, list):
            raise ValueError("Sanitation findings must be an array")
        normalized_findings: list[dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, Mapping):
                raise ValueError("Every sanitation finding must be an object")
            label = finding.get("label")
            confidence = finding.get("confidence")
            bbox = finding.get("bbox")
            if not isinstance(label, str) or not label.strip():
                raise ValueError("Sanitation findings require a label")
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0 <= float(confidence) <= 1
            ):
                raise ValueError("Sanitation finding confidence must be between 0 and 1")
            if not isinstance(bbox, Mapping) or set(bbox) != {
                "left",
                "top",
                "right",
                "bottom",
            }:
                raise ValueError("Sanitation findings require a normalized bbox")
            coordinates = {key: float(bbox[key]) for key in bbox}
            if not (
                0 <= coordinates["left"] < coordinates["right"] <= 1
                and 0 <= coordinates["top"] < coordinates["bottom"] <= 1
            ):
                raise ValueError("Sanitation finding bbox must be ordered within [0, 1]")
            normalized_findings.append(
                {
                    "label": label.strip(),
                    "confidence": round(float(confidence), 6),
                    "bbox": {key: round(coordinates[key], 6) for key in coordinates},
                }
            )
        if status == "pass" and normalized_findings:
            raise ValueError("A passing sanitation check cannot contain findings")
        if status != "pass" and not normalized_findings:
            raise ValueError("A non-passing sanitation check requires finding evidence")
        normalized.append(
            {
                "check_id": report["check_id"],
                "detector": {"name": name.strip(), "version": version.strip()},
                "status": status,
                "findings": normalized_findings,
            }
        )
    overall_status = (
        "fail"
        if any(item["status"] == "fail" for item in normalized)
        else "needs_review"
        if any(item["status"] == "needs_review" for item in normalized)
        else "pass"
    )
    evidence = {
        "schema_version": CONTROL_BOARD_SANITATION_SCHEMA_VERSION,
        "artifact_type": "control_board_sanitation_evidence",
        "source_path": str(source),
        "source_sha256": _file_sha256(source),
        "source_pixel_sha256": _pixel_sha256(source),
        "independent_detector_outputs": True,
        "status": overall_status,
        "checks": normalized,
    }
    evidence["evidence_sha256"] = _content_hash(evidence)
    return evidence


def validate_control_board_sanitation_evidence(
    source_path: str | Path,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate evidence integrity and binding, returning a defensive copy."""

    source = Path(source_path).expanduser().resolve()
    value = validate_control_board_sanitation_evidence_contract(evidence)
    if Path(str(value.get("source_path", ""))).expanduser().resolve() != source:
        raise ValueError("Sanitation evidence belongs to a different source path")
    if value.get("source_sha256") != _file_sha256(source):
        raise ValueError("Sanitation source bytes changed after inspection")
    if value.get("source_pixel_sha256") != _pixel_sha256(source):
        raise ValueError("Sanitation source pixels changed after inspection")
    reconstructed = create_control_board_sanitation_evidence(source, value.get("checks", []))
    if reconstructed["evidence_sha256"] != value["evidence_sha256"]:
        raise ValueError("Control-board sanitation evidence contents are inconsistent")
    return value


def validate_control_board_sanitation_evidence_contract(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a sanitation evidence record without reading its bound source."""

    value = dict(evidence)
    if value.get("schema_version") != CONTROL_BOARD_SANITATION_SCHEMA_VERSION:
        raise ValueError("Unsupported control-board sanitation evidence schema")
    if value.get("artifact_type") != "control_board_sanitation_evidence":
        raise ValueError("Sanitation evidence has the wrong artifact_type")
    if value.get("independent_detector_outputs") is not True:
        raise ValueError("Independent detector outputs are required for control-board sanitation")
    if value.get("status") != "pass":
        raise ValueError("Control-board panel sanitation must conclusively pass")
    checks = value.get("checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(REQUIRED_SANITATION_CHECKS)
        or {
            item.get("check_id") for item in checks if isinstance(item, Mapping)
        }
        != REQUIRED_SANITATION_CHECKS
    ):
        raise ValueError("Control-board sanitation evidence is missing mandatory checks")
    for item in checks:
        if not isinstance(item, Mapping):
            raise ValueError("Control-board sanitation checks must be objects")
        detector = item.get("detector")
        if not isinstance(detector, Mapping):
            raise ValueError("Control-board sanitation detector metadata is missing")
        if item.get("status") != "pass" or item.get("findings") != []:
            raise ValueError("Control-board sanitation checks must pass without findings")
        name = detector.get("name")
        version = detector.get("version")
        if (
            not isinstance(name, str)
            or not name.strip()
            or name.strip().lower() in {"caller_attestation", "self_report", "unknown"}
            or not isinstance(version, str)
            or not version.strip()
        ):
            raise ValueError("Control-board sanitation detector metadata is invalid")
    evidence_hash = value.pop("evidence_sha256", None)
    if not isinstance(evidence_hash, str) or evidence_hash != _content_hash(value):
        raise ValueError("Control-board sanitation evidence hash is invalid")
    value["evidence_sha256"] = evidence_hash
    return value


def validate_reference_control_board_manifest(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate manifest self-hash and every embedded sanitation contract."""

    value = dict(manifest)
    manifest_hash = value.pop("manifest_sha256", None)
    if not isinstance(manifest_hash, str) or manifest_hash != _content_hash(value):
        raise ValueError("Reference control-board manifest hash is invalid")
    panels = value.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= CONTROL_BOARD_MAX_PANELS:
        raise ValueError("Control-board manifest requires one to four panels")
    for panel in panels:
        if not isinstance(panel, Mapping):
            raise ValueError("Control-board manifest panels must be objects")
        evidence = panel.get("sanitation_evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError("Control-board manifest panel lacks sanitation evidence")
        sanitized = validate_control_board_sanitation_evidence_contract(evidence)
        if panel.get("source_sha256") != sanitized.get("source_sha256"):
            raise ValueError("Control-board panel source hash does not match sanitation evidence")
    value["manifest_sha256"] = manifest_hash
    return value


def build_reference_control_board(
    panels: Iterable[dict[str, Any]],
    output_path: str | Path,
    *,
    size: int = CONTROL_BOARD_SIZE,
) -> dict[str, Any]:
    """Build one text-free auxiliary image for a v3 provider request.

    Panel ordering is carried in the returned manifest rather than being
    printed into the image. Every panel must carry exact-image-bound outputs
    from the required independent sanitation checks.
    """

    values = [dict(item) for item in panels]
    if not 1 <= len(values) <= CONTROL_BOARD_MAX_PANELS:
        raise ValueError("A reference control board requires one to four panels")
    if size < 512 or size % 2:
        raise ValueError("Control board size must be an even integer of at least 512")

    for index, panel in enumerate(values):
        role = panel.get("role")
        if role not in CONTROL_BOARD_ROLES:
            raise ValueError(f"Unsupported control-board role at panel {index}: {role!r}")
        source = Path(str(panel.get("path", ""))).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Control-board panel does not exist: {source}")
        sanitation = panel.get("sanitation_evidence")
        if not isinstance(sanitation, Mapping):
            raise ValueError(
                "Every control-board panel requires independent sanitation_evidence"
            )
        panel["sanitation_evidence"] = validate_control_board_sanitation_evidence(
            source, sanitation
        )
        if role == "container_surface" and (
            not isinstance(panel.get("product_id"), str)
            or not panel["product_id"].strip()
        ):
            raise ValueError("Container panels require the exact target product_id")
        if role == "wood_material" and panel.get("source_policy") not in {
            "derived_material",
            "masked_raw_experimental",
        }:
            raise ValueError("Wood panels require a safe material-only source policy")
        panel["path"] = str(source)

    background = (128, 128, 128)
    board = Image.new("RGB", (size, size), background)
    gutter = max(4, round(size * CONTROL_BOARD_GUTTER / CONTROL_BOARD_SIZE))
    if len(values) == 1:
        cells = [(0, 0, size, size)]
    elif len(values) == 2:
        half = size // 2
        cells = [(0, 0, half, size), (half, 0, size, size)]
    else:
        half = size // 2
        cells = [
            (0, 0, half, half),
            (half, 0, size, half),
            (0, half, half, size),
            (half, half, size, size),
        ][: len(values)]

    manifest_panels: list[dict[str, Any]] = []
    for index, (panel, cell) in enumerate(zip(values, cells, strict=True)):
        left, top, right, bottom = cell
        inset = (
            left + gutter,
            top + gutter,
            right - gutter,
            bottom - gutter,
        )
        with Image.open(panel["path"]) as opened:
            prepared = ImageOps.exif_transpose(opened).convert("RGB")
            fitted = ImageOps.fit(
                prepared,
                (inset[2] - inset[0], inset[3] - inset[1]),
                method=Image.Resampling.LANCZOS,
            )
        board.paste(fitted, (inset[0], inset[1]))
        manifest_panels.append(
            {
                "index": index,
                "role": panel["role"],
                "product_id": panel.get("product_id"),
                "source_policy": panel.get("source_policy", "deidentified_container"),
                "source_sha256": hashlib.sha256(
                    Path(panel["path"]).read_bytes()
                ).hexdigest(),
                "sanitation_evidence": panel["sanitation_evidence"],
                "bbox_px": {
                    "left": inset[0],
                    "top": inset[1],
                    "right": inset[2],
                    "bottom": inset[3],
                },
            }
        )

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    board.save(temporary, format="PNG", optimize=True)
    os.replace(temporary, destination)
    pixel_sha256 = _pixel_sha256(destination)
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "reference_control_board",
        "path": str(destination),
        "width_px": size,
        "height_px": size,
        "pixel_sha256": pixel_sha256,
        "visible_labels": False,
        "panels": manifest_panels,
    }
    manifest["manifest_sha256"] = _content_hash(manifest)
    return manifest
