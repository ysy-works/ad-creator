from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from ..gemini_api import GeminiInteractionsClient
from ..image_contracts import (
    canonical_image_binding,
    dhash_distance,
    validate_brand_contract,
    validate_product_analysis_v3,
    validate_product_analysis_binding,
)
from ..jsonio import load_json, validate_json
from ..reference_library import inspect_reference_asset, validate_reference_geometry
from ..scene_graph import canonicalize_slot_ids, validate_scene_graph


PRODUCT_ANALYSIS_PROMPT_VERSION = "product_analysis_v3_brand_candidate_agreement"
PRODUCT_ANALYSIS_V3_PROMPT_VERSION = "product_analysis_v3_material_brand_applications"
REFERENCE_ANALYSIS_PROMPT_VERSION = "reference_analysis_v1"
REFERENCE_SCENE_GRAPH_PROMPT_VERSION = "reference_scene_graph_v2"
REFERENCE_SCENE_GRAPH_EXTRACTOR_VERSION = "reference_scene_graph_extractor_v3_counted"


def _brand_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "state": {
                "type": "string",
                "enum": ["verified_present", "verified_absent", "uncertain"],
            },
            "main_text": {"type": ["string", "null"]},
            "visible_text": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "non_text_mark": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": [
            "state",
            "main_text",
            "visible_text",
            "non_text_mark",
            "confidence",
        ],
    }


def _normalized_visible_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _brand_text_candidates(branding: dict[str, Any]) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for value in (branding.get("main_text"), *branding.get("visible_text", [])):
        normalized = _normalized_visible_text(value)
        if normalized is not None and normalized not in candidates:
            candidates[normalized] = " ".join(value.split())
    return candidates


def _reconcile_brand_crosscheck(
    first_brand: dict[str, Any],
    verification: dict[str, Any],
) -> str:
    """Merge two independent reads without promoting an uncertain observation."""
    first_candidates = _brand_text_candidates(first_brand)
    verification_candidates = _brand_text_candidates(verification)
    shared_candidates = set(first_candidates) & set(verification_candidates)
    matching_state = first_brand["state"] == verification["state"]
    exact_main_text = _normalized_visible_text(
        first_brand.get("main_text")
    ) == _normalized_visible_text(verification.get("main_text"))

    if matching_state and first_brand["state"] == "verified_absent":
        first_brand["confidence"] = min(
            first_brand["confidence"], verification["confidence"]
        )
        return "matched"

    if (
        matching_state
        and first_brand["state"] == "verified_present"
        and (exact_main_text or shared_candidates)
    ):
        verification_main = _normalized_visible_text(verification.get("main_text"))
        first_main = _normalized_visible_text(first_brand.get("main_text"))
        if exact_main_text:
            resolved_main = first_brand.get("main_text")
        elif verification_main in first_candidates:
            resolved_main = first_candidates[verification_main]
        elif first_main in verification_candidates:
            resolved_main = verification_candidates[first_main]
        else:
            # Both passes observed this exact text. Prefer the first pass's original
            # spelling while choosing the shortest shared wordmark-like candidate.
            selected = min(shared_candidates, key=lambda value: (len(value), value))
            resolved_main = first_candidates[selected]

        merged_visible = list(
            dict.fromkeys(
                first_brand.get("visible_text", [])
                + verification.get("visible_text", [])
            )
        )
        if resolved_main and resolved_main not in merged_visible:
            merged_visible.insert(0, resolved_main)
        first_brand.update(
            {
                "state": "verified_present",
                "main_text": resolved_main,
                "visible_text": merged_visible,
                "confidence": min(
                    first_brand["confidence"], verification["confidence"]
                ),
            }
        )
        return "matched_candidates" if not exact_main_text else "matched"

    candidates = list(
        dict.fromkeys(
            first_brand.get("visible_text", [])
            + verification.get("visible_text", [])
        )
    )
    first_brand.update(
        {
            "state": "uncertain",
            "main_text": None,
            "visible_text": candidates,
            "non_text_mark": None,
            "confidence": min(
                first_brand["confidence"], verification["confidence"]
            ),
        }
    )
    return "disagreed"


def _analysis_response_schema(
    project_root: Path,
    *,
    contract_version: str = "2.0.0",
    product_kind: str | None = None,
) -> dict[str, Any]:
    product_schema = deepcopy(
        load_json(project_root / "schemas/product-analysis.schema.json")
    )
    product_schema.pop("$schema", None)
    product_schema.pop("$id", None)
    definitions = product_schema.pop("$defs")
    for field in ("analysis_metadata", "source_binding", "$schema"):
        product_schema["properties"].pop(field, None)
    product_schema["required"] = [
        field
        for field in product_schema["required"]
        if field not in {"analysis_metadata", "source_binding"}
    ]
    product_schema["properties"]["schema_version"] = {"const": contract_version}
    if contract_version == "3.0.0":
        if product_kind not in {"beverage", "dessert"}:
            raise ValueError("Product Analysis v3 requires beverage or dessert product_kind")
        product_schema["properties"]["product_kind"] = {"const": product_kind}
        identity_schema = product_schema["properties"]["identity"]
        identity_schema.setdefault("required", []).append("serving_state")
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": definitions,
        "properties": {
            "analysis": product_schema,
            "analysis_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
        },
        "required": ["analysis", "analysis_confidence"],
    }


def _bbox_is_valid(value: dict[str, Any]) -> bool:
    return (
        0 <= value["left"] < value["right"] <= 1
        and 0 <= value["top"] < value["bottom"] <= 1
    )


def _validate_geometry(analysis: dict[str, Any]) -> None:
    geometry = analysis["geometry"]
    for name in ("container_bbox", "subject_bbox"):
        if not _bbox_is_valid(geometry[name]):
            raise ValueError(f"Invalid normalized {name}")
    for name in ("beverage_bbox", "interaction_bbox"):
        if geometry[name] is not None and not _bbox_is_valid(geometry[name]):
            raise ValueError(f"Invalid normalized {name}")

    container = geometry["container_bbox"]
    subject = geometry["subject_bbox"]
    tolerance = 0.025
    if not (
        subject["left"] <= container["left"] + tolerance
        and subject["top"] <= container["top"] + tolerance
        and subject["right"] >= container["right"] - tolerance
        and subject["bottom"] >= container["bottom"] - tolerance
    ):
        raise ValueError("subject_bbox must contain the container_bbox")

    straw = geometry["straw"]
    straw_fields = ("bbox", "centerline", "emergence_point", "angle_degrees")
    if straw["present"]:
        if any(straw[field] is None for field in straw_fields):
            raise ValueError("A present straw requires bbox, centerline and angle data")
        if not _bbox_is_valid(straw["bbox"]):
            raise ValueError("Invalid normalized straw bbox")
    elif any(straw[field] is not None for field in straw_fields):
        raise ValueError("An absent straw must have null geometry fields")


