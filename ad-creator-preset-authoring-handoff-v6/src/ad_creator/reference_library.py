from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .image_contracts import (
    canonical_image_binding,
    dhash_distance,
    perceptual_dhash,
)
from .serving_contracts import derive_container_service_profile


SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def iter_reference_images(root: str | Path) -> list[Path]:
    reference_root = Path(root).expanduser().resolve()
    if not reference_root.is_dir():
        raise NotADirectoryError(f"Reference root does not exist: {reference_root}")
    return sorted(
        path
        for path in reference_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _palette(image: Image.Image, count: int = 5) -> list[str]:
    sample = image.copy()
    sample.thumbnail((256, 256), Image.Resampling.LANCZOS)
    quantized = sample.quantize(colors=count, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colors = quantized.getcolors(maxcolors=256 * 256) or []
    ordered = [rgb for _frequency, rgb in sorted(colors, reverse=True)]
    palette = [f"#{red:02X}{green:02X}{blue:02X}" for red, green, blue in ordered[:count]]
    while len(palette) < 3:
        palette.append(palette[-1] if palette else "#808080")
    return palette


def _image_metrics(image: Image.Image) -> dict[str, Any]:
    sample = image.copy()
    sample.thumbnail((512, 512), Image.Resampling.LANCZOS)
    luminance = sample.convert("L")
    saturation = sample.convert("HSV").getchannel("S")
    edges = luminance.filter(ImageFilter.FIND_EDGES)
    if edges.width > 4 and edges.height > 4:
        edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))
    luminance_stat = ImageStat.Stat(luminance)
    return {
        "palette_hex": _palette(sample),
        "mean_luminance": round(luminance_stat.mean[0] / 255, 4),
        "luminance_stddev": round(min(1.0, luminance_stat.stddev[0] / 127.5), 4),
        "mean_saturation": round(ImageStat.Stat(saturation).mean[0] / 255, 4),
        "edge_energy": round(ImageStat.Stat(edges).mean[0] / 255, 4),
    }


def inspect_reference_asset(
    path: str | Path,
    *,
    reference_root: str | Path,
) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    root = Path(reference_root).expanduser().resolve()
    relative = source.relative_to(root)
    binding = canonical_image_binding(source)
    with Image.open(source) as opened:
        image_format = (opened.format or source.suffix.lstrip(".")).upper()
        image = ImageOps.exif_transpose(opened).convert("RGB")
        metrics = _image_metrics(image)
        dhash = perceptual_dhash(image)
    folder_tags = list(relative.parts[:-1]) or ["uncategorized"]
    asset_key = hashlib.sha256(
        f"{binding['pixel_sha256']}\0{relative.as_posix()}".encode("utf-8")
    ).hexdigest()
    return {
        "asset_id": f"ref_{asset_key[:16]}",
        "relative_path": relative.as_posix(),
        "file_sha256": _file_sha256(source),
        "pixel_sha256": binding["pixel_sha256"],
        "width_px": binding["width_px"],
        "height_px": binding["height_px"],
        "format": image_format,
        "source_folder_tags": folder_tags,
        "dhash": dhash,
        "duplicate_of": None,
        "local_color_metrics": metrics,
    }


def mark_near_duplicates(
    assets: Iterable[dict[str, Any]],
    *,
    maximum_dhash_distance: int = 3,
) -> list[dict[str, Any]]:
    records = [dict(asset) for asset in assets]
    exact_by_pixel: dict[str, str] = {}
    representatives: list[dict[str, Any]] = []
    for asset in records:
        exact = exact_by_pixel.get(asset["pixel_sha256"])
        if exact:
            asset["duplicate_of"] = exact
            continue
        exact_by_pixel[asset["pixel_sha256"]] = asset["asset_id"]
        near = next(
            (
                candidate
                for candidate in representatives
                if dhash_distance(asset["dhash"], candidate["dhash"])
                <= maximum_dhash_distance
            ),
            None,
        )
        if near is not None:
            asset["duplicate_of"] = near["asset_id"]
        else:
            representatives.append(asset)
    return records


def validate_reference_geometry(reference: dict[str, Any]) -> None:
    geometry = reference["geometry"]
    for name in ("container_bbox", "subject_bbox"):
        box = geometry[name]
        if not (
            0 <= box["left"] < box["right"] <= 1
            and 0 <= box["top"] < box["bottom"] <= 1
        ):
            raise ValueError(f"Invalid {name} in {reference['asset']['asset_id']}")
    straw = geometry["straw"]
    fields = ("bbox", "centerline", "emergence_point", "angle_degrees")
    if straw["present"] and any(straw[field] is None for field in fields):
        raise ValueError("Present straw requires both bbox and centerline geometry")
    if not straw["present"] and any(straw[field] is not None for field in fields):
        raise ValueError("Absent straw must have null geometry")


