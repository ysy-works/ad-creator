import json
from pathlib import Path
from typing import Any


DEFAULT_PRESET_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "presets" / "registry.json"
)


class PresetRoutingError(RuntimeError):
    pass


class PresetRegistryConfigurationError(PresetRoutingError):
    pass


class PresetSelectionError(PresetRoutingError):
    pass


def _registry(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PresetRegistryConfigurationError(
            "Cannot read the service preset registry."
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PresetRegistryConfigurationError(
            "Service preset registry schema is invalid."
        )
    slots = value.get("slots")
    if not isinstance(slots, dict) or not slots:
        raise PresetRegistryConfigurationError(
            "Service preset registry has no slots."
        )
    return value


def published_preset_ids(
    registry_path: str | Path = DEFAULT_PRESET_REGISTRY_PATH,
) -> tuple[str, ...]:
    registry = _registry(registry_path)
    slots = registry["slots"]
    published = tuple(
        slot_id
        for slot_id, value in slots.items()
        if isinstance(value, dict)
        and value.get("enabled") is True
        and value.get("status") == "published"
    )
    if not published:
        raise PresetRegistryConfigurationError(
            "Service preset registry has no published slots."
        )
    return published


def resolve_published_preset(
    *,
    preset_id: str | None,
    background_style: str,
    composition: str,
    registry_path: str | Path = DEFAULT_PRESET_REGISTRY_PATH,
) -> str:
    registry = _registry(registry_path)
    slots = registry["slots"]
    published = set(published_preset_ids(registry_path))
    supplied = (preset_id or "").strip() or None
    if supplied is not None:
        if supplied not in published:
            raise PresetSelectionError(f"Preset is not published: {supplied}")
        return supplied

    matches: list[str] = []
    for slot_id in published:
        slot = slots[slot_id]
        legacy = slot.get("legacy_gateway")
        if not isinstance(legacy, dict):
            continue
        if (
            legacy.get("background_style") == background_style
            and legacy.get("composition") == composition
        ):
            matches.append(slot_id)
    if not matches:
        raise PresetSelectionError(
            "No single published preset matches the legacy background_style/composition."
        )
    if len(matches) > 1:
        raise PresetRegistryConfigurationError(
            "Published presets have duplicate legacy gateway routes."
        )
    return matches[0]
