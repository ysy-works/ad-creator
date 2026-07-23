from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .image_contracts import canonical_image_binding


CONTACT_SHEET_RENDERER_VERSION = "local_contact_sheet_v1"
STATUS_COLORS = {
    "pass": "#2EA043",
    "needs_review": "#D29922",
    "fail": "#CF222E",
}


def contact_sheet_font(size: int) -> ImageFont.ImageFont:
    """Return the same portable font fallback used by reference QA sheets."""

    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def fit_contact_sheet_image(
    image: Image.Image,
    size: tuple[int, int],
) -> Image.Image:
    return ImageOps.contain(
        ImageOps.exif_transpose(image).convert("RGB"),
        size,
        method=Image.Resampling.LANCZOS,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_labeled_contact_sheet(
    cells: Sequence[Mapping[str, Any]],
    output_path: str | Path,
    *,
    columns: int,
    rows: int,
    cell_width: int = 320,
    cell_height: int = 400,
) -> dict[str, Any]:
    """Render local generated outputs and return deterministic grid metadata."""

    if columns < 1 or rows < 1:
        raise ValueError("Contact-sheet columns and rows must be positive")
    if len(cells) != columns * rows:
        raise ValueError("Contact-sheet cell count must exactly fill the grid")
    if cell_width < 120 or cell_height < 160:
        raise ValueError("Contact-sheet cells are too small for image and labels")

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    label_height = 72
    canvas = Image.new(
        "RGB",
        (columns * cell_width, rows * cell_height),
        "#E8E8E5",
    )
    title_font = contact_sheet_font(17)
    detail_font = contact_sheet_font(14)
    grid_cells: list[dict[str, Any]] = []

    for index, raw in enumerate(cells):
        case_id = raw.get("case_id")
        status = raw.get("status")
        image_path = Path(str(raw.get("image_path", ""))).expanduser().resolve()
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"Contact-sheet cell {index} requires case_id")
        if status not in STATUS_COLORS:
            raise ValueError(f"Contact-sheet cell {index} has an invalid status")
        if not image_path.is_file():
            raise FileNotFoundError(f"Contact-sheet image does not exist: {image_path}")

        row, column = divmod(index, columns)
        x0, y0 = column * cell_width, row * cell_height
        cell = Image.new("RGB", (cell_width, cell_height), "#F5F5F3")
        with Image.open(image_path) as opened:
            fitted = fit_contact_sheet_image(
                opened,
                (cell_width - 12, cell_height - label_height - 12),
            )
        left = (cell_width - fitted.width) // 2
        top = 6 + (cell_height - label_height - 12 - fitted.height) // 2
        cell.paste(fitted, (left, top))

        draw = ImageDraw.Draw(cell)
        draw.rectangle(
            (0, cell_height - label_height, cell_width, cell_height - label_height + 6),
            fill=STATUS_COLORS[status],
        )
        draw.text(
            (8, cell_height - label_height + 11),
            f"{index + 1:02d}  {case_id}",
            fill="#111111",
            font=title_font,
        )
        detail = str(raw.get("detail") or status).strip()
        draw.text(
            (8, cell_height - label_height + 38),
            detail[:48],
            fill="#444444",
            font=detail_font,
        )
        canvas.paste(cell, (x0, y0))
        grid_cells.append(
            {
                "index": index,
                "row": row,
                "column": column,
                "case_id": case_id,
                "status": status,
                "output_pixel_sha256": raw.get("output_pixel_sha256"),
            }
        )

    suffix = destination.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        canvas.save(destination, format="JPEG", quality=92, optimize=True)
    elif suffix == ".png":
        canvas.save(destination, format="PNG", optimize=True)
    else:
        raise ValueError("Contact sheet output must use .jpg, .jpeg, or .png")
    binding = canonical_image_binding(destination)
    return {
        "renderer_version": CONTACT_SHEET_RENDERER_VERSION,
        "path": str(destination),
        "file_sha256": _file_sha256(destination),
        "pixel_sha256": binding["pixel_sha256"],
        "width_px": binding["width_px"],
        "height_px": binding["height_px"],
        "columns": columns,
        "rows": rows,
        "cell_width_px": cell_width,
        "cell_height_px": cell_height,
        "cells": grid_cells,
    }
