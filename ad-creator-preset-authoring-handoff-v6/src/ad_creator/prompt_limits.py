from __future__ import annotations

from dataclasses import dataclass


DEFAULT_UNVERIFIED_PROMPT_CHARACTER_LIMIT = 6_000
SCHEMA_MAXIMUM_PROMPT_CHARACTER_LIMIT = 12_000


@dataclass(frozen=True)
class PromptLimitPolicy:
    policy_id: str
    maximum_characters: int
    verification_state: str


_MODEL_POLICIES = {
    ("higgsfield_cli", "gpt_image_2"): PromptLimitPolicy(
        policy_id="higgsfield_gpt_image_2_verified_12000_v1",
        maximum_characters=12_000,
        verification_state="verified_live",
    ),
    ("higgsfield_cli", "seedream_v5_pro"): PromptLimitPolicy(
        policy_id="higgsfield_seedream_v5_pro_conservative_6000_v1",
        maximum_characters=6_000,
        verification_state="unverified_conservative",
    ),
    ("higgsfield_cli", "flux_2"): PromptLimitPolicy(
        policy_id="higgsfield_flux_2_conservative_6000_v1",
        maximum_characters=6_000,
        verification_state="unverified_conservative",
    ),
    ("higgsfield_cli", "nano_banana_flash"): PromptLimitPolicy(
        policy_id="higgsfield_nano_banana_flash_conservative_6000_v1",
        maximum_characters=6_000,
        verification_state="unverified_conservative",
    ),
    ("openai_images_api", "gpt-image-1-mini"): PromptLimitPolicy(
        policy_id="openai_gpt_image_1_mini_verified_12000_v1",
        maximum_characters=12_000,
        verification_state="verified_live",
    ),
}


def resolve_prompt_limit_policy(
    *,
    provider: object,
    model: object,
) -> PromptLimitPolicy:
    """Resolve a transport-specific prompt cap without optimistic guessing.

    Known live-verified provider/model pairs may use the 12,000-character schema
    ceiling. Unknown pairs stay on the conservative cap until a separate probe
    publishes a new policy.
    """

    provider_key = provider if isinstance(provider, str) else ""
    model_key = model if isinstance(model, str) else ""
    policy = _MODEL_POLICIES.get((provider_key, model_key))
    if policy is not None:
        return policy
    return PromptLimitPolicy(
        policy_id="unknown_provider_model_conservative_6000_v1",
        maximum_characters=DEFAULT_UNVERIFIED_PROMPT_CHARACTER_LIMIT,
        verification_state="unverified_conservative",
    )
