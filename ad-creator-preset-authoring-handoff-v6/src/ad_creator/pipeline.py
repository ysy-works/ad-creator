from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .environment import load_project_env
from .evaluators.base import QualityEvaluator
from .evaluators.gemini import GeminiQualityEvaluator
from .jsonio import load_json, validate_json
from .features import load_service_features
from .image_contracts import validate_product_analysis_binding, verified_logo_text
from .postprocessing import apply_grade, image_metrics, instagram_center_crop, resolve_grade_strengths, save_image
from .prompting import PROMPT_COMPILER_VERSION, build_generation_request
from .provider_profiles import (
    OPENAI_PROVIDER_PROFILE_PATH,
    AppliedProviderProfile,
    apply_provider_profile,
    record_provider_profile,
)
from .providers.fake import FakeGenerationProvider
from .providers.higgsfield import HiggsfieldProvider
from .providers.openai import OpenAIImageProvider
from .quality_workflow import QualityWorkflowResult, evaluate_and_maybe_repair
from .reference_library import derive_container_design
from .request_validation import validate_generation_request
from .runs import RunStore, execute_once, execute_until_terminal, request_hash
from .scene_graph import (
    adapt_scene_graph_to_reference_v1,
    resolve_slot_plan,
    validate_scene_graph,
)


@dataclass(frozen=True)
class LocalPipelineResult:
    request_hash: str
    run_dir: Path
    manifest_path: Path
    reused_provider_job: bool
    outputs: dict[str, Path]
    status: str


