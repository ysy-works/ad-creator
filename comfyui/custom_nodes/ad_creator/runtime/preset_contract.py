from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


GLOBAL_MAX_PROVIDER_INPUTS = 4
GLOBAL_MAX_PRODUCT_SOURCES = 3
GLOBAL_MAX_REFERENCE_CONTROLS = 1
MAX_PROMPT_CHARACTERS = 12_000
SUPPORTED_CONTAINER_MODES = {"adopt_reference", "reconstruct_source"}
LEGACY_CONTAINER_MODE_ALIASES = {"preserve_source": "reconstruct_source"}
SUPPORTED_SERVING_TEMPERATURES = {"auto", "iced", "cold", "ambient", "hot"}
RUNTIME_COMPILER_VERSION = "preset-runtime-v1"


class PresetRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


@dataclass(frozen=True)
class ResolvedPresetContract:
    slot_id: str
    preset_id: str
    status: str
    source_review_status: str
    compiler_version: str
    prompt: str
    prompt_sha256: str
    bundle_sha256: str
    bundle_path: Path
    container_mode: str
    serving_temperature: str
    temperature_resolution_source: str
    companion_policy: str
    brand_input_enabled: bool
    brand_default_mode: str
    brand_policy_sha256: str
    provider_image_paths: tuple[Path, ...]
    provider_image_roles: tuple[str, ...]
    maximum_provider_inputs: int
    maximum_product_sources: int
    maximum_reference_controls: int
    aspect_ratio: str
    aspect_status: str
    delivery_width: int
    delivery_height: int
    generation_size: str
    safe_crop: str
    output_format: str
    bbox_qa: dict[str, Any]
    declared_transforms: tuple[dict[str, Any], ...]
    runtime_policy: dict[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", f"Cannot read JSON: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", f"JSON must be an object: {path.name}"
        )
    return value


def _safe_path(root: Path, base: Path, relative_path: str) -> Path:
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or Path(relative_path).is_absolute()
    ):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Preset paths must be non-empty and relative.",
        )
    candidate = (base / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Preset path escapes the published asset root.",
        ) from exc
    if not candidate.is_file():
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            f"Preset asset is missing: {candidate.name}",
        )
    return candidate


def _sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".json", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _verified_asset(
    *, preset_root: Path, bundle_dir: Path, binding: dict[str, Any], label: str
) -> Path:
    path = _safe_path(preset_root, bundle_dir, str(binding.get("path") or ""))
    expected = binding.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64 or _sha256(path) != expected:
        raise PresetRuntimeError(
            "PRESET_ASSET_HASH_MISMATCH", f"Preset {label} changed: {path.name}"
        )
    return path


def _compact(value: Any, limit: int = 220) -> str:
    return " ".join(str(value or "").split())[:limit]


def _lighting_prompt(sheet: dict[str, Any]) -> str:
    key = sheet.get("key_light") if isinstance(sheet.get("key_light"), dict) else {}
    shadow = (
        sheet.get("shadow_contract")
        if isinstance(sheet.get("shadow_contract"), dict)
        else {}
    )
    capture = (
        sheet.get("capture_contract")
        if isinstance(sheet.get("capture_contract"), dict)
        else {}
    )
    forbidden = sheet.get("forbidden") if isinstance(sheet.get("forbidden"), list) else []
    required = (
        sheet.get("lighting_sheet_id"),
        sheet.get("mood"),
        key.get("source"),
        key.get("direction"),
        key.get("relative_size"),
        shadow.get("edge"),
        capture.get("white_balance"),
    )
    if any(not isinstance(item, str) or not item.strip() for item in required):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Lighting sheet is missing an authoritative field.",
        )
    return (
        f"Sheet={_compact(sheet['lighting_sheet_id'], 100)}. "
        f"Mood={_compact(sheet['mood'])}. "
        f"Key={_compact(key['source'])}; direction={_compact(key['direction'])}; "
        f"apparent size={_compact(key['relative_size'])}. "
        f"Ambient={_compact(sheet.get('ambient_fill'))}. "
        f"Shadow edge={_compact(shadow['edge'])}; "
        f"attachment={_compact(shadow.get('attachment'))}. "
        f"White balance={_compact(capture['white_balance'])}; "
        f"texture={_compact(capture.get('texture'))}. "
        f"Reject={'; '.join(_compact(item, 90) for item in forbidden[:8])}."
    )


