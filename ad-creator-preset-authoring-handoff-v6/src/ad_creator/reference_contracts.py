from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .jsonio import load_json
from .lighting_contracts import ResolvedLightingContract
from .reference_catalog import load_reference_scene_graph
from .scene_graph import validate_scene_graph
from .surface_styles import SurfaceStyleProfile, validate_surface_style_profile
from .wood_materials import WoodMaterialProfile, validate_wood_material_profile


REFERENCE_ANALYSIS_V3_SCHEMA_VERSION = "3.0.0"
DEFAULT_LIGHTING_BASE_PATHS = {
    "white_direct_base_v1": "presets/lighting/white-direct-base-v1.json",
    "white_diffuse_base_v1": "presets/lighting/white-diffuse-base-v1.json",
}


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _catalog_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_dir():
        values = []
        for item in sorted(path.glob("*.json")):
            value = load_json(item)
            values.append(value)
        return values
    if path.suffix == ".jsonl":
        values = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSONL in {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise ValueError(f"Reference contract row must be an object: {path}")
            values.append(value)
        return values
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        values = payload["records"]
    elif isinstance(payload, dict):
        values = [payload]
    else:
        raise ValueError(f"Reference contract catalog must contain objects: {path}")
    if any(not isinstance(item, dict) for item in values):
        raise ValueError(f"Reference contract catalog rows must be objects: {path}")
    return values


def _record_reference_id(value: Mapping[str, Any]) -> str | None:
    for key in ("reference_id", "asset_id", "source_reference_id"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    asset = value.get("asset")
    if isinstance(asset, Mapping):
        candidate = asset.get("asset_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _lookup_component(
    catalog_path: Path | None,
    reference_id: str,
    *,
    wrapper_keys: Sequence[str],
) -> dict[str, Any] | None:
    if catalog_path is None:
        return None
    matches = [
        item
        for item in _catalog_records(catalog_path)
        if _record_reference_id(item) == reference_id
    ]
    if len(matches) > 1:
        raise ValueError(
            f"Reference contract catalog has duplicate rows for {reference_id}: {catalog_path}"
        )
    if not matches:
        return None
    value = matches[0]
    for key in wrapper_keys:
        wrapped = value.get(key)
        if isinstance(wrapped, Mapping):
            return copy.deepcopy(dict(wrapped))
    result = copy.deepcopy(value)
    for key in ("reference_id", "asset_id", "source_reference_id"):
        result.pop(key, None)
    return result


def lookup_reference_analysis_v3_sources(
    *,
    project_root: str | Path,
    reference_id: str,
    scene_graph_catalog_path: str | Path = (
        "data/reference-library/scene-graphs-v2.jsonl"
    ),
    lighting_delta_catalog_path: str | Path | None = (
        "data/reference-library/lighting-deltas-v3.jsonl"
    ),
    wood_profile_catalog_path: str | Path | None = (
        "data/reference-library/wood-material-profiles-v3.jsonl"
    ),
    lighting_base_paths: Mapping[str, str | Path] = DEFAULT_LIGHTING_BASE_PATHS,
) -> dict[str, Any]:
    """Resolve scene/light/material source contracts by stable reference ID.

    Missing optional delta/profile catalogs remain explicit misses; no material values
    are inferred or synthesized. A missing Scene Graph is fatal because layout cannot
    be resolved atomically without it.
    """

    if not isinstance(reference_id, str) or not reference_id.strip():
        raise ValueError("reference_id must be a non-empty string")
    root = Path(project_root).expanduser().resolve()
    scene_path = _resolve_path(root, scene_graph_catalog_path)
    scene_graph = load_reference_scene_graph(scene_path, reference_id)
    if scene_graph is None:
        raise FileNotFoundError(
            f"Reference {reference_id} has no Scene Graph in {scene_path}"
        )
    delta_path = (
        _resolve_path(root, lighting_delta_catalog_path)
        if lighting_delta_catalog_path is not None
        else None
    )
    wood_path = (
        _resolve_path(root, wood_profile_catalog_path)
        if wood_profile_catalog_path is not None
        else None
    )
    lighting_delta = _lookup_component(
        delta_path,
        reference_id,
        wrapper_keys=("lighting_delta", "delta_contract"),
    )
    wood_profile = _lookup_component(
        wood_path,
        reference_id,
        wrapper_keys=("wood_material_profile", "profile"),
    )
    lighting_base = None
    if lighting_delta is not None:
        base_id = lighting_delta.get("base_id")
        base_path_value = lighting_base_paths.get(str(base_id))
        if base_path_value is None:
            raise ValueError(
                f"Lighting delta for {reference_id} names unknown base_id {base_id!r}"
            )
        lighting_base = load_json(_resolve_path(root, base_path_value))
    return {
        "reference_id": reference_id,
        "scene_graph": scene_graph,
        "lighting_base": lighting_base,
        "lighting_delta": lighting_delta,
        "wood_material_profile": wood_profile,
        "catalog_hits": {
            "scene_graph": True,
            "lighting_delta": lighting_delta is not None,
            "wood_material_profile": wood_profile is not None,
        },
    }


def _normalized_material_family(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.casefold()
    for family, tokens in {
        "glass": ("glass", "crystal"),
        "plastic": ("plastic", "pet", "acrylic"),
        "paper": ("paper", "cardboard"),
        "ceramic": ("ceramic", "porcelain", "stoneware", "earthenware"),
        "metal": ("metal", "steel", "aluminum", "aluminium"),
        "wood": ("wood", "timber"),
        "stone": ("stone", "marble", "granite"),
        "fabric": ("fabric", "cloth", "textile"),
    }.items():
        if any(token in normalized for token in tokens):
            return family
    return None


def derive_reference_brand_observation(
    scene_object: Mapping[str, Any],
) -> dict[str, Any]:
    """Return compatibility evidence without ever returning reference brand text."""

    explicit = scene_object.get("brand_surface_observation")
    explicit = dict(explicit) if isinstance(explicit, Mapping) else {}
    legacy_state = scene_object.get("brand_or_watermark_state")
    state = explicit.get("state") or {
        "present": "verified_present",
        "absent": "verified_absent",
        "uncertain": "uncertain",
    }.get(legacy_state, "uncertain")
    if state not in {"verified_present", "verified_absent", "uncertain"}:
        state = "uncertain"

    container = scene_object.get("container")
    container = container if isinstance(container, Mapping) else {}
    confidence = explicit.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = 1.0 if state == "verified_absent" else 0.0
    confidence = max(0.0, min(1.0, float(confidence)))
    if state != "verified_present":
        return {
            "state": state,
            "material_family": None,
            "application_medium": None,
            "carrier_component": None,
            "surface_allowed": False,
            "confidence": confidence,
        }

    return {
        "state": "verified_present",
        "material_family": explicit.get("material_family")
        or _normalized_material_family(container.get("material")),
        "application_medium": explicit.get("application_medium"),
        "carrier_component": explicit.get("carrier_component"),
        "surface_allowed": explicit.get("surface_allowed", False),
        "confidence": confidence,
    }


def reference_brand_observations(scene_graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_scene_graph(dict(scene_graph))
    return [
        {
            "slot_id": item["slot_id"],
            **derive_reference_brand_observation(item),
        }
        for item in scene_graph["objects"]
    ]


def assemble_reference_analysis_v3(
    *,
    scene_graph: Mapping[str, Any],
    resolved_lighting: ResolvedLightingContract | Mapping[str, Any] | None = None,
    wood_profiles: Sequence[WoodMaterialProfile | Mapping[str, Any]] = (),
    surface_style_profiles: Sequence[SurfaceStyleProfile | Mapping[str, Any]] = (),
    status: str = "draft",
    analyzer_version: str = "reference_analysis_v3_unified_v1",
    publication_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble scene, lighting, material and brand evidence into one cacheable sidecar."""

    graph = copy.deepcopy(dict(scene_graph))
    validate_scene_graph(graph)
    if status not in {"draft", "published"}:
        raise ValueError("ReferenceAnalysisV3 status must be draft or published")
    evidence = {
        "schema_validated": False,
        "hash_validated": False,
        "contact_sheet_reviewed": False,
        **(dict(publication_evidence) if publication_evidence is not None else {}),
    }
    if any(not isinstance(value, bool) for value in evidence.values()) or set(evidence) != {
        "schema_validated",
        "hash_validated",
        "contact_sheet_reviewed",
    }:
        raise ValueError("ReferenceAnalysisV3 publication evidence is invalid")
    if status == "published" and not all(evidence.values()):
        raise ValueError(
            "ReferenceAnalysisV3 can be published only after schema, hash and contact-sheet review"
        )
    if isinstance(resolved_lighting, ResolvedLightingContract):
        lighting = resolved_lighting.to_dict()
    elif isinstance(resolved_lighting, Mapping):
        lighting = copy.deepcopy(dict(resolved_lighting))
    else:
        lighting = None
    if lighting is not None:
        if lighting.get("reference_id") != graph["asset"]["asset_id"]:
            raise ValueError("Resolved lighting belongs to a different reference ID")
        lighting_source_hash = lighting.get("source_pixel_sha256")
        if lighting_source_hash is not None and (
            lighting_source_hash != graph["asset"]["pixel_sha256"]
        ):
            raise ValueError("Resolved lighting source hash does not match the Scene Graph")
        if status == "published" and lighting_source_hash is None:
            raise ValueError("Published resolved lighting requires a source pixel hash")
    validated_profiles = [validate_wood_material_profile(item) for item in wood_profiles]
    for profile in validated_profiles:
        if profile.source_pixel_sha256 is not None and (
            profile.source_pixel_sha256 != graph["asset"]["pixel_sha256"]
        ):
            raise ValueError("Wood profile source hash does not match the Scene Graph")
        if status == "published" and profile.source_pixel_sha256 is None:
            raise ValueError("Published wood profiles require a source pixel hash")
    validated_surface_styles = [
        validate_surface_style_profile(item) for item in surface_style_profiles
    ]
    for profile in validated_surface_styles:
        if profile.source_pixel_sha256 != graph["asset"]["pixel_sha256"]:
            raise ValueError("Surface style profile source hash does not match the Scene Graph")
    profiles = [item.to_dict() for item in validated_profiles]
    profiles.extend(item.to_dict() for item in validated_surface_styles)
    payload = {
        "schema_version": REFERENCE_ANALYSIS_V3_SCHEMA_VERSION,
        "status": status,
        "publication_evidence": evidence,
        "analysis_metadata": {
            "provider": "unified_local_contract",
            "analyzer_version": analyzer_version,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "input_pixel_sha256": graph["asset"]["pixel_sha256"],
        },
        "asset_id": graph["asset"]["asset_id"],
        "scene_graph": graph,
        "lighting_contract": lighting,
        "surface_profiles": profiles,
        "brand_surface_observations": reference_brand_observations(graph),
    }
    stable = copy.deepcopy(payload)
    stable["analysis_metadata"].pop("analyzed_at")
    payload["contract_sha256"] = _canonical_hash(stable)
    return payload


def resolve_visual_contract(
    *,
    reference_analysis: Mapping[str, Any],
    wood_profile: WoodMaterialProfile | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if reference_analysis.get("schema_version") != REFERENCE_ANALYSIS_V3_SCHEMA_VERSION:
        raise ValueError("Resolved visual contract requires ReferenceAnalysisV3")
    selected_wood = (
        validate_wood_material_profile(wood_profile).to_dict()
        if wood_profile is not None
        else None
    )
    value = {
        "schema_version": "1.0.0",
        "reference_asset_id": reference_analysis["asset_id"],
        "reference_contract_sha256": reference_analysis["contract_sha256"],
        "lighting": copy.deepcopy(reference_analysis.get("lighting_contract")),
        "wood_material": selected_wood,
    }
    value["resolved_visual_contract_sha256"] = _canonical_hash(value)
    return value