class GeminiProductAnalyzer:
    def __init__(
        self,
        *,
        project_root: str | Path,
        cache_root: str | Path = "outputs/analysis-cache/product",
        model: str | None = None,
        fallback_models: Sequence[str] | None = None,
        timeout_seconds: float = 180,
        maximum_image_edge: int = 1024,
        thinking_level: str = "low",
        identity_overrides_path: str | Path = "configs/product-identity-overrides.json",
        client: GeminiInteractionsClient | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        configured_cache = Path(cache_root)
        self.cache_root = (
            configured_cache
            if configured_cache.is_absolute()
            else self.project_root / configured_cache
        )
        self.model = model or os.environ.get(
            "GEMINI_PRODUCT_ANALYZER_MODEL", "gemini-3.1-flash-lite"
        )
        configured_overrides = Path(identity_overrides_path)
        self.identity_overrides_path = (
            configured_overrides
            if configured_overrides.is_absolute()
            else self.project_root / configured_overrides
        )
        self.fallback_models = tuple(fallback_models or ())
        self.client = client or GeminiInteractionsClient(
            model=self.model,
            model_candidates=(self.model, *self.fallback_models),
            timeout_seconds=timeout_seconds,
            maximum_image_edge=maximum_image_edge,
            thinking_level=thinking_level,
        )

    def _cache_path(
        self,
        binding: dict[str, Any],
        *,
        contract_version: str = "2.0.0",
        product_kind: str | None = None,
    ) -> Path:
        contract = json.dumps(
            {
                "pixel_sha256": binding["pixel_sha256"],
                "model": self.model,
                "prompt_version": (
                    PRODUCT_ANALYSIS_V3_PROMPT_VERSION
                    if contract_version == "3.0.0"
                    else PRODUCT_ANALYSIS_PROMPT_VERSION
                ),
                "contract_version": contract_version,
                "product_kind": product_kind,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        key = hashlib.sha256(contract).hexdigest()
        return self.cache_root / binding["pixel_sha256"][:2] / f"{key}.json"

    def _validate(self, analysis: dict[str, Any], image_path: str | Path) -> None:
        validate_json(
            analysis,
            "product-analysis.schema.json",
            project_root=self.project_root,
        )
        validate_brand_contract(analysis)
        if analysis.get("schema_version") == "3.0.0":
            validate_product_analysis_v3(analysis)
        _validate_geometry(analysis)
        validate_product_analysis_binding(analysis, image_path)

    @staticmethod
    def _write_cache(path: Path, analysis: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _matching_identity_override(
        self,
        binding: dict[str, Any],
        overrides: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        exact = overrides.get(binding["pixel_sha256"])
        if exact is not None:
            return exact, "exact"

        perceptual_matches: list[dict[str, Any]] = []
        for override in overrides.values():
            source = override.get("source_binding")
            if not override.get("allow_perceptual_rebind") or not isinstance(source, dict):
                continue
            if (
                source.get("width_px") != binding["width_px"]
                or source.get("height_px") != binding["height_px"]
                or not source.get("dhash")
                or not source.get("mean_rgb")
            ):
                continue
            if dhash_distance(source["dhash"], binding["dhash"]) != 0:
                continue
            if max(
                abs(float(first) - float(second))
                for first, second in zip(
                    source["mean_rgb"], binding["mean_rgb"], strict=True
                )
            ) > 0.005:
                continue
            perceptual_matches.append(override)
        if len(perceptual_matches) == 1:
            return perceptual_matches[0], "perceptual_rebind"
        return None, None

    def _apply_identity_override(self, analysis: dict[str, Any]) -> bool:
        if not self.identity_overrides_path.is_file():
            return False
        payload = load_json(self.identity_overrides_path)
        if payload.get("schema_version") != "1.0.0":
            raise ValueError("Unsupported product identity override schema")
        override, match_mode = self._matching_identity_override(
            analysis["source_binding"],
            payload.get("overrides", {}),
        )
        if override is None:
            return False
        if override.get("verification_method") != "manual_pixel_review":
            raise ValueError("Product identity override requires manual pixel review")
        branding = override.get("branding")
        expected_fields = {
            "state",
            "main_text",
            "visible_text",
            "non_text_mark",
            "placement",
            "colors",
            "confidence",
        }
        if not isinstance(branding, dict) or set(branding) != expected_fields:
            raise ValueError("Product identity override must contain a complete branding contract")
        metadata_value = (
            "manual_pixel_review"
            if match_mode == "exact"
            else "manual_pixel_review_perceptual_rebind"
        )
        if analysis["identity"]["branding"] == branding:
            changed = (
                analysis["analysis_metadata"].get("identity_override")
                != metadata_value
            )
            analysis["analysis_metadata"]["identity_override"] = metadata_value
            return changed
        analysis["identity"]["branding"] = deepcopy(branding)
        analysis["analysis_metadata"].update(
            {
                "brand_crosscheck": "disagreed",
                "identity_override": metadata_value,
            }
        )
        analysis["analysis_metadata"].pop("binding_reuse", None)
        return True

    def _find_unbranded_visual_cache(
        self,
        binding: dict[str, Any],
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for path in self.cache_root.rglob("*.json") if self.cache_root.is_dir() else ():
            try:
                cached = load_json(path)
                source = cached["source_binding"]
                branding = cached["identity"]["branding"]
                metadata = cached["analysis_metadata"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if metadata.get("prompt_version") != PRODUCT_ANALYSIS_PROMPT_VERSION:
                continue
            if branding.get("state") != "verified_absent":
                continue
            if (
                source.get("width_px") != binding["width_px"]
                or source.get("height_px") != binding["height_px"]
                or not source.get("dhash")
                or not source.get("mean_rgb")
            ):
                continue
            if dhash_distance(source["dhash"], binding["dhash"]) > 3:
                continue
            if max(
                abs(float(first) - float(second))
                for first, second in zip(source["mean_rgb"], binding["mean_rgb"], strict=True)
            ) > 0.015:
                continue
            candidates.append(cached)
        source_hashes = {
            candidate["source_binding"]["pixel_sha256"] for candidate in candidates
        }
        exact_candidates = [
            candidate
            for candidate in candidates
            if candidate["source_binding"]["pixel_sha256"] == binding["pixel_sha256"]
        ]
        if exact_candidates:
            return max(
                exact_candidates,
                key=lambda candidate: candidate["analysis_metadata"]["analyzed_at"],
            )
        if len(source_hashes) != 1:
            return None
        return max(
            candidates,
            key=lambda candidate: candidate["analysis_metadata"]["analyzed_at"],
        )

    def analyze(
        self,
        image_path: str | Path,
        *,
        use_cache: bool = True,
        product_kind: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        contract_version = "3.0.0" if product_kind is not None else "2.0.0"
        if product_kind is not None and product_kind not in {"beverage", "dessert"}:
            raise ValueError("product_kind must be beverage or dessert")
        image = Path(image_path).expanduser().resolve()
        binding = canonical_image_binding(image)
        cache_path = self._cache_path(
            binding,
            contract_version=contract_version,
            product_kind=product_kind,
        )
        if use_cache and cache_path.is_file():
            cached = load_json(cache_path)
            if not cached["source_binding"].get("dhash"):
                cached["source_binding"].update(
                    {"dhash": binding["dhash"], "mean_rgb": binding["mean_rgb"]}
                )
                self._write_cache(cache_path, cached)
            changed = (
                self._apply_identity_override(cached)
                if contract_version == "2.0.0"
                else False
            )
            self._validate(cached, image)
            if changed:
                self._write_cache(cache_path, cached)
            return cached, True
        if use_cache and contract_version == "2.0.0":
            cached = self._find_unbranded_visual_cache(binding)
            if cached is not None:
                cached = deepcopy(cached)
                cached["source_binding"] = binding
                cached["analysis_metadata"][
                    "binding_reuse"
                ] = "verified_absent_perceptual_rebind"
                self._apply_identity_override(cached)
                self._validate(cached, image)
                self._write_cache(cache_path, cached)
                return cached, True

        prompt = """Analyze the single user product photo for a cafe-photo restyling service.
Return concise English facts only. The user's drink identity, real container construction,
liquid layers, ice, toppings and any VERIFIED visible branding are the protected contract.

Brand safety is strict:
- Never infer a cafe or brand from cup style, colors, context, familiarity or likely origin.
- verified_present means a visible mark or text is genuinely observable.
- verified_absent means there is no visible logo, label, lettering or symbol; then main_text
  must be null, visible_text empty and non_text_mark null.
- uncertain means a possible mark is too small, occluded or illegible; main_text must be null.
- Transcribe only characters you can actually see. Never autocomplete a wordmark.

Geometry uses normalized 0..1 coordinates. container_bbox includes the cup or glass body,
lid and sleeve but excludes straw, garnish, hand and arm. subject_bbox includes the complete
product including straw and garnish but excludes hand and arm. beverage_bbox covers visible
liquid. For a straw, return both bbox and a two-point centerline from its lower emergence point
to its upper tip. If no straw exists, every straw geometry field is null.

Describe how to improve an ordinary person's unattractive source angle without redesigning
the physical product. Prefer a believable smartphone viewpoint, useful negative space and
real spatial depth. Do not prescribe studio photography, extreme bokeh or advertising polish.
Return only the requested JSON."""
        if contract_version == "3.0.0":
            prompt += f"""

Product Analysis v3 requirements:
- The declared product_kind is {product_kind}; describe the protected product in identity.product.
- This service supports both beverages and desserts. Do not invent beverage properties for dessert.
- Return identity.serving_state as an explicit physical serving contract. For beverages record
  temperature as iced/cold/ambient/hot/unknown, visible ice, whether a straw and toppings are
  required, and whether side transparency is required to preserve layers or marbling. Use unknown
  instead of guessing. For desserts use not_applicable for every serving-state categorical field.
- Return branding.applications with the observed carrier material, application medium,
  carrier component, named surface, normalized bbox and confidence.
- For verified_present every compatibility field must be directly observable and specific.
  If material, medium, component or surface is not visually certain, mark that application
  uncertain and clear those fields rather than guessing.
- verified_absent applications have null compatibility fields, null bbox and no text.
"""
        response = self.client.generate_structured(
            prompt=prompt,
            schema=_analysis_response_schema(
                self.project_root,
                contract_version=contract_version,
                product_kind=product_kind,
            ),
            images=[("Image 1: user product identity source", image)],
        )
        analysis_model = getattr(self.client, "last_used_model", None) or self.model
        analysis = response["analysis"]
        serving_state = analysis.get("identity", {}).get("serving_state")
        if isinstance(serving_state, dict):
            # The nested serving contract has its own fixed version. Some
            # structured-output providers mirror the parent analysis version
            # into nested objects despite the schema const; normalize the
            # internal contract before repository validation.
            serving_state["schema_version"] = "1.0.0"
        first_brand = analysis["identity"]["branding"]
        brand_crosscheck = "not_needed"
        if first_brand["state"] != "verified_absent":
            verification = self.client.generate_structured(
                prompt="""Independently verify branding in this product photo. Do not use likely
brand knowledge or autocomplete. Transcribe only directly visible characters, preserving every
space, punctuation mark and capitalization exactly. verified_present requires clearly observable
text or a non-text mark. uncertain is mandatory when any character or spacing is ambiguous.
verified_absent means no logo, lettering, label, symbol or brand-like mark is visible. Return only
the requested JSON.""",
                schema=_brand_response_schema(),
                images=[("Image 1: product source for independent brand verification", image)],
            )
            brand_crosscheck = _reconcile_brand_crosscheck(
                first_brand,
                verification,
            )
            if contract_version == "3.0.0" and brand_crosscheck == "disagreed":
                first_brand["applications"] = [
                    {
                        "state": "uncertain",
                        "material_family": None,
                        "application_medium": None,
                        "carrier_component": None,
                        "surface": None,
                        "bbox": None,
                        "confidence": min(
                            float(first_brand.get("confidence", 0)),
                            float(verification.get("confidence", 0)),
                        ),
                        "main_text": None,
                        "visible_text": list(first_brand.get("visible_text", [])),
                        "non_text_mark": None,
                    }
                ]
        analysis["schema_version"] = contract_version
        if contract_version == "3.0.0":
            analysis["product_kind"] = product_kind
        analysis["analysis_metadata"] = {
            "provider": "gemini_interactions",
            "model": analysis_model,
            "prompt_version": (
                PRODUCT_ANALYSIS_V3_PROMPT_VERSION
                if contract_version == "3.0.0"
                else PRODUCT_ANALYSIS_PROMPT_VERSION
            ),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "confidence": response["analysis_confidence"],
            "brand_crosscheck": brand_crosscheck,
        }
        analysis["source_binding"] = binding
        if contract_version == "2.0.0":
            self._apply_identity_override(analysis)
        self._validate(analysis, image)

        self._write_cache(cache_path, analysis)
        return analysis, False


def _reference_response_schema(project_root: Path) -> dict[str, Any]:
    reference_schema = deepcopy(
        load_json(project_root / "schemas/reference-asset.schema.json")
    )
    reference_schema.pop("$schema", None)
    reference_schema.pop("$id", None)
    definitions = reference_schema.pop("$defs")
    for field in ("analysis_metadata", "asset", "runtime_policy"):
        reference_schema["properties"].pop(field)
    reference_schema["required"] = [
        field
        for field in reference_schema["required"]
        if field not in {"analysis_metadata", "asset", "runtime_policy"}
    ]
    color = reference_schema["properties"]["color"]
    local_fields = {
        "palette_hex",
        "mean_luminance",
        "luminance_stddev",
        "mean_saturation",
        "edge_energy",
    }
    for field in local_fields:
        color["properties"].pop(field)
    color["required"] = [field for field in color["required"] if field not in local_fields]
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": definitions,
        "properties": {
            "analysis": reference_schema,
            "analysis_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
        },
        "required": ["analysis", "analysis_confidence"],
    }


def _reference_batch_response_schema(
    project_root: Path,
    asset_ids: Sequence[str],
) -> dict[str, Any]:
    response_schema = _reference_response_schema(project_root)
    item_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "asset_id": {"type": "string", "enum": list(asset_ids)},
            "analysis": response_schema["properties"]["analysis"],
            "analysis_confidence": response_schema["properties"][
                "analysis_confidence"
            ],
        },
        "required": ["asset_id", "analysis", "analysis_confidence"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": response_schema["$defs"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": len(asset_ids),
                "maxItems": len(asset_ids),
                "items": item_schema,
            }
        },
        "required": ["items"],
    }


def _detailed_scene_graph_response_schema(
    project_root: Path,
    asset_ids: Sequence[str],
) -> dict[str, Any]:
    del project_root  # Final v2 validation still uses the canonical on-disk schema.

    coordinate_array = {
        "type": "array",
        "minItems": 4,
        "maxItems": 4,
        "items": {"type": "number"},
    }
    nullable_coordinate_array = {
        "type": ["array", "null"],
        "minItems": 4,
        "maxItems": 4,
        "items": {"type": "number"},
    }
    nullable_point = {
        "type": ["array", "null"],
        "minItems": 2,
        "maxItems": 2,
        "items": {"type": "number"},
    }
    string_array = {"type": "array", "items": {"type": "string"}}
    scene_analysis = {
        "type": "object",
        "properties": {
            "objects": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "slot_id": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["beverage", "dessert", "prop", "support"],
                        },
                        "role": {
                            "type": "string",
                            "enum": ["primary", "secondary", "accent", "support"],
                        },
                        "description": {"type": "string"},
                        "body_bbox": coordinate_array,
                        "full_bbox": coordinate_array,
                        "straw_present": {"type": "boolean"},
                        "straw_bbox": nullable_coordinate_array,
                        "straw_centerline": nullable_coordinate_array,
                        "straw_emergence": nullable_point,
                        "straw_angle": {"type": ["number", "null"]},
                        "container_class": {"type": ["string", "null"]},
                        "container_material": {"type": ["string", "null"]},
                        "container_silhouette": {"type": ["string", "null"]},
                        "container_components": string_array,
                        "interaction": {
                            "type": "string",
                            "enum": [
                                "resting",
                                "held",
                                "touching",
                                "pouring",
                                "overlapping",
                                "background",
                                "other",
                            ],
                        },
                        "support_surface_id": {"type": ["string", "null"]},
                        "depth_order": {"type": "integer"},
                        "occlusion_fraction": {"type": "number"},
                        "visible_text": string_array,
                        "brand_state": {
                            "type": "string",
                            "enum": ["present", "absent", "uncertain"],
                        },
                    },
                    "required": [
                        "slot_id",
                        "kind",
                        "role",
                        "description",
                        "body_bbox",
                        "full_bbox",
                        "straw_present",
                        "straw_bbox",
                        "straw_centerline",
                        "straw_emergence",
                        "straw_angle",
                        "container_class",
                        "container_material",
                        "container_silhouette",
                        "container_components",
                        "interaction",
                        "support_surface_id",
                        "depth_order",
                        "occlusion_fraction",
                        "visible_text",
                        "brand_state",
                    ],
                },
            },
            "support_surfaces": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "surface_id": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": [
                                "table",
                                "counter",
                                "tray",
                                "plate",
                                "saucer",
                                "shelf",
                                "ground",
                                "held_carrier",
                                "other",
                            ],
                        },
                        "bbox": coordinate_array,
                        "description": {"type": "string"},
                        "supports_objects": {"type": "boolean"},
                        "perspective_scale": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 2,
                            "items": {"type": "number"},
                        },
                    },
                    "required": [
                        "surface_id",
                        "kind",
                        "bbox",
                        "description",
                        "supports_objects",
                        "perspective_scale",
                    ],
                },
            },
            "protected_regions": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "region_id": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": [
                                "hand",
                                "visible_text",
                                "watermark",
                                "occupied",
                                "shadow",
                                "negative_space",
                            ],
                        },
                        "bbox": coordinate_array,
                        "reason": {"type": "string"},
                    },
                    "required": ["region_id", "kind", "bbox", "reason"],
                },
            },
            "insertion_zones": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "zone_id": {"type": "string"},
                        "bbox": coordinate_array,
                        "support_surface_id": {"type": "string"},
                        "allowed_kinds": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["beverage", "dessert"],
                            },
                        },
                        "scale_range": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 2,
                            "items": {"type": "number"},
                        },
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "zone_id",
                        "bbox",
                        "support_surface_id",
                        "allowed_kinds",
                        "scale_range",
                        "confidence",
                        "reason",
                    ],
                },
            },
            "composition": {
                "type": "object",
                "properties": {
                    "shot_type": {"type": "string"},
                    "camera_height": {"type": "string"},
                    "camera_pitch": {"type": "string"},
                    "lens_character": {"type": "string"},
                    "subject_position": {"type": "string"},
                    "negative_space": {"type": "string"},
                    "asymmetry_source": {"type": "string"},
                    "crop_character": {"type": "string"},
                },
                "required": [
                    "shot_type",
                    "camera_height",
                    "camera_pitch",
                    "lens_character",
                    "subject_position",
                    "negative_space",
                    "asymmetry_source",
                    "crop_character",
                ],
            },
            "depth": {
                "type": "object",
                "properties": {
                    "plane_count": {"type": "integer"},
                    "foreground": {"type": "string"},
                    "product_plane": {"type": "string"},
                    "midground": {"type": "string"},
                    "background": {"type": "string"},
                    "perspective_cues": string_array,
                    "far_plane_softness": {"type": "string"},
                    "atmospheric_separation": {"type": "string"},
                },
                "required": [
                    "plane_count",
                    "foreground",
                    "product_plane",
                    "midground",
                    "background",
                    "perspective_cues",
                    "far_plane_softness",
                    "atmospheric_separation",
                ],
            },
            "lighting": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string"},
                    "direction": {"type": "string"},
                    "source_size": {"type": "string"},
                    "hardness": {"type": "number"},
                    "contrast": {"type": "number"},
                    "shadow": {"type": "string"},
                    "highlight": {"type": "string"},
                    "transmitted_light": {"type": "string"},
                    "white_balance": {"type": "string"},
                },
                "required": [
                    "source_type",
                    "direction",
                    "source_size",
                    "hardness",
                    "contrast",
                    "shadow",
                    "highlight",
                    "transmitted_light",
                    "white_balance",
                ],
            },
            "color": {
                "type": "object",
                "properties": {
                    "exposure": {"type": "string"},
                    "saturation": {"type": "string"},
                    "contrast": {"type": "string"},
                    "black_point": {"type": "string"},
                },
                "required": ["exposure", "saturation", "contrast", "black_point"],
            },
            "facets": {
                "type": "object",
                "properties": {
                    "mood_tags": string_array,
                    "environment_tags": string_array,
                    "material_tags": string_array,
                    "shot_tags": string_array,
                },
                "required": [
                    "mood_tags",
                    "environment_tags",
                    "material_tags",
                    "shot_tags",
                ],
            },
            "taxonomy": {
                "type": "object",
                "properties": {
                    "environment_family": {"type": "string"},
                    "lighting_family": {"type": "string"},
                    "camera_angle": {"type": "string"},
                    "capture_style": {"type": "string"},
                    "dominant_surface": {"type": "string"},
                    "wood_prominence": {"type": "number"},
                    "accent_color_prominence": {"type": "number"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "environment_family",
                    "lighting_family",
                    "camera_angle",
                    "capture_style",
                    "dominant_surface",
                    "wood_prominence",
                    "accent_color_prominence",
                    "confidence",
                ],
            },
            "quality_flags": string_array,
        },
        "required": [
            "objects",
            "support_surfaces",
            "protected_regions",
            "insertion_zones",
            "composition",
            "depth",
            "lighting",
            "color",
            "facets",
            "taxonomy",
            "quality_flags",
        ],
    }
    item_schema = {
        "type": "object",
        "properties": {
            "asset_id": {"type": "string", "enum": list(asset_ids)},
            "analysis": scene_analysis,
            "analysis_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
        },
        "required": ["asset_id", "analysis", "analysis_confidence"],
    }
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": len(asset_ids),
                "maxItems": len(asset_ids),
                "items": item_schema,
            }
        },
        "required": ["items"],
    }


