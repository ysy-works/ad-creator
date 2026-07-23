from __future__ import annotations

import colorsys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat


GRADE_STRENGTHS = {
    "off": 0.0,
    "natural": 0.20,
    "balanced": 0.35,
    "expressive": 0.55,
}


def resolve_grade_strengths(lighting_sheet: dict[str, Any] | None = None) -> dict[str, float]:
    if not lighting_sheet:
        return dict(GRADE_STRENGTHS)
    values = {**GRADE_STRENGTHS, **lighting_sheet.get("grade_strengths", {})}
    return {name: float(values[name]) for name in GRADE_STRENGTHS}


def instagram_center_crop(
    image: Image.Image,
    *,
    target_size: tuple[int, int] | None = None,
) -> Image.Image:
    source = ImageOps.exif_transpose(image).convert("RGB")
    target_ratio = 4 / 5
    source_ratio = source.width / source.height
    if source_ratio > target_ratio:
        crop_width = round(source.height * target_ratio)
        left = (source.width - crop_width) // 2
        box = (left, 0, left + crop_width, source.height)
    else:
        crop_height = round(source.width / target_ratio)
        top = (source.height - crop_height) // 2
        box = (0, top, source.width, top + crop_height)
    cropped = source.crop(box)
    if target_size and cropped.size != target_size:
        cropped = cropped.resize(target_size, Image.Resampling.LANCZOS)
    return cropped


def instagram_natural_finish(
    image: Image.Image,
    *,
    target_size: tuple[int, int] = (880, 1100),
) -> Image.Image:
    """Apply one restrained, model-neutral social-delivery finish.

    The function deliberately removes a little synthetic-looking uniform
    acuity. The caller owns the single JPEG encode. It does not add a creative
    grade, fabricated grain, blur masking or sharpening, so model comparisons
    remain attributable to the provider output.
    """

    cropped = instagram_center_crop(image, target_size=target_size)
    softened = cropped.filter(ImageFilter.GaussianBlur(radius=0.32))
    natural = Image.blend(cropped, softened, 0.34)
    natural = ImageEnhance.Contrast(natural).enhance(0.985)
    natural = ImageEnhance.Color(natural).enhance(0.985)
    return natural


def _build_lut(profile: dict[str, Any]) -> ImageFilter.Color3DLUT:
    transform = profile["transform"]
    exposure = 2 ** float(transform.get("exposure_ev", 0.0))
    contrast = float(transform.get("contrast", 1.0))
    saturation = float(transform.get("saturation", 1.0))
    warmth = float(transform.get("warmth", 0.0))
    shadow_lift = float(transform.get("shadow_lift", 0.0))
    highlight_rolloff = float(transform.get("highlight_rolloff", 0.0))
    tone_curve = profile.get("tone_curve") or [[0.0, 0.0], [1.0, 1.0]]
    split_tone = profile.get("split_tone") or {}
    selective_saturation = profile.get("selective_saturation") or {}

    def curve(value: float) -> float:
        clamped = max(0.0, min(1.0, value))
        for index in range(1, len(tone_curve)):
            left = tone_curve[index - 1]
            right = tone_curve[index]
            if clamped <= float(right[0]):
                span = max(1e-9, float(right[0]) - float(left[0]))
                mix = (clamped - float(left[0])) / span
                return float(left[1]) + (float(right[1]) - float(left[1])) * mix
        return float(tone_curve[-1][1])

    hue_names = ("red", "yellow", "green", "cyan", "blue", "magenta")

    def callback(red: float, green: float, blue: float) -> tuple[float, float, float]:
        channels = [red * exposure, green * exposure, blue * exposure]
        luma = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
        lift = shadow_lift * max(0.0, 1.0 - luma) ** 2
        channels = [channel + lift for channel in channels]
        channels[0] += warmth * 0.035
        channels[2] -= warmth * 0.030
        luma = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
        channels = [luma + (channel - luma) * saturation for channel in channels]
        channels = [0.5 + (channel - 0.5) * contrast for channel in channels]
        channels = [curve(channel) for channel in channels]
        hue, sat, value = colorsys.rgb_to_hsv(
            *[max(0.0, min(1.0, channel)) for channel in channels]
        )
        hue_index = int((hue * 6.0) + 0.5) % 6
        sat *= float(selective_saturation.get(hue_names[hue_index], 1.0))
        channels = list(colorsys.hsv_to_rgb(hue, max(0.0, min(1.0, sat)), value))
        if split_tone:
            luma = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
            balance = float(split_tone.get("balance", 0.5))
            tone_strength = float(split_tone.get("strength", 0.0))
            shadow_weight = max(0.0, min(1.0, (balance - luma) / max(balance, 1e-6)))
            highlight_weight = max(
                0.0,
                min(1.0, (luma - balance) / max(1.0 - balance, 1e-6)),
            )
            shadow_rgb = split_tone.get("shadow_rgb", [0.5, 0.5, 0.5])
            highlight_rgb = split_tone.get("highlight_rgb", [0.5, 0.5, 0.5])
            channels = [
                channel
                + (float(shadow_rgb[index]) - 0.5) * tone_strength * shadow_weight
                + (float(highlight_rgb[index]) - 0.5) * tone_strength * highlight_weight
                for index, channel in enumerate(channels)
            ]
        if highlight_rolloff > 0:
            compressed = []
            for channel in channels:
                over = max(0.0, channel - 0.72)
                compressed.append(channel - over * highlight_rolloff * min(1.0, over / 0.28))
            channels = compressed
        return tuple(max(0.0, min(1.0, channel)) for channel in channels)

    return ImageFilter.Color3DLUT.generate(17, callback)


