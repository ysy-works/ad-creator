from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageOps

from .control_board import validate_reference_control_board_manifest
from .image_contracts import resolve_target_brand_contract, validate_product_analysis_binding
from .jsonio import load_json, validate_json
from .lighting_contracts import ReferenceLightingDelta, WhiteLightingBase, resolve_lighting_contract
from .pipeline import load_mood_package
from .postprocessing import (
    apply_grade,
    image_metrics,
    instagram_center_crop,
    resolve_grade_strengths,
    save_image,
)
from .prompting import assemble_product_set, build_multi_product_generation_request
from .providers.fake import FakeGenerationProvider
from .reference_contracts import (
    assemble_reference_analysis_v3,
    derive_reference_brand_observation,
    resolve_visual_contract,
)
from .request_validation import validate_generation_request
from .runs import RunStore, execute_once
from .scene_graph import resolve_slot_plan, validate_scene_graph
from .serving_contracts import (
    require_serving_compatibility_ready,
    resolve_serving_compatibility,
)
from .wood_materials import WoodMaterialProfile, validate_wood_material_profile


@dataclass(frozen=True)
class MultiLocalResult:
    request: dict[str, Any]
    manifest: dict[str, Any]
    manifest_path: Path
    output_path: Path
    reused_provider_job: bool


def postprocess_multi_product_output(
    *,
    project_root: str | Path,
    request: Mapping[str, Any],
    provider_output: str | Path,
    output_path: str | Path,
    grade_mode: str = "balanced",
    protection_mask: Image.Image | None = None,
) -> dict[str, Any]:
    """Apply the request-bound crop and grade to a V3 provider image.

    The grade profile path is part of the hashed runtime contract. This keeps
    multi-product output from silently bypassing the selected photographic
    finish, while allowing the caller to supply a real product/logo mask.
    """

    root = Path(project_root).resolve()
    runtime_contracts = request.get("runtime_contracts")
    if not isinstance(runtime_contracts, Mapping):
        raise ValueError("V3 postprocessing requires runtime_contracts")
    grade_profile = load_json(_resolve(root, runtime_contracts["grade_profile_path"]))
    lighting_sheet = load_json(_resolve(root, runtime_contracts["lighting_sheet_path"]))
    validate_json(grade_profile, "grade-profile.schema.json", project_root=root)
    validate_json(lighting_sheet, "lighting-sheet.schema.json", project_root=root)
    strengths = resolve_grade_strengths(lighting_sheet)
    if grade_mode not in strengths:
        raise ValueError(f"Unknown grade mode: {grade_mode}")
    strength = float(strengths[grade_mode])
    maximum = float(grade_profile["strength"]["max"])
    if strength > maximum:
        raise ValueError(
            f"Lighting-sheet grade strength {strength} exceeds profile maximum {maximum}"
        )

    source_path = Path(provider_output).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Provider output does not exist: {source_path}")
    target_pixels = tuple(request["postprocess"]["target_delivery_pixels"])
    with Image.open(source_path) as opened:
        cropped = instagram_center_crop(opened, target_size=target_pixels)
        graded = apply_grade(
            cropped,
            profile=grade_profile,
            strength=strength,
            protection_mask=protection_mask,
        )
    destination = save_image(graded, output_path)
    return {
        "output_path": str(destination.resolve()),
        "grade_profile_id": grade_profile["grade_profile_id"],
        "grade_mode": grade_mode,
        "grade_strength": strength,
        "protection_mask_connected": protection_mask is not None,
        "metrics": image_metrics(graded),
    }


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _control_board_pixel_hash(path: Path) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        digest = hashlib.sha256()
        digest.update(f"RGB:{image.width}x{image.height}:".encode("ascii"))
        digest.update(image.tobytes())
        return digest.hexdigest()