@dataclass(frozen=True)
class _PreparedPipeline:
    root: Path
    request: dict[str, Any]
    runtime_profile: dict[str, Any]
    grade_profile: dict[str, Any]
    lighting_sheet: dict[str, Any]


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def load_mood_package(project_root: str | Path, mood_package_path: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = _resolve(root, str(mood_package_path))
    package = load_json(path)
    validate_json(package, "mood-package.schema.json", project_root=root)
    package["_path"] = str(path)
    return package


def _prepare_pipeline(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_analysis_path: str | Path,
    scene_reference_path: str | Path | None = None,
    scene_graph_path: str | Path | None = None,
    target_slot_id: str = "auto",
    placement_mode: str = "replace",
    product_kind: str = "beverage",
    cross_kind_replacement: bool = False,
    unbound_slot_policy: str = "genericize",
    input_image: str | Path,
    seed: int = 713,
    tier: str = "default",
    features_path: str | Path | None = "configs/service-features.json",
    container_mode: str = "preserve_source",
    container_reference_image: str | Path | None = None,
    container_design_path: str | Path | None = None,
    brand_asset_image: str | Path | None = None,
    auto_paid_repair: bool | None = None,
    provider_profile_path: str | Path | None = None,
) -> _PreparedPipeline:
    root = Path(project_root).resolve()
    mood = load_mood_package(root, mood_package_path)
    preset = load_json(_resolve(root, mood["preset_path"]))
    profile = load_json(_resolve(root, mood["runtime_profile_path"]))
    provider_application: AppliedProviderProfile | None = None
    if provider_profile_path is not None:
        provider_application = apply_provider_profile(
            project_root=root,
            runtime_profile=profile,
            provider_profile_path=provider_profile_path,
        )
        profile = provider_application.runtime_profile
    recipe = load_json(_resolve(root, mood["scene_recipe_path"]))
    grade_profile = load_json(_resolve(root, mood["grade_profile_path"]))
    lighting_sheet = load_json(_resolve(root, mood["lighting_sheet_path"]))
    photographic_style_contract = (
        load_json(_resolve(root, mood["photographic_style_contract_path"]))
        if mood.get("photographic_style_contract_path")
        else None
    )
    product_analysis = load_json(_resolve(root, str(product_analysis_path)))
    scene_reference = (
        load_json(_resolve(root, str(scene_reference_path)))
        if scene_reference_path
        else None
    )
    scene_graph = (
        load_json(_resolve(root, str(scene_graph_path)))
        if scene_graph_path
        else None
    )
    slot_bindings = None
    container_reference_contract = scene_reference
    if scene_graph is not None:
        validate_scene_graph(scene_graph, project_root=str(root))
        slot_bindings = [
            {
                "input_product_id": "product_01",
                "target_slot_id": target_slot_id,
                "placement_mode": placement_mode,
                "product_kind": product_kind,
                "cross_kind_replacement": cross_kind_replacement,
            }
        ]
        slot_plan = resolve_slot_plan(
            scene_graph,
            slot_bindings,
            unbound_slot_policy=unbound_slot_policy,
        )
        resolved_binding = slot_plan["bindings"][0]
        resolved_target = (
            resolved_binding["target_slot_id"]
            if resolved_binding["placement_mode"] == "replace"
            else None
        )
        container_reference_contract = adapt_scene_graph_to_reference_v1(
            scene_graph,
            target_slot_id=resolved_target,
        )
        if scene_reference is not None and (
            scene_reference["asset"]["asset_id"]
            != container_reference_contract["asset"]["asset_id"]
        ):
            raise ValueError("Scene reference and scene graph identify different assets")
        if scene_reference is None:
            scene_reference = container_reference_contract
    features = load_service_features(root, features_path)
    container_design = (
        load_json(_resolve(root, str(container_design_path)))
        if container_design_path
        else (
            derive_container_design(container_reference_contract)
            if container_mode == "adopt_reference"
            and container_reference_contract is not None
            else None
        )
    )

    input_path = _resolve(root, str(input_image)).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input image does not exist: {input_path}")

    validate_json(preset, "reference-preset.schema.json", project_root=root)
    validate_json(recipe, "scene-recipe.schema.json", project_root=root)
    validate_json(product_analysis, "product-analysis.schema.json", project_root=root)
    if scene_reference is not None:
        validate_json(scene_reference, "reference-asset.schema.json", project_root=root)
    validate_json(grade_profile, "grade-profile.schema.json", project_root=root)
    validate_json(lighting_sheet, "lighting-sheet.schema.json", project_root=root)
    if container_design is not None:
        validate_json(container_design, "container-design.schema.json", project_root=root)
    validate_product_analysis_binding(product_analysis, input_path)

    request = build_generation_request(
        preset=preset,
        runtime_profile=profile,
        input_image=str(input_path),
        product_description=product_analysis["product_summary"],
        logo_text=verified_logo_text(product_analysis),
        seed=seed,
        tier=tier,
        product_analysis=product_analysis,
        scene_reference=scene_reference,
        scene_graph=scene_graph,
        slot_bindings=slot_bindings,
        unbound_slot_policy=unbound_slot_policy,
        scene_recipe=recipe,
        lighting_sheet=lighting_sheet,
        photographic_style_contract=photographic_style_contract,
        container_mode=container_mode,
        container_reference_image=(
            str(_resolve(root, str(container_reference_image)).resolve())
            if container_reference_image
            else None
        ),
        container_design=container_design,
        brand_asset_image=(
            str(_resolve(root, str(brand_asset_image)).resolve()) if brand_asset_image else None
        ),
        service_features=features,
        auto_paid_repair=auto_paid_repair,
    )
    request["mood_package_id"] = mood["mood_package_id"]
    lighting_payload = json.dumps(
        lighting_sheet,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    request["lighting_sheet"] = {
        "id": lighting_sheet["lighting_sheet_id"],
        "sha256": hashlib.sha256(lighting_payload).hexdigest(),
    }
    def contract_record(path_value: str) -> dict[str, str]:
        path = _resolve(root, path_value).resolve()
        return {
            "path": path_value,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    request["resolved_contracts"] = {
        "mood_package": contract_record(str(mood["_path"])),
        "preset": contract_record(mood["preset_path"]),
        "runtime_profile": contract_record(mood["runtime_profile_path"]),
        "scene_recipe": contract_record(mood["scene_recipe_path"]),
        "lighting_sheet": contract_record(mood["lighting_sheet_path"]),
        "grade_profile": contract_record(mood["grade_profile_path"]),
        "photographic_style_contract": (
            contract_record(mood["photographic_style_contract_path"])
            if mood.get("photographic_style_contract_path")
            else None
        ),
    }
    request["runtime_contracts"] = {
        "runtime_profile_path": mood["runtime_profile_path"],
        "lighting_sheet_path": mood["lighting_sheet_path"],
        "grade_profile_path": mood["grade_profile_path"],
    }
    if provider_application is not None:
        record_provider_profile(request, provider_application)
    request["prompt_compiler_version"] = PROMPT_COMPILER_VERSION
    validate_generation_request(request, maximum_credits=4)

    return _PreparedPipeline(
        root=root,
        request=request,
        runtime_profile=profile,
        grade_profile=grade_profile,
        lighting_sheet=lighting_sheet,
    )


def _postprocess_pipeline(
    prepared: _PreparedPipeline,
    *,
    store: RunStore,
    manifest: dict[str, Any],
    reused: bool,
) -> LocalPipelineResult:
    request = prepared.request
    grade_profile = prepared.grade_profile
    lighting_sheet = prepared.lighting_sheet
    if manifest["status"] not in {
        "provider_completed",
        "quality_passed",
        "needs_review",
        "rejected",
        "completed",
    }:
        raise RuntimeError(f"Cannot postprocess provider state: {manifest['status']}")
    status_before_postprocess = manifest["status"]
    provider_output_value = manifest["artifacts"].get("provider_output")
    if not provider_output_value:
        raise RuntimeError("Provider completed without a saved output artifact")
    provider_output = Path(provider_output_value)
    if not provider_output.is_file():
        raise FileNotFoundError(f"Provider output does not exist: {provider_output}")

    run_dir = store.run_dir(manifest["request_hash"])
    outputs: dict[str, Path] = {}
    with Image.open(provider_output) as opened:
        cropped = instagram_center_crop(opened, target_size=tuple(request["postprocess"]["target_delivery_pixels"]))
        outputs["crop"] = save_image(cropped, run_dir / "01_instagram_4x5.png")
        manifest["metrics"]["pre_grade"] = image_metrics(cropped)
        grade_strengths = resolve_grade_strengths(lighting_sheet)
        for name, strength in grade_strengths.items():
            graded = apply_grade(cropped, profile=grade_profile, strength=strength)
            output_path = save_image(graded, run_dir / f"02_grade_{name}.png")
            outputs[name] = output_path
            manifest["metrics"][f"grade_{name}"] = image_metrics(graded)

    manifest["artifacts"].update({name: str(path.resolve()) for name, path in outputs.items()})
    manifest["status"] = (
        "completed"
        if status_before_postprocess in {"provider_completed", "quality_passed", "completed"}
        else status_before_postprocess
    )
    manifest["postprocess"] = {
        "grade_profile_id": grade_profile["grade_profile_id"],
        "strengths": grade_strengths,
        "protection_mask": "not_connected_in_local_fixture",
    }
    manifest["events"].append({"at": manifest["updated_at"], "type": "postprocess_completed"})
    store.save(manifest)
    validate_json(manifest, "run-manifest.schema.json", project_root=prepared.root)

    return LocalPipelineResult(
        request_hash=manifest["request_hash"],
        run_dir=run_dir,
        manifest_path=store.manifest_path(manifest["request_hash"]),
        reused_provider_job=reused,
        outputs=outputs,
        status=manifest["status"],
    )


def run_local_pipeline(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_analysis_path: str | Path,
    scene_reference_path: str | Path | None = None,
    scene_graph_path: str | Path | None = None,
    target_slot_id: str = "auto",
    placement_mode: str = "replace",
    product_kind: str = "beverage",
    cross_kind_replacement: bool = False,
    unbound_slot_policy: str = "genericize",
    input_image: str | Path,
    fixture_image: str | Path | None,
    output_root: str | Path,
    seed: int = 713,
    tier: str = "default",
    features_path: str | Path | None = "configs/service-features.json",
    container_mode: str = "preserve_source",
    container_reference_image: str | Path | None = None,
    container_design_path: str | Path | None = None,
    brand_asset_image: str | Path | None = None,
    auto_paid_repair: bool | None = None,
) -> LocalPipelineResult:
    load_project_env(project_root)
    prepared = _prepare_pipeline(
        project_root=project_root,
        mood_package_path=mood_package_path,
        product_analysis_path=product_analysis_path,
        scene_reference_path=scene_reference_path,
        scene_graph_path=scene_graph_path,
        target_slot_id=target_slot_id,
        placement_mode=placement_mode,
        product_kind=product_kind,
        cross_kind_replacement=cross_kind_replacement,
        unbound_slot_policy=unbound_slot_policy,
        input_image=input_image,
        seed=seed,
        tier=tier,
        features_path=features_path,
        container_mode=container_mode,
        container_reference_image=container_reference_image,
        container_design_path=container_design_path,
        brand_asset_image=brand_asset_image,
        auto_paid_repair=auto_paid_repair,
    )
    run_root = _resolve(prepared.root, str(output_root)).resolve()
    fixture_path = (
        _resolve(prepared.root, str(fixture_image)).resolve() if fixture_image else None
    )
    store = RunStore(run_root)
    provider = FakeGenerationProvider(run_root / "_fake_provider", fixture_image=fixture_path)
    manifest, reused = execute_once(prepared.request, provider=provider, store=store)
    return _postprocess_pipeline(prepared, store=store, manifest=manifest, reused=reused)


def run_higgsfield_pipeline(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_analysis_path: str | Path,
    scene_reference_path: str | Path | None = None,
    scene_graph_path: str | Path | None = None,
    target_slot_id: str = "auto",
    placement_mode: str = "replace",
    product_kind: str = "beverage",
    cross_kind_replacement: bool = False,
    unbound_slot_policy: str = "genericize",
    input_image: str | Path,
    output_root: str | Path,
    cli_path: str | Path = ".tools/higgsfield/bin/higgsfield",
    seed: int = 713,
    tier: str = "default",
    features_path: str | Path | None = "configs/service-features.json",
    container_mode: str = "preserve_source",
    container_reference_image: str | Path | None = None,
    container_design_path: str | Path | None = None,
    brand_asset_image: str | Path | None = None,
    auto_paid_repair: bool | None = None,
    evaluator: QualityEvaluator | None = None,
    evaluator_config_path: str | Path = "configs/evaluator.json",
    timeout_seconds: float = 1200,
    poll_interval_seconds: float = 3,
) -> LocalPipelineResult:
    load_project_env(project_root)
    prepared = _prepare_pipeline(
        project_root=project_root,
        mood_package_path=mood_package_path,
        product_analysis_path=product_analysis_path,
        scene_reference_path=scene_reference_path,
        scene_graph_path=scene_graph_path,
        target_slot_id=target_slot_id,
        placement_mode=placement_mode,
        product_kind=product_kind,
        cross_kind_replacement=cross_kind_replacement,
        unbound_slot_policy=unbound_slot_policy,
        input_image=input_image,
        seed=seed,
        tier=tier,
        features_path=features_path,
        container_mode=container_mode,
        container_reference_image=container_reference_image,
        container_design_path=container_design_path,
        brand_asset_image=brand_asset_image,
        auto_paid_repair=auto_paid_repair,
    )
    run_root = _resolve(prepared.root, str(output_root)).resolve()
    store = RunStore(run_root)
    provider = HiggsfieldProvider(
        run_root / "_higgsfield_provider",
        cli_path=_resolve(prepared.root, str(cli_path)).resolve(),
        maximum_base_credits=4,
    )
    manifest, reused = execute_until_terminal(
        prepared.request,
        provider=provider,
        store=store,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    evaluator_config = load_json(_resolve(prepared.root, str(evaluator_config_path)))
    quality_evaluator = evaluator or GeminiQualityEvaluator(
        model=evaluator_config["model"],
        fallback_models=evaluator_config.get("fallback_models", []),
        timeout_seconds=float(evaluator_config["timeout_seconds"]),
        maximum_image_edge=int(evaluator_config["maximum_image_edge"]),
    )
    roles = prepared.request["generation"]["image_roles"]
    paths = prepared.request["generation"]["image_paths"]
    role_paths = dict(zip(roles, paths, strict=True))
    quality_result = evaluate_and_maybe_repair(
        project_root=prepared.root,
        request=prepared.request,
        manifest=manifest,
        store=store,
        provider=provider,
        evaluator=quality_evaluator,
        runtime_profile=prepared.runtime_profile,
        lighting_sheet=prepared.lighting_sheet,
        original_product_image=role_paths["product_source"],
        container_reference_image=(
            role_paths.get("scene_hint") or role_paths.get("container_reference")
        ),
        brand_asset_image=role_paths.get("brand_asset"),
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    manifest = quality_result.manifest
    return _postprocess_pipeline(prepared, store=store, manifest=manifest, reused=reused)


def run_openai_pipeline(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_analysis_path: str | Path,
    scene_reference_path: str | Path | None = None,
    scene_graph_path: str | Path | None = None,
    target_slot_id: str = "auto",
    placement_mode: str = "replace",
    product_kind: str = "beverage",
    cross_kind_replacement: bool = False,
    unbound_slot_policy: str = "genericize",
    input_image: str | Path,
    output_root: str | Path,
    provider_profile_path: str | Path = OPENAI_PROVIDER_PROFILE_PATH,
    seed: int = 713,
    features_path: str | Path | None = "configs/service-features.json",
    container_mode: str = "preserve_source",
    container_reference_image: str | Path | None = None,
    container_design_path: str | Path | None = None,
    brand_asset_image: str | Path | None = None,
    evaluator: QualityEvaluator | None = None,
    evaluator_config_path: str | Path = "configs/evaluator.json",
    timeout_seconds: float = 1200,
) -> LocalPipelineResult:
    """Run one paid OpenAI Images request, then QA without automatic repair."""
    load_project_env(project_root)
    prepared = _prepare_pipeline(
        project_root=project_root,
        mood_package_path=mood_package_path,
        product_analysis_path=product_analysis_path,
        scene_reference_path=scene_reference_path,
        scene_graph_path=scene_graph_path,
        target_slot_id=target_slot_id,
        placement_mode=placement_mode,
        product_kind=product_kind,
        cross_kind_replacement=cross_kind_replacement,
        unbound_slot_policy=unbound_slot_policy,
        input_image=input_image,
        seed=seed,
        features_path=features_path,
        container_mode=container_mode,
        container_reference_image=container_reference_image,
        container_design_path=container_design_path,
        brand_asset_image=brand_asset_image,
        auto_paid_repair=False,
        provider_profile_path=provider_profile_path,
    )
    run_root = _resolve(prepared.root, str(output_root)).resolve()
    store = RunStore(run_root)
    provider_application = apply_provider_profile(
        project_root=prepared.root,
        runtime_profile=prepared.runtime_profile,
        provider_profile_path=provider_profile_path,
    )
    if (
        prepared.request["runtime_contracts"]["provider_profile_sha256"]
        != provider_application.profile_sha256
    ):
        raise ValueError("OpenAI provider profile changed after request compilation")
    provider_config = provider_application.provider_profile
    provider = OpenAIImageProvider(
        run_root / "_openai_provider",
        model=provider_config["model"],
        endpoint=provider_config["endpoint"],
        size=provider_config["size"],
        input_fidelity=provider_config["input_fidelity"],
        output_format=provider_config["output_format"],
        moderation=provider_config["moderation"],
        timeout_seconds=min(
            float(timeout_seconds),
            float(provider_config["timeout_seconds"]),
        ),
    )
    manifest, reused = execute_once(
        prepared.request,
        provider=provider,
        store=store,
    )
    evaluator_config = load_json(_resolve(prepared.root, str(evaluator_config_path)))
    quality_evaluator = evaluator or GeminiQualityEvaluator(
        model=evaluator_config["model"],
        fallback_models=evaluator_config.get("fallback_models", []),
        timeout_seconds=float(evaluator_config["timeout_seconds"]),
        maximum_image_edge=int(evaluator_config["maximum_image_edge"]),
    )
    role_paths = dict(
        zip(
            prepared.request["generation"]["image_roles"],
            prepared.request["generation"]["image_paths"],
            strict=True,
        )
    )
    quality_result = evaluate_and_maybe_repair(
        project_root=prepared.root,
        request=prepared.request,
        manifest=manifest,
        store=store,
        provider=provider,
        evaluator=quality_evaluator,
        runtime_profile=prepared.runtime_profile,
        lighting_sheet=prepared.lighting_sheet,
        original_product_image=role_paths["product_source"],
        container_reference_image=(
            role_paths.get("scene_hint") or role_paths.get("container_reference")
        ),
        brand_asset_image=role_paths.get("brand_asset"),
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=0,
        allow_paid_repair=False,
    )
    return _postprocess_pipeline(
        prepared,
        store=store,
        manifest=quality_result.manifest,
        reused=reused,
    )


def preflight_higgsfield_pipeline(
    *,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_analysis_path: str | Path,
    scene_reference_path: str | Path | None = None,
    scene_graph_path: str | Path | None = None,
    target_slot_id: str = "auto",
    placement_mode: str = "replace",
    product_kind: str = "beverage",
    cross_kind_replacement: bool = False,
    unbound_slot_policy: str = "genericize",
    input_image: str | Path,
    output_root: str | Path,
    cli_path: str | Path = ".tools/higgsfield/bin/higgsfield",
    seed: int = 713,
    features_path: str | Path | None = "configs/service-features.json",
    container_mode: str = "preserve_source",
    container_reference_image: str | Path | None = None,
    container_design_path: str | Path | None = None,
    brand_asset_image: str | Path | None = None,
    auto_paid_repair: bool | None = None,
) -> dict[str, Any]:
    prepared = _prepare_pipeline(
        project_root=project_root,
        mood_package_path=mood_package_path,
        product_analysis_path=product_analysis_path,
        scene_reference_path=scene_reference_path,
        scene_graph_path=scene_graph_path,
        target_slot_id=target_slot_id,
        placement_mode=placement_mode,
        product_kind=product_kind,
        cross_kind_replacement=cross_kind_replacement,
        unbound_slot_policy=unbound_slot_policy,
        input_image=input_image,
        seed=seed,
        features_path=features_path,
        container_mode=container_mode,
        container_reference_image=container_reference_image,
        container_design_path=container_design_path,
        brand_asset_image=brand_asset_image,
        auto_paid_repair=auto_paid_repair,
    )
    run_root = _resolve(prepared.root, str(output_root)).resolve()
    provider = HiggsfieldProvider(
        run_root / "_higgsfield_provider",
        cli_path=_resolve(prepared.root, str(cli_path)).resolve(),
        maximum_base_credits=2,
    )
    estimate = provider.estimate_cost(prepared.request)
    if estimate > 2 or abs(estimate - prepared.request["generation"]["estimated_credits"]) > 1e-9:
        raise ValueError("Provider estimate does not satisfy the 2-credit request contract")
    scene_contract = prepared.request.get("scene_graph_contract") or {}
    slot_bindings = scene_contract.get("slot_plan", {}).get("bindings", [])
    selected_binding = slot_bindings[0] if slot_bindings else None
    return {
        "request_hash": request_hash(prepared.request),
        "estimated_credits": estimate,
        "account_credits": provider.account_credits(),
        "prompt_characters": len(prepared.request["generation"]["prompt"]),
        "container_mode": prepared.request["identity_policy"]["container"],
        "mood_package_id": prepared.request["mood_package_id"],
        "scene_recipe_id": prepared.request["scene_recipe_id"],
        "image_roles": prepared.request["generation"]["image_roles"],
        "scene_graph_asset_id": scene_contract.get("asset_id"),
        "target_slot_id": (
            selected_binding.get("target_slot_id") if selected_binding else None
        ),
        "placement_mode": (
            selected_binding.get("placement_mode") if selected_binding else None
        ),
        "submitted": False,
    }


def evaluate_existing_higgsfield_run(
    *,
    project_root: str | Path,
    manifest_path: str | Path,
    mood_package_path: str | Path,
    input_image: str | Path,
    container_reference_image: str | Path | None = None,
    evaluator: QualityEvaluator | None = None,
    evaluator_config_path: str | Path = "configs/evaluator.json",
) -> QualityWorkflowResult:
    root = Path(project_root).resolve()
    load_project_env(root)
    resolved_manifest = _resolve(root, str(manifest_path)).resolve()
    manifest = load_json(resolved_manifest)
    store = RunStore(resolved_manifest.parents[1])
    if store.manifest_path(manifest["request_hash"]).resolve() != resolved_manifest:
        raise ValueError("Manifest path does not match its request hash and run store")
    provider_output = manifest.get("artifacts", {}).get("provider_output")
    if not provider_output or not Path(provider_output).is_file():
        raise FileNotFoundError("Existing run has no saved provider output")

    mood = load_mood_package(root, mood_package_path)
    lighting_sheet = load_json(_resolve(root, mood["lighting_sheet_path"]))
    if manifest["request"]["lighting_sheet"]["id"] != lighting_sheet["lighting_sheet_id"]:
        raise ValueError("Manifest and mood package lighting sheets do not match")
    evaluator_config = load_json(_resolve(root, str(evaluator_config_path)))
    quality_evaluator = evaluator or GeminiQualityEvaluator(
        model=evaluator_config["model"],
        fallback_models=evaluator_config.get("fallback_models", []),
        timeout_seconds=float(evaluator_config["timeout_seconds"]),
        maximum_image_edge=int(evaluator_config["maximum_image_edge"]),
    )
    input_path = _resolve(root, str(input_image)).resolve()
    reference_path = (
        _resolve(root, str(container_reference_image)).resolve()
        if container_reference_image
        else None
    )
    if not input_path.is_file():
        raise FileNotFoundError(f"Input image does not exist: {input_path}")
    if manifest["request"]["identity_policy"]["container"] == "adopt_reference":
        if reference_path is None or not reference_path.is_file():
            raise FileNotFoundError("Adopt-reference QA requires the original container reference")

    return evaluate_and_maybe_repair(
        project_root=root,
        request=manifest["request"],
        manifest=manifest,
        store=store,
        provider=None,
        evaluator=quality_evaluator,
        runtime_profile=None,
        lighting_sheet=lighting_sheet,
        original_product_image=input_path,
        container_reference_image=reference_path,
        allow_paid_repair=False,
        force_re_evaluation=True,
    )


def run_local_quality_pipeline(
    *,
    evaluator: QualityEvaluator,
    project_root: str | Path,
    mood_package_path: str | Path,
    product_analysis_path: str | Path,
    scene_reference_path: str | Path | None = None,
    scene_graph_path: str | Path | None = None,
    target_slot_id: str = "auto",
    placement_mode: str = "replace",
    product_kind: str = "beverage",
    cross_kind_replacement: bool = False,
    unbound_slot_policy: str = "genericize",
    input_image: str | Path,
    fixture_image: str | Path | None,
    output_root: str | Path,
    seed: int = 713,
    features_path: str | Path | None = "configs/service-features.json",
    container_mode: str = "preserve_source",
    container_reference_image: str | Path | None = None,
    container_design_path: str | Path | None = None,
    brand_asset_image: str | Path | None = None,
    auto_paid_repair: bool | None = None,
) -> LocalPipelineResult:
    prepared = _prepare_pipeline(
        project_root=project_root,
        mood_package_path=mood_package_path,
        product_analysis_path=product_analysis_path,
        scene_reference_path=scene_reference_path,
        scene_graph_path=scene_graph_path,
        target_slot_id=target_slot_id,
        placement_mode=placement_mode,
        product_kind=product_kind,
        cross_kind_replacement=cross_kind_replacement,
        unbound_slot_policy=unbound_slot_policy,
        input_image=input_image,
        seed=seed,
        features_path=features_path,
        container_mode=container_mode,
        container_reference_image=container_reference_image,
        container_design_path=container_design_path,
        brand_asset_image=brand_asset_image,
        auto_paid_repair=auto_paid_repair,
    )
    run_root = _resolve(prepared.root, str(output_root)).resolve()
    fixture_path = (
        _resolve(prepared.root, str(fixture_image)).resolve() if fixture_image else None
    )
    store = RunStore(run_root)
    provider = FakeGenerationProvider(run_root / "_fake_provider", fixture_image=fixture_path)
    manifest, reused = execute_once(prepared.request, provider=provider, store=store)
    roles = prepared.request["generation"]["image_roles"]
    paths = prepared.request["generation"]["image_paths"]
    role_paths = dict(zip(roles, paths, strict=True))
    quality_result = evaluate_and_maybe_repair(
        project_root=prepared.root,
        request=prepared.request,
        manifest=manifest,
        store=store,
        provider=provider,
        evaluator=evaluator,
        runtime_profile=prepared.runtime_profile,
        lighting_sheet=prepared.lighting_sheet,
        original_product_image=role_paths["product_source"],
        container_reference_image=(
            role_paths.get("scene_hint") or role_paths.get("container_reference")
        ),
        brand_asset_image=role_paths.get("brand_asset"),
        poll_interval_seconds=0,
    )
    return _postprocess_pipeline(
        prepared,
        store=store,
        manifest=quality_result.manifest,
        reused=reused,
    )
