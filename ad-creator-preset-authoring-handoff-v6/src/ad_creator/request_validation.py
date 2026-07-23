from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .image_contracts import (
    require_generation_ready_brand_contract,
    validate_product_analysis_v3,
    validate_product_analysis_binding,
    verified_logo_text,
)
from .prompting import (
    GENERATION_REQUEST_V3_SCHEMA_VERSION,
    MULTI_PROMPT_COMPILER_VERSION,
    assemble_product_set,
    require_product_spec_generation_ready,
    validate_product_spec,
)
from .prompt_limits import resolve_prompt_limit_policy
from .serving_contracts import require_serving_compatibility_ready


DEFAULT_MODEL_ALLOWLIST = {"gpt_image_2", "gpt-image-1-mini"}
MODEL_PROVIDERS = {
    "gpt_image_2": "higgsfield_cli",
    "gpt-image-1-mini": "openai_images_api",
}


def _validate_provider_model(generation: dict[str, Any]) -> None:
    model = generation.get("job_type")
    provider = generation.get("provider")
    expected_provider = MODEL_PROVIDERS.get(model)
    # Provider-less requests remain valid for legacy callers. Once a provider is
    # declared, its model spelling is an exact transport contract.
    if provider is not None and expected_provider is not None and provider != expected_provider:
        raise ValueError(
            f"Provider/model mismatch: {provider!r} cannot run {model!r}; "
            f"expected {expected_provider!r}"
        )


def _validate_image_roles(request: dict[str, Any]) -> None:
    generation = request["generation"]
    image_paths = generation.get("image_paths")
    if not isinstance(image_paths, list):
        raise ValueError("Generation image_paths must be an array")
    roles = generation.get("image_roles")
    if roles is None:
        if len(image_paths) != 1:
            raise ValueError("Legacy requests may submit exactly one user product image")
        return
    if not isinstance(roles, list) or len(roles) != len(image_paths):
        raise ValueError("Generation image_roles must align with image_paths")
    if len(image_paths) > 4:
        raise ValueError("Legacy generation requests may submit at most four images")
    mode = request.get("identity_policy", {}).get("container", "preserve_source")
    reference_control = request.get("reference_control") or {}
    reference_role = reference_control.get("role", "container_design_only")
    if mode == "adopt_reference":
        expected_prefix = {
            "container_design_only": ["product_source", "container_reference"],
            "structured_only": ["product_source"],
            "sanitized_scene_hint": ["product_source", "scene_hint"],
        }.get(reference_role)
        if expected_prefix is None:
            raise ValueError(f"Unsupported reference control role: {reference_role}")
    else:
        expected_prefix = (
            ["product_source", "scene_hint"]
            if reference_role == "sanitized_scene_hint"
            else ["product_source"]
        )
    if roles[: len(expected_prefix)] != expected_prefix:
        raise ValueError(f"Invalid image roles for {mode}: {roles}")
    remaining = roles[len(expected_prefix) :]
    if remaining not in ([], ["brand_asset"]):
        raise ValueError(f"Unsupported additional image roles: {remaining}")
    features = request.get("service_features", {}).get("features", {})
    if mode == "adopt_reference" and features.get("container_choice", {}).get("enabled") is False:
        raise ValueError("Container choice is disabled; adopt_reference is not allowed")


def _product_analysis_brand_state(analysis: dict[str, Any]) -> str | None:
    identity = analysis.get("identity")
    if isinstance(identity, dict):
        branding = identity.get("branding")
        if isinstance(branding, dict):
            state = branding.get("state")
            if isinstance(state, str):
                return state
    for container_key in ("brand_application", "branding"):
        container = analysis.get(container_key)
        if not isinstance(container, dict):
            continue
        for state_key in ("presence_state", "state", "presence"):
            state = container.get(state_key)
            if isinstance(state, str):
                return state
    return None


def _validate_v3_products(request: dict[str, Any]) -> list[dict[str, Any]]:
    products = request.get("products")
    if not isinstance(products, list):
        raise ValueError("GenerationRequestV3 products must be an array")
    product_set = assemble_product_set(products)
    embedded_set = request.get("product_set")
    if embedded_set is not None and embedded_set != product_set:
        raise ValueError("GenerationRequestV3 product_set does not match products")
    for product in products:
        validate_product_spec(product)
        require_product_spec_generation_ready(product)
        require_serving_compatibility_ready(
            product["product_id"],
            product.get("serving_compatibility_resolution"),
        )
        analysis = product.get("product_analysis")
        if isinstance(analysis, dict):
            if analysis.get("schema_version") == "3.0.0":
                validate_product_analysis_v3(analysis)
            require_generation_ready_brand_contract(analysis)
            state = _product_analysis_brand_state(analysis)
            if state in {"uncertain", "unknown", "unverified"}:
                raise ValueError(
                    f"Product {product['product_id']} branding is uncertain; generation is blocked"
                )
    return products


