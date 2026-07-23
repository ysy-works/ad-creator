from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .image_contracts import canonical_image_binding
from .lighting_contracts import (
    DEFAULT_DIFFUSE_WHITE_BASE,
    DEFAULT_DIRECT_WHITE_BASE,
    DELTA_LIMITS,
    ReferenceLightingDelta,
    validate_reference_lighting_delta,
)


BACKFILL_SCHEMA_VERSION = "1.0.0"
TARGET_ANALYSIS_SCHEMA_VERSION = "3.0.0"
DEFAULT_LOCAL_ANALYZER_VERSION = "reference_analysis_v3_local_backfill_v1"
RECORD_STATUSES = frozenset({"draft", "needs_review"})

CLUSTER_FAMILY_NAMES = {
    "direct_sun_neutral_candid_v1": "white_direct",
    "soft_diffuse_neutral_candid_v1": "white_diffuse",
    "warm_wood_soft_window_v1": "wood",
    "modern_mineral_neutral_v1": "modern_mineral",
    "point_color_daylight_v1": "point_color",
    "sun_washed_vintage_table_v1": "vintage",
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    values: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            values.append(value)
    return values


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object at {path}")
    return value


def canonical_inventory_rows(
    inventory: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    canonical: list[dict[str, Any]] = []
    duplicates = 0
    seen_ids: set[str] = set()
    for raw in inventory:
        asset_id = str(raw.get("asset_id", ""))
        if not asset_id:
            raise ValueError("Inventory row is missing asset_id")
        if asset_id in seen_ids:
            raise ValueError(f"Inventory contains duplicate asset_id {asset_id!r}")
        seen_ids.add(asset_id)
        if raw.get("duplicate_of"):
            duplicates += 1
            continue
        pixel_hash = str(raw.get("pixel_sha256", ""))
        if not _is_sha256(pixel_hash):
            raise ValueError(f"Inventory asset {asset_id} has invalid pixel_sha256")
        relative_path = str(raw.get("relative_path", ""))
        if not relative_path:
            raise ValueError(f"Inventory asset {asset_id} is missing relative_path")
        canonical.append(dict(raw))
    canonical.sort(key=lambda item: str(item["asset_id"]))
    return canonical, duplicates


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite_number(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _normalized_folder_text(asset: Mapping[str, Any]) -> str:
    fragments = [str(asset.get("relative_path", ""))]
    tags = asset.get("source_folder_tags", [])
    if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes)):
        fragments.extend(str(value) for value in tags)
    return unicodedata.normalize("NFC", " ".join(fragments)).casefold()


def infer_cluster_from_local_inputs(asset: Mapping[str, Any]) -> str:
    """Conservative folder/metric fallback for an absent assignment.

    It deliberately returns only an existing operational mood family and never
    asserts that semantic scene analysis has happened.
    """

    text = _normalized_folder_text(asset)
    metrics = asset.get("local_color_metrics", {})
    metrics = metrics if isinstance(metrics, Mapping) else {}
    luminance = _finite_number(metrics.get("mean_luminance"), default=0.5)
    saturation = _finite_number(metrics.get("mean_saturation"), default=0.0)
    if any(term in text for term in ("직사", "direct sun", "direct_sun")):
        return "direct_sun_neutral_candid_v1"
    if any(term in text for term in ("우드", "wood", "timber")):
        return "warm_wood_soft_window_v1"
    if any(term in text for term in ("빈티지", "vintage", "retro")):
        return "sun_washed_vintage_table_v1"
    if any(term in text for term in ("포인트", "point color", "채도대비")):
        return "point_color_daylight_v1"
    if any(term in text for term in ("모던", "금속", "modern", "metal")):
        return "modern_mineral_neutral_v1"
    if saturation >= 0.24:
        return "point_color_daylight_v1"
    if luminance >= 0.50 and saturation <= 0.18:
        return "soft_diffuse_neutral_candid_v1"
    return "soft_diffuse_neutral_candid_v1"


def _safe_color_metrics(asset: Mapping[str, Any]) -> dict[str, Any]:
    raw = asset.get("local_color_metrics", {})
    raw = raw if isinstance(raw, Mapping) else {}
    palette = raw.get("palette_hex", [])
    if not isinstance(palette, Sequence) or isinstance(palette, (str, bytes)):
        palette = []
    safe_palette = [
        str(value).upper()
        for value in palette
        if isinstance(value, str)
        and len(value) == 7
        and value.startswith("#")
        and all(character in "0123456789abcdefABCDEF" for character in value[1:])
    ]
    values = {
        "mean_luminance": round(
            _clamp(_finite_number(raw.get("mean_luminance"), default=0.5), 0, 1),
            6,
        ),
        "luminance_stddev": round(
            _clamp(_finite_number(raw.get("luminance_stddev"), default=0.0), 0, 1),
            6,
        ),
        "mean_saturation": round(
            _clamp(_finite_number(raw.get("mean_saturation"), default=0.0), 0, 1),
            6,
        ),
        "edge_energy": round(
            _clamp(_finite_number(raw.get("edge_energy"), default=0.0), 0, 1),
            6,
        ),
        "palette_hex": safe_palette,
    }
    values["metric_source"] = "inventory_local_color_metrics"
    return values


def _palette_warmth_mired_delta(palette: Sequence[str]) -> float:
    channels: list[tuple[int, int]] = []
    for value in palette:
        try:
            channels.append((int(value[1:3], 16), int(value[5:7], 16)))
        except (ValueError, IndexError):
            continue
    if not channels:
        return 0.0
    red_minus_blue = sum(red - blue for red, blue in channels) / len(channels)
    return _clamp((red_minus_blue / 255.0) * 20.0, -20.0, 20.0)


def build_safe_lighting_delta(
    *,
    asset_id: str,
    source_pixel_sha256: str,
    cluster_id: str,
    color_metrics: Mapping[str, Any],
    scene_graph: Mapping[str, Any] | None,
) -> dict[str, Any]:
    graph_lighting = scene_graph.get("lighting", {}) if scene_graph else {}
    graph_lighting = graph_lighting if isinstance(graph_lighting, Mapping) else {}
    graph_source = str(graph_lighting.get("source_type", ""))
    direct = cluster_id == "direct_sun_neutral_candid_v1" or graph_source == "direct_sun"
    base = DEFAULT_DIRECT_WHITE_BASE if direct else DEFAULT_DIFFUSE_WHITE_BASE

    luminance = _finite_number(color_metrics.get("mean_luminance"), default=0.5)
    deviation = _finite_number(color_metrics.get("luminance_stddev"), default=0.0)
    edge_energy = _finite_number(color_metrics.get("edge_energy"), default=0.0)
    observed_hardness = graph_lighting.get("hardness")
    if observed_hardness is None:
        hardness_delta = (edge_energy - 0.05) * 0.75 + (deviation - 0.30) * 0.20
    else:
        hardness_delta = _finite_number(observed_hardness) - base.hardness
    hardness_delta = _clamp(hardness_delta, -DELTA_LIMITS["hardness"], DELTA_LIMITS["hardness"])

    shadow_density_delta = (0.50 - luminance) * 0.20 + (deviation - 0.35) * 0.10
    shadow_density_delta = _clamp(
        shadow_density_delta,
        -DELTA_LIMITS["shadow_density"],
        DELTA_LIMITS["shadow_density"],
    )
    exposure_delta = _clamp(
        (luminance - 0.55) * 0.40,
        -DELTA_LIMITS["exposure_ev"],
        DELTA_LIMITS["exposure_ev"],
    )
    palette = color_metrics.get("palette_hex", [])
    palette = palette if isinstance(palette, Sequence) else []
    white_balance_delta = _palette_warmth_mired_delta(palette)
    categorical_white_balance = str(graph_lighting.get("white_balance", ""))
    if categorical_white_balance == "warm":
        white_balance_delta = max(white_balance_delta, 10.0)
    elif categorical_white_balance == "cool":
        white_balance_delta = min(white_balance_delta, -10.0)

    graph_confidence = _finite_number(
        (scene_graph or {}).get("analysis_metadata", {}).get("confidence"),
        default=0.0,
    )
    confidence = _clamp(graph_confidence * 0.75, 0.0, 0.75) if scene_graph else 0.35
    delta = ReferenceLightingDelta(
        reference_id=asset_id,
        base_id=base.base_id,
        direction_delta_degrees=0.0,
        elevation_delta_degrees=0.0,
        hardness_delta=round(hardness_delta, 6),
        shadow_density_delta=round(shadow_density_delta, 6),
        exposure_delta_ev=round(exposure_delta, 6),
        white_balance_delta_mired=round(
            _clamp(
                white_balance_delta,
                -DELTA_LIMITS["white_balance_mired"],
                DELTA_LIMITS["white_balance_mired"],
            ),
            6,
        ),
        confidence=round(confidence, 6),
        source_pixel_sha256=source_pixel_sha256,
    )
    validate_reference_lighting_delta(delta, require_policy_bounds=True)
    value = delta.to_dict()
    value.update(
        {
            "status": "local_estimate",
            "family": base.family,
            "base_hash": base.base_hash,
            "inference": {
                "direction": "not_inferred_zero_delta",
                "elevation": "not_inferred_zero_delta",
                "photometric_source": (
                    "reused_scene_graph_plus_local_metrics"
                    if scene_graph
                    else "local_color_metrics_only"
                ),
                "policy_bounds": {
                    key: float(value) for key, value in DELTA_LIMITS.items()
                },
            },
        }
    )
    return value


def _scene_graph_index(
    values: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        asset = value.get("asset", {})
        if not isinstance(asset, Mapping) or not asset.get("asset_id"):
            continue
        asset_id = str(asset["asset_id"])
        if asset_id in result:
            raise ValueError(f"Scene Graph catalog contains duplicate {asset_id!r}")
        result[asset_id] = dict(value)
    return result


def _assignment_snapshot(
    asset: Mapping[str, Any], assignment: Mapping[str, Any] | None
) -> dict[str, Any]:
    assignment = assignment if isinstance(assignment, Mapping) else {}
    cluster_id = str(assignment.get("cluster_id") or infer_cluster_from_local_inputs(asset))
    taxonomy = assignment.get("taxonomy", {})
    taxonomy = dict(taxonomy) if isinstance(taxonomy, Mapping) else {}
    confidence = _clamp(
        _finite_number(assignment.get("confidence"), default=0.35), 0.0, 1.0
    )
    return {
        "cluster_id": cluster_id,
        "mood_family": CLUSTER_FAMILY_NAMES.get(cluster_id, "other"),
        "mood_package_path": assignment.get("mood_package_path"),
        "taxonomy": taxonomy,
        "confidence": round(confidence, 6),
        "source": (
            "assignment_snapshot_local_folder_and_metrics"
            if assignment
            else "local_folder_and_metrics_fallback"
        ),
        "evidence": list(assignment.get("evidence", []))
        if isinstance(assignment.get("evidence", []), list)
        else [],
    }


def _source_binding(asset: Mapping[str, Any], reference_root: Path) -> dict[str, Any]:
    expected = str(asset["pixel_sha256"])
    source_path = reference_root / str(asset["relative_path"])
    if not source_path.is_file():
        return {
            "expected_pixel_sha256": expected,
            "observed_pixel_sha256": None,
            "hash_status": "missing",
            "width_px": None,
            "height_px": None,
        }
    try:
        observed = canonical_image_binding(source_path)
    except (OSError, ValueError):
        return {
            "expected_pixel_sha256": expected,
            "observed_pixel_sha256": None,
            "hash_status": "unreadable",
            "width_px": None,
            "height_px": None,
        }
    observed_hash = str(observed["pixel_sha256"])
    return {
        "expected_pixel_sha256": expected,
        "observed_pixel_sha256": observed_hash,
        "hash_status": "matched" if observed_hash == expected else "mismatch",
        "width_px": observed["width_px"],
        "height_px": observed["height_px"],
    }


def _cache_key(
    *,
    analyzer_version: str,
    asset: Mapping[str, Any],
    binding: Mapping[str, Any],
    mood: Mapping[str, Any],
    scene_graph: Mapping[str, Any] | None,
) -> str:
    return canonical_hash(
        {
            "backfill_schema_version": BACKFILL_SCHEMA_VERSION,
            "target_analysis_schema_version": TARGET_ANALYSIS_SCHEMA_VERSION,
            "analyzer_version": analyzer_version,
            "asset": {
                "asset_id": asset["asset_id"],
                "relative_path": asset["relative_path"],
                "expected_pixel_sha256": asset["pixel_sha256"],
                "observed_pixel_sha256": binding.get("observed_pixel_sha256"),
                "hash_status": binding.get("hash_status"),
                "local_color_metrics": asset.get("local_color_metrics"),
                "source_folder_tags": asset.get("source_folder_tags"),
            },
            "mood": mood,
            "scene_graph_hash": canonical_hash(scene_graph) if scene_graph else None,
        }
    )


def _with_record_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("record_hash", None)
    result["record_hash"] = canonical_hash(result)
    return result


def validate_local_backfill_record(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != BACKFILL_SCHEMA_VERSION:
        raise ValueError("Unsupported local backfill record schema")
    if value.get("target_analysis_schema_version") != TARGET_ANALYSIS_SCHEMA_VERSION:
        raise ValueError("Local backfill record targets the wrong analysis schema")
    if value.get("status") not in RECORD_STATUSES:
        raise ValueError("Local backfill record has an unsafe status")
    if value.get("paid_services_allowed") is not False:
        raise ValueError("Local backfill must never allow paid services")
    if value.get("network_calls_allowed") is not False:
        raise ValueError("Local backfill must never allow network calls")
    asset = value.get("asset", {})
    if not isinstance(asset, Mapping) or not asset.get("asset_id"):
        raise ValueError("Local backfill record has no asset")
    binding = value.get("source_binding", {})
    if not isinstance(binding, Mapping):
        raise ValueError("Local backfill record has no source binding")
    if not _is_sha256(binding.get("expected_pixel_sha256")):
        raise ValueError("Local backfill record has an invalid expected pixel hash")
    validate_reference_lighting_delta(
        value.get("lighting_delta", {}), require_policy_bounds=True
    )
    expected_record_hash = value.get("record_hash")
    without_hash = dict(value)
    without_hash.pop("record_hash", None)
    if expected_record_hash != canonical_hash(without_hash):
        raise ValueError("Local backfill record hash mismatch")


def build_local_backfill_record(
    asset: Mapping[str, Any],
    *,
    reference_root: Path,
    analyzer_version: str,
    assignment: Mapping[str, Any] | None,
    scene_graph: Mapping[str, Any] | None,
) -> dict[str, Any]:
    asset_id = str(asset["asset_id"])
    binding = _source_binding(asset, reference_root)
    observed_hash = binding.get("observed_pixel_sha256")
    effective_source_hash = (
        str(observed_hash) if _is_sha256(observed_hash) else str(asset["pixel_sha256"])
    )
    mood = _assignment_snapshot(asset, assignment)
    prior_status = str((assignment or {}).get("analysis_status", "pending_analysis"))
    graph_source_hash = (
        str((scene_graph or {}).get("asset", {}).get("pixel_sha256", ""))
        if scene_graph
        else ""
    )
    graph_reusable = (
        prior_status == "analyzed"
        and scene_graph is not None
        and binding["hash_status"] == "matched"
        and graph_source_hash == asset["pixel_sha256"]
    )
    review_reasons = ["independent_ocr_incomplete", "brand_surface_observation_incomplete"]
    if binding["hash_status"] != "matched":
        review_reasons.append(f"source_pixels_{binding['hash_status']}")
    if not graph_reusable:
        review_reasons.extend(
            ["scene_graph_incomplete", "semantic_object_inventory_incomplete"]
        )
    if mood["mood_family"] == "wood":
        review_reasons.append("wood_surface_mask_and_profile_incomplete")
    status = "draft" if graph_reusable else "needs_review"
    color_metrics = _safe_color_metrics(asset)
    lighting = build_safe_lighting_delta(
        asset_id=asset_id,
        source_pixel_sha256=effective_source_hash,
        cluster_id=str(mood["cluster_id"]),
        color_metrics=color_metrics,
        scene_graph=scene_graph if graph_reusable else None,
    )
    cache_key = _cache_key(
        analyzer_version=analyzer_version,
        asset=asset,
        binding=binding,
        mood=mood,
        scene_graph=scene_graph if graph_reusable else None,
    )
    record = {
        "schema_version": BACKFILL_SCHEMA_VERSION,
        "target_analysis_schema_version": TARGET_ANALYSIS_SCHEMA_VERSION,
        "status": status,
        "analysis_origin": (
            "existing_analysis_reused" if graph_reusable else "local_metrics_draft"
        ),
        "analyzer_version": analyzer_version,
        "analysis_cache_key": cache_key,
        "paid_services_allowed": False,
        "network_calls_allowed": False,
        "asset": {
            "asset_id": asset_id,
            "relative_path": str(asset["relative_path"]),
            "width_px": asset.get("width_px"),
            "height_px": asset.get("height_px"),
        },
        "source_binding": binding,
        "prior_analysis": {
            "status": prior_status,
            "reused": graph_reusable,
            "scene_graph_hash": canonical_hash(scene_graph) if graph_reusable else None,
        },
        "mood": mood,
        "color_metrics": color_metrics,
        "lighting_delta": lighting,
        "components": {
            "scene_graph": {
                "status": "reused" if graph_reusable else "incomplete",
                "source_pixel_sha256": graph_source_hash or None,
            },
            "independent_ocr": {
                "status": "incomplete",
                "required_before_publication": True,
            },
            "brand_surfaces": {
                "status": "incomplete",
                "required_before_publication": True,
            },
            "wood_material": {
                "status": "incomplete"
                if mood["mood_family"] == "wood"
                else "not_applicable_from_taxonomy",
                "required_before_publication": mood["mood_family"] == "wood",
            },
        },
        "review_reasons": sorted(set(review_reasons)),
        "publication_gate": {
            "status": "blocked",
            "reason": "local backfill is non-authoritative draft evidence",
        },
    }
    result = _with_record_hash(record)
    validate_local_backfill_record(result)
    return result


def _valid_existing_by_id(
    existing: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], int]:
    result: dict[str, dict[str, Any]] = {}
    invalid = 0
    for item in existing:
        try:
            validate_local_backfill_record(item)
            asset_id = str(item["asset"]["asset_id"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        result[asset_id] = dict(item)
    return result, invalid


def build_local_backfill(
    assets: Iterable[Mapping[str, Any]],
    *,
    reference_root: Path,
    assignments: Mapping[str, Any],
    scene_graphs: Iterable[Mapping[str, Any]],
    analyzer_version: str = DEFAULT_LOCAL_ANALYZER_VERSION,
    existing_records: Iterable[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    graph_index = _scene_graph_index(scene_graphs)
    existing_by_id, invalid_existing = _valid_existing_by_id(existing_records)
    records: list[dict[str, Any]] = []
    cache_reused = 0
    cache_invalidated = 0
    for asset in assets:
        asset_id = str(asset["asset_id"])
        candidate = build_local_backfill_record(
            asset,
            reference_root=reference_root,
            analyzer_version=analyzer_version,
            assignment=assignments.get(asset_id),
            scene_graph=graph_index.get(asset_id),
        )
        existing = existing_by_id.get(asset_id)
        if existing and existing.get("analysis_cache_key") == candidate["analysis_cache_key"]:
            records.append(existing)
            cache_reused += 1
        else:
            records.append(candidate)
            if existing:
                cache_invalidated += 1
    records.sort(key=lambda value: str(value["asset"]["asset_id"]))
    return records, {
        "cache_reused_count": cache_reused,
        "cache_new_count": len(records) - cache_reused,
        "cache_invalidated_count": cache_invalidated,
        "ignored_invalid_cache_count": invalid_existing,
    }


def build_mood_family_summary(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        cluster_id = str(record.get("mood", {}).get("cluster_id", "unknown"))
        grouped.setdefault(cluster_id, []).append(record)
    result: dict[str, dict[str, Any]] = {}
    for cluster_id, values in sorted(grouped.items()):
        result[cluster_id] = {
            "mood_family": values[0].get("mood", {}).get("mood_family", "other"),
            "canonical_count": len(values),
            "existing_analysis_reused_count": sum(
                value.get("analysis_origin") == "existing_analysis_reused"
                for value in values
            ),
            "local_metrics_draft_count": sum(
                value.get("analysis_origin") == "local_metrics_draft"
                for value in values
            ),
            "status_counts": dict(
                sorted(Counter(str(value.get("status")) for value in values).items())
            ),
            "lighting_family_counts": dict(
                sorted(
                    Counter(
                        str(value.get("lighting_delta", {}).get("family", "unknown"))
                        for value in values
                    ).items()
                )
            ),
        }
    return result


def jsonl_bytes(records: Iterable[Mapping[str, Any]]) -> bytes:
    return "".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
        for value in records
    ).encode("utf-8")


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_atomic_checkpoint(
    *,
    output_path: Path,
    manifest_path: Path,
    records: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    output_payload = jsonl_bytes(records)
    output_sha256 = hashlib.sha256(output_payload).hexdigest()
    final_manifest = {
        **manifest,
        "checkpoint": {
            "atomic_replace": True,
            "record_count": len(records),
            "output_sha256": output_sha256,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_payload = (
        json.dumps(final_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_replace_bytes(output_path, output_payload)
    _atomic_replace_bytes(manifest_path, manifest_payload)
    return final_manifest


def build_manifest(
    *,
    records: Sequence[Mapping[str, Any]],
    analyzer_version: str,
    duplicate_count: int,
    cache_counters: Mapping[str, int],
    inventory_input_hash: str,
    assignments_input_hash: str,
    scene_graph_input_hash: str,
) -> dict[str, Any]:
    status_counts = Counter(str(value["status"]) for value in records)
    origins = Counter(str(value["analysis_origin"]) for value in records)
    source_hash_statuses = Counter(
        str(value["source_binding"]["hash_status"]) for value in records
    )
    return {
        "schema_version": BACKFILL_SCHEMA_VERSION,
        "target_analysis_schema_version": TARGET_ANALYSIS_SCHEMA_VERSION,
        "status": "draft",
        "analyzer_version": analyzer_version,
        "canonical_count": len(records),
        "duplicate_excluded_count": duplicate_count,
        "existing_analysis_reused_count": origins["existing_analysis_reused"],
        "local_metrics_draft_count": origins["local_metrics_draft"],
        "status_counts": dict(sorted(status_counts.items())),
        "source_hash_status_counts": dict(sorted(source_hash_statuses.items())),
        "mood_families": build_mood_family_summary(records),
        "cache": dict(cache_counters),
        "input_hashes": {
            "inventory": inventory_input_hash,
            "assignments": assignments_input_hash,
            "scene_graphs": scene_graph_input_hash,
        },
        "paid_call_count": 0,
        "network_call_count": 0,
        "publication_gate": {
            "status": "blocked",
            "requirements": [
                "independent OCR evidence is complete",
                "Scene Graph is complete for every reference",
                "brand-surface observations are reviewed",
                "wood candidates have reviewed original-resolution masks and profiles",
                "contact-sheet review is recorded",
            ],
        },
    }
