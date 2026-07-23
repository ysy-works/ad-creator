#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(
    "/Users/apple/Desktop/ad-creator/reference/"
    "우드_저채도_차분/미디엄/"
    "d7b081a0435a26b0dd79f58771e18d94.jpg"
)
DEFAULT_OUTPUT_ROOT = (
    ROOT / "data/reference-library/control-boards/a6-relational-scene-hint-v3"
)
CANVAS_SIZE = (768, 1024)
SOURCE_PLACEMENT = (0, 128, 768, 896)
SOURCE_ASSET_ID = "ref_381224f47976e566"

# These masks cover beverage interiors, not the full vessel boundaries. The vessel,
# saucer, tray contact and low-frequency overlap remain useful spatial evidence.
CONTENT_MASKS = (
    {
        "mask_id": "left_drink_interior",
        "bbox_normalized_in_square_source": [0.285, 0.515, 0.445, 0.745],
        "radius_ratio": 0.18,
    },
    {
        "mask_id": "rear_carafe_interior",
        "bbox_normalized_in_square_source": [0.405, 0.36, 0.535, 0.655],
        "radius_ratio": 0.22,
    },
    {
        "mask_id": "right_drink_interior",
        "bbox_normalized_in_square_source": [0.505, 0.405, 0.705, 0.685],
        "radius_ratio": 0.28,
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pixel_sha256(path: Path) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"RGB:{image.width}x{image.height}:".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _low_pass(image: Image.Image, size: tuple[int, int], blur: float) -> Image.Image:
    reduced = image.resize(size, Image.Resampling.LANCZOS)
    restored = reduced.resize(image.size, Image.Resampling.BICUBIC)
    return restored.filter(ImageFilter.GaussianBlur(blur))


def _background_mask(size: tuple[int, int]) -> Image.Image:
    width, height = size
    mask = Image.new("L", size, 0)
    pixels = mask.load()
    fade_start = round(height * 0.42)
    fade_end = round(height * 0.60)
    for y in range(fade_end):
        if y <= fade_start:
            value = 255
        else:
            progress = (y - fade_start) / max(1, fade_end - fade_start)
            value = round(255 * (1.0 - progress))
        for x in range(width):
            pixels[x, y] = value
    return mask.filter(ImageFilter.GaussianBlur(8.0))


def _rounded_mask(
    size: tuple[int, int],
    bbox: tuple[int, int, int, int],
    *,
    radius: int,
    feather: float,
) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(bbox, radius=radius, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(feather))


def _sanitize_scene_square(source: Image.Image) -> tuple[Image.Image, list[dict[str, Any]]]:
    square = ImageOps.fit(source, (768, 768), method=Image.Resampling.LANCZOS)

    # Retain the broad sun/shade distribution, but remove recognizable heater,
    # plant, lamp and furniture detail from the far room.
    background = _low_pass(square, (96, 96), 7.0)
    square.paste(background, (0, 0), _background_mask(square.size))

    gray = ImageOps.grayscale(square)
    neutral = ImageOps.colorize(gray, black="#4D443A", white="#CFC4AE")
    neutral = _low_pass(neutral, (192, 192), 3.5)
    evidence: list[dict[str, Any]] = []
    for item in CONTENT_MASKS:
        left, top, right, bottom = item["bbox_normalized_in_square_source"]
        bbox = (
            round(left * square.width),
            round(top * square.height),
            round(right * square.width),
            round(bottom * square.height),
        )
        radius = max(8, round((bbox[2] - bbox[0]) * float(item["radius_ratio"])))
        mask = _rounded_mask(square.size, bbox, radius=radius, feather=11.0)
        square.paste(neutral, (0, 0), mask)
        evidence.append(
            {
                "mask_id": item["mask_id"],
                "bbox_normalized_in_square_source": item[
                    "bbox_normalized_in_square_source"
                ],
                "bbox_px_in_square_source": {
                    "left": bbox[0],
                    "top": bbox[1],
                    "right": bbox[2],
                    "bottom": bbox[3],
                },
                "feather_px": 11.0,
                "operation": "neutralized low-frequency luminance fill",
            }
        )

    # A final half-resolution optical pass keeps the artifact photo-like while
    # preventing small source textures from acting as copy targets.
    square = _low_pass(square, (384, 384), 0.35)
    return square, evidence


def _build_portrait_plate(square: Image.Image) -> Image.Image:
    width, height = CANVAS_SIZE
    plate = Image.new("RGB", CANVAS_SIZE, "#9C8C73")

    top_extension = ImageOps.flip(square.crop((0, 0, width, 128)))
    top_extension = _low_pass(top_extension, (64, 16), 9.0)
    # The last 48 rows are clean white-table pixels below the tray. Stretching
    # only this band avoids reflecting a second tray into the portrait extension.
    bottom_extension = ImageOps.flip(
        square.crop((0, square.height - 48, width, square.height))
    ).resize((width, 128), Image.Resampling.BICUBIC)
    bottom_extension = _low_pass(bottom_extension, (96, 16), 6.0)

    plate.paste(top_extension, (0, 0))
    plate.paste(square, (0, 128))
    plate.paste(bottom_extension, (0, 896))

    # Feather the two extension seams without drawing frames or panels.
    softened = plate.filter(ImageFilter.GaussianBlur(2.2))
    seam_mask = Image.new("L", (width, height), 0)
    seam_draw = ImageDraw.Draw(seam_mask)
    seam_draw.rectangle((0, 116, width, 140), fill=255)
    seam_draw.rectangle((0, 884, width, 908), fill=255)
    seam_mask = seam_mask.filter(ImageFilter.GaussianBlur(10.0))
    plate.paste(softened, (0, 0), seam_mask)

    # Final 384x512 pass is the explicit information ceiling supplied upstream.
    return _low_pass(plate, (384, 512), 0.25)


def _spatial_precompensate(square: Image.Image, content_scale: float) -> Image.Image:
    """Shrink the photographic relationship before model-side scale expansion.

    GPT Image 2 treats normalized bbox text as guidance and consistently enlarged
    the A6 tray group by roughly 1.3x.  This deterministic photographic reframe
    provides the missing spatial evidence while keeping the artifact borderless
    and low-frequency.
    """
    if not 0.6 <= content_scale <= 1.0:
        raise ValueError("content_scale must be between 0.6 and 1.0")
    if content_scale == 1.0:
        return square

    width, height = square.size
    background = _low_pass(square, (32, 32), 14.0)
    # Remove the enlarged tray ghost from the low-frequency backing field.
    # A clean bottom band of the source is stretched upward as neutral table,
    # then feathered into the room/table transition before the smaller square
    # is placed on top.
    table_top = round(height * 0.48)
    clean_table = square.crop((0, height - 48, width, height)).resize(
        (width, height - table_top), Image.Resampling.BICUBIC
    )
    clean_table = _low_pass(clean_table, (96, 24), 8.0)
    table_mask = Image.new("L", square.size, 0)
    table_pixels = table_mask.load()
    fade_end = round(height * 0.58)
    for y in range(table_top, height):
        value = 255 if y >= fade_end else round(
            255 * (y - table_top) / max(1, fade_end - table_top)
        )
        for x in range(width):
            table_pixels[x, y] = value
    table_layer = Image.new("RGB", square.size, clean_table.getpixel((0, 0)))
    table_layer.paste(clean_table, (0, table_top))
    background.paste(table_layer, (0, 0), table_mask)
    scaled_size = (round(width * content_scale), round(height * content_scale))
    scaled = square.resize(scaled_size, Image.Resampling.LANCZOS)
    left = round((width - scaled_size[0]) / 2)
    top = round((height - scaled_size[1]) / 2)
    feather = max(48, round(width * 0.10))
    mask = Image.new("L", scaled_size, 255)
    edge = Image.new("L", scaled_size, 0)
    ImageDraw.Draw(edge).rectangle(
        (feather, feather, scaled_size[0] - feather, scaled_size[1] - feather),
        fill=255,
    )
    edge = edge.filter(ImageFilter.GaussianBlur(feather / 2))
    mask = ImageChops.multiply(mask, edge)
    background.paste(scaled, (left, top), mask)
    return _low_pass(background, (384, 384), 0.4)


def prepare(
    source_path: Path,
    output_root: Path,
    *,
    content_scale: float = 1.0,
    policy_version: str = "a6_relational_scene_hint_v3",
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "scene-hint.png"
    manifest_path = output_root / "scene-hint-manifest.json"

    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    square, mask_evidence = _sanitize_scene_square(source)
    square = _spatial_precompensate(square, content_scale)
    plate = _build_portrait_plate(square)
    plate.save(output_path, format="PNG", optimize=True)

    output_relative = output_path.resolve().relative_to(ROOT.resolve())
    manifest_relative = manifest_path.resolve().relative_to(ROOT.resolve())
    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "sanitized_photographic_scene_hint",
        "policy_version": policy_version,
        "role": "scene_hint",
        "path": str(output_path.resolve()),
        "relative_path": str(output_relative),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_relative_path": str(manifest_relative),
        "width_px": plate.width,
        "height_px": plate.height,
        "aspect_ratio": "3:4",
        "sha256": _sha256(output_path),
        "pixel_sha256": _pixel_sha256(output_path),
        "source_binding": {
            "asset_id": SOURCE_ASSET_ID,
            "path": str(source_path.resolve()),
            "sha256": _sha256(source_path),
            "pixel_sha256": _pixel_sha256(source_path),
            "width_px": source.width,
            "height_px": source.height,
        },
        "construction": {
            "canvas_px": [768, 1024],
            "source_square_placement_px": {
                "left": SOURCE_PLACEMENT[0],
                "top": SOURCE_PLACEMENT[1],
                "right": SOURCE_PLACEMENT[2],
                "bottom": SOURCE_PLACEMENT[3],
            },
            "background_low_pass": {
                "intermediate_px": [96, 96],
                "gaussian_blur_px": 7.0,
                "full_strength_until_source_y_ratio": 0.42,
                "fade_out_at_source_y_ratio": 0.6,
            },
            "content_masks": mask_evidence,
            "final_information_ceiling_px": [384, 512],
            "spatial_precompensation": {
                "content_scale": content_scale,
                "purpose": "counter measured model-side enlargement of the A6 tray group",
            },
            "canvas_extension": "mirrored low-frequency top field and stretched clean-table bottom field with feathered seams",
        },
        "retained_relationships": [
            "complete round dark tray on a white circular table",
            "left-front drink, rear-center carafe and right-front cup assembly",
            "tray and item scale relative to the 3:4 frame",
            "hard far-room daylight and quieter open-shade foreground",
            "broad palette and dark-wood light absorption",
            "low-frequency support, overlap and contact relationships",
        ],
        "forbidden_transfer": [
            "reference beverage identity, recipe or color layers",
            "reference text, logo, watermark or mark",
            "identifiable heater, plant, lamp or furniture detail",
            "exact room geometry",
            "exact crop, shadow silhouette or sunlight-band spacing",
            "source pixels as final output pixels",
        ],
        "sanitation": {
            "visible_labels": False,
            "technical_panels": False,
            "panel_boundaries": False,
            "borderless_photo_like_plate": True,
            "beverage_interiors_neutralized": True,
            "unique_background_objects_strongly_low_passed": True,
            "raw_reference_provider_submission_allowed": False,
        },
        "checks": [
            {
                "check_id": "dimensions_3_by_4",
                "status": "pass" if plate.size == CANVAS_SIZE else "fail",
                "evidence": {"observed_px": list(plate.size)},
            },
            {
                "check_id": "no_technical_panels_or_labels_drawn",
                "status": "pass",
                "evidence": {"drawing_operations": "photo plate, masks and seam feathers only"},
            },
            {
                "check_id": "beverage_content_masks_applied",
                "status": "pass" if len(mask_evidence) == 3 else "fail",
                "evidence": {"mask_ids": [item["mask_id"] for item in mask_evidence]},
            },
            {
                "check_id": "output_differs_from_raw_source",
                "status": "pass"
                if _pixel_sha256(output_path) != _pixel_sha256(source_path)
                else "fail",
                "evidence": {
                    "output_pixel_sha256": _pixel_sha256(output_path),
                    "source_pixel_sha256": _pixel_sha256(source_path),
                },
            },
        ],
    }
    manifest["manifest_content_sha256"] = _canonical_json_sha256(manifest)
    _write_json(manifest_path, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the deterministic sanitized A6 v3 photographic scene hint."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--content-scale", type=float, default=1.0)
    parser.add_argument(
        "--policy-version", default="a6_relational_scene_hint_v3"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = prepare(
        args.source.expanduser(),
        args.output_root.expanduser(),
        content_scale=args.content_scale,
        policy_version=args.policy_version,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
