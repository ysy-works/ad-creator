from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ad_creator.lighting_contracts import (
    ReferenceLightingDelta,
    WhiteLightingBase,
    resolve_lighting_contract,
    validate_reference_lighting_delta,
    validate_white_lighting_base,
)
from ad_creator.multi_pipeline import prepare_multi_product_request
from ad_creator.reference_contracts import (
    assemble_reference_analysis_v3,
    lookup_reference_analysis_v3_sources,
    resolve_visual_contract,
)
from ad_creator.wood_materials import validate_wood_material_profile


RESOLVED_REFERENCE_BUNDLE_VERSION = "1.0.0"


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _resolved_bundle_hash(value: Mapping[str, Any]) -> str:
    stable = copy.deepcopy(dict(value))
    stable.pop("resolved_contract_sha256", None)
    analysis = stable.get("reference_analysis")
    if isinstance(analysis, dict):
        metadata = analysis.get("analysis_metadata")
        if isinstance(metadata, dict):
            metadata.pop("analyzed_at", None)
    return _canonical_hash(stable)


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return copy.deepcopy(dict(value))


def resolve_reference_contract_bundle(
    *,
    scene_graph: Mapping[str, Any],
    lighting_base: WhiteLightingBase | Mapping[str, Any] | None = None,
    lighting_delta: ReferenceLightingDelta | Mapping[str, Any] | None = None,
    wood_material_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze all reference-derived V3 contracts into one tamper-evident bundle."""

    if (lighting_base is None) != (lighting_delta is None):
        raise ValueError("lighting_base and lighting_delta must be supplied together")

    base = (
        validate_white_lighting_base(lighting_base)
        if lighting_base is not None
        else None
    )
    delta = (
        validate_reference_lighting_delta(lighting_delta)
        if lighting_delta is not None
        else None
    )
    resolved_lighting = (
        resolve_lighting_contract(base, delta)
        if base is not None and delta is not None
        else None
    )
    wood = (
        validate_wood_material_profile(wood_material_profile)
        if wood_material_profile is not None
        else None
    )
    reference_analysis = assemble_reference_analysis_v3(
        scene_graph=_mapping(scene_graph, label="scene_graph"),
        resolved_lighting=resolved_lighting,
        wood_profiles=([wood] if wood is not None else []),
    )
    visual_contract = resolve_visual_contract(
        reference_analysis=reference_analysis,
        wood_profile=wood,
    )
    bundle = {
        "schema_version": RESOLVED_REFERENCE_BUNDLE_VERSION,
        "artifact_type": "resolved_reference_contract_bundle",
        "reference_analysis": reference_analysis,
        "resolved_visual_contract": visual_contract,
        "source_contracts": {
            "lighting_base": base.to_dict() if base is not None else None,
            "lighting_delta": delta.to_dict() if delta is not None else None,
            "wood_material_profile": wood.to_dict() if wood is not None else None,
        },
    }
    bundle["resolved_contract_sha256"] = _resolved_bundle_hash(bundle)
    return bundle


def resolve_reference_contract_bundle_by_id(
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
) -> dict[str, Any]:
    sources = lookup_reference_analysis_v3_sources(
        project_root=project_root,
        reference_id=reference_id,
        scene_graph_catalog_path=scene_graph_catalog_path,
        lighting_delta_catalog_path=lighting_delta_catalog_path,
        wood_profile_catalog_path=wood_profile_catalog_path,
    )
    bundle = resolve_reference_contract_bundle(
        scene_graph=sources["scene_graph"],
        lighting_base=sources["lighting_base"],
        lighting_delta=sources["lighting_delta"],
        wood_material_profile=sources["wood_material_profile"],
    )
    bundle["catalog_resolution"] = {
        "reference_id": reference_id,
        **sources["catalog_hits"],
    }
    bundle["resolved_contract_sha256"] = _resolved_bundle_hash(bundle)
    return bundle


def validate_reference_contract_bundle(
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-resolve a bundle and reject any changed scene, material, light or hash."""

    value = _mapping(bundle, label="resolved reference contract bundle")
    if value.get("schema_version") != RESOLVED_REFERENCE_BUNDLE_VERSION:
        raise ValueError("Unsupported resolved reference contract bundle version")
    if value.get("artifact_type") != "resolved_reference_contract_bundle":
        raise ValueError("Resolved reference contract bundle has the wrong artifact_type")
    supplied_hash = value.pop("resolved_contract_sha256", None)
    if supplied_hash != _resolved_bundle_hash(value):
        raise ValueError("Resolved reference contract bundle hash does not match")

    analysis = _mapping(value.get("reference_analysis"), label="reference_analysis")
    source_contracts = _mapping(
        value.get("source_contracts"), label="source_contracts"
    )
    expected = resolve_reference_contract_bundle(
        scene_graph=_mapping(analysis.get("scene_graph"), label="scene_graph"),
        lighting_base=source_contracts.get("lighting_base"),
        lighting_delta=source_contracts.get("lighting_delta"),
        wood_material_profile=source_contracts.get("wood_material_profile"),
    )
    expected_analysis = expected["reference_analysis"]
    stable_fields = (
        "status",
        "publication_evidence",
        "asset_id",
        "scene_graph",
        "lighting_contract",
        "surface_profiles",
        "brand_surface_observations",
        "contract_sha256",
    )
    if any(analysis.get(field) != expected_analysis.get(field) for field in stable_fields):
        raise ValueError("ReferenceAnalysisV3 does not match its embedded source contracts")
    if value.get("resolved_visual_contract") != expected["resolved_visual_contract"]:
        raise ValueError("Resolved visual contract does not match ReferenceAnalysisV3")

    value["resolved_contract_sha256"] = supplied_hash
    return value


def build_multi_product_request_from_bundle(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_set: Mapping[str, Any],
    resolved_reference_bundle: Mapping[str, Any],
    seed: int = 713,
    unbound_slot_policy: str = "genericize",
    control_board_image: str | Path | None = None,
    control_board_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a local V3 request and prove it used the connected resolved bundle."""

    bundle = validate_reference_contract_bundle(resolved_reference_bundle)
    source_contracts = bundle["source_contracts"]
    analysis = bundle["reference_analysis"]
    request = prepare_multi_product_request(
        project_root=project_root,
        mood_package_path=mood_package_path,
        products=_mapping(product_set, label="product_set"),
        scene_graph=analysis["scene_graph"],
        seed=seed,
        unbound_slot_policy=unbound_slot_policy,
        control_board_image=control_board_image,
        control_board_manifest=control_board_manifest,
        lighting_base=source_contracts.get("lighting_base"),
        lighting_delta=source_contracts.get("lighting_delta"),
        wood_material_profile=source_contracts.get("wood_material_profile"),
    )
    if (
        request["reference_analysis_contract"]["sha256"]
        != analysis["contract_sha256"]
    ):
        raise ValueError("Request resolved a different ReferenceAnalysisV3 contract")
    if (
        request["resolved_visual_contract"]["resolved_visual_contract_sha256"]
        != bundle["resolved_visual_contract"]["resolved_visual_contract_sha256"]
    ):
        raise ValueError("Request resolved a different visual contract")
    return request
