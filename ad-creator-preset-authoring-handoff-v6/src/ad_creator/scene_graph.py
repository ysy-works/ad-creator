from __future__ import annotations

import copy
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .jsonio import validate_json
from .reference_library import derive_reference_capabilities


MAJOR_KINDS = {"beverage", "dessert"}
REPLACEABLE_KINDS = {"beverage", "dessert", "prop"}
ROLE_ORDER = {"primary": 0, "secondary": 1, "accent": 2, "support": 3}
ORDINAL_NAMES = ("primary", "secondary", "tertiary")


def _box_is_valid(box: dict[str, Any]) -> bool:
    return (
        0 <= box["left"] < box["right"] <= 1
        and 0 <= box["top"] < box["bottom"] <= 1
    )


def _box_contains(outer: dict[str, Any], inner: dict[str, Any], tolerance: float = 0.02) -> bool:
    return (
        outer["left"] <= inner["left"] + tolerance
        and outer["top"] <= inner["top"] + tolerance
        and outer["right"] + tolerance >= inner["right"]
        and outer["bottom"] + tolerance >= inner["bottom"]
    )


def _area(box: dict[str, Any]) -> float:
    return max(0.0, box["right"] - box["left"]) * max(
        0.0, box["bottom"] - box["top"]
    )


def _intersection_area(first: dict[str, Any], second: dict[str, Any]) -> float:
    width = max(0.0, min(first["right"], second["right"]) - max(first["left"], second["left"]))
    height = max(0.0, min(first["bottom"], second["bottom"]) - max(first["top"], second["top"]))
    return width * height


def _overlap_fraction(candidate: dict[str, Any], occupied: dict[str, Any]) -> float:
    return _intersection_area(candidate, occupied) / max(_area(candidate), 1e-9)


def _validate_straw(straw: dict[str, Any], *, label: str) -> None:
    fields = ("bbox", "centerline", "emergence_point", "angle_degrees")
    if straw["present"] and any(straw[field] is None for field in fields):
        raise ValueError(f"{label}: present straw requires complete geometry")
    if not straw["present"] and any(straw[field] is not None for field in fields):
        raise ValueError(f"{label}: absent straw must have null geometry")
    if straw["bbox"] is not None and not _box_is_valid(straw["bbox"]):
        raise ValueError(f"{label}: invalid straw bbox")


def validate_scene_graph(
    graph: dict[str, Any],
    *,
    project_root: str | None = None,
) -> None:
    kwargs = {"project_root": project_root} if project_root is not None else {}
    validate_json(graph, "reference-scene-graph.schema.json", **kwargs)

    objects = graph["objects"]
    slot_ids = [item["slot_id"] for item in objects]
    if len(slot_ids) != len(set(slot_ids)):
        raise ValueError("Scene graph slot_id values must be unique")
    slots = set(slot_ids)

    surface_ids = [item["surface_id"] for item in graph["support_surfaces"]]
    if len(surface_ids) != len(set(surface_ids)):
        raise ValueError("Scene graph surface_id values must be unique")
    surfaces = set(surface_ids)

    for item in objects:
        body = item["body_bbox"]
        full = item["full_bbox"]
        if not _box_is_valid(body) or not _box_is_valid(full):
            raise ValueError(f"Invalid object geometry for {item['slot_id']}")
        if not _box_contains(full, body):
            raise ValueError(f"body_bbox must be contained by full_bbox for {item['slot_id']}")
        _validate_straw(item["straw"], label=item["slot_id"])
        if item["support_surface_id"] is not None and item["support_surface_id"] not in surfaces:
            raise ValueError(f"Unknown support surface for {item['slot_id']}")
        if item["replaceable"] and item["kind"] not in REPLACEABLE_KINDS:
            raise ValueError(f"Unsupported replaceable object kind for {item['slot_id']}")
        if item["replaceable"] and not item["allowed_kinds"]:
            raise ValueError(f"Replaceable slot {item['slot_id']} requires allowed_kinds")

    for relation in graph["relations"]:
        source = relation["from_slot_id"]
        target = relation["to_slot_id"]
        if source not in slots or target not in slots:
            raise ValueError("Scene graph relation references an unknown slot")
        if source == target:
            raise ValueError("Scene graph relation cannot reference the same slot twice")

    region_ids = [item["region_id"] for item in graph["protected_regions"]]
    if len(region_ids) != len(set(region_ids)):
        raise ValueError("Scene graph region_id values must be unique")
    for region in graph["protected_regions"]:
        if not _box_is_valid(region["bbox"]):
            raise ValueError(f"Invalid protected region {region['region_id']}")

    zone_ids = [item["zone_id"] for item in graph["insertion_zones"]]
    if len(zone_ids) != len(set(zone_ids)):
        raise ValueError("Scene graph zone_id values must be unique")
    for zone in graph["insertion_zones"]:
        if not _box_is_valid(zone["bbox"]):
            raise ValueError(f"Invalid insertion zone {zone['zone_id']}")
        if zone["support_surface_id"] not in surfaces:
            raise ValueError(f"Insertion zone {zone['zone_id']} has no support surface")
        if zone["scale_range"][0] > zone["scale_range"][1]:
            raise ValueError(f"Insertion zone {zone['zone_id']} has a reversed scale range")

    major = [item for item in objects if item["kind"] in MAJOR_KINDS]
    if not major:
        raise ValueError("Scene graph requires at least one beverage or dessert")
    observed_count = int(graph.get("observed_major_subject_count", len(major)))
    inventory_complete = bool(graph.get("object_inventory_complete", True))
    if inventory_complete and observed_count != len(major):
        raise ValueError("Complete scene graph inventory must match observed major count")
    if not inventory_complete and observed_count <= len(major):
        raise ValueError("Incomplete scene graph inventory must report omitted major subjects")
    expected_mode = (
        "solo" if observed_count == 1 else "pair" if observed_count == 2 else "set"
    )
    if graph["scene_mode"] != expected_mode:
        raise ValueError(
            f"scene_mode {graph['scene_mode']} does not match {len(major)} major objects"
        )
    if graph["taxonomy"]["scene_complexity"] != graph["scene_mode"]:
        raise ValueError("Taxonomy scene_complexity must match scene_mode")


