from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .image_contracts import canonical_image_binding


VISION_OCR_VERSION = "vision_ocr_hook_v1"


class VisionOCRUnavailable(RuntimeError):
    """Raised when the local macOS Vision OCR detector cannot produce evidence."""


Runner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


def _default_runner(command: Sequence[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def build_vision_ocr_binary(
    *,
    source_path: str | Path | None = None,
    binary_path: str | Path = "/tmp/ad_creator_vision_ocr_v1",
    clang_executable: str = "clang",
    timeout_seconds: int = 60,
) -> Path:
    """Compile the tiny native Vision helper, caching the binary in ``/tmp``."""

    source = (
        Path(source_path).expanduser().resolve()
        if source_path is not None
        else Path(__file__).resolve().parents[2] / "scripts" / "vision_ocr.m"
    )
    target = Path(binary_path).expanduser().resolve()
    if not source.is_file():
        raise VisionOCRUnavailable(f"Vision OCR Objective-C source does not exist: {source}")
    if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.setdefault("CLANG_MODULE_CACHE_PATH", "/tmp/ad_creator_clang_module_cache")
    command = [
        clang_executable,
        "-fobjc-arc",
        "-fmodules",
        "-framework",
        "Foundation",
        "-framework",
        "Vision",
        "-framework",
        "ImageIO",
        "-framework",
        "CoreGraphics",
        "-o",
        str(target),
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise VisionOCRUnavailable(f"Vision OCR helper could not compile: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise VisionOCRUnavailable(
            f"Vision OCR helper compilation failed: {detail[:1000]}"
        )
    return target


def _normalize_bbox(value: Mapping[str, Any], *, field: str) -> dict[str, float]:
    expected = {"left", "top", "right", "bottom"}
    if set(value) != expected:
        raise ValueError(f"{field} must contain left, top, right, bottom")
    result: dict[str, float] = {}
    for key in ("left", "top", "right", "bottom"):
        coordinate = value[key]
        if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool):
            raise ValueError(f"{field}.{key} must be numeric")
        result[key] = float(coordinate)
    if not (
        0 <= result["left"] < result["right"] <= 1
        and 0 <= result["top"] < result["bottom"] <= 1
    ):
        raise ValueError(f"{field} must be ordered within [0, 1]")
    return result


def _center_inside(detection: Mapping[str, Any], region: Mapping[str, float]) -> bool:
    bbox = detection["bbox"]
    center_x = (float(bbox["left"]) + float(bbox["right"])) / 2
    center_y = (float(bbox["top"]) + float(bbox["bottom"])) / 2
    return (
        region["left"] <= center_x <= region["right"]
        and region["top"] <= center_y <= region["bottom"]
    )


def _validate_detector_payload(payload: Any) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if not isinstance(payload, Mapping):
        raise VisionOCRUnavailable("Vision OCR returned a non-object payload")
    detector = payload.get("detector")
    if not isinstance(detector, Mapping):
        raise VisionOCRUnavailable("Vision OCR omitted detector metadata")
    name = detector.get("name")
    version = detector.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise VisionOCRUnavailable("Vision OCR detector metadata is invalid")
    raw_detections = payload.get("detections")
    if not isinstance(raw_detections, list):
        raise VisionOCRUnavailable("Vision OCR detections must be an array")
    detections: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_detections):
        if not isinstance(raw, Mapping):
            raise VisionOCRUnavailable(f"Vision OCR detection {index} is not an object")
        text = raw.get("text")
        confidence = raw.get("confidence")
        bbox = raw.get("bbox")
        if not isinstance(text, str) or not text.strip():
            raise VisionOCRUnavailable(f"Vision OCR detection {index} has no text")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
            or not isinstance(bbox, Mapping)
        ):
            raise VisionOCRUnavailable(f"Vision OCR detection {index} is invalid")
        detections.append(
            {
                "text": text.strip(),
                "confidence": round(float(confidence), 6),
                "bbox": _normalize_bbox(bbox, field=f"detections[{index}].bbox"),
            }
        )
    detections.sort(
        key=lambda item: (
            item["bbox"]["top"],
            item["bbox"]["left"],
            item["text"],
        )
    )
    return {"name": name, "version": version}, detections


