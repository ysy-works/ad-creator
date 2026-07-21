import json
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


def main() -> int:
    registry_path = COMFYUI_DIR / "presets" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    slots = registry.get("slots")
    if not isinstance(slots, dict) or set(slots) != EXPECTED_SLOTS:
        raise ValueError("Preset registry must declare the exact 12 service slots.")
    published = published_preset_slots(registry_path=registry_path)
    if published != EXPECTED_PUBLISHED:
        raise ValueError("Pilot must publish exactly the two approved medium presets.")
    legacy_routes: set[tuple[str, str]] = set()
    for slot_id in published:
        load_published_preset(slot_id, registry_path=registry_path)
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
