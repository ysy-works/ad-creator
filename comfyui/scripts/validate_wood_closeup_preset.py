import hashlib
import json
from pathlib import Path

from PIL import Image


COMFYUI_DIR = Path(__file__).resolve().parents[1]
BUNDLE_DIR = COMFYUI_DIR / "presets" / "wood__product_large"
BUNDLE_PATH = BUNDLE_DIR / "preset.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asset(binding: dict, label: str) -> Path:
    path = (BUNDLE_DIR / str(binding.get("path") or "")).resolve()
    _require(path.is_file(), f"Missing {label}: {path}")
    _require(_sha256(path) == binding.get("sha256"), f"Hash mismatch: {label}")
    return path


def main() -> int:
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    _require(bundle.get("slot_id") == "wood__product_large", "Wrong service slot.")
    _require(bundle.get("preset_id") == "instagram_wood_calm_window_closeup_v1", "Wrong preset id.")
    _require(bundle.get("status") == "published", "Preset is not published.")
    _require(bundle.get("source_review_status") == "passed_by_user_review", "User review is missing.")

    prompt = _asset(bundle["prompt_template"], "prompt template").read_text(encoding="utf-8")
    _require(prompt.count("{{INPUT_ROLES}}") == 1, "INPUT_ROLES placeholder is invalid.")
    _require(prompt.count("{{LIGHTING_CONTRACT}}") == 1, "LIGHTING_CONTRACT placeholder is invalid.")
    _require(prompt.count("{{ASPECT_CONTRACT}}") == 1, "ASPECT_CONTRACT placeholder is invalid.")
    _require('"CAFE AMERICANO"' in prompt, "Rear cup text lock is missing.")
    _require("1.05-1.12 times the cup bottom diameter" in prompt, "Straw ratio lock is missing.")
    _require("never sent because it over-strengthens scene replication" in json.dumps(bundle), "Scene-clone safeguard is missing.")

    _asset(bundle["lighting_sheet"], "lighting sheet")
    _asset(bundle["grade_profile"], "grade profile")
    for label, binding in bundle["contract_assets"].items():
        _asset(binding, label)

    hints = bundle.get("hint_images")
    _require(isinstance(hints, list) and len(hints) == 3, "Expected all three reviewed image assets.")
    roles = {item["role"] for item in hints}
    _require(
        roles
        == {
            "reference_cup_geometry_light_and_companion_evidence",
            "source_cup_geometry_light_and_companion_evidence",
            "approved_full_reference_for_offline_review",
        },
        "Hint roles changed.",
    )
    for item in hints:
        path = _asset(item, item["role"])
        with Image.open(path) as image:
            _require([image.width, image.height] == [item["width"], item["height"]], f"Dimension mismatch: {path.name}")

    modes = bundle.get("container_modes")
    _require(set(modes) == {"adopt_reference", "preserve_source"}, "Both cup modes are required.")
    _require(bundle.get("default_container_mode") == "adopt_reference", "Reviewed default mode changed.")
    _require(set(bundle.get("aspect_ratio_contracts", {})) == {"4:5", "1:1"}, "Aspect contracts changed.")
    _require(bundle["aspect_ratio_contracts"]["4:5"]["status"] == "published", "4:5 must be published.")
    _require(
        bundle["aspect_ratio_contracts"]["1:1"]["status"] == "prepared_pending_visual_qa",
        "Square mode must remain pending visual QA.",
    )

    print("Validated wood close-up preset bundle, contracts, hashes and three image assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