def _runtime_policy(bundle: dict[str, Any]) -> dict[str, Any]:
    policy = bundle.get("runtime_policy")
    if not isinstance(policy, dict):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Preset must declare runtime_policy.",
        )
    required = {
        "schema_version": 1,
        "compiler_version": RUNTIME_COMPILER_VERSION,
        "maximum_prompt_characters": MAX_PROMPT_CHARACTERS,
        "maximum_provider_inputs": GLOBAL_MAX_PROVIDER_INPUTS,
        "maximum_product_sources": GLOBAL_MAX_PRODUCT_SOURCES,
        "maximum_reference_controls": GLOBAL_MAX_REFERENCE_CONTROLS,
    }
    for field, expected in required.items():
        if policy.get(field) != expected:
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION",
                f"runtime_policy requires {field}={expected!r}.",
            )
    companion = policy.get("companion_policy")
    if companion not in {"none", "reference_relational", "explicit_only"}:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "companion_policy is invalid."
        )
    brand = policy.get("brand_input_policy")
    if not isinstance(brand, dict) or brand.get("enabled") is not False:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Brand input must remain explicitly disabled in this runtime version.",
        )
    brand_default_mode = brand.get("default_mode")
    if brand_default_mode not in {"none", "preset_typography"}:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "brand_input_policy default_mode is invalid.",
        )
    typography = brand.get("preset_typography", [])
    if not isinstance(typography, list) or any(
        not isinstance(item, dict) for item in typography
    ):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "brand_input_policy preset_typography must be a list of objects.",
        )
    if brand_default_mode == "none" and typography:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Brand-free presets cannot declare default typography.",
        )
    if brand_default_mode == "preset_typography":
        if not typography:
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION",
                "Preset typography mode requires at least one surface declaration.",
            )
        for item in typography:
            if any(
                not isinstance(item.get(field), str) or not item[field].strip()
                for field in ("text", "target_surface", "transfer_scope")
            ):
                raise PresetRuntimeError(
                    "INVALID_PRESET_CONFIGURATION",
                    "Preset typography declarations require text, target_surface and transfer_scope.",
                )
    override = brand.get("future_user_logo_override")
    if override is not None:
        if (
            not isinstance(override, dict)
            or override.get("enabled") is not False
            or override.get("request_scope") != "per_image"
            or override.get("replacement_action") != "replace_default_typography_only"
            or not isinstance(override.get("target_surface"), str)
            or not override["target_surface"].strip()
        ):
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION",
                "Future user-logo override contract is invalid or prematurely enabled.",
            )
    temperature = policy.get("temperature_policy")
    if not isinstance(temperature, dict) or temperature.get("mode") != "preset_primary":
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "temperature_policy must use preset_primary mode.",
        )
    fallback = temperature.get("emergency_fallback")
    if (
        not isinstance(fallback, dict)
        or fallback.get("enabled_when_policy_missing") is not True
        or fallback.get("minimum_confidence") != 0.85
        or fallback.get("unknown_action") != "needs_review"
        or fallback.get("conflict_action") != "needs_review"
    ):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "temperature emergency fallback contract is invalid.",
        )
    return dict(policy)


def _container_mode(bundle: dict[str, Any], policy: dict[str, Any], requested: str) -> str:
    requested = LEGACY_CONTAINER_MODE_ALIASES.get(requested, requested)
    if requested == "default":
        requested = str(
            policy.get("default_container_mode")
            or bundle.get("default_container_mode")
            or "adopt_reference"
        )
        requested = LEGACY_CONTAINER_MODE_ALIASES.get(requested, requested)
    if requested not in SUPPORTED_CONTAINER_MODES:
        raise PresetRuntimeError("UNSUPPORTED_CONTAINER_MODE", requested)
    supported = policy.get("supported_container_modes")
    if not isinstance(supported, list) or not supported:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "runtime_policy must declare supported_container_modes.",
        )
    normalized_supported = {
        LEGACY_CONTAINER_MODE_ALIASES.get(str(value), str(value)) for value in supported
    }
    if requested not in normalized_supported:
        raise PresetRuntimeError(
            "UNSUPPORTED_CONTAINER_MODE",
            f"Preset does not support container_mode={requested}.",
        )
    return requested


