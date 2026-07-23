from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Any

from .reference_library import derive_reference_capabilities
from .scene_graph import derive_scene_graph_capabilities
from .reference_taxonomy import (
    derive_inventory_taxonomy,
    derive_reference_taxonomy,
    frontend_mood_for_taxonomy,
    validate_taxonomy_axes,
)


DIRECT_CLUSTER_ID = "direct_sun_neutral_candid_v1"
SOFT_CLUSTER_ID = "soft_diffuse_neutral_candid_v1"
WOOD_CLUSTER_ID = "warm_wood_soft_window_v1"
POINT_CLUSTER_ID = "point_color_daylight_v1"
MINERAL_CLUSTER_ID = "modern_mineral_neutral_v1"
VINTAGE_CLUSTER_ID = "sun_washed_vintage_table_v1"

CLUSTER_CONFIG = {
    DIRECT_CLUSTER_ID: {
        "display_name": "맑은 직사광 · 뉴트럴 캔디드",
        "mood_package_path": "presets/moods/direct_sun_white_wall_v1/mood-package.json",
        "lighting_sheet_path": "presets/moods/direct_sun_white_wall_v1/lighting-sheet.json",
        "grade_profile_path": "presets/moods/direct_sun_white_wall_v1/grade-profile.json",
    },
    SOFT_CLUSTER_ID: {
        "display_name": "부드러운 창가 · 뉴트럴 캔디드",
        "mood_package_path": "presets/moods/soft_diffuse_window_neutral_v2/mood-package.json",
        "lighting_sheet_path": "presets/moods/soft_diffuse_window_neutral_v2/lighting-sheet.json",
        "grade_profile_path": "presets/moods/soft_diffuse_window_neutral_v1/grade-profile.json",
    },
    WOOD_CLUSTER_ID: {
        "display_name": "따뜻한 우드 · 부드러운 창가",
        "mood_package_path": "presets/moods/warm_wood_soft_window_v1/mood-package.json",
        "lighting_sheet_path": "presets/moods/warm_wood_soft_window_v1/lighting-sheet.json",
        "grade_profile_path": "presets/moods/warm_wood_soft_window_v1/grade-profile.json",
    },
    POINT_CLUSTER_ID: {
        "display_name": "절제된 포인트 컬러 · 자연광",
        "mood_package_path": "presets/moods/point_color_daylight_v1/mood-package.json",
        "lighting_sheet_path": "presets/moods/point_color_daylight_v1/lighting-sheet.json",
        "grade_profile_path": "presets/moods/point_color_daylight_v1/grade-profile.json",
    },
    MINERAL_CLUSTER_ID: {
        "display_name": "모던 미네랄 · 뉴트럴 확산광",
        "mood_package_path": "presets/moods/modern_mineral_neutral_v1/mood-package.json",
        "lighting_sheet_path": "presets/moods/modern_mineral_neutral_v1/lighting-sheet.json",
        "grade_profile_path": "presets/moods/modern_mineral_neutral_v1/grade-profile.json",
    },
    VINTAGE_CLUSTER_ID: {
        "display_name": "햇빛 스민 빈티지 테이블",
        "mood_package_path": "presets/moods/sun_washed_vintage_table_v1/mood-package.json",
        "lighting_sheet_path": "presets/moods/sun_washed_vintage_table_v1/lighting-sheet.json",
        "grade_profile_path": "presets/moods/sun_washed_vintage_table_v1/grade-profile.json",
    },
}


