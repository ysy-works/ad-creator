from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Any, Iterator

from PIL import Image

from .preset_contract import PresetRuntimeError


@contextmanager
def execute_product_transforms(
    source_path: str | Path,
    transforms: tuple[dict[str, Any], ...],
    *,
    product_analysis: dict[str, Any] | None = None,
) -> Iterator[tuple[Path, list[dict[str, Any]]]]:
    """Execute only typed transforms declared by the resolved preset.

    Provider normalization remains in the provider adapter because its encoding and
    size are provider capabilities, not mood policy. Geometry crops are applied only
    from explicit analyzed pixel coordinates. No image-content guess is made here.
    """

    source = Path(source_path).resolve()
    current = source
    temporary_paths: list[Path] = []
    audit: list[dict[str, Any]] = []
    try:
        for operation in transforms:
            operation_type = operation.get("type")
            if operation_type in {
                "normalize_product_source",
                "select_hint_by_container_mode",
                "sanitize_reference_control",
            }:
                audit.append({"type": operation_type, "status": "delegated_or_preverified"})
                continue
            if operation_type != "crop_product_by_analysis_geometry":
                raise PresetRuntimeError("UNSUPPORTED_TRANSFORM", str(operation_type))
            bbox = _pixel_bbox(product_analysis)
            if bbox is None:
                if operation.get("fallback") != "full_user_image":
                    raise PresetRuntimeError(
                        "PRODUCT_GEOMETRY_REQUIRED",
                        "Declared product crop requires analyzed pixel geometry.",
                    )
                audit.append(
                    {
                        "type": operation_type,
                        "status": "fallback",
                        "fallback": "full_user_image",
                        "reason": "product_analysis_geometry_missing",
                    }
                )
                continue
            with Image.open(current) as image:
                image.load()
                left, top, right, bottom = _clamped_bbox(bbox, image.width, image.height)
                cropped = image.convert("RGB").crop((left, top, right, bottom))
            if cropped.width < 2 or cropped.height < 2:
                raise PresetRuntimeError("INVALID_PRODUCT_GEOMETRY", "Crop is smaller than 2px.")
            handle = tempfile.NamedTemporaryFile(
                prefix="ad_creator_runtime_crop_", suffix=".png", delete=False
            )
            handle.close()
            temporary = Path(handle.name)
            cropped.save(temporary, format="PNG", optimize=True)
            temporary_paths.append(temporary)
            current = temporary
            audit.append(
                {
                    "type": operation_type,
                    "status": "applied",
                    "bbox_pixels": [left, top, right, bottom],
                    "output_dimensions": [cropped.width, cropped.height],
                }
            )
        yield current, audit
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


def _pixel_bbox(product_analysis: dict[str, Any] | None) -> tuple[int, int, int, int] | None:
    if not isinstance(product_analysis, dict):
        return None
    geometry = product_analysis.get("geometry")
    if not isinstance(geometry, dict):
        return None
    for key in ("container_bbox_pixels", "subject_bbox_pixels"):
        value = geometry.get(key)
        if (
            isinstance(value, list)
            and len(value) == 4
            and all(isinstance(item, int) for item in value)
        ):
            return tuple(value)  # type: ignore[return-value]
    return None


def _clamped_bbox(
    bbox: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return left, top, right, bottom
