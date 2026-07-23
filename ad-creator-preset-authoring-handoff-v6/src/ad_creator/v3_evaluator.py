from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from PIL import Image, ImageOps

from .brand_restoration import canonical_raster_hash
from .image_contracts import canonical_image_binding
from .jsonio import validate_json
from .qa import evaluate_multi_product_qa, evaluate_wood_material_qa
from .runs import request_hash


V3_EVALUATOR_VERSION = "v3_pixel_measurement_v1"


class EvidenceHook(Protocol):
    def __call__(
        self,
        image_path: str | Path,
        *,
        request: Mapping[str, Any],
        image_binding: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class BrandEvidenceHook(Protocol):
    def __call__(
        self,
        image_path: str | Path,
        *,
        regions: Mapping[str, Mapping[str, float]],
    ) -> Mapping[str, Any]: ...


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


def validate_v3_image_evaluation_report(
    report: Mapping[str, Any],
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    value = copy.deepcopy(dict(report))
    expected_hash = value.pop("report_sha256", None)
    if expected_hash != _canonical_hash(value):
        raise ValueError("V3 image evaluation report hash does not match its contents")
    value["report_sha256"] = expected_hash
    validate_json(
        value,
        "v3-image-evaluation-report.schema.json",
        **({"project_root": project_root} if project_root is not None else {}),
    )
    return value


def _validate_detector_envelope(
    evidence: Mapping[str, Any],
    *,
    pixel_sha256: str,
    field: str,
) -> dict[str, Any]:
    value = copy.deepcopy(dict(evidence))
    if value.get("input_pixel_sha256") != pixel_sha256:
        raise ValueError(f"{field} evidence is not bound to the evaluated image pixels")
    detector = value.get("detector")
    if not isinstance(detector, dict) or any(
        not isinstance(detector.get(key), str) or not detector[key].strip()
        for key in ("name", "version")
    ):
        raise ValueError(f"{field} evidence requires detector name and version")
    return value


def _bbox(value: Any, *, field: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a normalized bbox object")
    result: dict[str, float] = {}
    for key in ("left", "top", "right", "bottom"):
        item = value.get(key)
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"{field}.{key} must be numeric")
        result[key] = float(item)
    if not all(0 <= item <= 1 for item in result.values()):
        raise ValueError(f"{field} coordinates must be normalized to 0..1")
    if result["left"] >= result["right"] or result["top"] >= result["bottom"]:
        raise ValueError(f"{field} must have positive area")
    return result


def _mask_from_value(
    value: Any,
    *,
    size: tuple[int, int],
    project_root: Path,
    field: str,
) -> Image.Image:
    if isinstance(value, Image.Image):
        mask = value.copy().convert("L")
    elif isinstance(value, (str, Path)):
        path = Path(value).expanduser()
        path = path.resolve() if path.is_absolute() else (project_root / path).resolve()
        with Image.open(path) as opened:
            mask = opened.convert("L")
    else:
        raise ValueError(f"{field} must be a PIL mask or image path")
    if mask.size != size:
        raise ValueError(f"{field} dimensions must match the evaluated image")
    mask = mask.point(lambda item: 255 if item >= 128 else 0)
    if mask.getbbox() is None:
        raise ValueError(f"{field} cannot be empty")
    return mask


def _bbox_from_mask(mask: Image.Image) -> dict[str, float]:
    pixel_bbox = mask.getbbox()
    if pixel_bbox is None:
        raise ValueError("Cannot measure an empty mask")
    left, top, right, bottom = pixel_bbox
    return {
        "left": left / mask.width,
        "top": top / mask.height,
        "right": right / mask.width,
        "bottom": bottom / mask.height,
    }


def _bbox_iou(first: Mapping[str, float], second: Mapping[str, float]) -> float:
    left = max(first["left"], second["left"])
    top = max(first["top"], second["top"])
    right = min(first["right"], second["right"])
    bottom = min(first["bottom"], second["bottom"])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = (first["right"] - first["left"]) * (first["bottom"] - first["top"])
    second_area = (second["right"] - second["left"]) * (second["bottom"] - second["top"])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _geometry_measurements(
    observed: Mapping[str, float],
    target: Mapping[str, float],
) -> dict[str, float]:
    observed_width = observed["right"] - observed["left"]
    observed_height = observed["bottom"] - observed["top"]
    target_width = target["right"] - target["left"]
    target_height = target["bottom"] - target["top"]
    observed_center = (
        (observed["left"] + observed["right"]) / 2,
        (observed["top"] + observed["bottom"]) / 2,
    )
    target_center = (
        (target["left"] + target["right"]) / 2,
        (target["top"] + target["bottom"]) / 2,
    )
    return {
        "center_position_error": round(
            math.hypot(
                observed_center[0] - target_center[0],
                observed_center[1] - target_center[1],
            ),
            6,
        ),
        "width_ratio": round(observed_width / target_width, 6),
        "height_ratio": round(observed_height / target_height, 6),
        "target_bbox_iou": round(_bbox_iou(observed, target), 6),
        "frame_margin": round(
            min(
                observed["left"],
                observed["top"],
                1 - observed["right"],
                1 - observed["bottom"],
            ),
            6,
        ),
    }


def _is_generic(value: Mapping[str, Any]) -> bool:
    return bool(value.get("is_generic")) or value.get("role") == "generic" or value.get(
        "source_type"
    ) == "generic"


def _slot_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    scene = request.get("scene_graph_contract")
    if not isinstance(scene, Mapping):
        return {}
    plan = scene.get("slot_plan")
    return dict(plan) if isinstance(plan, Mapping) else {}


def _target_bindings(request: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for item in _slot_plan(request).get("bindings", []):
        if not isinstance(item, Mapping):
            continue
        product_id = item.get("input_product_id")
        target_bbox = item.get("target_bbox")
        if isinstance(product_id, str) and isinstance(target_bbox, Mapping):
            bindings[product_id] = {
                **dict(item),
                "target_bbox": _bbox(target_bbox, field=f"binding[{product_id}].target_bbox"),
            }
    return bindings


def _generic_targets(request: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for item in _slot_plan(request).get("slots", []):
        if not isinstance(item, Mapping) or item.get("action") != "genericize":
            continue
        slot_id = item.get("slot_id")
        if not isinstance(slot_id, str):
            continue
        value = dict(item)
        if isinstance(value.get("target_bbox"), Mapping):
            value["target_bbox"] = _bbox(
                value["target_bbox"], field=f"slot[{slot_id}].target_bbox"
            )
        targets[slot_id] = value
    return targets


def _evidence_regions(envelope: Mapping[str, Any], *, field: str) -> list[dict[str, Any]]:
    regions = envelope.get("regions")
    if isinstance(regions, Mapping):
        values = []
        for key, item in regions.items():
            if not isinstance(item, Mapping):
                raise ValueError(f"{field}.regions[{key!r}] must be an object")
            value = dict(item)
            value.setdefault("region_id", str(key))
            values.append(value)
        return values
    if isinstance(regions, Sequence) and not isinstance(regions, (str, bytes)):
        if any(not isinstance(item, Mapping) for item in regions):
            raise ValueError(f"{field}.regions must contain objects")
        return [dict(item) for item in regions]
    raise ValueError(f"{field} evidence requires a regions object or array")


def _observed_bbox(
    region: Mapping[str, Any],
    *,
    image_size: tuple[int, int],
    project_root: Path,
) -> tuple[dict[str, float] | None, dict[str, Any]]:
    output: dict[str, Any] = {}
    if "mask" in region or "mask_path" in region:
        mask = _mask_from_value(
            region.get("mask", region.get("mask_path")),
            size=image_size,
            project_root=project_root,
            field=f"region[{region.get('region_id', '?')}].mask",
        )
        measured = _bbox_from_mask(mask)
        output.update(
            {
                "bbox_source": "binary_mask",
                "mask_pixel_sha256": canonical_raster_hash(mask, "L"),
                "mask_coverage": round(
                    sum(1 for item in mask.get_flattened_data() if item)
                    / (mask.width * mask.height),
                    6,
                ),
            }
        )
        if isinstance(region.get("bbox"), Mapping):
            declared = _bbox(region["bbox"], field="region.bbox")
            output["declared_bbox_iou"] = round(_bbox_iou(measured, declared), 6)
            if output["declared_bbox_iou"] < 0.90:
                raise ValueError("Detector bbox and detector mask disagree")
        return measured, output
    if isinstance(region.get("bbox"), Mapping):
        return _bbox(region["bbox"], field="region.bbox"), {"bbox_source": "detector_bbox"}
    return None, {"bbox_source": "missing"}


def _brand_region_map(
    evidence: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if evidence is None:
        return {}
    regions = evidence.get("regions")
    if not isinstance(regions, Mapping):
        raise ValueError("Brand evidence regions must be keyed by region ID")
    result: dict[str, dict[str, Any]] = {}
    for key, raw in regions.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"Brand evidence region {key!r} must be an object")
        value = dict(raw)
        detected = value.get("detected")
        text = value.get("text")
        confidence = value.get("confidence")
        if not isinstance(detected, bool):
            raise ValueError(f"Brand evidence region {key!r} requires detected")
        if text is not None and not isinstance(text, str):
            raise ValueError(f"Brand evidence region {key!r} text must be a string or null")
        if isinstance(text, str) and text.strip() and not detected:
            raise ValueError(f"Brand evidence region {key!r} cannot hide detected text")
        if not (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and math.isfinite(float(confidence))
            and 0 <= float(confidence) <= 1
        ):
            raise ValueError(f"Brand evidence region {key!r} confidence is invalid")
        visual_identity = value.get("visual_identity_match")
        if visual_identity is not None:
            if not isinstance(visual_identity, Mapping):
                raise ValueError(
                    f"Brand evidence region {key!r} visual_identity_match must be an object"
                )
            visual_identity = dict(visual_identity)
            target_mark = visual_identity.get("target_non_text_mark")
            matched = visual_identity.get("matched")
            visual_confidence = visual_identity.get("confidence")
            visual_detector = visual_identity.get("detector")
            if not isinstance(target_mark, str) or not target_mark.strip():
                raise ValueError(
                    f"Brand evidence region {key!r} visual matcher requires target_non_text_mark"
                )
            if not isinstance(matched, bool):
                raise ValueError(
                    f"Brand evidence region {key!r} visual matcher requires matched"
                )
            if not (
                isinstance(visual_confidence, (int, float))
                and not isinstance(visual_confidence, bool)
                and math.isfinite(float(visual_confidence))
                and 0 <= float(visual_confidence) <= 1
            ):
                raise ValueError(
                    f"Brand evidence region {key!r} visual matcher confidence is invalid"
                )
            if not isinstance(visual_detector, Mapping) or any(
                not isinstance(visual_detector.get(detector_field), str)
                or not visual_detector[detector_field].strip()
                for detector_field in ("name", "version")
            ):
                raise ValueError(
                    f"Brand evidence region {key!r} visual matcher requires detector identity"
                )
            visual_bboxes = visual_identity.get("bboxes")
            if not isinstance(visual_bboxes, list):
                raise ValueError(
                    f"Brand evidence region {key!r} visual matcher requires bboxes"
                )
            visual_identity["bboxes"] = [
                _bbox(item, field=f"brand[{key}].visual_identity_match.bboxes")
                for item in visual_bboxes
            ]
            if matched and not visual_identity["bboxes"]:
                raise ValueError(
                    f"Brand evidence region {key!r} matched visual identity requires a bbox"
                )
            value["visual_identity_match"] = visual_identity
        result[str(key)] = value
    return result


def _attach_brand_measurement(
    measurement: dict[str, Any],
    *,
    region_id: str,
    brand_regions: Mapping[str, Mapping[str, Any]],
    brand_detector: Mapping[str, Any] | None,
) -> None:
    evidence = brand_regions.get(region_id)
    if evidence is None:
        return
    detected = evidence.get("detected")
    if isinstance(detected, bool):
        measurement["brand_detected"] = detected
    text = evidence.get("text")
    if text is None or isinstance(text, str):
        measurement["generated_logo_text"] = text
    reference_detected = evidence.get("reference_brand_detected")
    if isinstance(reference_detected, bool):
        measurement["reference_brand_detected"] = reference_detected
    for field in ("brand_asset_available", "brand_mask_available"):
        if isinstance(evidence.get(field), bool):
            measurement[field] = evidence[field]
    confidence = evidence.get("confidence")
    measurement["brand_evidence"] = {
        "detector": copy.deepcopy(dict(brand_detector or {})),
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
        "bboxes": copy.deepcopy(evidence.get("bboxes", [])),
    }
    visual_identity = evidence.get("visual_identity_match")
    if isinstance(visual_identity, Mapping):
        measurement["non_text_visual_identity"] = copy.deepcopy(
            dict(visual_identity)
        )


def _rgb_to_lab(red: int, green: int, blue: int) -> tuple[float, float, float]:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = linear(red), linear(green), linear(blue)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def pivot(value: float) -> float:
        delta = 6 / 29
        return value ** (1 / 3) if value > delta**3 else value / (3 * delta**2) + 4 / 29

    fx, fy, fz = pivot(x), pivot(y), pivot(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _delta_e00(first: Sequence[float], second: Sequence[float]) -> float:
    # Sharma et al. CIEDE2000, kL=kC=kH=1.
    l1, a1, b1 = (float(item) for item in first)
    l2, a2, b2 = (float(item) for item in second)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    ap1, ap2 = (1 + g) * a1, (1 + g) * a2
    cp1, cp2 = math.hypot(ap1, b1), math.hypot(ap2, b2)

    def hue(a: float, b: float) -> float:
        angle = math.degrees(math.atan2(b, a))
        return angle + 360 if angle < 0 else angle

    hp1, hp2 = hue(ap1, b1), hue(ap2, b2)
    dl, dc = l2 - l1, cp2 - cp1
    dh = hp2 - hp1
    if cp1 * cp2 == 0:
        dh = 0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    d_h = 2 * math.sqrt(cp1 * cp2) * math.sin(math.radians(dh / 2))
    l_bar, cp_bar = (l1 + l2) / 2, (cp1 + cp2) / 2
    if cp1 * cp2 == 0:
        hp_bar = hp1 + hp2
    elif abs(hp1 - hp2) <= 180:
        hp_bar = (hp1 + hp2) / 2
    elif hp1 + hp2 < 360:
        hp_bar = (hp1 + hp2 + 360) / 2
    else:
        hp_bar = (hp1 + hp2 - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(hp_bar - 30))
        + 0.24 * math.cos(math.radians(2 * hp_bar))
        + 0.32 * math.cos(math.radians(3 * hp_bar + 6))
        - 0.20 * math.cos(math.radians(4 * hp_bar - 63))
    )
    sl = 1 + 0.015 * (l_bar - 50) ** 2 / math.sqrt(20 + (l_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    delta_theta = 30 * math.exp(-((hp_bar - 275) / 25) ** 2)
    rc = 2 * math.sqrt(cp_bar**7 / (cp_bar**7 + 25**7))
    rt = -rc * math.sin(math.radians(2 * delta_theta))
    return math.sqrt(
        (dl / sl) ** 2
        + (dc / sc) ** 2
        + (d_h / sh) ** 2
        + rt * (dc / sc) * (d_h / sh)
    )


def _grain_features(image: Image.Image, mask: Image.Image) -> tuple[float | None, float | None]:
    scale = min(1.0, 256 / max(image.size))
    if scale < 1:
        size = (max(8, round(image.width * scale)), max(8, round(image.height * scale)))
        gray = image.convert("L").resize(size, Image.Resampling.BILINEAR)
        active = mask.resize(size, Image.Resampling.NEAREST)
    else:
        gray = image.convert("L")
        active = mask
    pixels = gray.load()
    mask_pixels = active.load()
    jxx = jyy = jxy = 0.0
    samples = 0
    for y in range(1, gray.height - 1):
        for x in range(1, gray.width - 1):
            if mask_pixels[x, y] < 128:
                continue
            gx = float(pixels[x + 1, y]) - float(pixels[x - 1, y])
            gy = float(pixels[x, y + 1]) - float(pixels[x, y - 1])
            jxx += gx * gx
            jyy += gy * gy
            jxy += gx * gy
            samples += 1
    if samples < 32 or jxx + jyy < samples * 2:
        return None, None
    gradient_direction = 0.5 * math.degrees(math.atan2(2 * jxy, jxx - jyy))
    grain_direction = (gradient_direction + 90) % 180
    normal = math.radians((grain_direction + 90) % 180)
    coordinates = []
    for x, y in ((0, 0), (gray.width - 1, 0), (0, gray.height - 1), (gray.width - 1, gray.height - 1)):
        coordinates.append(x * math.cos(normal) + y * math.sin(normal))
    low, high = min(coordinates), max(coordinates)
    bins = max(16, min(128, round(high - low) + 1))
    sums = [0.0] * bins
    counts = [0] * bins
    span = max(1e-6, high - low)
    for y in range(gray.height):
        for x in range(gray.width):
            if mask_pixels[x, y] < 128:
                continue
            coordinate = x * math.cos(normal) + y * math.sin(normal)
            index = min(bins - 1, max(0, int((coordinate - low) / span * bins)))
            sums[index] += float(pixels[x, y])
            counts[index] += 1
    profile = [sums[index] / counts[index] for index in range(bins) if counts[index]]
    if len(profile) < 12:
        return round(grain_direction, 6), None
    smooth = [
        sum(profile[max(0, index - 1) : min(len(profile), index + 2)])
        / len(profile[max(0, index - 1) : min(len(profile), index + 2)])
        for index in range(len(profile))
    ]
    mean = sum(smooth) / len(smooth)
    variance = sum((item - mean) ** 2 for item in smooth) / len(smooth)
    if variance < 0.5:
        return round(grain_direction, 6), None
    threshold = max(0.5, math.sqrt(variance) * 0.10)
    signs = [1 if item - mean > threshold else -1 if item - mean < -threshold else 0 for item in smooth]
    compact = [item for item in signs if item]
    transitions = sum(first != second for first, second in zip(compact, compact[1:]))
    frequency = max(0.5, transitions / 2)
    return round(grain_direction, 6), round(frequency, 6)


def extract_wood_surface_features(
    generated_image: Image.Image,
    material_mask: Image.Image,
) -> dict[str, Any]:
    image = generated_image.convert("RGB")
    mask = material_mask.convert("L").point(lambda item: 255 if item >= 128 else 0)
    if image.size != mask.size or mask.getbbox() is None:
        raise ValueError("Wood material mask must be non-empty and match the image")
    active_count = sum(1 for item in mask.get_flattened_data() if item)
    stride = max(1, math.ceil(math.sqrt(active_count / 50000)))
    rgb = image.load()
    active = mask.load()
    labs: list[tuple[float, float, float]] = []
    for y in range(0, image.height, stride):
        for x in range(0, image.width, stride):
            if active[x, y]:
                labs.append(_rgb_to_lab(*rgb[x, y]))
    if not labs:
        raise ValueError("Wood material mask has no sampleable pixels")
    lab_median = [_median([item[channel] for item in labs]) for channel in range(3)]
    direction, frequency = _grain_features(image, mask)
    return {
        "lab_median": [round(item, 6) for item in lab_median],
        "chroma": round(math.hypot(lab_median[1], lab_median[2]), 6),
        "grain_direction_degrees": direction,
        "grain_frequency": frequency,
        "surface_coverage": round(active_count / (image.width * image.height), 6),
        "mask_pixel_sha256": canonical_raster_hash(mask, "L"),
    }


def _wood_measurements(
    generated_image: Image.Image,
    *,
    material_mask: Image.Image,
    profile: Mapping[str, Any],
    leakage: Mapping[str, Any],
) -> dict[str, Any]:
    features = extract_wood_surface_features(generated_image, material_mask)
    appearance = profile.get("appearance")
    appearance = dict(appearance) if isinstance(appearance, Mapping) else {}
    lab = appearance.get("lab")
    lab = dict(lab) if isinstance(lab, Mapping) else {}
    expected_lab = lab.get("median")
    result: dict[str, Any] = {
        "observed_lab_median": features["lab_median"],
        "observed_chroma": features["chroma"],
        "observed_grain_direction_degrees": features["grain_direction_degrees"],
        "observed_grain_frequency": features["grain_frequency"],
        "observed_surface_coverage": features["surface_coverage"],
        "material_mask_pixel_sha256": features["mask_pixel_sha256"],
    }
    if isinstance(expected_lab, Sequence) and len(expected_lab) == 3 and all(
        isinstance(item, (int, float)) and not isinstance(item, bool)
        for item in expected_lab
    ):
        expected = [float(item) for item in expected_lab]
        result["delta_e00"] = round(_delta_e00(expected, features["lab_median"]), 6)
        result["lightness_difference"] = round(features["lab_median"][0] - expected[0], 6)
        result["chroma_difference"] = round(
            features["chroma"] - math.hypot(expected[1], expected[2]), 6
        )
    expected_direction = appearance.get("grain_direction_degrees")
    observed_direction = features["grain_direction_degrees"]
    if isinstance(expected_direction, (int, float)) and observed_direction is not None:
        difference = abs(float(observed_direction) - float(expected_direction)) % 180
        result["grain_direction_difference_degrees"] = round(min(difference, 180 - difference), 6)
    expected_frequency = appearance.get("grain_frequency")
    observed_frequency = features["grain_frequency"]
    if (
        isinstance(expected_frequency, (int, float))
        and float(expected_frequency) > 0
        and observed_frequency is not None
    ):
        result["grain_frequency_ratio"] = round(
            float(observed_frequency) / float(expected_frequency), 6
        )
    expected_coverage = appearance.get("surface_occupancy")
    if isinstance(expected_coverage, (int, float)):
        result["surface_coverage_error"] = round(
            features["surface_coverage"] - float(expected_coverage), 6
        )
    for source, target in {
        "swatch_boundary_detected": "swatch_boundary_detected",
        "object_detected": "source_object_copied",
        "text_detected": "source_text_copied",
        "layout_copied": "source_layout_copied",
    }.items():
        if isinstance(leakage.get(source), bool):
            result[target] = leakage[source]
    return result


def _default_brand_evidence(
    image_path: Path,
    *,
    regions: Mapping[str, Mapping[str, float]],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from .vision_ocr import run_vision_ocr
    except (ImportError, AttributeError):
        return None, "vision_ocr_unavailable"
    try:
        result = run_vision_ocr(image_path, regions=regions)
    except Exception as exc:  # local system OCR is optional; never turn failure into pass
        return None, f"vision_ocr_error:{type(exc).__name__}"
    if not isinstance(result, Mapping):
        return None, "vision_ocr_invalid_result"
    return dict(result), None


def _leakage_result(
    *,
    request: Mapping[str, Any],
    envelope: Mapping[str, Any] | None,
    pixel_sha256: str,
) -> dict[str, Any]:
    applicable = request.get("reference_control_board_manifest") is not None
    if not applicable:
        return {
            "status": "not_applicable",
            "measurements": {},
            "missing_measurements": [],
            "hard_failures": [],
        }
    required = (
        "text_detected",
        "object_detected",
        "layout_copied",
        "swatch_boundary_detected",
    )
    if envelope is None:
        return {
            "status": "needs_review",
            "measurements": {},
            "missing_measurements": list(required),
            "hard_failures": [],
        }
    raw_checks = envelope.get("checks")
    raw_checks = dict(raw_checks) if isinstance(raw_checks, Mapping) else {}
    checks: dict[str, dict[str, Any]] = {}
    measurements: dict[str, bool] = {}
    missing: list[str] = []
    detector_identities: set[tuple[str, str]] = set()
    for field in required:
        raw = raw_checks.get(field)
        if not isinstance(raw, Mapping):
            missing.append(field)
            continue
        check = copy.deepcopy(dict(raw))
        if check.get("input_pixel_sha256") != pixel_sha256:
            raise ValueError(f"Leakage check {field} belongs to different image pixels")
        detector = check.get("detector")
        if not isinstance(detector, Mapping) or any(
            not isinstance(detector.get(key), str) or not detector[key].strip()
            for key in ("name", "version")
        ):
            raise ValueError(f"Leakage check {field} requires detector name and version")
        identity = (str(detector["name"]), str(detector["version"]))
        if identity in detector_identities:
            raise ValueError(
                "Text, object, layout and boundary leakage checks require independent detector identities"
            )
        detector_identities.add(identity)
        detected = check.get("detected")
        confidence = check.get("confidence")
        bboxes = check.get("bboxes")
        if not isinstance(detected, bool):
            raise ValueError(f"Leakage check {field} requires detected")
        if not (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and math.isfinite(float(confidence))
            and 0 <= float(confidence) <= 1
        ):
            raise ValueError(f"Leakage check {field} requires confidence in 0..1")
        if not isinstance(bboxes, list):
            raise ValueError(f"Leakage check {field} requires a bboxes array")
        check["bboxes"] = [
            _bbox(item, field=f"leakage.checks.{field}.bboxes") for item in bboxes
        ]
        if detected and not check["bboxes"]:
            raise ValueError(f"Detected leakage check {field} requires at least one bbox")
        check["confidence"] = float(confidence)
        checks[field] = check
        measurements[field] = detected
    detected = [field for field in required if measurements.get(field) is True]
    return {
        "status": "rejected" if detected else "needs_review" if missing else "passed",
        "detector": copy.deepcopy(envelope.get("detector")),
        "checks": checks,
        "measurements": measurements,
        "missing_measurements": missing,
        "hard_failures": ["material_board_leakage"] if detected else [],
        "detected": detected,
    }


def build_evaluator_readiness_contract(
    *,
    product_region_detector_ready: bool,
    brand_ocr_ready: bool,
    leakage_detectors_ready: bool,
    wood_measurement_ready: bool,
    regression_status: str,
) -> dict[str, Any]:
    capabilities = {
        "product_region_detector_ready": bool(product_region_detector_ready),
        "brand_ocr_ready": bool(brand_ocr_ready),
        "leakage_detectors_ready": bool(leakage_detectors_ready),
        "wood_measurement_ready": bool(wood_measurement_ready),
    }
    complete = all(capabilities.values())
    value = {
        "status": "ready" if complete and regression_status == "pass" else "not_ready",
        "version": V3_EVALUATOR_VERSION,
        "required_measurements_complete": complete,
        "regression_status": regression_status,
        "capabilities": capabilities,
    }
    value["contract_sha256"] = _canonical_hash(value)
    return value


class V3ImageMeasurementExtractor:
    """Measure a generated image using pixel-bound local detector evidence."""

    def __init__(
        self,
        *,
        product_region_hook: EvidenceHook | None = None,
        brand_evidence_hook: BrandEvidenceHook | None = None,
        wood_region_hook: EvidenceHook | None = None,
        leakage_evidence_hook: EvidenceHook | None = None,
        use_system_ocr: bool = True,
    ) -> None:
        self.product_region_hook = product_region_hook
        self.brand_evidence_hook = brand_evidence_hook
        self.wood_region_hook = wood_region_hook
        self.leakage_evidence_hook = leakage_evidence_hook
        self.use_system_ocr = use_system_ocr

    def extract(
        self,
        generated_image: str | Path,
        *,
        request: Mapping[str, Any],
        project_root: str | Path | None = None,
    ) -> dict[str, Any]:
        image_path = Path(generated_image).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"Generated image does not exist: {image_path}")
        root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else image_path.parent
        )
        binding = canonical_image_binding(image_path)
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        if not isinstance(request.get("products"), list):
            raise ValueError("GenerationRequestV3 products must be an array")
        products = [dict(item) for item in request["products"] if isinstance(item, Mapping)]
        exact_products = [item for item in products if not _is_generic(item)]
        if not 1 <= len(exact_products) <= 3:
            raise ValueError("V3 image evaluator supports one to three exact products")
        exact_ids = [item.get("product_id") for item in exact_products]
        if any(not isinstance(item, str) or not item for item in exact_ids):
            raise ValueError("Every exact product requires product_id")
        generation_request_sha256 = request_hash(dict(request))

        region_envelope = None
        region_detector_measured = self.product_region_hook is not None
        if self.product_region_hook is not None:
            raw = self.product_region_hook(
                image_path,
                request=request,
                image_binding=binding,
            )
            region_envelope = _validate_detector_envelope(
                raw,
                pixel_sha256=binding["pixel_sha256"],
                field="product region",
            )
            regions = _evidence_regions(region_envelope, field="product region")
        else:
            regions = []

        targets = _target_bindings(request)
        generic_targets = _generic_targets(request)
        measured_regions: list[dict[str, Any]] = []
        ocr_regions: dict[str, dict[str, float]] = {}
        for index, region in enumerate(regions):
            region_id = region.get("region_id")
            if not isinstance(region_id, str) or not region_id:
                region_id = f"region_{index + 1}"
            observed_bbox, mask_evidence = _observed_bbox(
                region,
                image_size=image.size,
                project_root=root,
            )
            measured = {**region, **mask_evidence, "region_id": region_id}
            measured.pop("mask", None)
            measured.pop("mask_path", None)
            brand_surface_value = measured.pop(
                "brand_surface_mask",
                measured.pop("brand_surface_mask_path", None),
            )
            if brand_surface_value is not None:
                brand_surface_mask = _mask_from_value(
                    brand_surface_value,
                    size=image.size,
                    project_root=root,
                    field=f"region[{region_id}].brand_surface_mask",
                )
                measured["brand_surface_mask_pixel_sha256"] = canonical_raster_hash(
                    brand_surface_mask, "L"
                )
                measured["brand_surface_bbox"] = _bbox_from_mask(brand_surface_mask)
            measured["observed_bbox"] = observed_bbox
            measured_regions.append(measured)
            if observed_bbox is not None:
                ocr_regions[region_id] = observed_bbox

        brand_envelope = None
        ocr_unavailable_reason = None
        if self.brand_evidence_hook is not None:
            raw_brand = self.brand_evidence_hook(image_path, regions=ocr_regions)
            brand_envelope = _validate_detector_envelope(
                raw_brand,
                pixel_sha256=binding["pixel_sha256"],
                field="brand OCR",
            )
        elif self.use_system_ocr and ocr_regions:
            raw_brand, ocr_unavailable_reason = _default_brand_evidence(
                image_path,
                regions=ocr_regions,
            )
            if raw_brand is not None:
                brand_envelope = _validate_detector_envelope(
                    raw_brand,
                    pixel_sha256=binding["pixel_sha256"],
                    field="brand OCR",
                )
        brand_regions = _brand_region_map(brand_envelope)
        brand_detector = brand_envelope.get("detector") if brand_envelope else None

        regions_by_expected: dict[str, dict[str, Any]] = {}
        exact_observed_ids: list[str] = []
        generic_regions: list[dict[str, Any]] = []
        for region in measured_regions:
            role = region.get("role")
            if role == "generic":
                generic_regions.append(region)
                continue
            if role != "exact":
                continue
            observed_id = region.get("observed_product_id")
            if isinstance(observed_id, str) and observed_id:
                exact_observed_ids.append(observed_id)
            expected_id = region.get("expected_product_id")
            if not isinstance(expected_id, str):
                slot_id = region.get("target_slot_id")
                expected_id = next(
                    (
                        product_id
                        for product_id, binding_value in targets.items()
                        if binding_value.get("target_slot_id") == slot_id
                    ),
                    None,
                )
            if isinstance(expected_id, str):
                if expected_id in regions_by_expected:
                    raise ValueError(f"Multiple exact regions claim product {expected_id}")
                regions_by_expected[expected_id] = region

        product_measurements: list[dict[str, Any]] = []
        for product in exact_products:
            product_id = str(product["product_id"])
            region = regions_by_expected.get(product_id)
            if region is None:
                continue
            record: dict[str, Any] = {
                "product_id": product_id,
                "region_id": region["region_id"],
            }
            observed_id = region.get("observed_product_id")
            if isinstance(observed_id, str) and observed_id:
                record["observed_product_id"] = observed_id
            observed_bbox = region.get("observed_bbox")
            target = targets.get(product_id, {}).get("target_bbox")
            if isinstance(observed_bbox, Mapping):
                record["observed_bbox"] = copy.deepcopy(dict(observed_bbox))
                record["bbox_source"] = region.get("bbox_source")
                if isinstance(region.get("mask_pixel_sha256"), str):
                    record["mask_pixel_sha256"] = region["mask_pixel_sha256"]
                if isinstance(region.get("brand_surface_mask_pixel_sha256"), str):
                    record["brand_surface_mask_pixel_sha256"] = region[
                        "brand_surface_mask_pixel_sha256"
                    ]
                if isinstance(region.get("brand_surface_bbox"), Mapping):
                    record["brand_surface_bbox"] = copy.deepcopy(
                        dict(region["brand_surface_bbox"])
                    )
            if isinstance(observed_bbox, Mapping) and isinstance(target, Mapping):
                record["target_bbox"] = copy.deepcopy(dict(target))
                record.update(_geometry_measurements(observed_bbox, target))
            for field in (
                "support_relation_match",
                "occlusion_relation_match",
                "active_relation_match",
            ):
                if isinstance(region.get(field), bool):
                    record[field] = region[field]
            for field in (
                "observed_temperature",
                "observed_ice_presence",
                "observed_container_service_temperature",
            ):
                if isinstance(region.get(field), str):
                    record[field] = region[field]
            _attach_brand_measurement(
                record,
                region_id=region["region_id"],
                brand_regions=brand_regions,
                brand_detector=brand_detector if isinstance(brand_detector, Mapping) else None,
            )
            product_measurements.append(record)

        product_report = evaluate_multi_product_qa(
            product_measurements,
            expected_product_ids=[str(item) for item in exact_ids],
            product_specs=exact_products,
            observed_exact_product_ids=(exact_observed_ids if region_detector_measured else None),
            observed_exact_product_count=(
                sum(region.get("role") == "exact" for region in measured_regions)
                if region_detector_measured
                else None
            ),
        )
        for product_result in product_report.get("product_results", []):
            if not isinstance(product_result, dict):
                continue
            brand_result = product_result.get("brand_result")
            if not isinstance(brand_result, dict) or brand_result.get("repairable") is not True:
                continue
            measurements = product_result.get("measurements")
            measurements = measurements if isinstance(measurements, dict) else {}
            product_id = str(product_result.get("product_id", "unknown"))
            for field in (
                "brand_surface_mask_pixel_sha256",
                "brand_surface_bbox",
            ):
                if field in measurements:
                    continue
                if field not in product_result["missing_measurements"]:
                    product_result["missing_measurements"].append(field)
                qualified = f"{product_id}.{field}"
                if qualified not in product_report["missing_measurements"]:
                    product_report["missing_measurements"].append(qualified)

        generic_results: list[dict[str, Any]] = []
        generic_hard: list[str] = []
        generic_missing: list[str] = []
        max_generic = 0 if len(exact_products) == 3 else 1
        if region_detector_measured and len(generic_regions) > max_generic:
            generic_hard.append("generic_subject_count_exceeds_policy")
        if region_detector_measured and len(generic_regions) != len(generic_targets):
            generic_hard.append("generic_subject_count_mismatch")
        generic_by_slot = {
            str(item.get("target_slot_id")): item
            for item in generic_regions
            if isinstance(item.get("target_slot_id"), str)
        }
        for slot_id in generic_targets:
            region = generic_by_slot.get(slot_id)
            if region is None:
                generic_missing.append(f"{slot_id}.product_record")
                continue
            observed_bbox = region.get("observed_bbox")
            result: dict[str, Any] = {
                "slot_id": slot_id,
                "region_id": region["region_id"],
                "hard_failures": [],
                "missing_measurements": [],
            }
            if isinstance(observed_bbox, Mapping):
                margin = min(
                    observed_bbox["left"],
                    observed_bbox["top"],
                    1 - observed_bbox["right"],
                    1 - observed_bbox["bottom"],
                )
                result["frame_margin"] = round(float(margin), 6)
                if margin < 0.06:
                    result["hard_failures"].append("frame_margin_below_0_06")
            else:
                result["missing_measurements"].append("observed_bbox")
            occlusion = region.get("occlusion_fraction")
            if (
                isinstance(occlusion, (int, float))
                and not isinstance(occlusion, bool)
                and math.isfinite(float(occlusion))
                and 0 <= float(occlusion) <= 1
            ):
                result["occlusion_fraction"] = float(occlusion)
                if float(occlusion) > 0.20:
                    result["hard_failures"].append("occlusion_exceeds_0_20")
            else:
                result["missing_measurements"].append("occlusion_fraction")
            support = region.get("support_relation_match")
            if isinstance(support, bool):
                result["support_relation_match"] = support
                if not support:
                    result["hard_failures"].append("support_relation_failed")
            else:
                result["missing_measurements"].append("support_relation_match")
            brand_measurement: dict[str, Any] = {}
            _attach_brand_measurement(
                brand_measurement,
                region_id=region["region_id"],
                brand_regions=brand_regions,
                brand_detector=brand_detector if isinstance(brand_detector, Mapping) else None,
            )
            if isinstance(brand_measurement.get("brand_detected"), bool):
                result["brand_detected"] = brand_measurement["brand_detected"]
                if brand_measurement["brand_detected"]:
                    result["hard_failures"].append("generic_brand_forbidden")
            else:
                result["missing_measurements"].append("brand_detected")
            if result["hard_failures"]:
                result["status"] = "fail"
            elif result["missing_measurements"]:
                result["status"] = "needs_review"
            else:
                result["status"] = "pass"
            generic_results.append(result)
            generic_hard.extend(
                f"{slot_id}.{item}" for item in result["hard_failures"]
            )
            generic_missing.extend(
                f"{slot_id}.{item}" for item in result["missing_measurements"]
            )
        if not region_detector_measured and generic_targets:
            generic_missing.append("generic_subject_count")

        leakage_envelope = None
        if self.leakage_evidence_hook is not None:
            leakage_envelope = _validate_detector_envelope(
                self.leakage_evidence_hook(
                    image_path,
                    request=request,
                    image_binding=binding,
                ),
                pixel_sha256=binding["pixel_sha256"],
                field="material leakage",
            )
        leakage_report = _leakage_result(
            request=request,
            envelope=leakage_envelope,
            pixel_sha256=binding["pixel_sha256"],
        )

        wood_report = None
        wood_measurements = None
        wood_profile = request.get("wood_material_profile")
        if isinstance(wood_profile, Mapping):
            material_mask = None
            wood_missing_reason = None
            if self.wood_region_hook is not None:
                wood_envelope = _validate_detector_envelope(
                    self.wood_region_hook(
                        image_path,
                        request=request,
                        image_binding=binding,
                    ),
                    pixel_sha256=binding["pixel_sha256"],
                    field="wood region",
                )
                mask_value = wood_envelope.get("mask", wood_envelope.get("mask_path"))
                if mask_value is not None:
                    material_mask = _mask_from_value(
                        mask_value,
                        size=image.size,
                        project_root=root,
                        field="wood region mask",
                    )
                else:
                    wood_missing_reason = "wood_material_mask"
            else:
                wood_missing_reason = "wood_region_detector"
            if material_mask is None:
                wood_measurements = {
                    "measurement_unavailable_reason": wood_missing_reason,
                    **{
                        target: leakage_report["measurements"][source]
                        for source, target in {
                            "swatch_boundary_detected": "swatch_boundary_detected",
                            "object_detected": "source_object_copied",
                            "text_detected": "source_text_copied",
                            "layout_copied": "source_layout_copied",
                        }.items()
                        if isinstance(leakage_report["measurements"].get(source), bool)
                    },
                }
            else:
                wood_measurements = _wood_measurements(
                    image,
                    material_mask=material_mask,
                    profile=wood_profile,
                    leakage=leakage_report["measurements"],
                )
            wood_report = evaluate_wood_material_qa(wood_measurements)

        hard_failures = [
            *product_report["hard_failures"],
            *generic_hard,
            *[f"leakage.{item}" for item in leakage_report["hard_failures"]],
            *(
                [f"wood.{item}" for item in wood_report["hard_failures"]]
                if wood_report is not None
                else []
            ),
        ]
        missing_measurements = [
            *product_report["missing_measurements"],
            *generic_missing,
            *[f"leakage.{item}" for item in leakage_report["missing_measurements"]],
            *(
                [f"wood.{item}" for item in wood_report["missing_measurements"]]
                if wood_report is not None
                else []
            ),
        ]
        if ocr_unavailable_reason and exact_products:
            missing_measurements.append(f"brand_ocr.{ocr_unavailable_reason}")
        if hard_failures:
            overall = "rejected"
        elif missing_measurements or product_report["overall_status"] == "needs_review" or any(
            item.get("status") == "needs_review" for item in generic_results
        ) or leakage_report["status"] == "needs_review" or (
            wood_report is not None and wood_report["overall_status"] == "needs_review"
        ):
            overall = "needs_review"
        elif (
            wood_report is not None
            and wood_report["overall_status"] == "passed_with_warnings"
        ):
            overall = "passed_with_warnings"
        else:
            overall = "passed"
        report = {
            "schema_version": "3.0.0",
            "evaluator": {
                "name": "local_v3_pixel_measurement",
                "version": V3_EVALUATOR_VERSION,
                "mode": "local_deterministic_with_bound_detector_evidence",
            },
            "evaluated_image": str(image_path),
            "evaluated_image_binding": binding,
            "generation_request_sha256": generation_request_sha256,
            "overall_status": overall,
            "product_measurements": product_measurements,
            "generic_results": generic_results,
            "wood_measurements": wood_measurements,
            "leakage_evidence": leakage_report,
            "qa": {
                "multi_product": product_report,
                "wood": wood_report,
            },
            "hard_failures": list(dict.fromkeys(hard_failures)),
            "missing_measurements": list(dict.fromkeys(missing_measurements)),
            "evidence_versions": {
                "product_region": copy.deepcopy(
                    region_envelope.get("detector") if region_envelope else None
                ),
                "brand_ocr": copy.deepcopy(brand_detector),
                "wood_region": (
                    copy.deepcopy(wood_envelope.get("detector"))
                    if isinstance(wood_profile, Mapping)
                    and self.wood_region_hook is not None
                    else None
                ),
                "leakage": {
                    field: copy.deepcopy(check.get("detector"))
                    for field, check in leakage_report.get("checks", {}).items()
                },
            },
        }
        report["report_sha256"] = _canonical_hash(report)
        return validate_v3_image_evaluation_report(report)


def evaluate_v3_generated_image(
    generated_image: str | Path,
    *,
    request: Mapping[str, Any],
    project_root: str | Path | None = None,
    product_region_hook: EvidenceHook | None = None,
    brand_evidence_hook: BrandEvidenceHook | None = None,
    wood_region_hook: EvidenceHook | None = None,
    leakage_evidence_hook: EvidenceHook | None = None,
    use_system_ocr: bool = True,
) -> dict[str, Any]:
    return V3ImageMeasurementExtractor(
        product_region_hook=product_region_hook,
        brand_evidence_hook=brand_evidence_hook,
        wood_region_hook=wood_region_hook,
        leakage_evidence_hook=leakage_evidence_hook,
        use_system_ocr=use_system_ocr,
    ).extract(
        generated_image,
        request=request,
        project_root=project_root,
    )