def _scene_graph_response_schema(
    project_root: Path,
    asset_ids: Sequence[str],
) -> dict[str, Any]:
    """Keep Gemini's enforced schema shallow; validate the full contract locally."""
    del project_root
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": len(asset_ids),
                "maxItems": len(asset_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "asset_id": {"type": "string", "enum": list(asset_ids)},
                        "analysis": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "analysis_confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "major_subject_count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8,
                        },
                        "has_hand": {"type": "boolean"},
                        "has_scene_text": {"type": "boolean"},
                    },
                    "required": [
                        "asset_id",
                        "analysis",
                        "analysis_confidence",
                        "major_subject_count",
                        "has_hand",
                        "has_scene_text",
                    ],
                },
            }
        },
        "required": ["items"],
    }


def _clamp(value: Any, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, float(value)))


def _fraction(value: Any, *, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return _clamp(value, 0.0, 1.0)
    aliases = {
        "none": 0.0,
        "absent": 0.0,
        "trace": 0.1,
        "very_low": 0.12,
        "diffuse": 0.2,
        "low": 0.25,
        "soft": 0.28,
        "mild": 0.35,
        "standard": 0.45,
        "balanced": 0.45,
        "moderate": 0.55,
        "medium": 0.55,
        "medium_hard": 0.65,
        "moderately_hard": 0.65,
        "high": 0.75,
        "hard": 0.75,
        "very_hard": 0.9,
        "strong": 0.85,
        "full": 1.0,
    }
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip(
        "_"
    )
    return aliases.get(normalized, fallback)


def _choice(
    value: Any,
    allowed: Sequence[str],
    *,
    fallback: str,
    aliases: dict[str, str] | None = None,
) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip(
        "_"
    )
    normalized = (aliases or {}).get(normalized, normalized)
    return normalized if normalized in allowed else fallback


def _identifier(value: Any, *, prefix: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip(
        "_"
    )
    if not normalized:
        normalized = fallback
    if not normalized.startswith(prefix):
        normalized = f"{prefix}{normalized}"
    return normalized[:56].rstrip("_")


def _object_kind(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip(
        "_"
    )
    if normalized in {"beverage", "dessert", "prop", "support"}:
        return normalized
    if any(
        token in normalized
        for token in (
            "beverage",
            "drink",
            "coffee",
            "latte",
            "tea",
            "juice",
            "soda",
            "glass",
            "cup",
            "mug",
            "bottle",
        )
    ):
        return "beverage"
    if any(
        token in normalized
        for token in ("dessert", "cake", "pastry", "bread", "cookie", "croissant")
    ):
        return "dessert"
    return "prop"


def _string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [] if value is None else [value]
    return list(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )


def _number_pair(
    value: Any,
    *,
    default: tuple[float, float],
    minimum: float,
    maximum: float,
) -> tuple[float, float]:
    if isinstance(value, dict):
        candidates = [
            value.get("min", value.get("lower", value.get("near"))),
            value.get("max", value.get("upper", value.get("far"))),
        ]
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        candidates = [value[0], value[1]]
    elif isinstance(value, (int, float)):
        candidates = [value, value]
    else:
        candidates = list(default)
    try:
        first = _clamp(candidates[0], minimum, maximum)
        second = _clamp(candidates[1], minimum, maximum)
    except (TypeError, ValueError):
        first, second = default
    return min(first, second), max(first, second)


def _coordinate_from_compact(
    value: Any,
    *,
    axis_size: int | None,
) -> float:
    coordinate = float(value)
    if abs(coordinate) <= 1.5:
        return _clamp(coordinate, 0.0, 1.0)
    if abs(coordinate) <= 1000:
        return _clamp(coordinate / 1000, 0.0, 1.0)
    if axis_size is None:
        raise ValueError("Pixel scene coordinate requires source image dimensions")
    return _clamp(coordinate / axis_size, 0.0, 1.0)


def _bbox_from_compact(
    value: Any,
    *,
    confidence: float,
    image_size: tuple[int, int] | None = None,
) -> dict[str, float]:
    if isinstance(value, dict):
        value = [
            value.get("left"),
            value.get("top"),
            value.get("right"),
            value.get("bottom"),
        ]
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Compact scene bbox must contain four coordinates")
    width = image_size[0] if image_size is not None else None
    height = image_size[1] if image_size is not None else None
    try:
        left = _coordinate_from_compact(value[0], axis_size=width)
        top = _coordinate_from_compact(value[1], axis_size=height)
        right = _coordinate_from_compact(value[2], axis_size=width)
        bottom = _coordinate_from_compact(value[3], axis_size=height)
    except (TypeError, ValueError) as exc:
        raise ValueError("Compact scene bbox contains non-numeric coordinates") from exc
    if right - left < 0.002 or bottom - top < 0.002:
        raise ValueError("Compact scene bbox has no usable area")
    return {
        "left": round(left, 4),
        "top": round(top, 4),
        "right": round(right, 4),
        "bottom": round(bottom, 4),
        "confidence": round(_clamp(confidence, 0.0, 1.0), 4),
    }


def _point_from_compact(
    value: Any,
    *,
    image_size: tuple[int, int] | None = None,
) -> dict[str, float] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y")]
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Compact scene point must contain two coordinates")
    width = image_size[0] if image_size is not None else None
    height = image_size[1] if image_size is not None else None
    x = _coordinate_from_compact(value[0], axis_size=width)
    y = _coordinate_from_compact(value[1], axis_size=height)
    return {
        "x": round(_clamp(x, 0.0, 1.0), 4),
        "y": round(_clamp(y, 0.0, 1.0), 4),
    }


def _centerline_from_compact(
    value: Any,
    *,
    image_size: tuple[int, int] | None = None,
) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list) and len(value) == 2:
        first = _point_from_compact(value[0], image_size=image_size)
        second = _point_from_compact(value[1], image_size=image_size)
        if first is not None and second is not None:
            return [first["x"], first["y"], second["x"], second["y"]]
    if isinstance(value, list) and len(value) == 4:
        try:
            first = _point_from_compact(value[:2], image_size=image_size)
            second = _point_from_compact(value[2:], image_size=image_size)
            if first is not None and second is not None:
                return [first["x"], first["y"], second["x"], second["y"]]
        except (TypeError, ValueError):
            return None
    return None


def _union_bbox(first: dict[str, float], second: dict[str, float]) -> dict[str, float]:
    return {
        "left": min(first["left"], second["left"]),
        "top": min(first["top"], second["top"]),
        "right": max(first["right"], second["right"]),
        "bottom": max(first["bottom"], second["bottom"]),
        "confidence": min(first["confidence"], second["confidence"]),
    }


def _derived_relations(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for first, second in combinations(objects, 2):
        first_box = first["body_bbox"]
        second_box = second["body_bbox"]
        first_x = (first_box["left"] + first_box["right"]) / 2
        second_x = (second_box["left"] + second_box["right"]) / 2
        if abs(first_x - second_x) >= 0.04:
            left, right = (first, second) if first_x < second_x else (second, first)
            relations.append(
                {
                    "from_slot_id": left["slot_id"],
                    "predicate": "left_of",
                    "to_slot_id": right["slot_id"],
                    "confidence": 0.84,
                }
            )
        if first["depth_order"] != second["depth_order"]:
            front, rear = (
                (first, second)
                if first["depth_order"] < second["depth_order"]
                else (second, first)
            )
            relations.append(
                {
                    "from_slot_id": front["slot_id"],
                    "predicate": "in_front_of",
                    "to_slot_id": rear["slot_id"],
                    "confidence": 0.78,
                }
            )
        if first["kind"] in {"beverage", "dessert"} and second["kind"] in {
            "beverage",
            "dessert",
        }:
            relations.append(
                {
                    "from_slot_id": first["slot_id"],
                    "predicate": "paired_with",
                    "to_slot_id": second["slot_id"],
                    "confidence": 0.75,
                }
            )
        if len(relations) >= 24:
            break
    return relations[:24]


def _hydrate_scene_graph_analysis(
    compact: dict[str, Any],
    *,
    confidence: float,
    image_size: tuple[int, int],
) -> dict[str, Any]:
    bbox_confidence = max(0.5, min(0.96, confidence))
    surface_ids: dict[str, str] = {}
    surfaces = []
    for index, source in enumerate(compact["support_surfaces"], 1):
        surface_id = _identifier(
            source.get("surface_id"),
            prefix="surface_",
            fallback=f"surface_{index:02d}",
        )
        while surface_id in surface_ids.values():
            surface_id = f"{surface_id}_{index:02d}"
        surface_ids[str(source.get("surface_id"))] = surface_id
        lower, upper = _number_pair(
            source.get("perspective_scale"),
            default=(0.75, 1.15),
            minimum=0.001,
            maximum=2.0,
        )
        surfaces.append(
            {
                "surface_id": surface_id,
                "kind": _choice(
                    source.get("kind"),
                    (
                        "table",
                        "counter",
                        "tray",
                        "plate",
                        "saucer",
                        "shelf",
                        "ground",
                        "held_carrier",
                        "other",
                    ),
                    fallback="other",
                    aliases={
                        "molded_fiber_carrier": "held_carrier",
                        "cardboard_carrier": "held_carrier",
                        "drink_carrier": "held_carrier",
                        "human_body": "held_carrier",
                        "wood_tray": "tray",
                        "serving_tray": "tray",
                    },
                ),
                "bbox": _bbox_from_compact(
                    source["bbox"],
                    confidence=bbox_confidence,
                    image_size=image_size,
                ),
                "plane_description": str(source.get("description") or "").strip()
                or "visible support plane",
                "supports_objects": bool(source["supports_objects"]),
                "perspective_scale": [round(min(lower, upper), 4), round(max(lower, upper), 4)],
            }
        )

    objects = []
    hydration_flags: list[str] = []
    seen_slots: set[str] = set()
    for index, source in enumerate(compact["objects"], 1):
        slot_id = _identifier(
            source.get("slot_id"), prefix="", fallback=f"object_{index:02d}"
        )
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,48}", slot_id):
            slot_id = f"object_{index:02d}"
        while slot_id in seen_slots:
            slot_id = f"{slot_id[:43]}_{index:02d}"
        seen_slots.add(slot_id)
        kind = _object_kind(source.get("kind"))
        body = _bbox_from_compact(
            source["body_bbox"],
            confidence=bbox_confidence,
            image_size=image_size,
        )
        full = _bbox_from_compact(
            source["full_bbox"],
            confidence=bbox_confidence,
            image_size=image_size,
        )
        full = _union_bbox(full, body)
        straw_present = bool(source["straw_present"] and kind == "beverage")
        straw_bbox = None
        centerline = None
        emergence = None
        angle = None
        if straw_present:
            raw_bbox = source.get("straw_bbox")
            line = _centerline_from_compact(
                source.get("straw_centerline"), image_size=image_size
            )
            if line is None and raw_bbox is not None:
                normalized_straw_box = _bbox_from_compact(
                    raw_bbox,
                    confidence=bbox_confidence,
                    image_size=image_size,
                )
                left = normalized_straw_box["left"]
                top = normalized_straw_box["top"]
                right = normalized_straw_box["right"]
                bottom = normalized_straw_box["bottom"]
                center = (float(left) + float(right)) / 2
                line = [center, float(bottom), center, float(top)]
            if raw_bbox is None and line is not None:
                lower_x, lower_y, tip_x, tip_y = (float(value) for value in line)
                padding = 0.006
                raw_bbox = [
                    min(lower_x, tip_x) - padding,
                    min(lower_y, tip_y) - padding,
                    max(lower_x, tip_x) + padding,
                    max(lower_y, tip_y) + padding,
                ]
            if line is None or raw_bbox is None:
                straw_present = False
                hydration_flags.append("incomplete_straw_geometry_dropped")
            else:
                straw_bbox = _bbox_from_compact(
                    raw_bbox,
                    confidence=bbox_confidence,
                    image_size=image_size,
                )
        if straw_present:
            line = _centerline_from_compact(
                source.get("straw_centerline"), image_size=image_size
            )
            if line is None:
                normalized_straw_box = _bbox_from_compact(
                    source["straw_bbox"],
                    confidence=bbox_confidence,
                    image_size=image_size,
                )
                left = normalized_straw_box["left"]
                top = normalized_straw_box["top"]
                right = normalized_straw_box["right"]
                bottom = normalized_straw_box["bottom"]
                center = (float(left) + float(right)) / 2
                line = [center, float(bottom), center, float(top)]
            centerline = [
                _point_from_compact(line[:2], image_size=image_size),
                _point_from_compact(line[2:], image_size=image_size),
            ]
            emergence = _point_from_compact(
                source.get("straw_emergence"), image_size=image_size
            )
            if emergence is None:
                emergence = deepcopy(centerline[0])
                hydration_flags.append("straw_emergence_derived")
            raw_angle = source.get("straw_angle")
            if raw_angle is None:
                delta_x = centerline[1]["x"] - centerline[0]["x"]
                delta_y = centerline[1]["y"] - centerline[0]["y"]
                raw_angle = math.degrees(math.atan2(delta_y, delta_x))
                hydration_flags.append("straw_angle_derived")
            angle = round(_clamp(raw_angle, -180.0, 180.0), 2)
            full = _union_bbox(full, straw_bbox)
        container = None
        if kind == "beverage":
            container = {
                "class": (source.get("container_class") or "unknown beverage vessel").strip(),
                "material": (source.get("container_material") or "unknown material").strip(),
                "silhouette": (source.get("container_silhouette") or "visible vessel silhouette").strip(),
                "components": _string_list(source.get("container_components")),
            }
        margin = 0.02
        crop_safe = (
            body["left"] >= margin
            and body["right"] <= 1 - margin
            and body["top"] >= margin
            and body["bottom"] <= 1 - margin
        )
        occlusion = _fraction(source.get("occlusion_fraction"), fallback=0.15)
        interaction = _choice(
            source.get("interaction"),
            (
                "resting",
                "held",
                "touching",
                "pouring",
                "overlapping",
                "background",
                "other",
            ),
            fallback="other",
            aliases={
                "held_in_carrier": "held",
                "held_by_hand": "held",
                "on_table": "resting",
                "placed": "resting",
                "none": "resting",
            },
        )
        support_id = surface_ids.get(str(source.get("support_surface_id")))
        replaceable = (
            kind in {"beverage", "dessert"}
            and interaction != "pouring"
            and occlusion <= 0.65
        )
        allowed_kinds = [kind] if kind in {"beverage", "dessert", "prop"} else []
        if (
            replaceable
            and crop_safe
            and support_id is not None
            and interaction not in {"held", "pouring"}
            and occlusion <= 0.2
        ):
            allowed_kinds = ["beverage", "dessert"]
        objects.append(
            {
                "slot_id": slot_id,
                "kind": kind,
                "role": _choice(
                    source.get("role"),
                    ("primary", "secondary", "accent", "support"),
                    fallback="accent"
                    if kind not in {"beverage", "dessert"}
                    else "secondary",
                    aliases={
                        "main": "primary",
                        "main_subject": "primary",
                        "hero": "primary",
                        "subject": "primary",
                        "secondary_subject": "secondary",
                    },
                ),
                "description": str(source.get("description") or "").strip()
                or f"visible {kind}",
                "body_bbox": body,
                "full_bbox": full,
                "straw": {
                    "present": straw_present,
                    "bbox": straw_bbox,
                    "centerline": centerline,
                    "emergence_point": emergence,
                    "angle_degrees": angle,
                },
                "container": container,
                "interaction": interaction,
                "support_surface_id": support_id,
                "depth_order": int(_clamp(source["depth_order"], 0, 20)),
                "occlusion_fraction": round(occlusion, 4),
                "replaceable": replaceable,
                "allowed_kinds": allowed_kinds,
                "visible_text": _string_list(source.get("visible_text")),
                "brand_or_watermark_state": _choice(
                    source.get("brand_state"),
                    ("present", "absent", "uncertain"),
                    fallback="uncertain",
                    aliases={
                        "visible": "present",
                        "none": "absent",
                        "partial": "uncertain",
                    },
                ),
                "crop_safe": crop_safe,
            }
        )

    protected_regions = []
    seen_region_ids: set[str] = set()
    for index, source in enumerate(compact["protected_regions"], 1):
        try:
            box = _bbox_from_compact(
                source["bbox"],
                confidence=bbox_confidence,
                image_size=image_size,
            )
        except (TypeError, ValueError):
            continue
        region_id = _identifier(
            source.get("region_id"),
            prefix="region_",
            fallback=f"region_{index:02d}",
        )
        while region_id in seen_region_ids:
            region_id = f"{region_id[:51]}_{index:02d}"
        seen_region_ids.add(region_id)
        protected_regions.append(
            {
                "region_id": region_id,
                "kind": _choice(
                    source.get("kind"),
                    (
                        "hand",
                        "visible_text",
                        "watermark",
                        "occupied",
                        "shadow",
                        "negative_space",
                    ),
                    fallback="occupied",
                    aliases={
                        "human_hand": "hand",
                        "human": "hand",
                        "anatomy": "hand",
                        "text": "visible_text",
                        "clothing": "occupied",
                        "accessory": "occupied",
                    },
                ),
                "bbox": box,
                "reason": source["reason"].strip() or "protected visible region",
            }
        )

    insertion_zones = []
    seen_zone_ids: set[str] = set()
    for index, source in enumerate(compact["insertion_zones"], 1):
        surface_id = surface_ids.get(str(source.get("support_surface_id")))
        if surface_id is None:
            continue
        try:
            box = _bbox_from_compact(
                source["bbox"],
                confidence=bbox_confidence,
                image_size=image_size,
            )
        except (TypeError, ValueError):
            continue
        lower, upper = _number_pair(
            source.get("scale_range"),
            default=(0.7, 1.0),
            minimum=0.001,
            maximum=2.0,
        )
        zone_id = _identifier(
            source.get("zone_id"),
            prefix="zone_",
            fallback=f"zone_{index:02d}",
        )
        while zone_id in seen_zone_ids:
            zone_id = f"{zone_id[:53]}_{index:02d}"
        seen_zone_ids.add(zone_id)
        insertion_zones.append(
            {
                "zone_id": zone_id,
                "bbox": box,
                "support_surface_id": surface_id,
                "allowed_kinds": [
                    value
                    for value in _string_list(source.get("allowed_kinds"))
                    if value in {"beverage", "dessert"}
                ]
                or ["beverage"],
                "scale_range": [round(min(lower, upper), 4), round(max(lower, upper), 4)],
                "confidence": round(
                    _fraction(source.get("confidence"), fallback=0.55), 4
                ),
                "reason": str(source.get("reason") or "").strip()
                or "visible empty support area",
            }
        )

    major_objects = [
        item for item in objects if item["kind"] in {"beverage", "dessert"}
    ]
    primary_major = [item for item in major_objects if item["role"] == "primary"]
    if major_objects:
        primary = max(
            primary_major or major_objects,
            key=lambda item: (
                (item["body_bbox"]["right"] - item["body_bbox"]["left"])
                * (item["body_bbox"]["bottom"] - item["body_bbox"]["top"]),
                -item["depth_order"],
            ),
        )
        for item in major_objects:
            item["role"] = "primary" if item is primary else "secondary"

    taxonomy = deepcopy(compact["taxonomy"])
    taxonomy["environment_family"] = _choice(
        taxonomy["environment_family"],
        (
            "white_neutral",
            "warm_wood",
            "point_color",
            "modern_mineral",
            "vintage_warm",
            "dark_moody",
            "mixed_other",
        ),
        fallback="mixed_other",
        aliases={
            "white": "white_neutral",
            "wood": "warm_wood",
            "indoor_neutral": "white_neutral",
            "neutral_interior": "white_neutral",
            "indoor_bright": "white_neutral",
            "minimal_interior": "white_neutral",
            "minimal_studio": "white_neutral",
            "minimalist_cafe": "white_neutral",
            "outdoor_wall": "white_neutral",
            "rustic_interior": "vintage_warm",
            "rustic_cafe": "vintage_warm",
            "warm_vintage": "vintage_warm",
            "wood_interior": "warm_wood",
            "wooden_interior": "warm_wood",
            "color_accent": "point_color",
            "accent_color": "point_color",
            "concrete_interior": "modern_mineral",
            "industrial_minimal": "modern_mineral",
            "modern_industrial": "modern_mineral",
        },
    )
    taxonomy["lighting_family"] = _choice(
        taxonomy["lighting_family"],
        ("direct_sun", "soft_window", "overcast", "warm_ambient", "mixed"),
        fallback="mixed",
        aliases={
            "window": "soft_window",
            "soft_diffuse": "soft_window",
            "ambient_natural": "soft_window",
            "natural_light": "soft_window",
            "natural_window": "soft_window",
            "window_light": "soft_window",
            "ambient_diffuse": "soft_window",
            "flat_even": "soft_window",
            "natural_hard": "direct_sun",
            "hard_sunlight": "direct_sun",
            "natural_sunlight": "direct_sun",
        },
    )
    taxonomy["camera_angle"] = _choice(
        taxonomy["camera_angle"],
        ("eye_level", "slightly_above", "high_angle", "overhead"),
        fallback="slightly_above",
        aliases={"top_down": "overhead"},
    )
    taxonomy["capture_style"] = _choice(
        taxonomy["capture_style"],
        ("held_product", "tabletop", "closeup", "group", "overflow"),
        fallback="tabletop",
        aliases={
            "held": "held_product",
            "first_person": "held_product",
            "minimalist": "tabletop",
            "minimal": "tabletop",
            "minimalist_product": "tabletop",
            "cinematic_photography": "tabletop",
            "candid": "group",
        },
    )
    for field, fallback in (
        ("wood_prominence", 0.0),
        ("accent_color_prominence", 0.15),
        ("confidence", confidence),
    ):
        taxonomy[field] = round(_fraction(taxonomy.get(field), fallback=fallback), 4)
    lighting = deepcopy(compact["lighting"])
    lighting["source_type"] = _choice(
        lighting["source_type"],
        ("direct_sun", "soft_window", "overcast", "artificial_warm", "mixed", "unknown"),
        fallback="unknown",
        aliases={
            "window": "soft_window",
            "daylight": "soft_window",
            "window_light": "soft_window",
            "window_blinds": "soft_window",
            "natural_window": "soft_window",
            "natural_light": "soft_window",
            "natural_sunlight": "direct_sun",
            "sunlight": "direct_sun",
            "hard_sunlight": "direct_sun",
            "artificial_ambient": "mixed",
            "indoor_ambient": "mixed",
            "ambient": "mixed",
        },
    )
    lighting["source_size"] = _choice(
        lighting["source_size"],
        ("small", "medium", "large", "unknown"),
        fallback="unknown",
        aliases={
            "broad": "large",
            "very_large": "large",
            "large_diffuse": "large",
            "compact": "small",
        },
    )
    lighting["white_balance"] = _choice(
        lighting["white_balance"],
        ("cool", "neutral", "slightly_warm", "warm", "mixed"),
        fallback="neutral",
    )
    lighting["hardness"] = round(
        _fraction(lighting.get("hardness"), fallback=0.35), 4
    )
    lighting["contrast"] = round(
        _fraction(lighting.get("contrast"), fallback=0.45), 4
    )
    depth = deepcopy(compact["depth"])
    depth["plane_count"] = int(_clamp(depth["plane_count"], 1, 5))
    depth["perspective_cues"] = _string_list(depth.get("perspective_cues")) or [
        "visible plane separation"
    ]
    depth["far_plane_softness"] = _choice(
        depth["far_plane_softness"],
        ("none", "subtle", "moderate", "strong"),
        fallback="subtle",
        aliases={"mild": "subtle", "medium": "moderate"},
    )
    depth["atmospheric_separation"] = _choice(
        depth["atmospheric_separation"],
        ("none", "trace", "mild", "strong"),
        fallback="trace",
        aliases={"subtle": "trace", "moderate": "mild"},
    )
    composition = deepcopy(compact["composition"])
    composition["shot_type"] = _choice(
        composition["shot_type"],
        ("handheld", "tabletop", "overhead", "closeup", "group", "overflow", "other"),
        fallback="other",
        aliases={
            "medium_close_up": "closeup",
            "medium_closeup": "closeup",
            "top_down_angle": "overhead",
            "flat_lay": "overhead",
        },
    )
    composition["camera_height"] = _choice(
        composition["camera_height"],
        ("low", "product_level", "slightly_above", "high", "overhead"),
        fallback="slightly_above",
        aliases={"eye_level": "product_level", "top_down": "overhead"},
    )
    composition["lens_character"] = _choice(
        composition["lens_character"],
        ("phone_wide", "phone_normal", "phone_mild_tele", "unknown"),
        fallback="unknown",
        aliases={"wide": "phone_wide", "normal": "phone_normal"},
    )
    color = deepcopy(compact["color"])
    color["exposure"] = _choice(
        color["exposure"],
        ("dark", "low", "balanced", "bright", "high_key"),
        fallback="balanced",
        aliases={"normal": "balanced"},
    )
    color["saturation"] = _choice(
        color["saturation"],
        ("muted", "restrained", "natural", "vivid"),
        fallback="natural",
        aliases={"neutral": "natural", "vibrant": "vivid"},
    )
    color["contrast"] = _choice(
        color["contrast"],
        ("low", "soft", "medium", "strong"),
        fallback="medium",
        aliases={"standard": "medium", "moderate": "medium"},
    )
    color["black_point"] = _choice(
        color["black_point"],
        ("lifted", "natural", "deep"),
        fallback="natural",
        aliases={"elevated": "lifted", "raised": "lifted", "normal": "natural"},
    )
    facets = deepcopy(compact["facets"])
    for field in ("mood_tags", "environment_tags", "material_tags", "shot_tags"):
        facets[field] = _string_list(facets.get(field)) or ["unspecified"]
    return {
        "objects": objects,
        "relations": _derived_relations(objects),
        "support_surfaces": surfaces,
        "protected_regions": protected_regions,
        "insertion_zones": insertion_zones,
        "composition": composition,
        "depth": depth,
        "lighting": lighting,
        "color": color,
        "facets": facets,
        "taxonomy": taxonomy,
        "quality_flags": list(
            dict.fromkeys([*_string_list(compact.get("quality_flags")), *hydration_flags])
        ),
    }


def _legacy_frontend_mood(taxonomy: dict[str, Any]) -> str:
    family = taxonomy["environment_family"]
    if family == "warm_wood" and taxonomy["wood_prominence"] >= 0.55:
        return "wood"
    if family == "vintage_warm" and taxonomy["wood_prominence"] >= 0.55:
        return "wood"
    if family in {"point_color", "dark_moody"} or taxonomy[
        "accent_color_prominence"
    ] >= 0.55:
        return "point_color"
    return "white"


class GeminiReferenceAnalyzer:
    def __init__(
        self,
        *,
        project_root: str | Path,
        reference_root: str | Path,
        cache_root: str | Path = "outputs/analysis-cache/reference",
        model: str | None = None,
        fallback_models: Sequence[str] | None = None,
        timeout_seconds: float = 180,
        maximum_image_edge: int = 1024,
        thinking_level: str = "low",
        client: GeminiInteractionsClient | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.reference_root = Path(reference_root).expanduser().resolve()
        configured_cache = Path(cache_root)
        self.cache_root = (
            configured_cache
            if configured_cache.is_absolute()
            else self.project_root / configured_cache
        )
        self.model = model or os.environ.get(
            "GEMINI_REFERENCE_ANALYZER_MODEL", "gemini-3.1-flash-lite"
        )
        self.fallback_models = tuple(fallback_models or ())
        self.client = client or GeminiInteractionsClient(
            model=self.model,
            model_candidates=(self.model, *self.fallback_models),
            timeout_seconds=timeout_seconds,
            maximum_image_edge=maximum_image_edge,
            thinking_level=thinking_level,
        )

    def _cache_path(self, asset: dict[str, Any]) -> Path:
        key_payload = json.dumps(
            {
                "pixel_sha256": asset["pixel_sha256"],
                "asset_id": asset["asset_id"],
                "model": self.model,
                "prompt_version": REFERENCE_ANALYSIS_PROMPT_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        key = hashlib.sha256(key_payload).hexdigest()
        return self.cache_root / asset["pixel_sha256"][:2] / f"{key}.json"

    def _validate(self, reference: dict[str, Any]) -> None:
        validate_json(
            reference,
            "reference-asset.schema.json",
            project_root=self.project_root,
        )
        validate_reference_geometry(reference)

    def analyze(
        self,
        image_path: str | Path,
        *,
        use_cache: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        return self.analyze_many([image_path], use_cache=use_cache)[0]

    def analyze_many(
        self,
        image_paths: Sequence[str | Path],
        *,
        use_cache: bool = True,
    ) -> list[tuple[dict[str, Any], bool]]:
        if len(image_paths) > 8:
            raise ValueError("Gemini reference batches support at most 8 images")
        if not image_paths:
            return []

        records: list[dict[str, Any]] = []
        asset_ids: list[str] = []
        for index, image_path in enumerate(image_paths):
            image = Path(image_path).expanduser().resolve()
            asset = inspect_reference_asset(image, reference_root=self.reference_root)
            local_metrics = asset.pop("local_color_metrics")
            asset_id = asset["asset_id"]
            asset_ids.append(asset_id)
            records.append(
                {
                    "index": index,
                    "image": image,
                    "asset": asset,
                    "local_metrics": local_metrics,
                    "cache_path": self._cache_path(asset),
                }
            )
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("Gemini reference batch contains duplicate input asset_id values")

        results: list[tuple[dict[str, Any], bool] | None] = [None] * len(records)
        uncached: list[dict[str, Any]] = []
        for record in records:
            cache_path = record["cache_path"]
            if use_cache and cache_path.is_file():
                cached = load_json(cache_path)
                if (
                    cached["asset"]["pixel_sha256"]
                    != record["asset"]["pixel_sha256"]
                    or cached["asset"]["asset_id"] != record["asset"]["asset_id"]
                ):
                    raise ValueError("Cached reference analysis is bound to different pixels")
                self._validate(cached)
                results[record["index"]] = (cached, True)
            else:
                uncached.append(record)

        if uncached:
            prompt = """Analyze every labeled cafe-photo reference as a separate abstract,
reusable scene contract. Return exactly one item for each supplied asset_id and copy each
asset_id exactly. Use concise but specific English. Do not recommend copying the exact scene,
hand anatomy, branding, props, wall marks or shadow silhouette. Extract composition, camera
relationship, physical lighting, color behavior and real spatial depth so a NEW original
smartphone photo can be generated with a similar visual feeling.

Geometry uses normalized 0..1 coordinates. container_bbox includes the cup or glass body,
lid and sleeve but excludes straw, garnish and hand. subject_bbox includes the complete drink
product including straw and garnish but excludes hand. If a straw exists, return its separate
bbox, lower-to-upper two-point centerline, lid emergence point and angle. If absent, every straw
geometry field is null.

Depth must distinguish physical planes and perspective cues from blur. Treat uniform Gaussian
blur, portrait cutout edges, exaggerated DSLR bokeh or a foggy wash as quality problems. A good
natural phone image may have only subtle distance-dependent loss of fine detail. Lighting must
describe a single physically coherent source, shadow edge, highlight and glass transmission.

Folder names are not evidence and are not supplied. Classify only visible facts. Report all
visible text or marks so the runtime can explicitly exclude them. Return only requested JSON."""
            requested_ids = [record["asset"]["asset_id"] for record in uncached]
            response = self.client.generate_structured(
                prompt=prompt,
                schema=_reference_batch_response_schema(
                    self.project_root,
                    requested_ids,
                ),
                images=[
                    (
                        f"Reference asset_id={record['asset']['asset_id']}",
                        record["image"],
                    )
                    for record in uncached
                ],
            )
            items = response.get("items")
            if not isinstance(items, list):
                raise ValueError("Gemini reference batch response must contain an items array")
            returned_ids = [
                item.get("asset_id") if isinstance(item, dict) else None for item in items
            ]
            duplicates = sorted(
                {
                    asset_id
                    for asset_id in returned_ids
                    if asset_id is not None and returned_ids.count(asset_id) > 1
                }
            )
            if duplicates:
                raise ValueError(
                    "Gemini reference batch returned duplicate asset_id values: "
                    + ", ".join(duplicates)
                )
            missing = sorted(set(requested_ids) - set(returned_ids))
            unexpected = sorted(
                str(asset_id) for asset_id in set(returned_ids) - set(requested_ids)
            )
            if missing or unexpected:
                raise ValueError(
                    "Gemini reference batch asset_id mismatch; "
                    f"missing={missing}, unexpected={unexpected}"
                )

            by_id = {item["asset_id"]: item for item in items}
            actual_model = getattr(self.client, "last_used_model", None) or self.model
            for record in uncached:
                item = by_id[record["asset"]["asset_id"]]
                reference = item["analysis"]
                reference["schema_version"] = "1.0.0"
                reference["analysis_metadata"] = {
                    "provider": "gemini_interactions",
                    "model": actual_model,
                    "prompt_version": REFERENCE_ANALYSIS_PROMPT_VERSION,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "confidence": item["analysis_confidence"],
                }
                reference["asset"] = record["asset"]
                reference["color"].update(record["local_metrics"])
                reference["runtime_policy"] = {
                    "scene_pixels_allowed": False,
                    "container_pixels_allowed": True,
                    "copy_exclusions": [
                        "exact background layout and wall marks",
                        "exact prop arrangement and crop",
                        "visible text, logos and watermarks",
                        "exact hand anatomy and pose",
                        "exact shadow silhouette",
                    ],
                }
                self._validate(reference)
                cache_path = record["cache_path"]
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(reference, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, cache_path)
                results[record["index"]] = (reference, False)

        if any(result is None for result in results):
            raise RuntimeError("Gemini reference batch left an input without a result")
        return [result for result in results if result is not None]


class GeminiSceneGraphAnalyzer:
    """Lite-first, batched analyzer for the multi-object reference sidecar."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        reference_root: str | Path,
        cache_root: str | Path = "outputs/analysis-cache/reference-v2",
        model: str | None = None,
        fallback_models: Sequence[str] | None = None,
        timeout_seconds: float = 180,
        maximum_image_edge: int = 768,
        thinking_level: str = "minimal",
        force_refresh_results: bool = False,
        client: GeminiInteractionsClient | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.reference_root = Path(reference_root).expanduser().resolve()
        configured_cache = Path(cache_root)
        self.cache_root = (
            configured_cache
            if configured_cache.is_absolute()
            else self.project_root / configured_cache
        )
        self.model = model or os.environ.get(
            "GEMINI_REFERENCE_SCENE_ANALYZER_MODEL", "gemini-3.1-flash-lite"
        )
        self.fallback_models = tuple(fallback_models or ())
        self.force_refresh_results = force_refresh_results
        self.client = client or GeminiInteractionsClient(
            model=self.model,
            model_candidates=(self.model, *self.fallback_models),
            timeout_seconds=timeout_seconds,
            maximum_image_edge=maximum_image_edge,
            thinking_level=thinking_level,
        )

    def _cache_path(self, asset: dict[str, Any]) -> Path:
        payload = json.dumps(
            {
                "pixel_sha256": asset["pixel_sha256"],
                "asset_id": asset["asset_id"],
                "model": self.model,
                "prompt_version": REFERENCE_SCENE_GRAPH_EXTRACTOR_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        key = hashlib.sha256(payload).hexdigest()
        return self.cache_root / asset["pixel_sha256"][:2] / f"{key}.json"

    def _validate(self, graph: dict[str, Any]) -> None:
        validate_scene_graph(graph, project_root=str(self.project_root))

    def analyze(
        self,
        image_path: str | Path,
        *,
        use_cache: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        return self.analyze_many([image_path], use_cache=use_cache)[0]

    def analyze_many(
        self,
        image_paths: Sequence[str | Path],
        *,
        use_cache: bool = True,
    ) -> list[tuple[dict[str, Any], bool]]:
        if len(image_paths) > 8:
            raise ValueError("Gemini scene-graph batches support at most 8 images")
        if not image_paths:
            return []

        records: list[dict[str, Any]] = []
        asset_ids: list[str] = []
        for index, image_path in enumerate(image_paths):
            image = Path(image_path).expanduser().resolve()
            asset = inspect_reference_asset(image, reference_root=self.reference_root)
            local_metrics = asset.pop("local_color_metrics")
            asset_ids.append(asset["asset_id"])
            cache_path = self._cache_path(asset)
            records.append(
                {
                    "index": index,
                    "image": image,
                    "asset": asset,
                    "local_metrics": local_metrics,
                    "cache_path": cache_path,
                    "raw_path": cache_path.with_suffix(".raw.json"),
                }
            )
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("Gemini scene-graph batch contains duplicate asset_id values")

        results: list[tuple[dict[str, Any], bool] | None] = [None] * len(records)
        uncached: list[dict[str, Any]] = []
        for record in records:
            cache_path = record["cache_path"]
            if (
                use_cache
                and not self.force_refresh_results
                and cache_path.is_file()
            ):
                cached = load_json(cache_path)
                if (
                    cached["asset"]["pixel_sha256"]
                    != record["asset"]["pixel_sha256"]
                    or cached["asset"]["asset_id"] != record["asset"]["asset_id"]
                ):
                    raise ValueError("Cached scene graph is bound to different pixels")
                self._validate(cached)
                results[record["index"]] = (cached, True)
            else:
                uncached.append(record)

        if uncached:
            prompt = """Analyze every labeled cafe reference independently as a reusable scene
graph for an original smartphone-photo restyling service. Return exactly one item per asset_id.
Use concise English and copy every asset_id exactly. The reference pixels are offline analysis
only: never recommend reproducing its exact products, branding, hand anatomy, prop arrangement,
wall marks, crop, or shadow silhouette.

First scan the full frame in a 3x3 grid, including partially occluded back rows and edge crops.
Set major_subject_count to every visibly distinct beverage or dessert. Then return exactly that
many beverage/dessert objects; do not stop after the front row or merge overlapping cups. Set
has_hand and has_scene_text from the entire frame, including poster text and small cup marks. If
the scene contains more than eight major subjects, set the count to 8 as an overflow sentinel and
return up to eight representative objects without inventing hidden geometry.

List every visible beverage and dessert as a separate object. Add only compositionally meaningful
props or supports. Give each object a unique provisional snake_case slot_id; the service will
canonicalize IDs later. Every bbox is the compact array [left, top, right, bottom]. body_bbox is the
physical cup/dessert body without straw, garnish, hand or arm. full_bbox includes that object's
straw and garnish but still excludes hands. A straw centerline is [lower_x, lower_y, tip_x, tip_y]
and its emergence point is [x, y]. A missing straw requires null for every straw geometry field.
Do not merge two drinks, or a drink and dessert, into one box. Hands are protected_regions, not
product objects. The service derives replaceability, allowed replacement kinds, crop safety and
object relations locally; report visible evidence rather than trying to make those policy choices.

For each object, report its visible interaction, support surface, front-to-back depth order and
occlusion. Describe held, pouring, severely occluded and crop-cut evidence precisely. The service
derives replaceability and allowed replacement kinds after extraction. Relations describe only
clearly visible object relationships.

Support surfaces and insertion zones use normalized 0..1 boxes. Propose at most three insertion
zones only when an actually empty, crop-safe support area exists. Exclude products, hands, text,
important shadows, and intentionally beautiful negative space. Do not invent a zone when unsure.

Taxonomy has independent axes. A small wooden chair edge does not make a scene warm_wood:
wood_prominence estimates visible compositional area, while accent_color_prominence measures the
strength and area of deliberate color accents. Camera angle is one of eye_level, slightly_above,
high_angle, overhead. Scene complexity follows the visible beverage+dessert count: one solo, two
pair, three or more set. Extract composition, real spatial planes, perspective, physically coherent
lighting, restrained smartphone focus falloff, color behavior, materials and capture style from
visible evidence only. Folder names are not evidence and are not supplied. Record all text or
marks so runtime prompts can forbid brand leakage. Use the exact snake_case category vocabulary
implied by each field name: phone_wide/phone_normal/phone_mild_tele for lens, none/subtle/moderate/
strong for far-plane softness, and none/trace/mild/strong for atmospheric separation. Return only
requested JSON.

Every analysis object must contain all of these keys and nested fields:
- objects: slot_id, kind, role, description, body_bbox, full_bbox, straw_present, straw_bbox,
  straw_centerline, straw_emergence, straw_angle, container_class, container_material,
  container_silhouette, container_components, interaction, support_surface_id, depth_order,
  occlusion_fraction, visible_text, brand_state.
- support_surfaces: surface_id, kind, bbox, description, supports_objects, perspective_scale.
- protected_regions: region_id, kind, bbox, reason.
- insertion_zones: zone_id, bbox, support_surface_id, allowed_kinds, scale_range, confidence, reason.
- composition: shot_type, camera_height, camera_pitch, lens_character, subject_position,
  negative_space, asymmetry_source, crop_character.
- depth: plane_count, foreground, product_plane, midground, background, perspective_cues,
  far_plane_softness, atmospheric_separation.
- lighting: source_type, direction, source_size, hardness, contrast, shadow, highlight,
  transmitted_light, white_balance.
- color: exposure, saturation, contrast, black_point.
- facets: mood_tags, environment_tags, material_tags, shot_tags.
- taxonomy: environment_family, lighting_family, camera_angle, capture_style, dominant_surface,
  wood_prominence, accent_color_prominence, confidence.
- quality_flags: an array of short strings, empty when no visible concern exists."""
            requested_ids = [record["asset"]["asset_id"] for record in uncached]
            items: list[dict[str, Any]] = []
            model_by_id: dict[str, str] = {}
            request_records = []
            for record in uncached:
                raw_path = record["raw_path"]
                if use_cache and raw_path.is_file():
                    staged = load_json(raw_path)
                    if (
                        staged.get("asset_id") == record["asset"]["asset_id"]
                        and staged.get("pixel_sha256")
                        == record["asset"]["pixel_sha256"]
                        and staged.get("prompt_version")
                        == REFERENCE_SCENE_GRAPH_EXTRACTOR_VERSION
                        and isinstance(staged.get("item"), dict)
                    ):
                        items.append(staged["item"])
                        model_by_id[record["asset"]["asset_id"]] = staged.get(
                            "model", self.model
                        )
                        continue
                request_records.append(record)

            if request_records:
                network_ids = [
                    record["asset"]["asset_id"] for record in request_records
                ]
                response = self.client.generate_structured(
                    prompt=prompt,
                    schema=_scene_graph_response_schema(
                        self.project_root,
                        network_ids,
                    ),
                    images=[
                        (
                            f"Reference scene asset_id={record['asset']['asset_id']}",
                            record["image"],
                        )
                        for record in request_records
                    ],
                )
                network_items = response.get("items")
                if not isinstance(network_items, list):
                    raise ValueError(
                        "Gemini scene-graph response must contain an items array"
                    )
                actual_model = (
                    getattr(self.client, "last_used_model", None) or self.model
                )
                request_by_id = {
                    record["asset"]["asset_id"]: record for record in request_records
                }
                for item in network_items:
                    asset_id = item.get("asset_id") if isinstance(item, dict) else None
                    record = request_by_id.get(asset_id)
                    if record is None:
                        items.append(item)
                        continue
                    raw_path = record["raw_path"]
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    staged = {
                        "asset_id": asset_id,
                        "pixel_sha256": record["asset"]["pixel_sha256"],
                        "model": actual_model,
                        "prompt_version": REFERENCE_SCENE_GRAPH_EXTRACTOR_VERSION,
                        "item": item,
                    }
                    temporary = raw_path.with_suffix(".json.tmp")
                    temporary.write_text(
                        json.dumps(staged, ensure_ascii=False, indent=2, sort_keys=True)
                        + "\n",
                        encoding="utf-8",
                    )
                    os.replace(temporary, raw_path)
                    items.append(item)
                    model_by_id[asset_id] = actual_model
            returned_ids = [
                item.get("asset_id") if isinstance(item, dict) else None for item in items
            ]
            duplicates = sorted(
                {
                    asset_id
                    for asset_id in returned_ids
                    if asset_id is not None and returned_ids.count(asset_id) > 1
                }
            )
            if duplicates:
                raise ValueError(
                    "Gemini scene-graph batch returned duplicate asset_id values: "
                    + ", ".join(duplicates)
                )
            missing = sorted(set(requested_ids) - set(returned_ids))
            unexpected = sorted(
                str(asset_id) for asset_id in set(returned_ids) - set(requested_ids)
            )
            if missing or unexpected:
                raise ValueError(
                    "Gemini scene-graph batch asset_id mismatch; "
                    f"missing={missing}, unexpected={unexpected}"
                )

            by_id = {item["asset_id"]: item for item in items}
            for record in uncached:
                asset_id = record["asset"]["asset_id"]
                item = by_id[asset_id]
                graph = _hydrate_scene_graph_analysis(
                    item["analysis"],
                    confidence=float(item["analysis_confidence"]),
                    image_size=(
                        int(record["asset"]["width_px"]),
                        int(record["asset"]["height_px"]),
                    ),
                )
                major_count = sum(
                    obj["kind"] in {"beverage", "dessert"}
                    for obj in graph["objects"]
                )
                if major_count < 1:
                    raise ValueError("Scene graph contains no beverage or dessert")
                reported_major_count = int(item["major_subject_count"])
                inventory_complete = major_count == reported_major_count
                if not inventory_complete and reported_major_count == 8:
                    graph["quality_flags"].extend(
                        [
                            "overflow_scene_at_least_eight_major_subjects",
                            "object_inventory_intentionally_incomplete",
                        ]
                    )
                    for obj in graph["objects"]:
                        obj["replaceable"] = False
                elif not inventory_complete:
                    raise ValueError(
                        "Scene graph major subject count mismatch: "
                        f"reported={reported_major_count}, objects={major_count}"
                    )
                has_hand_region = any(
                    region["kind"] == "hand" for region in graph["protected_regions"]
                )
                if bool(item["has_hand"]) and not has_hand_region:
                    raise ValueError("Scene graph reported a hand without a hand region")
                has_localized_text = any(
                    obj["visible_text"] for obj in graph["objects"]
                ) or any(
                    region["kind"] in {"visible_text", "watermark"}
                    for region in graph["protected_regions"]
                )
                if bool(item["has_scene_text"]) and not has_localized_text:
                    graph["quality_flags"].append(
                        "scene_text_reported_without_localized_region"
                    )
                graph["observed_major_subject_count"] = reported_major_count
                graph["object_inventory_complete"] = inventory_complete
                graph["scene_mode"] = (
                    "solo"
                    if reported_major_count == 1
                    else "pair"
                    if reported_major_count == 2
                    else "set"
                )
                graph["taxonomy"]["scene_complexity"] = graph["scene_mode"]
                graph["taxonomy"]["frontend_mood"] = _legacy_frontend_mood(
                    graph["taxonomy"]
                )
                graph["taxonomy"]["frontend_angle"] = graph["taxonomy"][
                    "camera_angle"
                ]
                graph["schema_version"] = "2.0.0"
                graph["analysis_metadata"] = {
                    "provider": "gemini_interactions",
                    "model": model_by_id.get(asset_id, self.model),
                    "prompt_version": REFERENCE_SCENE_GRAPH_PROMPT_VERSION,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "confidence": item["analysis_confidence"],
                }
                graph["asset"] = record["asset"]
                graph["color"].update(record["local_metrics"])
                graph["runtime_policy"] = {
                    "scene_pixels_allowed": False,
                    "container_pixels_allowed": True,
                    "copy_exclusions": [
                        "exact reference products, beverages, desserts and branding",
                        "exact background layout, wall marks and prop arrangement",
                        "visible text, logos and watermarks",
                        "exact hand anatomy, pose and clothing",
                        "exact crop and shadow silhouette",
                    ],
                    "maximum_exact_products": 2,
                    "maximum_generic_companions": 1,
                    "maximum_major_subjects": 3,
                    "maximum_props": 2,
                }
                graph = canonicalize_slot_ids(graph)
                self._validate(graph)
                cache_path = record["cache_path"]
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, cache_path)
                results[record["index"]] = (graph, False)

        if any(result is None for result in results):
            raise RuntimeError("Gemini scene-graph batch left an input without a result")
        return [result for result in results if result is not None]