def _temperature(
    policy: dict[str, Any], requested: str, container_mode: str
) -> tuple[str, str]:
    if requested not in SUPPORTED_SERVING_TEMPERATURES:
        raise PresetRuntimeError("INVALID_SERVING_TEMPERATURE", requested)
    temperature_policy = policy["temperature_policy"]
    by_mode = temperature_policy.get("container_mode_rules")
    if not isinstance(by_mode, dict) or container_mode not in by_mode:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            f"temperature_policy has no rule for {container_mode}.",
        )
    rule = by_mode[container_mode]
    if not isinstance(rule, dict):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Temperature mode rule must be an object."
        )
    allowed = rule.get("allowed_product_states")
    if not isinstance(allowed, list) or not allowed:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Temperature mode rule has no allowed states."
        )
    allowed_set = {str(value) for value in allowed}
    if requested == "auto":
        auto_action = rule.get("auto_action")
        if auto_action == "preserve_source_state":
            return "source_authoritative", "user_product_image"
        if auto_action == "use_preset_default_state":
            default_state = str(rule.get("default_state") or "")
            normalized = (
                "cold"
                if default_state == "iced" and "iced" not in allowed_set
                else default_state
            )
            if default_state not in allowed_set and normalized not in allowed_set:
                raise PresetRuntimeError(
                    "INVALID_PRESET_CONFIGURATION",
                    "Temperature preset default is not allowed for this container mode.",
                )
            return default_state, "preset_default"
        if auto_action == "requires_explicit_state":
            raise PresetRuntimeError(
                "SERVING_TEMPERATURE_REVIEW_REQUIRED",
                "This container mode requires an explicit hot/ice selection.",
            )
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Temperature auto_action is invalid."
        )
    normalized = "cold" if requested == "iced" and "iced" not in allowed_set else requested
    if requested not in allowed_set and normalized not in allowed_set:
        raise PresetRuntimeError(
            "INCOMPATIBLE_SERVING_TEMPERATURE",
            f"{container_mode} does not support {requested}.",
        )
    return requested, "explicit_request"


def _iter_contract_bindings(bundle: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    contract_assets = bundle.get("contract_assets")
    if contract_assets is None:
        return ()
    if not isinstance(contract_assets, dict):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "contract_assets must be an object."
        )
    values: list[tuple[str, dict[str, Any]]] = []
    for name, binding in contract_assets.items():
        if not isinstance(binding, dict):
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION", f"Invalid contract asset: {name}"
            )
        values.append((str(name), binding))
    return tuple(values)


def _selected_hints(
    *,
    bundle: dict[str, Any],
    preset_root: Path,
    bundle_dir: Path,
    container_mode: str,
) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    hints = bundle.get("hint_images")
    if not isinstance(hints, list):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Preset hint_images must be a list."
        )
    legacy_mode = "preserve_source" if container_mode == "reconstruct_source" else container_mode
    mode_contracts = bundle.get("container_modes")
    mode_contract = None
    if isinstance(mode_contracts, dict):
        mode_contract = mode_contracts.get(container_mode) or mode_contracts.get(legacy_mode)
    selected_role = (
        mode_contract.get("provider_hint_role")
        if isinstance(mode_contract, dict)
        else None
    )
    paths: list[Path] = []
    roles: list[str] = []
    for item in hints:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION", "Preset hint binding is invalid."
            )
        path = _verified_asset(
            preset_root=preset_root,
            bundle_dir=bundle_dir,
            binding=item,
            label="hint image",
        )
        try:
            with Image.open(path) as image:
                dimensions = [image.width, image.height]
                image.verify()
        except (OSError, Image.DecompressionBombError) as exc:
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION", "Preset hint image is invalid."
            ) from exc
        if dimensions != [item.get("width"), item.get("height")]:
            raise PresetRuntimeError(
                "PRESET_ASSET_DIMENSION_MISMATCH",
                f"Preset hint dimensions changed: {path.name}",
            )
        scopes = item.get("container_mode_scope")
        normalized_scopes = None
        if isinstance(scopes, list):
            normalized_scopes = {
                LEGACY_CONTAINER_MODE_ALIASES.get(str(value), str(value)) for value in scopes
            }
        scoped_for_mode = normalized_scopes is None or container_mode in normalized_scopes
        sent = item.get("send_to_provider") is True and scoped_for_mode
        if selected_role is not None:
            sent = item["role"] == selected_role
        if sent:
            paths.append(path)
            roles.append(item["role"])
    if selected_role is not None and selected_role not in roles:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            f"container mode hint role is unavailable: {selected_role}",
        )
    if len(paths) > GLOBAL_MAX_REFERENCE_CONTROLS:
        raise PresetRuntimeError(
            "PROVIDER_INPUT_LIMIT_EXCEEDED",
            "A preset may send at most one reference control image.",
        )
    return tuple(paths), tuple(roles)