def _slot_sort_key(item: dict[str, Any]) -> tuple[int, float, float, float]:
    box = item["body_bbox"]
    return (
        ROLE_ORDER[item["role"]],
        -_area(box),
        box["left"],
        box["top"],
    )


def canonicalize_slot_ids(graph: dict[str, Any]) -> dict[str, Any]:
    """Assign deterministic semantic slot IDs and update every relation."""
    value = copy.deepcopy(graph)
    old_ids = [item["slot_id"] for item in value["objects"]]
    if len(old_ids) != len(set(old_ids)):
        raise ValueError("Cannot canonicalize duplicate source slot IDs")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in value["objects"]:
        grouped[item["kind"]].append(item)

    mapping: dict[str, str] = {}
    for kind, items in grouped.items():
        for index, item in enumerate(sorted(items, key=_slot_sort_key)):
            suffix = ORDINAL_NAMES[index] if index < len(ORDINAL_NAMES) else f"{index + 1:02d}"
            mapping[item["slot_id"]] = f"{kind}_{suffix}"

    for item in value["objects"]:
        item["slot_id"] = mapping[item["slot_id"]]
    for relation in value["relations"]:
        relation["from_slot_id"] = mapping[relation["from_slot_id"]]
        relation["to_slot_id"] = mapping[relation["to_slot_id"]]
    value["objects"].sort(
        key=lambda item: (
            0 if item["kind"] in MAJOR_KINDS else 1,
            _slot_sort_key(item),
            item["slot_id"],
        )
    )
    return value


def primary_scene_object(graph: dict[str, Any]) -> dict[str, Any]:
    major = [item for item in graph["objects"] if item["kind"] in MAJOR_KINDS]
    primary = [item for item in major if item["role"] == "primary"]
    return sorted(primary or major, key=_slot_sort_key)[0]


def _safe_insertion_zones(graph: dict[str, Any]) -> list[dict[str, Any]]:
    occupied = [item["full_bbox"] for item in graph["objects"]]
    occupied.extend(
        region["bbox"]
        for region in graph["protected_regions"]
        if region["kind"] in {"hand", "visible_text", "watermark", "occupied", "negative_space"}
    )
    return [
        copy.deepcopy(zone)
        for zone in graph["insertion_zones"]
        if zone["confidence"] >= 0.72
        and all(_overlap_fraction(zone["bbox"], box) <= 0.12 for box in occupied)
        and zone["bbox"]["left"] >= 0.05
        and zone["bbox"]["right"] <= 0.95
        and zone["bbox"]["top"] >= 0.06
        and zone["bbox"]["bottom"] <= 0.94
    ]


