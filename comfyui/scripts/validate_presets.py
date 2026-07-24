import hashlib
import json
import sys
from pathlib import Path


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))
sys.path.insert(0, str(COMFYUI_DIR.parent))

from ad_creator.adapters.openai_image import (
    default_published_preset_slot,
    load_published_preset,
    published_preset_slots,
)
from comfyui.orchestrator import resolve_published_preset


EXPECTED_SLOTS = {
    f"{family}__{composition}"
    for family in ("natural_white", "wood", "vivid")
    for composition in (
        "product_large",
        "product_center",
        "aerial_shot",
        "handheld_lifestyle",
    )
}


def _sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".json", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _validate_alternatives(registry: dict, registry_path: Path) -> None:
    alternatives = registry.get("alternatives", {})
    if not isinstance(alternatives, dict):
        raise ValueError("Preset alternatives must be an object.")
    for preset_id, alternative in alternatives.items():
        if not isinstance(alternative, dict) or alternative.get("enabled") is not False:
            raise ValueError(f"Alternative must remain unrouted: {preset_id}")
        bundle_path = (registry_path.parent / str(alternative.get("bundle") or "")).resolve()
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        if bundle.get("preset_id") != preset_id:
            raise ValueError(f"Alternative bundle ID mismatch: {preset_id}")
        for key in ("prompt_template", "lighting_sheet", "grade_profile"):
            binding = bundle.get(key)
            if not isinstance(binding, dict):
                raise ValueError(f"Alternative is missing {key}: {preset_id}")
            asset_path = (bundle_path.parent / str(binding.get("path") or "")).resolve()
            if _sha256(asset_path) != binding.get("sha256"):
                raise ValueError(f"Alternative {key} hash changed: {preset_id}")


def _validate_passed_manifest(registry: dict, registry_path: Path) -> None:
    manifest_name = registry.get("passed_presets_manifest")
    if not isinstance(manifest_name, str) or not manifest_name:
        raise ValueError("Registry must bind passed-presets manifest.")
    manifest_path = registry_path.parent / manifest_name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("default_slot_id") != registry.get("default_preset_slot"):
        raise ValueError("Passed manifest default slot differs from registry.")
    for item in manifest.get("presets", []):
        bundle_path = registry_path.parent / str(item.get("bundle") or "")
        if not bundle_path.is_file() or _sha256(bundle_path) != item.get("bundle_sha256"):
            raise ValueError(f"Passed preset bundle is missing or changed: {item.get('preset_id')}")


def main() -> int:
    registry_path = COMFYUI_DIR / "presets" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    slots = registry.get("slots")
    if not isinstance(slots, dict) or set(slots) != EXPECTED_SLOTS:
        raise ValueError("Preset registry must declare the exact 12 service slots.")

    published = published_preset_slots(registry_path=registry_path)
    if not published:
        raise ValueError("Preset registry must publish at least one reviewed preset.")
    default_slot = default_published_preset_slot(registry_path=registry_path)
    if default_slot not in published:
        raise ValueError("Default preset must be one of the published slots.")

    _validate_alternatives(registry, registry_path)
    _validate_passed_manifest(registry, registry_path)
    legacy_routes: set[tuple[str, str]] = set()
    for slot_id in published:
        bundle_path = registry_path.parent / str(slots[slot_id].get("bundle") or "")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        runtime_policy = bundle.get("runtime_policy")
        supported_modes = (
            runtime_policy.get("supported_container_modes")
            if isinstance(runtime_policy, dict)
            else None
        )
        if set(supported_modes or []) != {"adopt_reference", "reconstruct_source"}:
            raise ValueError(f"Published preset must support both cup modes: {slot_id}")

        portrait = load_published_preset(
            slot_id,
            aspect_ratio="4:5",
            serving_temperature="cold",
            registry_path=registry_path,
        )
        square = load_published_preset(
            slot_id,
            aspect_ratio="1:1",
            serving_temperature="cold",
            registry_path=registry_path,
        )
        if portrait.aspect_status != "published":
            raise ValueError(f"4:5 must be published: {slot_id}")
        if square.aspect_status != "published":
            raise ValueError(f"1:1 must be published: {slot_id}")
        for resolved in (portrait, square):
            if len(resolved.prompt) > 12_000:
                raise ValueError(f"Prompt exceeds 12,000 characters: {slot_id}")
            if 1 + len(resolved.provider_image_paths) > 4:
                raise ValueError(f"Provider input cap exceeded: {slot_id}")
            if resolved.brand_input_enabled:
                raise ValueError(f"Brand input must remain disabled: {slot_id}")

        for container_mode in ("adopt_reference", "reconstruct_source"):
            for aspect_ratio in ("4:5", "1:1"):
                resolved = load_published_preset(
                    slot_id,
                    aspect_ratio=aspect_ratio,
                    container_mode=container_mode,
                    serving_temperature="auto",
                    registry_path=registry_path,
                )
                if resolved.container_mode != container_mode:
                    raise ValueError(
                        f"Cup mode resolved incorrectly: {slot_id} {container_mode}"
                    )
                if resolved.aspect_status != "published":
                    raise ValueError(
                        f"Aspect ratio is not published: {slot_id} {aspect_ratio}"
                    )

        legacy = slots[slot_id].get("legacy_gateway")
        if not isinstance(legacy, dict):
            raise ValueError(f"Published preset has no legacy route: {slot_id}")
        route = (legacy.get("background_style"), legacy.get("composition"))
        if not all(isinstance(value, str) and value for value in route):
            raise ValueError(f"Published preset has an invalid legacy route: {slot_id}")
        if route in legacy_routes:
            raise ValueError(f"Published presets have a duplicate legacy route: {route}")
        legacy_routes.add(route)
        if (
            resolve_published_preset(
                preset_id=None,
                background_style=route[0],
                composition=route[1],
                registry_path=registry_path,
            )
            != slot_id
        ):
            raise ValueError(f"Legacy route resolves to the wrong preset: {slot_id}")

    print(
        "Validated 12 preset slots; "
        f"published: {', '.join(published)}; default: {default_slot}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