def _mode_prompt_binding(
    bundle: dict[str, Any], container_mode: str
) -> dict[str, Any]:
    default = bundle.get("prompt_template")
    if not isinstance(default, dict):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Preset has no prompt template."
        )
    modes = bundle.get("container_modes")
    if not isinstance(modes, dict):
        return default
    legacy_mode = "preserve_source" if container_mode == "reconstruct_source" else container_mode
    mode = modes.get(container_mode) or modes.get(legacy_mode)
    if not isinstance(mode, dict):
        return default
    binding = mode.get("prompt_template")
    return binding if isinstance(binding, dict) else default


def _runtime_prompt_clause(
    *, policy: dict[str, Any], container_mode: str, serving_temperature: str
) -> str:
    companion = str(policy["companion_policy"])
    if companion == "none":
        companion_clause = "Generate no companion product or undeclared scene prop."
    elif companion == "reference_relational":
        companion_clause = (
            "Generate only the generic unbranded companions explicitly declared by this preset; "
            "never duplicate the exact user product."
        )
    else:
        companion_clause = "Generate only companions explicitly supplied by the request."
    temperature_clause = (
        "SERVING STATE AUTHORITY: Image 1 is the sole authority for beverage type, "
        "source serving temperature, visible ice state, liquid layers, foam or crema, "
        "toppings, garnish and beverage color. Reference and control images have no "
        "beverage or serving-state authority: never copy their drink, hot-or-cold state, "
        "ice or no-ice state, foam, crema, steam, garnish, recipe or beverage color. "
        "Preserve only serving cues actually visible in Image 1; do not invent ice, "
        "condensation or steam."
        if serving_temperature == "source_authoritative"
        else f"The product serving state is explicitly {serving_temperature}; keep its vessel and visible service cues physically compatible."
    )
    brand = policy["brand_input_policy"]
    brand_mode = str(brand["default_mode"])
    if brand_mode == "preset_typography":
        declarations = "; ".join(
            f'exact text "{_compact(item["text"], 80)}" on {_compact(item["target_surface"], 120)}'
            for item in brand["preset_typography"]
        )
        brand_clause = (
            "Brand input is disabled for this execution. Preserve only the preset-declared "
            f"default typography ({declarations}). Treat it as surface-specific default copy, not "
            "authority to transfer any source or reference brand. Add no other logo, wordmark, "
            "label text, invented lettering or watermark. The future per-image user-logo override "
            "remains inactive."
        )
    else:
        brand_clause = (
            "Brand input is disabled for this execution. Generate every exact and generic "
            "vessel without a logo, wordmark, copied label, invented lettering or watermark. "
            "No earlier prompt phrase authorizes branding."
        )
    return (
        "\n\n[RUNTIME POLICY - AUTHORITATIVE]\n"
        f"Compiler={RUNTIME_COMPILER_VERSION}. Container mode={container_mode}. "
        f"{temperature_clause} {companion_clause} "
        f"{brand_clause}"
    )


