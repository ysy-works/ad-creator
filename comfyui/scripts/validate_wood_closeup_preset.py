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
    content = path.read_bytes()
    if path.suffix.lower() in {".json", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _asset(binding: dict, label: str) -> Path:
    path = (BUNDLE_DIR / str(binding.get("path") or "")).resolve()
    _require(path.is_file(), f"Missing {label}: {path}")
    _require(_sha256(path) == binding.get("sha256"), f"Hash mismatch: {label}")
    return path


def main() -> int:
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    _require(bundle.get("slot_id") == "wood__product_large", "Wrong service slot.")
    _require(bundle.get("preset_id") == "instagram_wood_calm_window_closeup_v1", "Wrong preset id.")
    _require(bundle.get("status") == "published", "Preset must be published after visual QA.")
    _require(
        bundle.get("source_review_status") == "passed_by_user_review",
        "Provider visual validation state changed.",
    )

    prompt = _asset(bundle["prompt_template"], "prompt template").read_text(encoding="utf-8")
    _require(prompt.count("{{INPUT_ROLES}}") == 1, "INPUT_ROLES placeholder is invalid.")
    _require(prompt.count("{{LIGHTING_CONTRACT}}") == 1, "LIGHTING_CONTRACT placeholder is invalid.")
    _require(prompt.count("{{ASPECT_CONTRACT}}") == 1, "ASPECT_CONTRACT placeholder is invalid.")
    _require('"CAFE AMERICANO"' in prompt, "Rear cup text lock is missing.")
    _require("1.05-1.12 times the cup bottom diameter" in prompt, "Straw ratio lock is missing.")
    _require(
        "mandatory component of the adopted reference cup regardless of whether Image 1 has a straw" in prompt,
        "Adopted straw must be independent of source serving cues.",
    )
    _require(
        "Preserve every source-visible primary label, logo, wordmark and printed design" in prompt,
        "Reconstruct-source primary branding lock is missing.",
    )
    _require(
        "the separate rear companion must still carry" in prompt,
        "Source branding must not suppress preset companion typography.",
    )
    _require("Do not copy the approved reference scene pixel-for-pixel." in prompt, "Scene-clone safeguard is missing.")
    brand_policy = bundle["runtime_policy"]["brand_input_policy"]
    _require(
        brand_policy.get("source_visible_branding_modes") == ["reconstruct_source"],
        "Source-visible branding authority must be limited to reconstruct_source.",
    )
    typography = brand_policy["preset_typography"][0]
    _require(
        "cylindrical" in typography["target_surface"]
        and "curvature" in typography["target_surface"],
        "Rear cup typography must declare a curved cylindrical target surface.",
    )

    _asset(bundle["lighting_sheet"], "lighting sheet")
    _asset(bundle["grade_profile"], "grade profile")
    for label, binding in bundle["contract_assets"].items():
        _asset(binding, label)

    hints = bundle.get("hint_images")
    _require(isinstance(hints, list) and len(hints) == 2, "Expected two provider hint images.")
    roles = {item["role"] for item in hints}
    _require(
        roles
        == {
            "reference_cup_geometry_light_and_companion_evidence",
            "source_cup_geometry_light_and_companion_evidence",
        },
        "Hint roles changed.",
    )
    for item in hints:
        path = _asset(item, item["role"])
        with Image.open(path) as image:
            _require([image.width, image.height] == [item["width"], item["height"]], f"Dimension mismatch: {path.name}")
    reference_hint = next(
        item
        for item in hints
        if item["role"] == "reference_cup_geometry_light_and_companion_evidence"
    )
    _require(
        any("mandatory single black straw" in rule for rule in reference_hint.get("transfer_scope", [])),
        "Reference hint transfer scope must explicitly include the adopted straw.",
    )

    modes = bundle.get("container_modes")
    _require(set(modes) == {"adopt_reference", "reconstruct_source"}, "Both cup modes are required.")
    _require(
        modes["reconstruct_source"].get("preserve_source_visible_branding") is True,
        "Reconstruct-source mode must preserve visible source identity.",
    )
    _require(bundle.get("default_container_mode") == "adopt_reference", "Reviewed default mode changed.")
    _require(set(bundle.get("aspect_ratio_contracts", {})) == {"4:5", "1:1"}, "Aspect contracts changed.")
    _require(bundle["aspect_ratio_contracts"]["4:5"]["status"] == "published", "4:5 must be published.")
    _require(
        bundle["aspect_ratio_contracts"]["1:1"]["status"] == "published",
        "Square mode must be published after visual QA.",
    )

    print("Validated wood close-up preset bundle, contracts, hashes and two provider hint images.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