def _smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    if edge1 <= edge0:
        return (values >= edge1).astype(np.float32)
    scaled = np.clip((values - edge0) / (edge1 - edge0), 0.0, 1.0)
    return scaled * scaled * (3.0 - 2.0 * scaled)


def _apply_targeted_relight(
    image: Image.Image,
    *,
    policy: dict[str, Any],
    scope_mask: Image.Image | None,
) -> Image.Image:
    """Apply a profile-declared relight to automatically selected tonal regions.

    The policy is reusable across presets. It never owns spatial composition: the
    existing product protection mask supplies the scope, while luminance and
    saturation rules select the material-like pixels inside that scope.
    """
    if scope_mask is None or policy.get("scope") != "protection_mask":
        return image

    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    maximum = rgb.max(axis=2)
    minimum = rgb.min(axis=2)
    luma = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    saturation = np.divide(
        maximum - minimum,
        np.maximum(maximum, 1e-6),
        out=np.zeros_like(maximum),
        where=maximum > 1e-6,
    )

    lower, upper = (float(value) for value in policy["luma_range"])
    luma_feather = float(policy["luma_feather"])
    saturation_limit = float(policy["max_saturation"])
    saturation_feather = float(policy["saturation_feather"])
    lower_weight = _smoothstep(lower, lower + luma_feather, luma)
    upper_weight = 1.0 - _smoothstep(upper - luma_feather, upper, luma)
    chroma_weight = 1.0 - _smoothstep(
        saturation_limit - saturation_feather,
        saturation_limit,
        saturation,
    )
    scope = np.asarray(
        ImageOps.fit(
            scope_mask.convert("L"),
            image.size,
            method=Image.Resampling.BILINEAR,
        ),
        dtype=np.float32,
    ) / 255.0
    spatial_focus = policy.get("spatial_focus")
    if isinstance(spatial_focus, dict):
        active_y, active_x = np.where(scope > 0.01)
        if active_x.size and active_y.size:
            left, right = active_x.min(), active_x.max()
            top, bottom = active_y.min(), active_y.max()
            x_axis = np.arange(scope.shape[1], dtype=np.float32)
            y_axis = np.arange(scope.shape[0], dtype=np.float32)
            normalized_x = (x_axis - left) / max(float(right - left), 1.0)
            normalized_y = (y_axis - top) / max(float(bottom - top), 1.0)
            grid_x, grid_y = np.meshgrid(normalized_x, normalized_y)
            center_x, center_y = (float(value) for value in spatial_focus["center"])
            radius_x, radius_y = (float(value) for value in spatial_focus["radius"])
            distance = np.sqrt(
                ((grid_x - center_x) / max(radius_x, 1e-6)) ** 2
                + ((grid_y - center_y) / max(radius_y, 1e-6)) ** 2
            )
            focus_feather = float(spatial_focus["feather"])
            scope *= 1.0 - _smoothstep(1.0 - focus_feather, 1.0, distance)
    selection = np.clip(lower_weight * upper_weight * chroma_weight * scope, 0.0, 1.0)

    relit = rgb * (2 ** float(policy["exposure_ev"]))
    warmth = float(policy["warmth"])
    relit[:, :, 0] += warmth * 0.035
    relit[:, :, 2] -= warmth * 0.030
    relit_luma = (
        0.2126 * relit[:, :, 0]
        + 0.7152 * relit[:, :, 1]
        + 0.0722 * relit[:, :, 2]
    )
    relit = relit_luma[:, :, None] + (
        relit - relit_luma[:, :, None]
    ) * float(policy["saturation"])
    alpha = (selection * float(policy["blend_strength"]))[:, :, None]
    output = np.clip(rgb * (1.0 - alpha) + relit * alpha, 0.0, 1.0)
    return Image.fromarray(np.rint(output * 255.0).astype(np.uint8), mode="RGB")


