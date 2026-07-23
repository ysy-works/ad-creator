from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, NotRequired, Sequence, TypedDict

from PIL import Image, ImageChops, ImageDraw, ImageOps

from .jsonio import validate_json


BRAND_ASSET_SCHEMA_VERSION = "1.0.0"
BRAND_RESTORATION_VERSION = "deterministic_brand_restore_v1"


class BrandAsset(TypedDict):
    schema_version: Literal["1.0.0"]
    asset_id: str
    product_id: str
    status: Literal["draft", "published"]
    rgba_path: str
    mask_path: str
    rgba_pixel_sha256: str
    mask_pixel_sha256: str
    source_product_pixel_sha256: str
    source_bbox: dict[str, float]
    identity: dict[str, str | None]
    application: dict[str, str]
    warp_policy: dict[str, Any]
    confidence: float
    contract_sha256: NotRequired[str]


@dataclass(frozen=True)
class BrandRestorationResult:
    image: Image.Image
    report: dict[str, Any]


def canonical_raster_hash(image: Image.Image, mode: str) -> str:
    normalized = image.convert(mode)
    digest = hashlib.sha256()
    digest.update(f"{mode}:{normalized.width}x{normalized.height}:".encode("ascii"))
    digest.update(normalized.tobytes())
    return digest.hexdigest()


