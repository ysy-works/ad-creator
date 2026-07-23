from __future__ import annotations

from pathlib import Path
from typing import Any


def ordered_image_inputs(
    generation: dict[str, Any],
    *,
    allow_legacy: bool = True,
) -> list[dict[str, Any]]:
    """Return one canonical ordered image-input list.

    Generation request v3 stores image roles next to their paths so adding a
    second or third product cannot desynchronise parallel arrays.  The legacy
    v2 arrays remain readable for historical manifests and existing workflows.
    """

    value = generation.get("image_inputs")
    if value is not None:
        if not isinstance(value, list) or not value:
            raise ValueError("generation.image_inputs must be a non-empty list")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"generation.image_inputs[{index}] must be an object")
            role = item.get("role")
            path = item.get("path")
            if not isinstance(role, str) or not role.strip():
                raise ValueError(f"generation.image_inputs[{index}].role is required")
            if not isinstance(path, str) or not path.strip():
                raise ValueError(f"generation.image_inputs[{index}].path is required")
            normalized_item = {"role": role, "path": path}
            product_id = item.get("product_id")
            if product_id is not None:
                if not isinstance(product_id, str) or not product_id.strip():
                    raise ValueError(
                        f"generation.image_inputs[{index}].product_id must be non-empty"
                    )
                normalized_item["product_id"] = product_id
            normalized.append(normalized_item)
        return normalized

    if not allow_legacy:
        raise ValueError("Generation request v3 requires generation.image_inputs")
    paths = generation.get("image_paths")
    roles = generation.get("image_roles")
    if not isinstance(paths, list) or not paths:
        raise ValueError("generation image inputs are missing")
    if roles is None:
        roles = ["product_source", *["unspecified"] * (len(paths) - 1)]
    if not isinstance(roles, list) or len(roles) != len(paths):
        raise ValueError("Legacy generation image roles must align with image paths")
    return [
        {"role": role, "path": path}
        for role, path in zip(roles, paths, strict=True)
    ]


def resolved_image_paths(generation: dict[str, Any]) -> list[Path]:
    return [
        Path(item["path"]).expanduser().resolve()
        for item in ordered_image_inputs(generation)
    ]


def product_source_inputs(generation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in ordered_image_inputs(generation)
        if item["role"] == "product_source"
    ]


def first_input_for_role(
    generation: dict[str, Any],
    role: str,
) -> dict[str, Any] | None:
    return next(
        (item for item in ordered_image_inputs(generation) if item["role"] == role),
        None,
    )