def _frame_margin(box: dict[str, Any]) -> float:
    return min(box["left"], box["top"], 1 - box["right"], 1 - box["bottom"])


def _replacement_candidate_key(
    item: dict[str, Any],
    *,
    product_kind: str,
) -> tuple[int, float, float, float, tuple[int, float, float, float], str]:
    """Rank automatic replacement candidates without depending on catalog order."""
    return (
        0 if item["kind"] == product_kind else 1,
        -_frame_margin(item["full_bbox"]),
        item["occlusion_fraction"],
        -_area(item["body_bbox"]),
        _slot_sort_key(item),
        item["slot_id"],
    )


def _insertion_candidate_key(
    item: dict[str, Any],
) -> tuple[float, float, float, str]:
    return (
        -_frame_margin(item["bbox"]),
        -item["confidence"],
        -_area(item["bbox"]),
        item["zone_id"],
    )


def _generic_companion_is_safe(item: dict[str, Any]) -> bool:
    """Generic subjects are allowed only in ordinary, crop-safe support slots."""
    return (
        item["kind"] in MAJOR_KINDS
        and item["support_surface_id"] is not None
        and item["interaction"] in {"resting", "touching"}
        and item["occlusion_fraction"] <= 0.20
        and _frame_margin(item["full_bbox"]) >= 0.06
    )