def _validate_v3_image_inputs(
    request: dict[str, Any],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    generation = request["generation"]
    if "image_paths" in generation or "image_roles" in generation:
        raise ValueError(
            "GenerationRequestV3 must use image_inputs, not legacy image_paths/image_roles"
        )
    image_inputs = generation.get("image_inputs")
    if not isinstance(image_inputs, list) or not 1 <= len(image_inputs) <= 4:
        raise ValueError("GenerationRequestV3 image_inputs must contain one to four images")

    product_inputs = []
    control_board_seen = False
    for index, item in enumerate(image_inputs):
        if not isinstance(item, dict):
            raise ValueError("Every image_inputs item must be an object")
        role = item.get("role")
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Every image_inputs item requires a non-empty path")
        if role == "product_source":
            if control_board_seen:
                raise ValueError("product_source inputs must precede the control board")
            if set(item) != {"role", "path", "product_id"}:
                raise ValueError(
                    "product_source inputs require exactly role, path and product_id"
                )
            product_id = item.get("product_id")
            if not isinstance(product_id, str) or not product_id.strip():
                raise ValueError("product_source inputs require a product_id")
            product_inputs.append(item)
        elif role == "reference_control_board":
            if set(item) != {"role", "path"}:
                raise ValueError(
                    "reference_control_board inputs require exactly role and path"
                )
            if control_board_seen or index != len(image_inputs) - 1:
                raise ValueError(
                    "At most one reference_control_board is allowed and it must be last"
                )
            control_board_seen = True
        else:
            raise ValueError(f"Unsupported GenerationRequestV3 image role: {role!r}")

    expected_ids = [item["product_id"] for item in products]
    observed_ids = [item["product_id"] for item in product_inputs]
    if observed_ids != expected_ids:
        raise ValueError(
            "Ordered product_source inputs must match the ProductSpec product order"
        )
    expected_paths = [item["source_image"] for item in products]
    observed_paths = [item["path"] for item in product_inputs]
    if observed_paths != expected_paths:
        raise ValueError("product_source paths must match their ProductSpec source_image")
    if control_board_seen and request.get("reference_control_board_manifest") is None:
        raise ValueError("reference_control_board requires a separate manifest")
    if not control_board_seen and request.get("reference_control_board_manifest") is not None:
        raise ValueError("A control-board manifest cannot exist without its image input")
    return image_inputs


def validate_generation_request(
    request: dict[str, Any],
    *,
    maximum_credits: float = 2,
    maximum_prompt_characters: int | None = None,
    allowed_models: set[str] = DEFAULT_MODEL_ALLOWLIST,
    allow_virtual_images: bool = False,
) -> None:
    generation = request.get("generation")
    if not isinstance(generation, dict):
        raise ValueError("Generation request is missing generation")
    model = generation.get("job_type")
    if model not in allowed_models:
        raise ValueError(f"Model is not allowlisted: {model}")
    _validate_provider_model(generation)
    credits = generation.get("estimated_credits")
    if not isinstance(credits, (int, float)) or credits < 0 or credits > maximum_credits:
        raise ValueError(f"Estimated credits exceed the {maximum_credits}-credit limit")
    prompt = generation.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Generation prompt is empty")
    prompt_policy = resolve_prompt_limit_policy(
        provider=generation.get("provider"),
        model=model,
    )
    prompt_limit = prompt_policy.maximum_characters
    if maximum_prompt_characters is not None:
        if maximum_prompt_characters <= 0:
            raise ValueError("maximum_prompt_characters must be positive")
        prompt_limit = min(prompt_limit, maximum_prompt_characters)
    declared_limit = generation.get("prompt_character_limit")
    if declared_limit is not None and declared_limit != prompt_policy.maximum_characters:
        raise ValueError(
            "Generation prompt_character_limit does not match the provider/model policy"
        )
    declared_policy_id = generation.get("prompt_limit_policy_id")
    if declared_policy_id is not None and declared_policy_id != prompt_policy.policy_id:
        raise ValueError(
            "Generation prompt_limit_policy_id does not match the provider/model policy"
        )
    declared_verification = generation.get("prompt_limit_verification_state")
    if (
        declared_verification is not None
        and declared_verification != prompt_policy.verification_state
    ):
        raise ValueError(
            "Generation prompt_limit_verification_state does not match the provider/model policy"
        )
    if len(prompt) > prompt_limit:
        raise ValueError(
            f"Generation prompt has {len(prompt)} characters; limit is {prompt_limit} "
            f"({prompt_policy.policy_id})"
        )
    is_v3 = request.get("schema_version") == GENERATION_REQUEST_V3_SCHEMA_VERSION
    if is_v3:
        if request.get("prompt_compiler_version") != MULTI_PROMPT_COMPILER_VERSION:
            raise ValueError(
                "GenerationRequestV3 must use natural_compact_v5_multi"
            )
        products = _validate_v3_products(request)
        image_inputs = _validate_v3_image_inputs(request, products)
    else:
        if "image_inputs" in generation:
            raise ValueError("Legacy generation requests cannot use image_inputs")
        _validate_image_roles(request)
    analysis = request.get("product_analysis")
    if isinstance(analysis, dict):
        require_generation_ready_brand_contract(analysis)
        brand_contract = request.get("brand_contract")
        expected_brand = {
            "state": analysis["identity"]["branding"]["state"],
            "allowed_main_text": verified_logo_text(analysis),
            "visible_text": analysis["identity"]["branding"]["visible_text"],
            "non_text_mark": analysis["identity"]["branding"]["non_text_mark"],
        }
        resolution = request.get("brand_transfer_resolution")
        action = resolution.get("action") if isinstance(resolution, dict) else None
        if action in {"preserve_source_exact", "transfer_source_exact"}:
            expected_final_brand = expected_brand
        elif action == "omit_branding":
            expected_final_brand = {
                "state": "verified_absent",
                "allowed_main_text": None,
                "visible_text": [],
                "non_text_mark": None,
            }
        elif action == "block_uncertain":
            raise ValueError("Request brand transfer resolution blocks generation")
        elif action is None:
            expected_final_brand = expected_brand
        else:
            raise ValueError(f"Unsupported legacy brand transfer action: {action!r}")
        if brand_contract != expected_final_brand:
            raise ValueError("Request brand contract does not match final brand resolution")
        policy_action = request.get("identity_policy", {}).get("branding")
        if action is not None and policy_action != action:
            raise ValueError("Identity branding policy does not match final brand resolution")
        if expected_final_brand["state"] != "verified_present" and "brand_asset" in generation.get(
            "image_roles", []
        ):
            raise ValueError("Unbranded final targets cannot submit a brand asset")
    if allow_virtual_images:
        return
    raw_paths = (
        [item["path"] for item in image_inputs]
        if is_v3
        else generation["image_paths"]
    )
    for raw_path in raw_paths:
        image_path = Path(raw_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"Generation input image does not exist: {image_path}")
    if is_v3:
        for product in products:
            product_analysis = product.get("product_analysis")
            if isinstance(product_analysis, dict):
                if product_analysis.get("schema_version") == "3.0.0":
                    validate_product_analysis_v3(product_analysis)
                require_generation_ready_brand_contract(product_analysis)
                validate_product_analysis_binding(
                    product_analysis,
                    product["source_image"],
                )
        return
    if isinstance(analysis, dict):
        role_paths = dict(
            zip(generation["image_roles"], generation["image_paths"], strict=True)
        )
        binding_path = role_paths["product_source"]
        transform = request.get("provider_input_transform")
        if isinstance(transform, dict):
            if transform.get("role") != "product_source":
                raise ValueError("Provider input transform must target product_source")
            if transform.get("provider_path") != binding_path:
                raise ValueError("Provider input transform path does not match product_source")
            source_path = transform.get("source_path")
            if not isinstance(source_path, str) or not Path(source_path).is_file():
                raise ValueError("Provider input transform source path is missing")
            source_digest = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
            if transform.get("source_pixel_sha256") != source_digest:
                raise ValueError("Provider input transform source hash does not match")
            provider_digest = hashlib.sha256(Path(binding_path).read_bytes()).hexdigest()
            if transform.get("provider_pixel_sha256") != provider_digest:
                raise ValueError("Provider input transform output hash does not match")
            binding_path = source_path
        validate_product_analysis_binding(analysis, binding_path)


def validate_repair_request(
    request: dict[str, Any],
    *,
    maximum_credits: float = 2,
    maximum_prompt_characters: int | None = None,
    allowed_models: set[str] = DEFAULT_MODEL_ALLOWLIST,
    allow_virtual_images: bool = False,
) -> None:
    if request.get("repair_type") != "conditional_product_identity":
        raise ValueError("Unsupported repair request type")
    generation = request.get("generation", {})
    if generation.get("job_type") not in allowed_models:
        raise ValueError(f"Model is not allowlisted: {generation.get('job_type')}")
    _validate_provider_model(generation)
    credits = generation.get("estimated_credits")
    if not isinstance(credits, (int, float)) or credits < 0 or credits > maximum_credits:
        raise ValueError(f"Estimated repair credits exceed the {maximum_credits}-credit limit")
    prompt = generation.get("prompt")
    prompt_policy = resolve_prompt_limit_policy(
        provider=generation.get("provider"),
        model=generation.get("job_type"),
    )
    prompt_limit = prompt_policy.maximum_characters
    if maximum_prompt_characters is not None:
        if maximum_prompt_characters <= 0:
            raise ValueError("maximum_prompt_characters must be positive")
        prompt_limit = min(prompt_limit, maximum_prompt_characters)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > prompt_limit:
        raise ValueError("Repair prompt is empty or oversized")
    roles = generation.get("image_roles")
    paths = generation.get("image_paths")
    if not isinstance(roles, list) or not isinstance(paths, list) or len(roles) != len(paths):
        raise ValueError("Repair image roles must align with image paths")
    if roles[:2] != ["generated_scene", "product_source"] or roles[2:] not in ([], ["brand_asset"]):
        raise ValueError(f"Invalid repair image roles: {roles}")
    if request.get("maximum_attempts") != 1:
        raise ValueError("Repair requests must allow exactly one attempt")
    if not allow_virtual_images:
        for raw_path in paths:
            if not Path(raw_path).is_file():
                raise FileNotFoundError(f"Repair input image does not exist: {raw_path}")