def validate_reference_control_board_binding(
    path: str | Path,
    manifest: Mapping[str, Any],
) -> None:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Reference control board does not exist: {source}")
    artifact_type = manifest.get("artifact_type")
    if artifact_type == "sanitized_photographic_scene_hint":
        manifest_path = Path(str(manifest.get("path", ""))).expanduser().resolve()
        if manifest_path != source:
            raise ValueError("Scene-hint manifest path does not match the submitted image")
        if manifest.get("pixel_sha256") != _control_board_pixel_hash(source):
            raise ValueError("Scene-hint pixels changed after publication")
        sanitation = manifest.get("sanitation") or {}
        required = {
            "borderless_photo_like_plate": True,
            "technical_panels": False,
            "panel_boundaries": False,
            "visible_labels": False,
            "raw_reference_provider_submission_allowed": False,
            "fixed_placeholder_color_used": False,
        }
        if any(sanitation.get(key) is not value for key, value in required.items()):
            raise ValueError("Scene-hint sanitation contract is incomplete")
        return
    if artifact_type != "reference_control_board":
        raise ValueError("Control-board manifest has the wrong artifact_type")
    if manifest.get("visible_labels") is not False:
        raise ValueError("Reference control board must be label-free")
    manifest_path = Path(str(manifest.get("path", ""))).expanduser().resolve()
    if manifest_path != source:
        raise ValueError("Control-board manifest path does not match the submitted image")
    if manifest.get("pixel_sha256") != _control_board_pixel_hash(source):
        raise ValueError("Reference control board changed after its manifest was created")
    validate_reference_control_board_manifest(manifest)
    panels = manifest.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 4:
        raise ValueError("Control-board manifest requires one to four panels")