def active_relations_for_slot_plan(
    graph: dict[str, Any],
    slot_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return only relations whose endpoints survive the resolved scene plan."""
    active_ids = {
        item["slot_id"]
        for item in slot_plan["slots"]
        if item["action"] != "remove"
    }
    return [
        copy.deepcopy(relation)
        for relation in graph["relations"]
        if relation["from_slot_id"] in active_ids
        and relation["to_slot_id"] in active_ids
    ]


def derive_scene_graph_capabilities(graph: dict[str, Any]) -> dict[str, Any]:
    validate_scene_graph(graph)
    major = [item for item in graph["objects"] if item["kind"] in MAJOR_KINDS]
    replacement_slots = [
        item
        for item in major
        if item["replaceable"]
        and item["crop_safe"]
        and item["interaction"] not in {"pouring"}
        and item["occlusion_fraction"] <= 0.45
    ]
    conservative_cross_kind = [
        item["slot_id"]
        for item in replacement_slots
        if item["interaction"] not in {"held", "pouring"}
        and item["occlusion_fraction"] <= 0.2
        and {"beverage", "dessert"}.issubset(set(item["allowed_kinds"]))
    ]
    safe_zones = _safe_insertion_zones(graph)
    primary = primary_scene_object(graph)
    default = next(
        (item["slot_id"] for item in replacement_slots if item["role"] == "primary"),
        replacement_slots[0]["slot_id"] if replacement_slots else None,
    )
    reasons = []
    inventory_complete = bool(graph.get("object_inventory_complete", True))
    if not inventory_complete:
        replacement_slots = []
        conservative_cross_kind = []
        safe_zones = []
        default = None
        reasons.append("incomplete_overflow_object_inventory")
    if not replacement_slots:
        reasons.append("no_crop_safe_replaceable_major_slot")
    observed_count = int(graph.get("observed_major_subject_count", len(major)))
    if observed_count > graph["runtime_policy"]["maximum_major_subjects"]:
        reasons.append("reference_set_requires_runtime_simplification")
    if graph["depth"]["far_plane_softness"] == "strong":
        reasons.append("far_plane_softness_must_be_clamped_for_smartphone_naturalness")
    return {
        "policy_version": "reference_scene_runtime_v2",
        "scene_generation_eligible": bool(replacement_slots) and inventory_complete,
        "default_target_slot_id": default,
        "primary_slot_id": primary["slot_id"],
        "replaceable_slot_ids": [item["slot_id"] for item in replacement_slots],
        "cross_kind_slot_ids": conservative_cross_kind,
        "safe_insertion_zone_ids": [zone["zone_id"] for zone in safe_zones],
        "requires_scene_simplification": observed_count
        > graph["runtime_policy"]["maximum_major_subjects"],
        "maximum_exact_products": graph["runtime_policy"]["maximum_exact_products"],
        "maximum_generic_companions": graph["runtime_policy"]["maximum_generic_companions"],
        "maximum_major_subjects": graph["runtime_policy"]["maximum_major_subjects"],
        "maximum_props": graph["runtime_policy"]["maximum_props"],
        "reason_codes": reasons,
    }


def resolve_slot_plan(
    graph: dict[str, Any],
    bindings: Iterable[dict[str, Any]],
    *,
    unbound_slot_policy: str = "genericize",
    maximum_exact_products: int | None = None,
) -> dict[str, Any]:
    """Atomically resolve one to three exact products and bounded generic companions.

    ``maximum_exact_products`` lets the v3 service apply its three-product limit even
    while older scene-graph sidecars still advertise a two-product runtime limit. The
    default deliberately preserves the v2 sidecar behavior.
    """
    validate_scene_graph(graph)
    if unbound_slot_policy not in {"genericize", "remove"}:
        raise ValueError(f"Unsupported unbound slot policy: {unbound_slot_policy}")
    capabilities = derive_scene_graph_capabilities(graph)
    object_by_id = {item["slot_id"]: item for item in graph["objects"]}
    zone_by_id = {item["zone_id"]: item for item in _safe_insertion_zones(graph)}
    normalized = [copy.deepcopy(item) for item in bindings]
    if not normalized:
        if capabilities["default_target_slot_id"] is None:
            raise ValueError("Scene graph has no default product slot")
        normalized = [
            {
                "input_product_id": "product_01",
                "target_slot_id": "auto",
                "placement_mode": "replace",
                "product_kind": "beverage",
                "cross_kind_replacement": False,
            }
        ]
    effective_maximum = (
        capabilities["maximum_exact_products"]
        if maximum_exact_products is None
        else maximum_exact_products
    )
    if not isinstance(effective_maximum, int) or not 1 <= effective_maximum <= 3:
        raise ValueError("maximum_exact_products must be between 1 and 3")
    if not 1 <= len(normalized) <= effective_maximum:
        raise ValueError("Slot plan exceeds the maximum exact user-product count")
    product_ids = [item["input_product_id"] for item in normalized]
    if any(not isinstance(value, str) or not value.strip() for value in product_ids):
        raise ValueError("Product IDs must be non-empty strings")
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("Product IDs must be unique")

    def candidate_ids(binding: dict[str, Any]) -> list[str]:
        mode = binding.get("placement_mode", "replace")
        product_kind = binding.get("product_kind", "beverage")
        if product_kind not in MAJOR_KINDS:
            raise ValueError(f"Unsupported product kind: {product_kind}")
        target_id = binding.get("target_slot_id", "auto")
        if mode not in {"replace", "add"}:
            raise ValueError(f"Unsupported placement mode: {mode}")
        if target_id != "auto":
            return [target_id]
        if mode == "replace":
            candidates = []
            for item in graph["objects"]:
                if item["slot_id"] not in capabilities["replaceable_slot_ids"]:
                    continue
                if product_kind not in item["allowed_kinds"]:
                    continue
                cross_kind = product_kind != item["kind"]
                if cross_kind and not binding.get("cross_kind_replacement", False):
                    continue
                if cross_kind and item["slot_id"] not in capabilities["cross_kind_slot_ids"]:
                    continue
                candidates.append(item)
            candidates.sort(
                key=lambda item: _replacement_candidate_key(
                    item,
                    product_kind=product_kind,
                )
            )
            return [item["slot_id"] for item in candidates]
        candidates = [
            item
            for item in zone_by_id.values()
            if product_kind in item["allowed_kinds"]
        ]
        candidates.sort(key=_insertion_candidate_key)
        return [item["zone_id"] for item in candidates]

    def validate_target(binding: dict[str, Any], target_id: str) -> dict[str, Any]:
        mode = binding.get("placement_mode", "replace")
        product_kind = binding.get("product_kind", "beverage")
        if mode == "replace":
            target = object_by_id.get(target_id)
            if target is None or target_id not in capabilities["replaceable_slot_ids"]:
                raise ValueError(f"Target slot is not replaceable: {target_id}")
            cross_kind = product_kind != target["kind"]
            if cross_kind and not binding.get("cross_kind_replacement", False):
                raise ValueError("Cross-kind replacement requires explicit opt-in")
            if product_kind not in target["allowed_kinds"]:
                raise ValueError(f"Target slot {target_id} does not allow {product_kind}")
            if cross_kind and target_id not in capabilities["cross_kind_slot_ids"]:
                raise ValueError(f"Target slot {target_id} is unsafe for cross-kind replacement")
            target_box = target["body_bbox"]
        else:
            target = zone_by_id.get(target_id)
            if target is None:
                raise ValueError(f"Insertion zone is not runtime-safe: {target_id}")
            if product_kind not in target["allowed_kinds"]:
                raise ValueError(f"Insertion zone {target_id} does not allow {product_kind}")
            target_box = target["bbox"]
        return {
            "input_product_id": binding["input_product_id"],
            "target_slot_id": target_id,
            "placement_mode": mode,
            "product_kind": product_kind,
            "cross_kind_replacement": bool(binding.get("cross_kind_replacement", False)),
            "target_bbox": copy.deepcopy(target_box),
        }

    candidate_matrix = [candidate_ids(binding) for binding in normalized]
    for binding, candidates in zip(normalized, candidate_matrix, strict=True):
        if not candidates:
            mode = binding.get("placement_mode", "replace")
            if binding.get("target_slot_id", "auto") == "auto":
                message = (
                    "Scene graph has no compatible automatic product slot"
                    if mode == "replace"
                    else "Scene graph has no runtime-safe compatible insertion zone"
                )
                raise ValueError(message)

    # Bind every product or none. With at most three products a deterministic
    # backtracking match is simpler and safer than a greedy fallback.
    assignments: list[str | None] = [None] * len(normalized)

    def assign(index: int, used: set[str]) -> bool:
        if index == len(normalized):
            return True
        for target_id in candidate_matrix[index]:
            if target_id in used:
                continue
            assignments[index] = target_id
            if assign(index + 1, used | {target_id}):
                return True
        assignments[index] = None
        return False

    if not assign(0, set()):
        raise ValueError("Products cannot be assigned to unique compatible slots atomically")

    resolved_bindings = [
        validate_target(binding, target_id)
        for binding, target_id in zip(normalized, assignments, strict=True)
        if target_id is not None
    ]
    bound_objects = {
        item["target_slot_id"]
        for item in resolved_bindings
        if item["placement_mode"] == "replace"
    }
    held_count = sum(
        object_by_id[item["target_slot_id"]]["interaction"] == "held"
        for item in resolved_bindings
        if item["placement_mode"] == "replace"
    )
    if held_count > 1:
        raise ValueError("A multi-product plan may contain at most one held exact product")

    requested_generic_limit = 0 if len(resolved_bindings) == 3 else 1
    companion_limit = min(
        capabilities["maximum_generic_companions"],
        requested_generic_limit,
        max(0, capabilities["maximum_major_subjects"] - len(resolved_bindings)),
    )
    companions = [
        item
        for item in graph["objects"]
        if item["slot_id"] not in bound_objects and _generic_companion_is_safe(item)
    ]
    companions.sort(key=_slot_sort_key)
    generic_ids = {
        item["slot_id"]
        for item in companions[:companion_limit]
        if unbound_slot_policy == "genericize"
    }
    slots = []
    for item in graph["objects"]:
        if item["slot_id"] in bound_objects:
            action = "bind_product"
        elif item["slot_id"] in generic_ids:
            action = "genericize"
        elif item["kind"] in MAJOR_KINDS:
            action = "remove"
        else:
            action = "retain_abstractly" if item["role"] == "accent" else "remove"
        slots.append(
            {
                "slot_id": item["slot_id"],
                "kind": item["kind"],
                "role": item["role"],
                "action": action,
                "target_bbox": copy.deepcopy(item["body_bbox"]),
                "support_surface_id": item["support_surface_id"],
                "depth_order": item["depth_order"],
                "runtime_appearance": copy.deepcopy(
                    item.get("runtime_appearance")
                ),
            }
        )
    plan = {
        "schema_version": "1.0.0",
        "reference_asset_id": graph["asset"]["asset_id"],
        "scene_mode": graph["scene_mode"],
        "bindings": resolved_bindings,
        "slots": slots,
        "active_slots": [
            copy.deepcopy(item) for item in slots if item["action"] != "remove"
        ],
        "unbound_slot_policy": unbound_slot_policy,
        "generic_companion_count": len(generic_ids),
        "generic_companion_limit": companion_limit,
        "safe_insertion_zone_ids": capabilities["safe_insertion_zone_ids"],
        "requires_scene_simplification": capabilities["requires_scene_simplification"],
    }
    plan["active_relations"] = active_relations_for_slot_plan(graph, plan)
    return plan


def adapt_scene_graph_to_reference_v1(
    graph: dict[str, Any],
    *,
    target_slot_id: str | None = None,
) -> dict[str, Any]:
    """Produce the legacy singleton contract without discarding the v2 sidecar."""
    validate_scene_graph(graph)
    explicit_anchor = target_slot_id is not None
    if target_slot_id is None:
        anchor = primary_scene_object(graph)
    else:
        anchor = next(
            (item for item in graph["objects"] if item["slot_id"] == target_slot_id),
            None,
        )
        if anchor is None:
            raise ValueError(f"Unknown scene-graph target slot: {target_slot_id}")
        if anchor["kind"] not in MAJOR_KINDS:
            raise ValueError("Legacy scene anchor must be a beverage or dessert slot")
    container = anchor["container"] or {
        "class": "plate" if anchor["kind"] == "dessert" else "unknown container",
        "material": "unknown",
        "silhouette": "the visible primary subject support",
        "components": [],
    }
    hand = next(
        (region["bbox"] for region in graph["protected_regions"] if region["kind"] == "hand"),
        None,
    )
    major_count = sum(item["kind"] in MAJOR_KINDS for item in graph["objects"])
    interaction = {
        "resting": "none",
        "held": "held",
        "touching": "touching",
        "pouring": "pouring",
    }.get(anchor["interaction"], "other")
    if major_count > 1 and not explicit_anchor:
        interaction = "group"
    primary_description = anchor["description"]
    if major_count > 1 and not explicit_anchor:
        primary_description = (
            f"group of {major_count} products including {anchor['description']}"
        )
    reference = {
        "schema_version": "1.0.0",
        "analysis_metadata": {
            **copy.deepcopy(graph["analysis_metadata"]),
            "prompt_version": "reference_analysis_v1",
        },
        "asset": copy.deepcopy(graph["asset"]),
        "subject": {
            "primary_subject": primary_description,
            "beverage": anchor["description"] if anchor["kind"] == "beverage" else "none",
            "container": copy.deepcopy(container),
            "interaction": interaction,
            "visible_text": list(
                dict.fromkeys(
                    text
                    for item in graph["objects"]
                    for text in item["visible_text"]
                )
            ),
            "brand_or_watermark_state": (
                "present"
                if any(item["brand_or_watermark_state"] == "present" for item in graph["objects"])
                else "uncertain"
                if any(item["brand_or_watermark_state"] == "uncertain" for item in graph["objects"])
                else "absent"
            ),
        },
        "geometry": {
            "container_bbox": copy.deepcopy(anchor["body_bbox"]),
            "subject_bbox": copy.deepcopy(anchor["full_bbox"]),
            "straw": copy.deepcopy(anchor["straw"]),
            "hand_bbox": copy.deepcopy(hand),
        },
        "composition": copy.deepcopy(graph["composition"]),
        "depth": copy.deepcopy(graph["depth"]),
        "lighting": copy.deepcopy(graph["lighting"]),
        "color": copy.deepcopy(graph["color"]),
        "facets": copy.deepcopy(graph["facets"]),
        "runtime_policy": {
            "scene_pixels_allowed": False,
            "container_pixels_allowed": True,
            "copy_exclusions": copy.deepcopy(graph["runtime_policy"]["copy_exclusions"]),
        },
        "quality_flags": list(
            dict.fromkeys([*graph["quality_flags"], "adapted_from_reference_scene_graph_v2"])
        ),
    }
    return reference


def bootstrap_single_subject_scene_graph(
    reference: dict[str, Any],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    """Conservatively promote a verified v1 singleton into the v2 sidecar format."""
    capabilities = derive_reference_capabilities(reference)
    subject = reference["subject"]
    composition = reference["composition"]
    if (
        not capabilities["scene_generation_eligible"]
        or capabilities["multiple_primary_products"]
        or subject["interaction"] == "group"
        or composition["shot_type"] in {"group", "overflow"}
    ):
        raise ValueError("Legacy reference is not a verified single-subject scene")

    kind = "beverage" if subject["beverage"].strip().lower() != "none" else "dessert"
    interaction = {
        "none": "resting",
        "held": "held",
        "touching": "touching",
        "pouring": "pouring",
        "other": "resting",
    }[subject["interaction"]]
    support_surface_id = None if interaction == "held" else "surface_primary"
    body_box = copy.deepcopy(reference["geometry"]["container_bbox"])
    full_box = copy.deepcopy(reference["geometry"]["subject_bbox"])
    if not _box_contains(full_box, body_box):
        full_box = {
            "left": min(full_box["left"], body_box["left"]),
            "top": min(full_box["top"], body_box["top"]),
            "right": max(full_box["right"], body_box["right"]),
            "bottom": max(full_box["bottom"], body_box["bottom"]),
            "confidence": min(
                float(full_box.get("confidence", 1.0)),
                float(body_box.get("confidence", 1.0)),
            ),
        }
    object_value = {
        "slot_id": f"{kind}_primary",
        "kind": kind,
        "role": "primary",
        "description": subject["primary_subject"],
        "body_bbox": body_box,
        "full_bbox": full_box,
        "straw": copy.deepcopy(reference["geometry"]["straw"]),
        "container": copy.deepcopy(subject["container"]) if kind == "beverage" else None,
        "interaction": interaction,
        "support_surface_id": support_surface_id,
        "depth_order": 1,
        "occlusion_fraction": 0.08 if interaction in {"held", "touching"} else 0.0,
        "replaceable": interaction != "pouring",
        "allowed_kinds": [kind],
        "visible_text": copy.deepcopy(subject["visible_text"]),
        "brand_or_watermark_state": subject["brand_or_watermark_state"],
        "crop_safe": (
            body_box["left"] >= 0.03
            and body_box["right"] <= 0.97
            and body_box["top"] >= 0.03
            and body_box["bottom"] <= 0.97
        ),
    }
    support_surfaces = []
    if support_surface_id is not None:
        top = round(max(0.0, min(0.82, body_box["top"] - 0.12)), 3)
        support_surfaces.append(
            {
                "surface_id": support_surface_id,
                "kind": "table",
                "bbox": {
                    "left": 0.0,
                    "top": top,
                    "right": 1.0,
                    "bottom": 1.0,
                    "confidence": 0.62,
                },
                "plane_description": reference["depth"]["product_plane"],
                "supports_objects": True,
                "perspective_scale": [0.7, 1.2],
            }
        )
    protected_regions = []
    hand_box = reference["geometry"]["hand_bbox"]
    if hand_box is not None:
        protected_regions.append(
            {
                "region_id": "region_hand",
                "kind": "hand",
                "bbox": copy.deepcopy(hand_box),
                "reason": "retain only the reference-derived hand interaction footprint",
            }
        )
    normalized_taxonomy = copy.deepcopy(taxonomy)
    normalized_taxonomy["scene_complexity"] = "solo"
    normalized_taxonomy["confidence"] = min(
        float(normalized_taxonomy["confidence"]),
        0.72,
    )
    graph = {
        "schema_version": "2.0.0",
        "analysis_metadata": {
            "provider": "local_v1_bootstrap",
            "model": "deterministic_adapter",
            "prompt_version": "reference_scene_graph_v2",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.68,
        },
        "asset": copy.deepcopy(reference["asset"]),
        "scene_mode": "solo",
        "objects": [object_value],
        "relations": [],
        "support_surfaces": support_surfaces,
        "protected_regions": protected_regions,
        "insertion_zones": [],
        "composition": copy.deepcopy(composition),
        "depth": copy.deepcopy(reference["depth"]),
        "lighting": copy.deepcopy(reference["lighting"]),
        "color": copy.deepcopy(reference["color"]),
        "facets": copy.deepcopy(reference["facets"]),
        "taxonomy": normalized_taxonomy,
        "runtime_policy": {
            "scene_pixels_allowed": False,
            "container_pixels_allowed": True,
            "copy_exclusions": [
                "exact reference product identity and branding",
                "exact prop arrangement and shadow silhouette",
            ],
            "maximum_exact_products": 2,
            "maximum_generic_companions": 1,
            "maximum_major_subjects": 3,
            "maximum_props": 2,
        },
        "quality_flags": [
            "bootstrapped_from_v1_single_subject",
            "no_empty_insertion_zones_without_v2_visual_analysis",
        ],
    }
    validate_scene_graph(graph)
    return graph