def _cluster_for_taxonomy(
    taxonomy: dict[str, Any],
    *,
    allow_direct: bool = True,
) -> str:
    environment = taxonomy["environment_family"]
    if environment == "vintage_warm":
        return VINTAGE_CLUSTER_ID
    if taxonomy["wood_prominence"] >= 0.55:
        return WOOD_CLUSTER_ID
    if environment == "point_color" or taxonomy["accent_color_prominence"] >= 0.55:
        return POINT_CLUSTER_ID
    if environment == "modern_mineral" or any(
        token in taxonomy["dominant_surface"]
        for token in ("concrete", "stone", "metal", "steel", "chrome", "mineral")
    ):
        return MINERAL_CLUSTER_ID
    if allow_direct and taxonomy["lighting_family"] == "direct_sun":
        return DIRECT_CLUSTER_ID
    return SOFT_CLUSTER_ID


def _physical_lighting_family(
    reference: dict[str, Any],
    taxonomy: dict[str, Any],
) -> str:
    lighting = reference["lighting"]
    current = taxonomy["lighting_family"]
    if lighting["source_type"] == "direct_sun" or current == "direct_sun":
        return "direct_sun"

    shadow = str(lighting.get("shadow", "")).lower()
    hard_shadow = any(
        token in shadow
        for token in ("sharp", "distinct", "hard", "long", "dappled", "stripe", "strong")
    )
    if (
        lighting["hardness"] >= 0.65
        and lighting["contrast"] >= 0.55
        and hard_shadow
    ):
        return "direct_sun"
    if lighting["source_type"] in {"soft_window", "overcast"}:
        return lighting["source_type"]
    if (
        lighting["source_size"] == "large"
        and lighting["hardness"] <= 0.4
        and any(token in shadow for token in ("soft", "diffuse", "subtle", "faint"))
    ):
        return "soft_window"
    return current


