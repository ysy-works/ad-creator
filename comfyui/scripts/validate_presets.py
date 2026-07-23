import json
import hashlib
import hashlib
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
    validated_preset_slots,
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
EXPECTED_PUBLISHED = (
    "natural_white__product_center",
    "natural_white__handheld_lifestyle",
    "wood__product_center",
)
EXPECTED_VALIDATED = (
    "natural_white__aerial_shot",
    "wood__product_large",
)
EXPECTED_WOOD_DEFAULT = "tokyo_a6_relational_scene_hint_v4"
EXPECTED_WOOD_ALTERNATIVE = "instagram_wood_45deg_relational_v3"


def _sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".json", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def main() -> int:
    registry_path = COMFYUI_DIR / "presets" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    slots = registry.get("slots")
    if not isinstance(slots, dict) or set(slots) != EXPECTED_SLOTS:
        raise ValueError("Preset registry must declare the exact 12 service slots.")
    published = published_preset_slots(registry_path=registry_path)
    if published != EXPECTED_PUBLISHED:
        raise ValueError("Published presets do not match the currently reviewed registry set.")
    validated = validated_preset_slots(registry_path=registry_path)
    if validated != EXPECTED_VALIDATED:
        raise ValueError("Validated presets do not match the pending provider-review set.")
    if default_published_preset_slot(registry_path=registry_path) != "wood__product_center":
        raise ValueError("A6 must remain the default routed preset.")
    if slots["wood__product_center"].get("preset_id") != EXPECTED_WOOD_DEFAULT:
        raise ValueError("The routed wood medium preset must be the approved A6 preset.")
    alternatives = registry.get("alternatives")
    if not isinstance(alternatives, dict) or set(alternatives) != {
        EXPECTED_WOOD_ALTERNATIVE,
    }:
        raise ValueError("Registry must preserve exactly the reviewed unrouted alternatives.")
    legacy = alternatives[EXPECTED_WOOD_ALTERNATIVE]
    if legacy.get("enabled") is not False or legacy.get("status") != "available_not_routed":
        raise ValueError("The 45-degree alternative must remain available but unrouted.")
    legacy_bundle_path = (registry_path.parent / str(legacy.get("bundle") or "")).resolve()
    legacy_bundle = json.loads(legacy_bundle_path.read_text(encoding="utf-8"))
    if (
        legacy_bundle.get("preset_id") != EXPECTED_WOOD_ALTERNATIVE
        or legacy_bundle.get("status") != "available_not_routed"
    ):
        raise ValueError("The 45-degree alternative bundle is invalid.")
    for key in ("prompt_template", "lighting_sheet", "grade_profile"):
        binding = legacy_bundle.get(key)
        if not isinstance(binding, dict):
            raise ValueError(f"The 45-degree alternative is missing {key}.")
        asset_path = (legacy_bundle_path.parent / str(binding.get("path") or "")).resolve()
        if _sha256(asset_path) != binding.get("sha256"):
            raise ValueError(f"The 45-degree alternative {key} hash changed.")
    legacy_routes: set[tuple[str, str]] = set()
    for slot_id in published:
        values: dict[str, str] = {}
        if slot_id == "natural_white__handheld_lifestyle":
            values = {
                "container_mode": "adopt_reference",
                "serving_temperature": "cold",
            }
        portrait = load_published_preset(
            slot_id,
            aspect_ratio="4:5",
            registry_path=registry_path,
            **values,
        )
        square = load_published_preset(
            slot_id,
            aspect_ratio="1:1",
            registry_path=registry_path,
            **values,
        )
        if portrait.aspect_status != "published":
            raise ValueError(f"4:5 must be published: {slot_id}")
        if square.aspect_status != "prepared_pending_visual_qa":
            raise ValueError(f"1:1 must remain prepared pending visual QA: {slot_id}")
        legacy = slots[slot_id].get("legacy_gateway")
        if not isinstance(legacy, dict):
            raise ValueError(f"Published preset has no legacy gateway route: {slot_id}")
        route = (legacy.get("background_style"), legacy.get("composition"))
        if not all(isinstance(value, str) and value for value in route):
            raise ValueError(f"Published preset has an invalid legacy gateway route: {slot_id}")
        if route in legacy_routes:
            raise ValueError(f"Published presets have a duplicate legacy gateway route: {route}")
        legacy_routes.add(route)
        resolved = resolve_published_preset(
            preset_id=None,
            background_style=route[0],
            composition=route[1],
            registry_path=registry_path,
        )
        if resolved != slot_id:
            raise ValueError(f"Legacy route resolves to the wrong preset: {slot_id}")
    white_overhead = load_published_preset(
        "natural_white__aerial_shot",
        container_mode="adopt_reference",
        allowed_statuses=("validated",),
        registry_path=registry_path,
    )
    white_overhead_source = load_published_preset(
        "natural_white__aerial_shot",
        container_mode="reconstruct_source",
        allowed_statuses=("validated",),
        registry_path=registry_path,
    )
    white_handheld = load_published_preset(
        "natural_white__handheld_lifestyle",
        container_mode="adopt_reference",
        serving_temperature="cold",
        allowed_statuses=("published",),
        registry_path=registry_path,
    )
    white_handheld_source = load_published_preset(
        "natural_white__handheld_lifestyle",
        container_mode="reconstruct_source",
        serving_temperature="auto",
        allowed_statuses=("published",),
        registry_path=registry_path,
    )
    wood_closeup = load_published_preset(
        "wood__product_large",
        container_mode="adopt_reference",
        serving_temperature="cold",
        allowed_statuses=("validated",),
        registry_path=registry_path,
    )
    wood_closeup_source = load_published_preset(
        "wood__product_large",
        container_mode="reconstruct_source",
        allowed_statuses=("validated",),
        registry_path=registry_path,
    )
    for resolved in (
        white_overhead,
        white_overhead_source,
        white_handheld,
        white_handheld_source,
        wood_closeup,
        wood_closeup_source,
    ):
        if len(resolved.prompt) > 12000:
            raise ValueError(f"Prompt exceeds 12,000 characters: {resolved.preset_id}")
        if 1 + len(resolved.provider_image_paths) > 4:
            raise ValueError(f"Provider input cap exceeded: {resolved.preset_id}")
        if resolved.brand_input_enabled:
            raise ValueError(f"Brand input must remain disabled: {resolved.preset_id}")
    passed_manifest = json.loads(
        (registry_path.parent / str(registry["passed_presets_manifest"])).read_text(
            encoding="utf-8"
        )
    )
    passed_ids = [item["preset_id"] for item in passed_manifest["presets"]]
    if passed_ids != [
        "tokyo_a6_relational_scene_hint_v4",
        "instagram_white_diffuse_wall_table_v1",
        "instagram_wood_45deg_relational_v3",
        "instagram_white_direct_handheld_refined_v5",
    ]:
        raise ValueError("Passed preset retention manifest changed.")
    if passed_manifest.get("default_preset_id") != EXPECTED_WOOD_DEFAULT:
        raise ValueError("Passed preset default must remain A6.")
    for item in passed_manifest["presets"]:
        bundle_path = registry_path.parent / item["bundle"]
        if not bundle_path.is_file():
            raise ValueError(f"Passed preset bundle is missing: {item['preset_id']}")
        actual_sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        if actual_sha256 != item.get("bundle_sha256"):
            raise ValueError(f"Passed preset bundle hash changed: {item['preset_id']}")
    print(
        "Validated 12 preset slots; "
        f"published: {', '.join(published)}; "
        f"provider-validation pending: {', '.join(validated)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