def _resolved_brand_products(
    products: Sequence[dict[str, Any]],
    scene_graph: dict[str, Any],
    *,
    unbound_slot_policy: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    product_set = assemble_product_set(list(products))
    values = product_set["products"]
    slot_plan = resolve_slot_plan(
        scene_graph,
        [
            {
                "input_product_id": item["product_id"],
                "target_slot_id": item.get("target_slot_id", "auto"),
                "placement_mode": item.get("placement_mode", "replace"),
                "product_kind": item["product_kind"],
                "cross_kind_replacement": item.get("cross_kind_replacement", False),
            }
            for item in values
        ],
        unbound_slot_policy=unbound_slot_policy,
        maximum_exact_products=3,
    )
    binding_by_product = {
        item["input_product_id"]: item for item in slot_plan["bindings"]
    }
    object_by_id = {item["slot_id"]: item for item in scene_graph["objects"]}

    resolved: list[dict[str, Any]] = []
    for product in values:
        value = copy.deepcopy(product)
        analysis = value.get("product_analysis")
        if not isinstance(analysis, dict):
            raise ValueError(f"Exact product {value['product_id']} requires product_analysis")
        validate_product_analysis_binding(analysis, value["source_image"])
        policy = value.get("container_policy", "preserve_source")
        mode = policy if isinstance(policy, str) else policy.get("mode")
        reference_observation = None
        binding = binding_by_product[value["product_id"]]
        target_scene_object = None
        if mode == "adopt_reference" and binding["placement_mode"] == "replace":
            target_scene_object = object_by_id[binding["target_slot_id"]]
            reference_observation = derive_reference_brand_observation(
                target_scene_object
            )
        contract = resolve_target_brand_contract(
            analysis,
            policy,
            reference_observation,
        )
        action = contract["brand_transfer_resolution"]["action"]
        if action == "block_uncertain":
            raise ValueError(
                f"Product {value['product_id']} branding is uncertain; paid submission blocked"
            )
        value.update(contract)
        serving_resolution = resolve_serving_compatibility(
            product_analysis=analysis,
            product_kind=value["product_kind"],
            description=value.get("description"),
            container_mode=str(mode),
            target_scene_object=target_scene_object,
        )
        value["serving_compatibility_resolution"] = serving_resolution
        require_serving_compatibility_ready(
            value["product_id"], serving_resolution
        )
        resolved.append(value)
    return resolved, slot_plan


def prepare_multi_product_request(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    products: Sequence[dict[str, Any]] | Mapping[str, Any],
    scene_graph: Mapping[str, Any],
    seed: int = 713,
    tier: str = "default",
    unbound_slot_policy: str = "genericize",
    control_board_image: str | Path | None = None,
    control_board_manifest: Mapping[str, Any] | None = None,
    lighting_base: WhiteLightingBase | Mapping[str, Any] | None = None,
    lighting_delta: ReferenceLightingDelta | Mapping[str, Any] | None = None,
    wood_material_profile: WoodMaterialProfile | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile and validate one zero-side-effect GenerationRequestV3."""

    root = Path(project_root).resolve()
    mood = load_mood_package(root, mood_package_path)
    preset = load_json(_resolve(root, mood["preset_path"]))
    runtime_profile = load_json(_resolve(root, mood["runtime_profile_path"]))
    scene_recipe = load_json(_resolve(root, mood["scene_recipe_path"]))
    lighting_sheet = load_json(_resolve(root, mood["lighting_sheet_path"]))
    photographic_style_contract = None
    photographic_style_contract_path = mood.get("photographic_style_contract_path")
    if photographic_style_contract_path is not None:
        photographic_style_contract = load_json(
            _resolve(root, photographic_style_contract_path)
        )
        validate_json(
            photographic_style_contract,
            "photographic-style-contract.schema.json",
            project_root=root,
        )
    product_integration_contract = None
    product_integration_contract_path = mood.get("product_integration_contract_path")
    if product_integration_contract_path is not None:
        product_integration_contract = load_json(
            _resolve(root, product_integration_contract_path)
        )
        validate_json(
            product_integration_contract,
            "product-integration-contract.schema.json",
            project_root=root,
        )
    graph = copy.deepcopy(dict(scene_graph))
    validate_scene_graph(graph, project_root=str(root))
    raw_products = products.get("products") if isinstance(products, Mapping) else products
    if not isinstance(raw_products, Sequence) or isinstance(raw_products, (str, bytes)):
        raise ValueError("products must contain one to three ProductSpec objects")
    resolved_products, expected_slot_plan = _resolved_brand_products(
        list(raw_products),
        graph,
        unbound_slot_policy=unbound_slot_policy,
    )

    resolved_lighting = None
    if (lighting_base is None) != (lighting_delta is None):
        raise ValueError("lighting_base and lighting_delta must be supplied together")
    if lighting_base is not None and lighting_delta is not None:
        resolved_lighting = resolve_lighting_contract(lighting_base, lighting_delta)
    if wood_material_profile is None and mood.get("wood_material_profile_path"):
        wood_material_profile = load_json(
            _resolve(root, mood["wood_material_profile_path"])
        )
    wood_profile = (
        validate_wood_material_profile(wood_material_profile)
        if wood_material_profile is not None
        else None
    )
    reference_analysis = assemble_reference_analysis_v3(
        scene_graph=graph,
        resolved_lighting=resolved_lighting,
        wood_profiles=([wood_profile] if wood_profile is not None else []),
    )
    visual_contract = resolve_visual_contract(
        reference_analysis=reference_analysis,
        wood_profile=wood_profile,
    )

    if control_board_image is None and control_board_manifest is None:
        preset_board_path = mood.get("reference_control_board_path")
        preset_board_manifest_path = mood.get(
            "reference_control_board_manifest_path"
        )
        if preset_board_path is not None or preset_board_manifest_path is not None:
            if not preset_board_path or not preset_board_manifest_path:
                raise ValueError(
                    "Mood package must bind both reference control board and manifest"
                )
            control_board_image = preset_board_path
            control_board_manifest = load_json(
                _resolve(root, preset_board_manifest_path)
            )
    board_path = None
    board_manifest_value = None
    if control_board_image is not None or control_board_manifest is not None:
        if control_board_image is None or control_board_manifest is None:
            raise ValueError("Control-board image and manifest must be supplied together")
        board_path = _resolve(root, control_board_image)
        board_manifest_value = copy.deepcopy(dict(control_board_manifest))
        validate_reference_control_board_binding(board_path, board_manifest_value)

    request = build_multi_product_generation_request(
        preset=preset,
        runtime_profile=runtime_profile,
        products=resolved_products,
        scene_graph=graph,
        seed=seed,
        tier=tier,
        unbound_slot_policy=unbound_slot_policy,
        scene_recipe=scene_recipe,
        lighting_sheet=lighting_sheet,
        resolved_lighting_contract=(
            resolved_lighting.to_dict() if resolved_lighting is not None else None
        ),
        wood_material_profile=(wood_profile.to_dict() if wood_profile else None),
        control_board_image=(str(board_path) if board_path else None),
        control_board_manifest=board_manifest_value,
        photographic_style_contract=photographic_style_contract,
        product_integration_contract=product_integration_contract,
    )
    actual_slot_plan = request["scene_graph_contract"]["slot_plan"]
    if actual_slot_plan != expected_slot_plan:
        raise ValueError("Brand preflight and request builder resolved different slot plans")
    request.update(
        {
            "mood_package_id": mood["mood_package_id"],
            "lighting_sheet": {
                "id": lighting_sheet["lighting_sheet_id"],
                "sha256": _json_hash(lighting_sheet),
            },
            "resolved_visual_contract": visual_contract,
            "reference_analysis_contract": {
                "asset_id": reference_analysis["asset_id"],
                "status": reference_analysis["status"],
                "sha256": reference_analysis["contract_sha256"],
            },
            "runtime_contracts": {
                "runtime_profile_path": mood["runtime_profile_path"],
                "lighting_sheet_path": mood["lighting_sheet_path"],
                "grade_profile_path": mood["grade_profile_path"],
                **(
                    {
                        "photographic_style_contract_path": photographic_style_contract_path
                    }
                    if photographic_style_contract_path is not None
                    else {}
                ),
                **(
                    {
                        "product_integration_contract_path": product_integration_contract_path
                    }
                    if product_integration_contract_path is not None
                    else {}
                ),
                **(
                    {"wood_material_profile_path": mood["wood_material_profile_path"]}
                    if mood.get("wood_material_profile_path")
                    else {}
                ),
                **(
                    {
                        "reference_control_board_path": mood[
                            "reference_control_board_path"
                        ],
                        "reference_control_board_manifest_path": mood[
                            "reference_control_board_manifest_path"
                        ],
                    }
                    if mood.get("reference_control_board_path")
                    else {}
                ),
            },
            "repair_policy": {
                "auto_paid_repair": False,
                "minimum_trigger_confidence": 1.0,
                "maximum_attempts": 0,
                "maximum_additional_credits": 0,
            },
        }
    )
    validate_generation_request(request, maximum_credits=2)
    return request


def prepare_multi_product_request_from_paths(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_set_path: str | Path,
    scene_graph_path: str | Path,
    control_board_image: str | Path | None = None,
    control_board_manifest_path: str | Path | None = None,
    lighting_base_path: str | Path | None = None,
    lighting_delta_path: str | Path | None = None,
    wood_material_profile_path: str | Path | None = None,
    seed: int = 713,
    unbound_slot_policy: str = "genericize",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    return prepare_multi_product_request(
        project_root=root,
        mood_package_path=mood_package_path,
        products=load_json(_resolve(root, product_set_path)),
        scene_graph=load_json(_resolve(root, scene_graph_path)),
        seed=seed,
        unbound_slot_policy=unbound_slot_policy,
        control_board_image=control_board_image,
        control_board_manifest=(
            load_json(_resolve(root, control_board_manifest_path))
            if control_board_manifest_path is not None
            else None
        ),
        lighting_base=(
            load_json(_resolve(root, lighting_base_path))
            if lighting_base_path is not None
            else None
        ),
        lighting_delta=(
            load_json(_resolve(root, lighting_delta_path))
            if lighting_delta_path is not None
            else None
        ),
        wood_material_profile=(
            load_json(_resolve(root, wood_material_profile_path))
            if wood_material_profile_path is not None
            else None
        ),
    )


def run_local_multi_pipeline(
    *,
    request: dict[str, Any],
    output_root: str | Path,
    fixture_image: str | Path | None = None,
) -> MultiLocalResult:
    validate_generation_request(request, maximum_credits=2)
    store = RunStore(output_root)
    provider = FakeGenerationProvider(
        Path(output_root) / "_fake_provider",
        fixture_image=fixture_image,
    )
    manifest, reused = execute_once(request, provider=provider, store=store)
    output_value = manifest.get("artifacts", {}).get("provider_output")
    if not output_value:
        raise RuntimeError("Fake multi-product run produced no output artifact")
    output_path = Path(output_value)
    return MultiLocalResult(
        request=request,
        manifest=manifest,
        manifest_path=store.manifest_path(manifest["request_hash"]),
        output_path=output_path,
        reused_provider_job=reused,
    )