def classify_reference(
    reference: dict[str, Any],
    *,
    inventory_asset: dict[str, Any] | None = None,
    scene_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_source = (
        scene_graph
        if scene_graph is not None
        and all(key in scene_graph for key in ("lighting", "color", "depth"))
        else reference
    )
    lighting = evidence_source["lighting"]
    color = evidence_source["color"]
    taxonomy = (
        dict(scene_graph["taxonomy"])
        if scene_graph is not None
        else derive_reference_taxonomy(reference, inventory_asset)
    )
    taxonomy["lighting_family"] = _physical_lighting_family(reference, taxonomy)
    taxonomy["frontend_mood"] = frontend_mood_for_taxonomy(taxonomy)
    validate_taxonomy_axes(taxonomy)
    cluster_id = _cluster_for_taxonomy(taxonomy)
    if cluster_id == DIRECT_CLUSTER_ID and (
        color["mean_luminance"] < 0.43 or color["mean_saturation"] > 0.22
    ):
        cluster_id = (
            POINT_CLUSTER_ID
            if color["mean_saturation"] >= 0.24
            else SOFT_CLUSTER_ID
        )
    if cluster_id == DIRECT_CLUSTER_ID:
        core = color["mean_luminance"] >= 0.5 and color["mean_saturation"] <= 0.21
    elif cluster_id == SOFT_CLUSTER_ID:
        core = (
            lighting["source_type"] in {"soft_window", "overcast"}
            and lighting["hardness"] <= 0.4
            and color["mean_luminance"] >= 0.5
            and color["mean_saturation"] <= 0.16
            and evidence_source["depth"]["far_plane_softness"] != "strong"
        )
    elif cluster_id == WOOD_CLUSTER_ID:
        core = (
            taxonomy["wood_prominence"] >= 0.55
            and taxonomy["lighting_family"] in {"soft_window", "overcast", "warm_ambient"}
            and color["mean_saturation"] <= 0.28
        )
    elif cluster_id == POINT_CLUSTER_ID:
        core = (
            taxonomy["accent_color_prominence"] >= 0.55
            and color["mean_saturation"] <= 0.35
            and lighting["source_type"] != "unknown"
        )
    elif cluster_id == VINTAGE_CLUSTER_ID:
        core = (
            taxonomy["lighting_family"] == "direct_sun"
            and lighting["hardness"] >= 0.55
            and color["mean_saturation"] <= 0.30
        )
    else:
        core = (
            taxonomy["environment_family"] == "modern_mineral"
            and taxonomy["wood_prominence"] < 0.55
            and lighting["hardness"] <= 0.55
        )
    evidence = [
        f"environment={taxonomy['environment_family']}",
        f"lighting={taxonomy['lighting_family']}",
        f"angle={taxonomy['camera_angle']}",
        f"capture={taxonomy['capture_style']}",
        f"wood={taxonomy['wood_prominence']}",
        f"accent={taxonomy['accent_color_prominence']}",
        f"hardness={lighting['hardness']}",
        f"mean_luminance={color['mean_luminance']}",
        f"mean_saturation={color['mean_saturation']}",
    ]
    return {
        "cluster_id": cluster_id,
        "membership": "core" if core else "provisional",
        "confidence": 0.9 if core else 0.62,
        "evidence": evidence,
        "taxonomy": taxonomy,
    }


def _cluster_summary(cluster_id: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    core = [member for member in members if member["classification"]["membership"] == "core"]
    references = [member["reference"] for member in members]
    lights = [reference["lighting"] for reference in references]
    colors = [reference["color"] for reference in references]
    taxonomies = [member["classification"]["taxonomy"] for member in members]
    return {
        **CLUSTER_CONFIG[cluster_id],
        "core_reference_ids": [member["reference"]["asset"]["asset_id"] for member in core],
        "analyzed_reference_ids": [
            member["reference"]["asset"]["asset_id"] for member in members
        ],
        "statistics": {
            "analyzed_count": len(members),
            "core_count": len(core),
            "median_hardness": round(median(light["hardness"] for light in lights), 4),
            "median_contrast": round(median(light["contrast"] for light in lights), 4),
            "median_luminance": round(
                median(color["mean_luminance"] for color in colors), 4
            ),
            "median_saturation": round(
                median(color["mean_saturation"] for color in colors), 4
            ),
            "source_types": dict(Counter(light["source_type"] for light in lights)),
            "white_balance": dict(Counter(light["white_balance"] for light in lights)),
            "environment_families": dict(
                Counter(value["environment_family"] for value in taxonomies)
            ),
            "camera_angles": dict(Counter(value["camera_angle"] for value in taxonomies)),
            "capture_styles": dict(Counter(value["capture_style"] for value in taxonomies)),
        },
    }


def build_reference_assignments(
    inventory: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    curation: dict[str, Any] | None = None,
    scene_graphs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    curated_source_clusters: dict[str, str] = {}
    curated_exclusions: dict[str, set[str]] = {}
    if curation:
        for cluster_id, curated in curation["clusters"].items():
            for asset_id in curated["source_asset_ids"]:
                existing = curated_source_clusters.get(asset_id)
                if existing and existing != cluster_id:
                    raise ValueError(
                        f"Curated asset {asset_id} belongs to multiple clusters"
                    )
                curated_source_clusters[asset_id] = cluster_id
            for asset_id in curated.get("excluded_asset_ids", {}):
                curated_exclusions.setdefault(asset_id, set()).add(cluster_id)

    analysis_by_id = {reference["asset"]["asset_id"]: reference for reference in analyses}
    graph_by_id = {
        graph["asset"]["asset_id"]: graph for graph in (scene_graphs or [])
    }
    members: dict[str, list[dict[str, Any]]] = {cluster_id: [] for cluster_id in CLUSTER_CONFIG}
    assignments: dict[str, dict[str, Any]] = {}
    for asset in inventory:
        asset_id = asset["asset_id"]
        reference = analysis_by_id.get(asset_id)
        if reference is None:
            taxonomy = derive_inventory_taxonomy(asset)
            cluster_id = curated_source_clusters.get(
                asset_id,
                _cluster_for_taxonomy(taxonomy),
            )
            curated = asset_id in curated_source_clusters
            assignments[asset_id] = {
                "analysis_status": "duplicate" if asset["duplicate_of"] else "pending_analysis",
                "canonical_asset_id": asset["duplicate_of"] or asset_id,
                "cluster_id": cluster_id,
                "membership": "curated_pending" if curated else "inventory_provisional",
                "confidence": 0.92 if curated else taxonomy["confidence"],
                "evidence": (
                    ["manual visual curation; semantic analysis pending"]
                    if curated
                    else ["local folder tags and color metrics only"]
                ),
                "taxonomy": taxonomy,
                "mood_package_path": CLUSTER_CONFIG[cluster_id]["mood_package_path"],
                "runtime_capabilities": None,
            }
            continue
        classification = classify_reference(
            reference,
            inventory_asset=asset,
            scene_graph=graph_by_id.get(asset_id),
        )
        curated_cluster = curated_source_clusters.get(asset_id)
        if curated_cluster is not None:
            classification.update(
                {
                    "cluster_id": curated_cluster,
                    "membership": "core",
                    "confidence": 0.98,
                    "evidence": [
                        *classification["evidence"],
                        "manual visual curation override",
                    ],
                }
            )
        excluded = curated_exclusions.get(asset_id, set())
        if classification["cluster_id"] in excluded:
            inventory_taxonomy = derive_inventory_taxonomy(asset)
            fallback_cluster = _cluster_for_taxonomy(
                inventory_taxonomy,
                allow_direct=False,
            )
            classification.update(
                {
                    "cluster_id": fallback_cluster,
                    "membership": "provisional",
                    "confidence": min(float(classification["confidence"]), 0.62),
                    "evidence": [
                        *classification["evidence"],
                        f"manual curation excludes {','.join(sorted(excluded))}",
                        "fallback uses inventory taxonomy without direct-sun routing",
                    ],
                }
            )
        cluster_id = classification["cluster_id"]
        summary_reference = graph_by_id.get(asset_id) or reference
        members[cluster_id].append(
            {"reference": summary_reference, "classification": classification}
        )
        assignments[asset_id] = {
            "analysis_status": "analyzed",
            "canonical_asset_id": asset_id,
            **classification,
            "mood_package_path": CLUSTER_CONFIG[cluster_id]["mood_package_path"],
            "runtime_capabilities": (
                derive_scene_graph_capabilities(graph_by_id[asset_id])
                if asset_id in graph_by_id
                else derive_reference_capabilities(reference)
            ),
        }

    for asset in inventory:
        canonical_id = asset["duplicate_of"]
        if not canonical_id or canonical_id not in assignments:
            continue
        inherited = dict(assignments[canonical_id])
        inherited.update(
            {
                "analysis_status": "duplicate",
                "canonical_asset_id": canonical_id,
                "duplicate_of": canonical_id,
                "evidence": [f"inherited from canonical duplicate {canonical_id}"],
            }
        )
        assignments[asset["asset_id"]] = inherited

    cluster_summaries = {
        cluster_id: _cluster_summary(cluster_id, cluster_members)
        for cluster_id, cluster_members in members.items()
        if cluster_members
    }
    if curation:
        inventory_ids = {asset["asset_id"] for asset in inventory}
        for cluster_id, curated in curation["clusters"].items():
            unknown = set(curated["source_asset_ids"]) - inventory_ids
            if unknown:
                raise ValueError(
                    f"Curated cluster {cluster_id} contains unknown assets: {sorted(unknown)}"
                )
            cluster_summaries.setdefault(
                cluster_id,
                {
                    **CLUSTER_CONFIG[cluster_id],
                    "core_reference_ids": [],
                    "analyzed_reference_ids": [],
                    "statistics": {"analyzed_count": 0, "core_count": 0},
                },
            )["curation"] = curated

    return {
        "schema_version": "1.0.0",
        "policy_version": "multi_axis_reference_taxonomy_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "curation_version": curation["curation_version"] if curation else None,
        "clusters": cluster_summaries,
        "assignments": assignments,
    }
