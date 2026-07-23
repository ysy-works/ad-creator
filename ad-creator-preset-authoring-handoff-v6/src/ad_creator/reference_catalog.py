from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .image_contracts import canonical_image_binding, dhash_distance
from .jsonio import load_json


@dataclass(frozen=True)
class ReferenceLookup:
    pixel_sha256: str
    asset_id: str | None
    canonical_asset_id: str | None
    relative_path: str | None
    analysis: dict[str, Any] | None
    scene_graph: dict[str, Any] | None
    mood_package_path: str | None
    cluster_id: str | None
    match_method: str
    match_distance: int | None


def load_reference_assignment(
    assignments_path: str | Path | None,
    asset_id: str | None,
) -> dict[str, Any] | None:
    if not assignments_path or not asset_id:
        return None
    path = Path(assignments_path)
    if not path.is_file():
        return None
    payload = load_json(path)
    return payload.get("assignments", {}).get(asset_id)


def load_reference_scene_graph(
    scene_graph_catalog_path: str | Path | None,
    *asset_ids: str | None,
) -> dict[str, Any] | None:
    """Load a v2 sidecar by selected or canonical asset ID.

    JSONL remains the source of truth during curation so new analyses can be
    checkpointed without a SQLite migration. A single checked-in JSON sidecar
    is also accepted for a reviewed runtime override.
    """
    if not scene_graph_catalog_path:
        return None
    path = Path(scene_graph_catalog_path)
    if not path.is_file():
        return None
    requested = {asset_id for asset_id in asset_ids if asset_id}
    if not requested:
        return None
    if path.suffix.lower() == ".json":
        value = load_json(path)
        asset_id = value.get("asset", {}).get("asset_id")
        return value if asset_id in requested else None
    matches: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        asset_id = value.get("asset", {}).get("asset_id")
        if asset_id in requested:
            matches[asset_id] = value
    for asset_id in asset_ids:
        if asset_id in matches:
            return matches[asset_id]
    return None


def lookup_reference(
    image_path: str | Path,
    *,
    catalog_path: str | Path,
    assignments_path: str | Path | None = None,
    scene_graph_catalog_path: str | Path | None = None,
) -> ReferenceLookup:
    binding = canonical_image_binding(image_path)
    catalog = Path(catalog_path)
    if not catalog.is_file():
        raise FileNotFoundError(f"Reference catalog does not exist: {catalog}")
    connection = sqlite3.connect(catalog)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT asset_id, relative_path, analysis_json, duplicate_of,
                   analysis_status, dhash
            FROM reference_assets
            WHERE pixel_sha256 = ?
            ORDER BY CASE analysis_status WHEN 'analyzed' THEN 0 ELSE 1 END, relative_path
            LIMIT 1
            """,
            (binding["pixel_sha256"],),
        ).fetchone()
        match_method = "exact_pixel" if row else "none"
        match_distance: int | None = 0 if row else None
        if row is None:
            candidates = connection.execute(
                """
                SELECT asset_id, relative_path, analysis_json, duplicate_of,
                       analysis_status, dhash
                FROM reference_assets
                WHERE width_px = ? AND height_px = ?
                """,
                (binding["width_px"], binding["height_px"]),
            ).fetchall()
            ranked = sorted(
                [
                    (
                        dhash_distance(binding["dhash"], candidate["dhash"]),
                        candidate,
                    )
                    for candidate in candidates
                ],
                key=lambda item: (item[0], item[1]["asset_id"]),
            )
            ranked = [item for item in ranked if item[0] <= 3]
            if ranked:
                best_distance = ranked[0][0]
                best = [candidate for distance, candidate in ranked if distance == best_distance]
                canonical_ids = {
                    candidate["duplicate_of"] or candidate["asset_id"] for candidate in best
                }
                if len(canonical_ids) == 1:
                    row = sorted(
                        best,
                        key=lambda candidate: (
                            candidate["analysis_status"] != "analyzed",
                            candidate["asset_id"],
                        ),
                    )[0]
                    match_method = "perceptual_dhash"
                    match_distance = best_distance
    finally:
        connection.close()
    asset_id = row["asset_id"] if row else None
    canonical_asset_id = (row["duplicate_of"] or asset_id) if row else None
    assignment = load_reference_assignment(assignments_path, asset_id)
    if assignment is None and canonical_asset_id != asset_id:
        assignment = load_reference_assignment(assignments_path, canonical_asset_id)
    analysis = json.loads(row["analysis_json"]) if row and row["analysis_json"] else None
    scene_graph = load_reference_scene_graph(
        scene_graph_catalog_path,
        asset_id,
        canonical_asset_id,
    )
    return ReferenceLookup(
        pixel_sha256=binding["pixel_sha256"],
        asset_id=asset_id,
        canonical_asset_id=canonical_asset_id,
        relative_path=row["relative_path"] if row else None,
        analysis=analysis,
        scene_graph=scene_graph,
        mood_package_path=assignment.get("mood_package_path") if assignment else None,
        cluster_id=assignment.get("cluster_id") if assignment else None,
        match_method=match_method,
        match_distance=match_distance,
    )