def resolve_preset_contract(
    slot_id: str,
    *,
    aspect_ratio: str = "4:5",
    container_mode: str = "default",
    serving_temperature: str = "auto",
    registry_path: str | Path,
    allowed_statuses: tuple[str, ...] = ("published",),
) -> ResolvedPresetContract:
    registry_path = Path(registry_path).resolve()
    registry = _read_json(registry_path)
    if registry.get("schema_version") != 1:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Preset registry schema_version must be 1."
        )
    slots = registry.get("slots")
    if not isinstance(slots, dict) or slot_id not in slots:
        raise PresetRuntimeError("UNKNOWN_PRESET", f"Unknown preset slot: {slot_id}")
    slot = slots[slot_id]
    if not isinstance(slot, dict) or not slot.get("enabled"):
        raise PresetRuntimeError("PRESET_NOT_READY", f"Preset is not enabled: {slot_id}")
    slot_status = str(slot.get("status") or "")
    if slot_status not in allowed_statuses:
        raise PresetRuntimeError(
            "PRESET_NOT_READY", f"Preset status is {slot_status or 'missing'}: {slot_id}"
        )
    preset_root = registry_path.parent.resolve()
    bundle_path = _safe_path(preset_root, preset_root, str(slot.get("bundle") or ""))
    bundle = _read_json(bundle_path)
    if (
        bundle.get("schema_version") != 1
        or bundle.get("slot_id") != slot_id
        or bundle.get("preset_id") != slot.get("preset_id")
        or bundle.get("family") != slot.get("family")
        or bundle.get("composition") != slot.get("composition")
        or bundle.get("status") != slot_status
    ):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Preset registry and bundle do not match."
        )
    review_status = str(bundle.get("source_review_status") or "")
    if slot_status == "published" and review_status != "passed_by_user_review":
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Published preset must be passed by user review.",
        )
    if slot_status == "validated" and review_status == "passed_by_user_review":
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION",
            "Validated preset must not claim passed user review.",
        )
    bundle_dir = bundle_path.parent
    policy = _runtime_policy(bundle)
    resolved_mode = _container_mode(bundle, policy, container_mode)
    resolved_temperature, temperature_source = _temperature(
        policy, serving_temperature, resolved_mode
    )

    prompt_path = _verified_asset(
        preset_root=preset_root,
        bundle_dir=bundle_dir,
        binding=_mode_prompt_binding(bundle, resolved_mode),
        label="prompt template",
    )
    lighting_binding = bundle.get("lighting_sheet")
    grade_binding = bundle.get("grade_profile")
    if not isinstance(lighting_binding, dict) or not isinstance(grade_binding, dict):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Preset is missing lighting or grade."
        )
    lighting_path = _verified_asset(
        preset_root=preset_root,
        bundle_dir=bundle_dir,
        binding=lighting_binding,
        label="lighting sheet",
    )
    _verified_asset(
        preset_root=preset_root,
        bundle_dir=bundle_dir,
        binding=grade_binding,
        label="grade profile",
    )
    if grade_binding.get("apply_in_pilot") is not False:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Grade profile must remain review-only."
        )
    for name, binding in _iter_contract_bindings(bundle):
        _verified_asset(
            preset_root=preset_root,
            bundle_dir=bundle_dir,
            binding=binding,
            label=name,
        )

    provider_paths, provider_roles = _selected_hints(
        bundle=bundle,
        preset_root=preset_root,
        bundle_dir=bundle_dir,
        container_mode=resolved_mode,
    )
    input_lines = [
        "Image 1 is the exact user product source and the only product-identity authority."
    ]
    for index, role in enumerate(provider_roles, start=2):
        input_lines.append(f"Image {index} is the published {role.replace('_', ' ')}.")
    template = prompt_path.read_text(encoding="utf-8")
    for placeholder in ("{{INPUT_ROLES}}", "{{LIGHTING_CONTRACT}}", "{{ASPECT_CONTRACT}}"):
        if template.count(placeholder) > 1:
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION",
                f"Prompt template may contain {placeholder} at most once.",
            )
    aspects = bundle.get("aspect_ratio_contracts")
    if not isinstance(aspects, dict) or aspect_ratio not in aspects:
        raise PresetRuntimeError(
            "UNSUPPORTED_ASPECT_RATIO", f"Unsupported aspect ratio: {aspect_ratio}"
        )
    aspect = aspects[aspect_ratio]
    if not isinstance(aspect, dict):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Aspect contract must be an object."
        )
    prompt_addendum = aspect.get("prompt_addendum")
    bbox_qa = aspect.get("bbox_qa")
    if (
        not isinstance(prompt_addendum, str)
        or not prompt_addendum.strip()
        or not isinstance(bbox_qa, dict)
        or bbox_qa.get("crop_allowed") is not False
    ):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Aspect prompt or bbox QA is invalid."
        )
    prompt = template
    compiled_sections = (
        ("{{INPUT_ROLES}}", "[RESOLVED INPUT ROLES]\n" + "\n".join(input_lines)),
        ("{{LIGHTING_CONTRACT}}", "[RESOLVED LIGHTING CONTRACT]\n" + _lighting_prompt(_read_json(lighting_path))),
        ("{{ASPECT_CONTRACT}}", "[RESOLVED ASPECT CONTRACT]\n" + prompt_addendum.strip()),
    )
    for placeholder, compiled in compiled_sections:
        if placeholder in prompt:
            _, _, replacement = compiled.partition("\n")
            prompt = prompt.replace(placeholder, replacement)
        else:
            prompt += "\n\n" + compiled
    mode_contracts = bundle.get("container_modes")
    if isinstance(mode_contracts, dict):
        legacy_mode = "preserve_source" if resolved_mode == "reconstruct_source" else resolved_mode
        mode_contract = mode_contracts.get(resolved_mode) or mode_contracts.get(legacy_mode)
        if isinstance(mode_contract, dict) and isinstance(mode_contract.get("prompt_addendum"), str):
            prompt += "\n\n" + mode_contract["prompt_addendum"].strip()
    prompt += _runtime_prompt_clause(
        policy=policy,
        container_mode=resolved_mode,
        serving_temperature=resolved_temperature,
    )
    if "{{" in prompt or "}}" in prompt:
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "Prompt has unresolved placeholders."
        )
    if len(prompt) > MAX_PROMPT_CHARACTERS:
        raise PresetRuntimeError(
            "PROMPT_LIMIT_EXCEEDED",
            f"Compiled prompt is {len(prompt)} characters; limit is {MAX_PROMPT_CHARACTERS}.",
        )

    per_preset_limit = GLOBAL_MAX_PROVIDER_INPUTS
    reference_policy = bundle.get("provider_reference_policy")
    if isinstance(reference_policy, dict):
        value = reference_policy.get("maximum_images")
        if not isinstance(value, int) or not 1 <= value <= GLOBAL_MAX_PROVIDER_INPUTS:
            raise PresetRuntimeError(
                "INVALID_PRESET_CONFIGURATION", "provider_reference_policy maximum is invalid."
            )
        per_preset_limit = value
    if 1 + len(provider_paths) > per_preset_limit:
        raise PresetRuntimeError(
            "PROVIDER_INPUT_LIMIT_EXCEEDED",
            "Preset input plan exceeds its declared provider limit.",
        )
    transforms = bundle.get("transforms", [])
    if not isinstance(transforms, list) or any(not isinstance(item, dict) for item in transforms):
        raise PresetRuntimeError(
            "INVALID_PRESET_CONFIGURATION", "transforms must be a list of objects."
        )
    allowed_transform_types = {
        "normalize_product_source",
        "crop_product_by_analysis_geometry",
        "select_hint_by_container_mode",
        "sanitize_reference_control",
    }
    for item in transforms:
        if item.get("type") not in allowed_transform_types:
            raise PresetRuntimeError(
                "UNSUPPORTED_TRANSFORM", str(item.get("type"))
            )

    return ResolvedPresetContract(
        slot_id=slot_id,
        preset_id=str(bundle["preset_id"]),
        status=slot_status,
        source_review_status=review_status,
        compiler_version=RUNTIME_COMPILER_VERSION,
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        bundle_sha256=_canonical_json_sha256(bundle),
        bundle_path=bundle_path,
        container_mode=resolved_mode,
        serving_temperature=resolved_temperature,
        temperature_resolution_source=temperature_source,
        companion_policy=str(policy["companion_policy"]),
        brand_input_enabled=False,
        brand_default_mode=str(policy["brand_input_policy"]["default_mode"]),
        brand_policy_sha256=_canonical_json_sha256(policy["brand_input_policy"]),
        provider_image_paths=provider_paths,
        provider_image_roles=provider_roles,
        maximum_provider_inputs=per_preset_limit,
        maximum_product_sources=GLOBAL_MAX_PRODUCT_SOURCES,
        maximum_reference_controls=GLOBAL_MAX_REFERENCE_CONTROLS,
        aspect_ratio=aspect_ratio,
        aspect_status=str(aspect.get("status") or ""),
        delivery_width=int(aspect["width"]),
        delivery_height=int(aspect["height"]),
        generation_size=str(aspect["generation_size"]),
        safe_crop=str(aspect["safe_crop"]),
        output_format=str(aspect["format"]),
        bbox_qa=dict(bbox_qa),
        declared_transforms=tuple(dict(item) for item in transforms),
        runtime_policy=policy,
    )