def _canonical_contract_hash(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    payload.pop("contract_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _normalized_bbox(value: Mapping[str, Any], *, name: str) -> dict[str, float]:
    coordinates = {}
    for key in ("left", "top", "right", "bottom"):
        item = value.get(key)
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"{name}.{key} must be numeric")
        coordinates[key] = float(item)
    if not all(0 <= item <= 1 for item in coordinates.values()):
        raise ValueError(f"{name} must be normalized to 0..1")
    if coordinates["left"] >= coordinates["right"] or coordinates["top"] >= coordinates["bottom"]:
        raise ValueError(f"{name} must have positive width and height")
    return coordinates


def build_brand_asset(
    *,
    project_root: str | Path,
    asset_id: str,
    product_id: str,
    rgba_path: str | Path,
    mask_path: str | Path,
    source_product_pixel_sha256: str,
    source_bbox: Mapping[str, Any],
    allowed_main_text: str | None,
    non_text_mark: str | None,
    material_family: str,
    application_medium: str,
    carrier_component: str,
    surface: str,
    confidence: float,
    status: str = "draft",
) -> BrandAsset:
    root = Path(project_root).expanduser().resolve()
    rgba_file = _resolve(root, rgba_path)
    mask_file = _resolve(root, mask_path)
    with Image.open(rgba_file) as opened:
        rgba = opened.convert("RGBA")
    with Image.open(mask_file) as opened:
        mask = opened.convert("L")
    if rgba.size != mask.size:
        raise ValueError("Brand RGBA and asset mask dimensions must match")
    if mask.getbbox() is None:
        raise ValueError("Brand asset mask cannot be empty")
    value: BrandAsset = {
        "schema_version": BRAND_ASSET_SCHEMA_VERSION,
        "asset_id": asset_id,
        "product_id": product_id,
        "status": status,  # type: ignore[typeddict-item]
        "rgba_path": str(rgba_path),
        "mask_path": str(mask_path),
        "rgba_pixel_sha256": canonical_raster_hash(rgba, "RGBA"),
        "mask_pixel_sha256": canonical_raster_hash(mask, "L"),
        "source_product_pixel_sha256": source_product_pixel_sha256,
        "source_bbox": _normalized_bbox(source_bbox, name="source_bbox"),
        "identity": {
            "allowed_main_text": allowed_main_text,
            "non_text_mark": non_text_mark,
        },
        "application": {
            "material_family": material_family,
            "application_medium": application_medium,
            "carrier_component": carrier_component,
            "surface": surface,
        },
        "warp_policy": {
            "mode": "perspective_quad",
            "curved_surface": "target_mask_only",
            "maximum_attempts": 1,
            "outside_mask_change_allowed": False,
        },
        "confidence": float(confidence),
    }
    value["contract_sha256"] = _canonical_contract_hash(value)
    return validate_brand_asset(value, project_root=root, verify_files=True)


def validate_brand_asset(
    asset: BrandAsset | Mapping[str, Any],
    *,
    project_root: str | Path,
    verify_files: bool = True,
) -> BrandAsset:
    root = Path(project_root).expanduser().resolve()
    value = copy.deepcopy(dict(asset))
    # ``project_root`` resolves asset paths. The package-owned schema remains at the
    # package project root so callers may keep assets in an isolated workspace.
    validate_json(value, "brand-asset.schema.json")
    if value.get("contract_sha256") != _canonical_contract_hash(value):
        raise ValueError("BrandAsset contract_sha256 does not match its contents")
    if value["status"] == "published" and float(value["confidence"]) < 0.90:
        raise ValueError("Published BrandAsset requires confidence >= 0.90")
    _normalized_bbox(value["source_bbox"], name="source_bbox")
    if not verify_files:
        return value  # type: ignore[return-value]
    rgba_file = _resolve(root, value["rgba_path"])
    mask_file = _resolve(root, value["mask_path"])
    with Image.open(rgba_file) as opened:
        rgba = opened.convert("RGBA")
    with Image.open(mask_file) as opened:
        mask = opened.convert("L")
    if rgba.size != mask.size:
        raise ValueError("Brand RGBA and asset mask dimensions must match")
    if mask.getbbox() is None:
        raise ValueError("Brand asset mask cannot be empty")
    if canonical_raster_hash(rgba, "RGBA") != value["rgba_pixel_sha256"]:
        raise ValueError("Brand RGBA pixel hash does not match BrandAsset")
    if canonical_raster_hash(mask, "L") != value["mask_pixel_sha256"]:
        raise ValueError("Brand mask pixel hash does not match BrandAsset")
    return value  # type: ignore[return-value]


def _solve_linear(matrix: list[list[float]], values: list[float]) -> list[float]:
    size = len(values)
    augmented = [row[:] + [value] for row, value in zip(matrix, values, strict=True)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            raise ValueError("Target brand quadrilateral is degenerate")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            augmented[row] = [
                item - factor * pivot_item
                for item, pivot_item in zip(
                    augmented[row], augmented[column], strict=True
                )
            ]
    return [augmented[row][-1] for row in range(size)]


def _perspective_coefficients(
    destination: Sequence[tuple[float, float]],
    source: Sequence[tuple[float, float]],
) -> tuple[float, ...]:
    if len(destination) != 4 or len(source) != 4:
        raise ValueError("Perspective mapping requires four source and destination points")
    matrix: list[list[float]] = []
    values: list[float] = []
    for (x, y), (u, v) in zip(destination, source, strict=True):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        values.append(u)
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.append(v)
    return tuple(_solve_linear(matrix, values))


def _quad_pixels(
    quad: Sequence[Sequence[float]],
    size: tuple[int, int],
) -> list[tuple[float, float]]:
    if len(quad) != 4:
        raise ValueError("target_quad must contain four normalized points")
    width, height = size
    result = []
    for point in quad:
        if not (
            len(point) == 2
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in point)
        ):
            raise ValueError("target_quad points must be numeric [x, y] pairs")
        x, y = float(point[0]), float(point[1])
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValueError("target_quad points must be normalized to 0..1")
        result.append((x * (width - 1), y * (height - 1)))
    area = 0.0
    for index, point in enumerate(result):
        following = result[(index + 1) % 4]
        area += point[0] * following[1] - following[0] * point[1]
    if abs(area) < 2.0:
        raise ValueError("target_quad must have non-zero area")
    return result


def _mask_difference_count(first: Image.Image, second: Image.Image, mask: Image.Image) -> int:
    difference = ImageChops.difference(first.convert("RGB"), second.convert("RGB"))
    changed = difference.convert("L").point(lambda value: 255 if value else 0)
    outside = ImageOps.invert(mask.convert("L"))
    return sum(
        1
        for value in ImageChops.multiply(changed, outside).get_flattened_data()
        if value
    )


def validate_restoration_surface_authorization(
    target_surface_mask: Image.Image,
    target_quad: Sequence[Sequence[float]],
    *,
    expected_mask_pixel_sha256: str,
    expected_bbox: Mapping[str, Any],
) -> tuple[Image.Image, list[tuple[float, float]], dict[str, float]]:
    """Bind a caller-supplied repair mask and quad to the surface measured by V3 QA."""

    surface_mask = target_surface_mask.convert("L").point(
        lambda value: 255 if value >= 128 else 0
    )
    pixel_bbox = surface_mask.getbbox()
    if pixel_bbox is None:
        raise ValueError("Target surface mask cannot be empty")
    actual_hash = canonical_raster_hash(surface_mask, "L")
    if actual_hash != expected_mask_pixel_sha256:
        raise ValueError("Target surface mask does not match the V3 QA-authorized mask")
    left, top, right, bottom = pixel_bbox
    actual_bbox = {
        "left": left / surface_mask.width,
        "top": top / surface_mask.height,
        "right": right / surface_mask.width,
        "bottom": bottom / surface_mask.height,
    }
    authorized_bbox = _normalized_bbox(expected_bbox, name="authorized_surface_bbox")
    if any(abs(actual_bbox[key] - authorized_bbox[key]) > 1e-6 for key in actual_bbox):
        raise ValueError("Target surface bbox does not match the V3 QA-authorized bbox")

    destination_quad = _quad_pixels(target_quad, surface_mask.size)
    polygon_mask = Image.new("L", surface_mask.size, 0)
    ImageDraw.Draw(polygon_mask).polygon(destination_quad, fill=255)
    outside_surface = ImageChops.multiply(polygon_mask, ImageOps.invert(surface_mask))
    if outside_surface.getbbox() is not None:
        raise ValueError("Target quadrilateral extends outside the V3 QA-authorized surface")
    return surface_mask, destination_quad, actual_bbox


def restore_single_product_brand(
    generated_image: Image.Image,
    *,
    brand_asset: BrandAsset | Mapping[str, Any],
    project_root: str | Path,
    target_brand_contract: Mapping[str, Any],
    target_surface_mask: Image.Image,
    target_quad: Sequence[Sequence[float]],
    product_id: str,
    source_product_pixel_sha256: str,
    authorized_surface_mask_pixel_sha256: str,
    authorized_surface_bbox: Mapping[str, Any],
    product_count: int = 1,
    clean_plate_image: Image.Image | None = None,
    cleanup_mask: Image.Image | None = None,
    attempt_index: int = 1,
) -> BrandRestorationResult:
    """Apply one exact local logo asset; every pixel outside the authorized mask is locked."""

    if product_count != 1:
        raise ValueError("Deterministic brand restoration is allowed for one product only")
    if attempt_index != 1:
        raise ValueError("Deterministic brand restoration permits exactly one attempt")
    asset = validate_brand_asset(
        brand_asset,
        project_root=project_root,
        verify_files=True,
    )
    if asset["status"] != "published":
        raise ValueError("BrandAsset must be published before restoration")
    if product_id != asset["product_id"]:
        raise ValueError("BrandAsset belongs to a different product")
    if asset["source_product_pixel_sha256"] != source_product_pixel_sha256:
        raise ValueError("BrandAsset belongs to different source product pixels")
    if target_brand_contract.get("state") != "verified_present":
        raise ValueError("Brand restoration requires a verified_present target contract")
    expected_text = target_brand_contract.get("allowed_main_text")
    if expected_text != asset["identity"].get("allowed_main_text"):
        raise ValueError("BrandAsset text does not exactly match the target brand contract")
    if target_brand_contract.get("placement_source") != "source_product":
        raise ValueError("Brand restoration may use source-product placement only")
    surface_policy = target_brand_contract.get("surface_policy")
    if (
        not isinstance(surface_policy, Mapping)
        or surface_policy.get("mode") != "source_application_only"
    ):
        raise ValueError(
            "Brand restoration requires the source-application-only surface policy"
        )
    for field in (
        "material_family",
        "application_medium",
        "carrier_component",
        "surface",
    ):
        required = surface_policy.get(field)
        if required is not None and required != asset["application"][field]:
            raise ValueError(
                f"BrandAsset is incompatible with target surface field {field}"
            )

    base = ImageOps.exif_transpose(generated_image).convert("RGB")
    if target_surface_mask.size != base.size:
        raise ValueError("Target surface mask must match the generated image dimensions")
    surface_mask, destination_quad, measured_surface_bbox = (
        validate_restoration_surface_authorization(
            target_surface_mask,
            target_quad,
            expected_mask_pixel_sha256=authorized_surface_mask_pixel_sha256,
            expected_bbox=authorized_surface_bbox,
        )
    )
    if (clean_plate_image is None) != (cleanup_mask is None):
        raise ValueError("Clean plate and cleanup mask must be supplied together")
    if clean_plate_image is not None and clean_plate_image.size != base.size:
        raise ValueError("Clean plate must match the generated image dimensions")
    if cleanup_mask is not None and cleanup_mask.size != base.size:
        raise ValueError("Cleanup mask must match the generated image dimensions")

    polygon_mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(polygon_mask).polygon(destination_quad, fill=255)
    authorized_mask = ImageChops.multiply(surface_mask, polygon_mask)
    if authorized_mask.getbbox() is None:
        raise ValueError("Target quadrilateral does not overlap the authorized surface mask")

    prepared = base
    if clean_plate_image is not None and cleanup_mask is not None:
        cleanup = ImageChops.multiply(cleanup_mask.convert("L"), authorized_mask)
        prepared = Image.composite(
            ImageOps.exif_transpose(clean_plate_image).convert("RGB"),
            prepared,
            cleanup,
        )

    root = Path(project_root).expanduser().resolve()
    with Image.open(_resolve(root, asset["rgba_path"])) as opened:
        logo = opened.convert("RGBA")
    with Image.open(_resolve(root, asset["mask_path"])) as opened:
        asset_mask = opened.convert("L")
    source_quad = [
        (0.0, 0.0),
        (float(logo.width - 1), 0.0),
        (float(logo.width - 1), float(logo.height - 1)),
        (0.0, float(logo.height - 1)),
    ]
    coefficients = _perspective_coefficients(destination_quad, source_quad)
    warped_logo = logo.transform(
        base.size,
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    warped_asset_mask = asset_mask.transform(
        base.size,
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
        fillcolor=0,
    )
    effective_mask = ImageChops.multiply(warped_logo.getchannel("A"), warped_asset_mask)
    effective_mask = ImageChops.multiply(effective_mask, authorized_mask)
    if effective_mask.getbbox() is None:
        raise ValueError("Warped brand asset has no authorized visible pixels")
    restored = Image.composite(warped_logo.convert("RGB"), prepared, effective_mask)
    outside_change_count = _mask_difference_count(base, restored, authorized_mask)
    if outside_change_count:
        raise RuntimeError("Brand restoration changed pixels outside the authorized mask")
    report = {
        "schema_version": "1.0.0",
        "restoration_version": BRAND_RESTORATION_VERSION,
        "decision": "restored",
        "attempt_index": attempt_index,
        "product_id": product_id,
        "brand_asset_id": asset["asset_id"],
        "brand_asset_contract_sha256": asset["contract_sha256"],
        "source_product_pixel_sha256": source_product_pixel_sha256,
        "expected_text": expected_text,
        "target_quad": [[float(item) for item in point] for point in target_quad],
        "authorized_bbox_px": list(authorized_mask.getbbox() or ()),
        "authorized_surface_mask_pixel_sha256": authorized_surface_mask_pixel_sha256,
        "authorized_surface_bbox": measured_surface_bbox,
        "effective_logo_bbox_px": list(effective_mask.getbbox() or ()),
        "changed_pixels_outside_authorized_mask": outside_change_count,
        "input_pixel_sha256": canonical_raster_hash(base, "RGB"),
        "output_pixel_sha256": canonical_raster_hash(restored, "RGB"),
        "verification_required": ["exact_logo_ocr", "logo_position", "outside_mask_lock"],
    }
    return BrandRestorationResult(image=restored, report=report)
