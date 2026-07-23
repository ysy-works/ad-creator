from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .image_contracts import canonical_image_binding
from .reference_contracts import assemble_reference_analysis_v3
from .surface_styles import SurfaceStyleProfile, extract_surface_style_profile
from .wood_materials import WoodMaterialProfile, extract_wood_material_profile


@dataclass(frozen=True)
class ReferenceAnalyzerV3Result:
    analysis: dict[str, Any]
    wood_profiles: tuple[WoodMaterialProfile, ...]
    surface_style_profiles: tuple[SurfaceStyleProfile, ...]


class ReferenceAnalyzerV3:
    """Local, zero-credit assembly of scene, light, material and surface contracts.

    Segmentation and semantic detectors remain replaceable upstream components.
    This analyzer requires their original-resolution masks and binds every
    extracted measurement to the source pixels before producing a V3 sidecar.
    """

    def __init__(self, *, analyzer_version: str = "reference_analyzer_v3_local_v1") -> None:
        if not analyzer_version.strip():
            raise ValueError("ReferenceAnalyzerV3 requires an analyzer_version")
        self.analyzer_version = analyzer_version

    def analyze(
        self,
        source_image: str | Path,
        *,
        scene_graph: Mapping[str, Any],
        resolved_lighting: Mapping[str, Any] | None = None,
        wood_surfaces: Sequence[Mapping[str, Any]] = (),
        surface_styles: Sequence[Mapping[str, Any]] = (),
        status: str = "draft",
        publication_evidence: Mapping[str, Any] | None = None,
    ) -> ReferenceAnalyzerV3Result:
        source = Path(source_image).expanduser().resolve()
        binding = canonical_image_binding(source)
        graph_hash = scene_graph.get("asset", {}).get("pixel_sha256")
        if graph_hash != binding["pixel_sha256"]:
            raise ValueError("Reference source pixels do not match the Scene Graph")
        woods: list[WoodMaterialProfile] = []
        for index, raw in enumerate(wood_surfaces):
            spec = dict(raw)
            mask = spec.pop("material_mask", None)
            bbox = spec.pop("surface_bbox", None)
            if mask is None or bbox is None:
                raise ValueError(
                    f"Wood surface {index} requires material_mask and surface_bbox"
                )
            woods.append(
                extract_wood_material_profile(
                    source,
                    mask,
                    surface_bbox=bbox,
                    **spec,
                )
            )
        styles: list[SurfaceStyleProfile] = []
        for index, raw in enumerate(surface_styles):
            spec = dict(raw)
            mask = spec.pop("material_mask", None)
            bbox = spec.pop("surface_bbox", None)
            profile_id = spec.pop("profile_id", None)
            if mask is None or bbox is None or not isinstance(profile_id, str):
                raise ValueError(
                    f"Surface style {index} requires profile_id, material_mask and surface_bbox"
                )
            styles.append(
                extract_surface_style_profile(
                    source,
                    mask,
                    profile_id=profile_id,
                    surface_bbox=bbox,
                    **spec,
                )
            )
        if status != "draft" and (woods or styles):
            raise ValueError("Newly extracted profiles require review before publication")
        analysis = assemble_reference_analysis_v3(
            scene_graph=scene_graph,
            resolved_lighting=resolved_lighting,
            wood_profiles=woods,
            surface_style_profiles=styles,
            status=status,
            analyzer_version=self.analyzer_version,
            publication_evidence=publication_evidence,
        )
        return ReferenceAnalyzerV3Result(
            analysis=analysis,
            wood_profiles=tuple(woods),
            surface_style_profiles=tuple(styles),
        )