def _validate_objectness_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    detector = payload.get("objectness_detector")
    status = payload.get("objectness_status")
    objects = payload.get("salient_objects")
    if status != "available":
        return {
            "status": "unavailable",
            "detector": dict(detector) if isinstance(detector, Mapping) else None,
            "error": str(payload.get("objectness_error") or "objectness unavailable"),
            "objects": [],
        }
    if not isinstance(detector, Mapping) or not isinstance(objects, list):
        raise VisionOCRUnavailable("Vision objectness payload is incomplete")
    name = detector.get("name")
    version = detector.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise VisionOCRUnavailable("Vision objectness detector metadata is invalid")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(objects):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("bbox"), Mapping):
            raise VisionOCRUnavailable(f"Vision salient object {index} is invalid")
        confidence = raw.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
        ):
            raise VisionOCRUnavailable(f"Vision salient object {index} confidence is invalid")
        normalized.append(
            {
                "label": str(raw.get("label") or "salient_object"),
                "confidence": round(float(confidence), 6),
                "bbox": _normalize_bbox(
                    raw["bbox"], field=f"salient_objects[{index}].bbox"
                ),
            }
        )
    return {
        "status": "available",
        "detector": {"name": name, "version": version},
        "error": None,
        "objects": normalized,
    }


def run_vision_ocr(
    image_path: str | Path,
    *,
    regions: Mapping[str, Mapping[str, Any]] | None = None,
    script_path: str | Path | None = None,
    swift_executable: str = "swift",
    native_binary: str | Path | None = None,
    include_objectness: bool = False,
    timeout_seconds: int = 90,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Run exact-image-bound OCR and group findings into named normalized regions.

    Detector failures raise :class:`VisionOCRUnavailable`; callers must map that
    to ``needs_review`` rather than treating absent output as a clean image.
    """

    source = Path(image_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"OCR image does not exist: {source}")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    script = None
    if script_path is not None:
        script = Path(script_path).expanduser().resolve()
        if not script.is_file():
            raise VisionOCRUnavailable(f"Vision OCR script does not exist: {script}")

    normalized_regions: dict[str, dict[str, float]] = {}
    source_regions = regions or {
        "full_image": {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}
    }
    for region_id, bbox in source_regions.items():
        if not isinstance(region_id, str) or not region_id.strip():
            raise ValueError("OCR region ids must be non-empty strings")
        if region_id in normalized_regions:
            raise ValueError(f"Duplicate OCR region id: {region_id}")
        normalized_regions[region_id] = _normalize_bbox(
            bbox, field=f"regions.{region_id}"
        )

    invoke = runner or _default_runner
    if runner is not None or script is not None:
        command = [swift_executable, str(script), str(source)]
    else:
        executable = (
            Path(native_binary).expanduser().resolve()
            if native_binary is not None
            else build_vision_ocr_binary()
        )
        if not executable.is_file():
            raise VisionOCRUnavailable(f"Vision OCR binary does not exist: {executable}")
        command = [str(executable), str(source)]
    try:
        completed = invoke(command, timeout_seconds)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise VisionOCRUnavailable(f"Vision OCR could not run: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise VisionOCRUnavailable(
            f"Vision OCR exited with {completed.returncode}: {detail[:500]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise VisionOCRUnavailable("Vision OCR returned invalid JSON") from exc
    detector, detections = _validate_detector_payload(payload)

    grouped: dict[str, dict[str, Any]] = {}
    for region_id, region in normalized_regions.items():
        selected = [item for item in detections if _center_inside(item, region)]
        grouped[region_id] = {
            "detected": bool(selected),
            "text": " ".join(item["text"] for item in selected) or None,
            "confidence": (
                round(max(item["confidence"] for item in selected), 6)
                if selected
                else 0.0
            ),
            "bboxes": [item["bbox"] for item in selected],
        }

    binding = canonical_image_binding(source)
    result = {
        "schema_version": "1.0.0",
        "hook_version": VISION_OCR_VERSION,
        "input_pixel_sha256": binding["pixel_sha256"],
        "detector": detector,
        "regions": grouped,
    }
    if include_objectness:
        result["objectness"] = _validate_objectness_payload(payload)
    return result