_MULTI_SUBJECT_PATTERN = re.compile(
    r"\b(group|pair|two|three|four|five|six|multiple|assorted|several)\b",
    re.IGNORECASE,
)
_NON_CONTAINER_CLASSES = {
    "plate",
    "saucer",
    "tray",
    "dish",
    "bowl",
    "paper bag",
    "box",
}
_SUPPORTED_CONTAINER_MATERIALS = {
    "glass",
    "plastic",
    "paper",
    "ceramic",
    "metal",
    "steel",
}


def derive_reference_capabilities(reference: dict[str, Any]) -> dict[str, Any]:
    """Derive versioned service policy without mutating the semantic analysis."""
    validate_reference_geometry(reference)
    subject = reference["subject"]
    container = subject["container"]
    primary_text = f"{subject['primary_subject']} {subject['beverage']}"
    component_text = " ".join(container["components"])
    multiple_products = bool(_MULTI_SUBJECT_PATTERN.search(primary_text)) or any(
        token in component_text.lower() for token in ("carrier", "cup holder")
    )
    container_class = container["class"].strip().lower()
    container_material = container["material"].strip().lower()
    non_container_subject = container_class in _NON_CONTAINER_CLASSES
    material_supported = any(
        material in container_material for material in _SUPPORTED_CONTAINER_MATERIALS
    )
    scene_generation_eligible = not multiple_products
    container_adoption_eligible = (
        scene_generation_eligible and not non_container_subject and material_supported
    )
    reasons = []
    if multiple_products:
        reasons.append("multiple_primary_products_without_single_anchor")
    if non_container_subject:
        reasons.append("reference_subject_is_not_a_drink_container")
    if not material_supported:
        reasons.append("unsupported_or_uncertain_container_material")
    if reference["depth"]["far_plane_softness"] == "strong":
        reasons.append("far_plane_softness_must_be_clamped_for_smartphone_naturalness")

    return {
        "policy_version": "reference_runtime_policy_v1",
        "scene_generation_eligible": scene_generation_eligible,
        "placement_anchor": "subject_bbox" if non_container_subject else "container_bbox",
        "container_adoption_eligible": container_adoption_eligible,
        "multiple_primary_products": multiple_products,
        "handheld_required": subject["interaction"] == "held",
        "depth_transfer": (
            "clamp_to_moderate"
            if reference["depth"]["far_plane_softness"] == "strong"
            else "as_analyzed"
        ),
        "reason_codes": reasons,
    }


def derive_container_design(reference: dict[str, Any]) -> dict[str, Any]:
    """Derive a role-limited cup contract without transferring scene identity."""
    validate_reference_geometry(reference)
    capabilities = derive_reference_capabilities(reference)
    if not capabilities["container_adoption_eligible"]:
        reasons = ", ".join(capabilities["reason_codes"]) or "unsupported reference"
        raise ValueError(f"Reference container cannot be adopted: {reasons}")
    asset = reference["asset"]
    source = reference["subject"]["container"]
    box = reference["geometry"]["container_bbox"]
    pixel_width = (box["right"] - box["left"]) * asset["width_px"]
    pixel_height = (box["bottom"] - box["top"]) * asset["height_px"]
    ratio = max(0.5, min(6.0, pixel_height / max(pixel_width, 1)))
    lower = round(ratio * 0.92, 3)
    upper = round(ratio * 1.08, 3)
    service_profile = derive_container_service_profile(
        {
            "description": reference["subject"]["beverage"],
            "container": {
                "class": source["class"],
                "material": source["material"],
                "silhouette": source["silhouette"],
                "components": source["components"],
            },
            "straw": reference["geometry"]["straw"],
        }
    )
    if service_profile is None:
        raise ValueError("Reference container service profile could not be derived")
    temperatures_by_service = {
        "cold": ["cold"],
        "hot": ["hot"],
        "ambient": ["ambient"],
        "dual": ["cold", "hot", "ambient"],
        # Legacy designs cannot represent an unresolved temperature. Keep the
        # least assumptive ambient-only contract so cold/hot products block.
        "unknown": ["ambient"],
    }
    return {
        "schema_version": "1.0.0",
        "container_design_id": f"auto_{asset['asset_id']}",
        "display_name": f"Reference-derived {source['class']}",
        "design": {
            "class": source["class"],
            "material": source["material"],
            "geometry": source["silhouette"],
            "components": source["components"],
            "height_to_width_ratio": [lower, upper],
        },
        "allowed_transfer": [
            "container material",
            "container silhouette and height-to-width relationship",
            "rim, lid, sleeve and handle structure only when visibly present",
            "immediate support components such as a saucer, coaster or pedestal and their support relation only when listed in design.components",
        ],
        "forbidden_transfer": [
            "reference beverage, color layers, ice, garnish or toppings",
            "reference text, logo, watermark or decorative brand mark",
            "reference background, unrelated prop arrangement, crop, hand or shadow silhouette",
        ],
        "compatibility": {
            "beverage_temperatures": temperatures_by_service[
                service_profile["service_temperature"]
            ],
            "supports_toppings": service_profile["supports_toppings"] is True,
            "supports_straw": service_profile["supports_straw"] is True,
            "brand_surface": "the main unobstructed front-facing container surface",
        },
    }
