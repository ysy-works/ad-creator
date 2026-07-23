from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonio import load_json


OPENAI_PROVIDER_PROFILE_PATH = "configs/providers/openai-gpt-image-1-mini.json"


@dataclass(frozen=True)
class AppliedProviderProfile:
    runtime_profile: dict[str, Any]
    provider_profile: dict[str, Any]
    profile_path: str
    profile_sha256: str


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _contract_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def apply_provider_profile(
    *,
    project_root: str | Path,
    runtime_profile: dict[str, Any],
    provider_profile_path: str | Path,
) -> AppliedProviderProfile:
    """Overlay a provider transport contract without mutating the mood profile."""
    root = Path(project_root).resolve()
    resolved = _resolve(root, provider_profile_path)
    provider_profile = load_json(resolved)
    required = {"provider", "model", "submission_path"}
    missing = sorted(required - set(provider_profile))
    if missing:
        raise ValueError(f"Provider profile is missing required fields: {missing}")

    applied = copy.deepcopy(runtime_profile)
    applied["provider"] = provider_profile["provider"]
    applied["model"] = provider_profile["model"]
    applied["submission_path"] = provider_profile["submission_path"]

    if provider_profile["provider"] == "openai_images_api":
        if provider_profile["model"] != "gpt-image-1-mini":
            raise ValueError("OpenAI provider profile must use gpt-image-1-mini")
        if provider_profile["submission_path"] != "images_edit":
            raise ValueError("OpenAI provider profile must use images_edit")
        if provider_profile.get("size") not in {
            "1024x1024",
            "1024x1536",
            "1536x1024",
        }:
            raise ValueError("OpenAI provider profile uses an unsupported image size")
        if provider_profile.get("input_fidelity") not in {"low", "high"}:
            raise ValueError("OpenAI provider profile must declare input_fidelity")
        if provider_profile.get("automatic_retries") != 0:
            raise ValueError("OpenAI provider profile must disable automatic retries")
        for cost in applied["cost_profiles"].values():
            cost["credits_per_image"] = 0
        applied["retry_policy"]["identity_repair"]["credits"] = 0

    return AppliedProviderProfile(
        runtime_profile=applied,
        provider_profile=provider_profile,
        profile_path=_contract_path(root, resolved),
        profile_sha256=hashlib.sha256(
            json.dumps(
                provider_profile,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    )


def record_provider_profile(
    request: dict[str, Any],
    application: AppliedProviderProfile,
) -> None:
    """Record the applied transport and its non-Higgsfield billing semantics."""
    generation = request["generation"]
    profile = application.provider_profile
    generation["provider"] = profile["provider"]
    generation["job_type"] = profile["model"]
    generation["submission_path"] = profile["submission_path"]
    request.setdefault("runtime_contracts", {})["provider_profile_path"] = (
        application.profile_path
    )
    request["runtime_contracts"]["provider_profile_sha256"] = (
        application.profile_sha256
    )

    if profile["provider"] == "openai_images_api":
        generation["estimated_credits"] = 0
        generation["billing_not_applicable"] = {
            "scope": "legacy_higgsfield_credit_accounting",
            "api_billing": "applies_separately",
        }
        generation["billing_metadata"] = {
            "legacy_unit": "higgsfield_credit",
            "legacy_credits": 0,
            "usage_source": "provider_response_metadata",
        }
        request["repair_policy"]["auto_paid_repair"] = False