def apply_grade(
    image: Image.Image,
    *,
    profile: dict[str, Any],
    strength: float,
    protection_mask: Image.Image | None = None,
) -> Image.Image:
    if not 0 <= strength <= float(profile["strength"]["max"]):
        raise ValueError(f"Grade strength {strength} is outside the profile range")
    original = ImageOps.exif_transpose(image).convert("RGB")
    graded = original.filter(_build_lut(profile))
    local_contrast = profile.get("local_contrast")
    if isinstance(local_contrast, dict) and float(local_contrast.get("amount", 0.0)) > 0:
        graded = graded.filter(
            ImageFilter.UnsharpMask(
                radius=float(local_contrast.get("radius", 2.0)),
                percent=round(float(local_contrast.get("amount", 0.0)) * 100),
                threshold=int(local_contrast.get("threshold", 4)),
            )
        )
    mixed = Image.blend(original, graded, strength)
    if protection_mask is not None:
        mask = ImageOps.fit(protection_mask.convert("L"), original.size, method=Image.Resampling.BILINEAR)
        protection = float(profile.get("protection", {}).get("mask_strength", 0.85))
        mask = mask.point(lambda value: round(value * protection))
        mixed = Image.composite(original, mixed, mask)
    targeted_relight = profile.get("targeted_relight")
    if strength > 0 and isinstance(targeted_relight, dict):
        mixed = _apply_targeted_relight(
            mixed,
            policy=targeted_relight,
            scope_mask=protection_mask,
        )
    return mixed


def image_metrics(image: Image.Image) -> dict[str, Any]:
    rgb = image.convert("RGB")
    luma = rgb.convert("L")
    stats = ImageStat.Stat(luma)
    histogram = luma.histogram()
    pixels = max(1, rgb.width * rgb.height)
    clipped_dark = sum(histogram[:3]) / pixels
    clipped_bright = sum(histogram[253:]) / pixels
    return {
        "width": rgb.width,
        "height": rgb.height,
        "aspect_ratio": round(rgb.width / rgb.height, 6),
        "luma_mean": round(stats.mean[0] / 255, 6),
        "luma_stddev": round(stats.stddev[0] / 255, 6),
        "clipped_dark_ratio": round(clipped_dark, 6),
        "clipped_bright_ratio": round(clipped_bright, 6),
    }


def save_image(image: Image.Image, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    return destination
