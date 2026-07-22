import json
import hashlib
import sys
from pathlib import Path


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))
sys.path.insert(0, str(COMFYUI_DIR.parent))

from ad_creator.adapters.openai_image import load_published_preset, published_preset_slots
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
    "wood__product_center",
)
EXPECTED_WOOD_DEFAULT = "tokyo_a6_relational_scene_hint_v4"
EXPECTED_WOOD_ALTERNATIVE = "instagram_wood_45deg_relational_v3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    registry_path = COMFYUI_DIR / "presets" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    slots = registry.get("slots")
    if not isinstance(slots, dict) or set(slots) != EXPECTED_SLOTS:
        raise ValueError("Preset registry must declare the exact 12 service slots.")
    published = published_preset_slots(registry_path=registry_path)
    if published != EXPECTED_PUBLISHED:
        raise ValueError("Pilot must publish exactly the two approved medium presets.")
    if slots["wood__product_center"].get("preset_id") != EXPECTED_WOOD_DEFAULT:
        raise ValueError("The routed wood medium preset must be the approved A6 preset.")
    alternatives = registry.get("alternatives")
    if not isinstance(alternatives, dict) or set(alternatives) != {EXPECTED_WOOD_ALTERNATIVE}:
        raise ValueError("Registry must preserve exactly the reviewed 45-degree alternative.")
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
        portrait = load_published_preset(slot_id, aspect_ratio="4:5", registry_path=registry_path)
        square = load_published_preset(slot_id, aspect_ratio="1:1", registry_path=registry_path)
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
    print(f"Validated 12 preset slots; published: {', '.join(published)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
