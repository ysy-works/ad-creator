from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image
from comfy_api.v0_0_2 import ComfyExtension, io, ui
from typing_extensions import override

from ad_creator.analyzers.gemini import GeminiProductAnalyzer, GeminiReferenceAnalyzer
from ad_creator.brand_restoration import restore_single_product_brand
from ad_creator.diagnostic_pilot import (
    diagnostic_request_hash,
    execute_diagnostic_pilot_case,
    validate_diagnostic_pilot_bundle,
)
from ad_creator.generation_inputs import ordered_image_inputs
from ad_creator.jsonio import dump_json, load_json, validate_json
from ad_creator.environment import load_project_env
from ad_creator.features import load_service_features, ui_feature_state
from ad_creator.image_contracts import (
    canonical_image_binding,
    validate_product_analysis_binding,
    verified_logo_text,
)
from ad_creator.evaluators.fake import FakeQualityEvaluator
from ad_creator.evaluators.gemini import GeminiQualityEvaluator
from ad_creator.pipeline import load_mood_package
from ad_creator.multi_pipeline import validate_reference_control_board_binding
from ad_creator.paid_readiness import require_v3_paid_submission_allowed
from ad_creator.postprocessing import GRADE_STRENGTHS, apply_grade, image_metrics, resolve_grade_strengths
from ad_creator.prompting import (
    PROMPT_COMPILER_VERSION,
    assemble_product_set,
    build_generation_request,
    create_product_spec,
)
from ad_creator.provider_profiles import apply_provider_profile, record_provider_profile
from ad_creator.providers.higgsfield import HiggsfieldProvider
from ad_creator.providers.openai import OpenAIImageProvider
from ad_creator.qa import normalize_multi_product_qa, normalize_qa_report, route_repair
from ad_creator.quality_workflow import evaluate_and_maybe_repair
from ad_creator.request_validation import validate_generation_request
from ad_creator.reference_library import (
    derive_container_design,
    derive_reference_capabilities,
)
from ad_creator.reference_catalog import lookup_reference
from ad_creator.scene_graph import (
    adapt_scene_graph_to_reference_v1,
    derive_scene_graph_capabilities,
    resolve_slot_plan,
    validate_scene_graph,
)
from ad_creator.runs import RunStore, execute_once, execute_until_terminal, request_hash
from ad_creator.v3_evaluator import (
    evaluate_v3_generated_image,
    validate_v3_image_evaluation_report,
)
from ad_creator.wood_materials import (
    validate_wood_material_profile,
    wood_material_profile_hash,
)

from .v3_contracts import (
    build_multi_product_request_from_bundle,
    resolve_reference_contract_bundle,
    resolve_reference_contract_bundle_by_id,
)


CATEGORY = "ad-creator/local"
OVERHEAD_SURFACE_EVIDENCE_PRESETS = {
    "instagram_white_neutral_overhead_spatial_v1",
}
WOOD_CLOSEUP_PRESET_ID = "instagram_wood_calm_window_closeup_v1"


def _project_root() -> Path:
    configured = os.environ.get("AD_CREATOR_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (_project_root() / path).resolve()


def _service_features_path() -> str:
    return os.environ.get(
        "AD_CREATOR_FEATURES_PATH",
        "configs/service-features.json",
    )


def _ui_feature_state() -> dict[str, bool]:
    features = load_service_features(_project_root(), _service_features_path())
    return ui_feature_state(features)


def _hidden_unless(visible: bool) -> dict[str, bool]:
    return {} if visible else {"hidden": True}


def _tensor_digest(image: torch.Tensor) -> str:
    tensor = image.detach().to(device="cpu", dtype=torch.float32).contiguous()
    return hashlib.sha256(tensor.numpy().tobytes()).hexdigest()


def _pil_to_tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _tensor_to_pil(image: torch.Tensor) -> Image.Image:
    array = image.detach().to(device="cpu", dtype=torch.float32).clamp(0, 1).numpy()
    return Image.fromarray(np.rint(array * 255).astype(np.uint8), mode="RGB")


def _save_tensor_input(image: torch.Tensor, role: str) -> Path:
    if image.ndim != 4 or image.shape[0] != 1:
        raise ValueError(f"{role} must contain exactly one ComfyUI image")
    digest = _tensor_digest(image)
    path = _project_root() / "outputs/comfyui-inputs" / f"{role}-{digest[:24]}.png"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".png.tmp")
        _tensor_to_pil(image[0]).save(temporary, format="PNG", optimize=True)
        os.replace(temporary, path)
    return path.resolve()


def _beverage_surface_evidence_crop(
    image: torch.Tensor,
    analysis: dict[str, Any],
) -> tuple[torch.Tensor, dict[str, float]]:
    """Keep beverage-top evidence while removing most source-camera sidewall bias."""
    if image.ndim != 4 or image.shape[0] != 1:
        raise ValueError("product_source must contain exactly one ComfyUI image")
    geometry = analysis.get("geometry") or {}
    container = geometry.get("container_bbox") or geometry.get("subject_bbox")
    subject = geometry.get("subject_bbox") or container
    if not isinstance(container, dict) or not isinstance(subject, dict):
        return image, {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}

    try:
        container_left = float(container["left"])
        container_top = float(container["top"])
        container_right = float(container["right"])
        container_bottom = float(container["bottom"])
        subject_left = float(subject["left"])
        subject_top = float(subject["top"])
        subject_right = float(subject["right"])
    except (KeyError, TypeError, ValueError):
        return image, {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}

    box_width = max(0.01, container_right - container_left)
    box_height = max(0.01, container_bottom - container_top)
    crop_box = {
        "left": max(0.0, min(container_left, subject_left) - 0.08 * box_width),
        "top": max(0.0, min(subject_top, container_top - 0.03 * box_height)),
        "right": min(1.0, max(container_right, subject_right) + 0.08 * box_width),
        "bottom": min(1.0, container_top + 0.34 * box_height),
    }
    height = int(image.shape[1])
    width = int(image.shape[2])
    left = max(0, min(width - 2, int(round(crop_box["left"] * width))))
    right = max(left + 2, min(width, int(round(crop_box["right"] * width))))
    top = max(0, min(height - 2, int(round(crop_box["top"] * height))))
    bottom = max(top + 2, min(height, int(round(crop_box["bottom"] * height))))
    crop = image[:, top:bottom, left:right, :].contiguous()
    if crop.shape[1] < 32 or crop.shape[2] < 32:
        return image, {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0}
    return crop, crop_box


def _adopted_container_beverage_evidence(
    image: torch.Tensor,
    analysis: dict[str, Any],
) -> tuple[torch.Tensor, dict[str, Any]]:
    """Retain drink evidence while removing the source vessel silhouette."""
    if image.ndim != 4 or image.shape[0] != 1:
        raise ValueError("product_source must contain exactly one ComfyUI image")
    geometry = analysis.get("geometry") or {}
    container = geometry.get("container_bbox") or geometry.get("subject_bbox")
    if not isinstance(container, dict):
        raise ValueError("adopt_reference requires a measured source container bbox")
    try:
        left = float(container["left"])
        top = float(container["top"])
        right = float(container["right"])
        bottom = float(container["bottom"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("adopt_reference source container bbox is invalid") from error
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("adopt_reference source container bbox is out of bounds")

    source = _tensor_to_pil(image[0])
    width, height = source.size
    box_width = right - left
    box_height = bottom - top

    def pixel_box(box: dict[str, float]) -> tuple[int, int, int, int]:
        x0 = max(0, min(width - 2, int(round(box["left"] * width))))
        y0 = max(0, min(height - 2, int(round(box["top"] * height))))
        x1 = max(x0 + 2, min(width, int(round(box["right"] * width))))
        y1 = max(y0 + 2, min(height, int(round(box["bottom"] * height))))
        return x0, y0, x1, y1

    top_box = {
        "left": max(0.0, left - 0.04 * box_width),
        "top": max(0.0, top - 0.05 * box_height),
        "right": min(1.0, right + 0.04 * box_width),
        "bottom": min(1.0, top + 0.30 * box_height),
    }
    layer_box = {
        "left": left + 0.24 * box_width,
        "top": top + 0.20 * box_height,
        "right": right - 0.24 * box_width,
        "bottom": bottom - 0.08 * box_height,
    }
    top_crop = source.crop(pixel_box(top_box))
    layer_crop = source.crop(pixel_box(layer_box))
    canvas = Image.new("RGB", (768, 768), (232, 228, 222))

    def paste_contained(crop: Image.Image, bounds: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = bounds
        available_width = x1 - x0
        available_height = y1 - y0
        scale = min(available_width / crop.width, available_height / crop.height)
        resized = crop.resize(
            (
                max(1, int(round(crop.width * scale))),
                max(1, int(round(crop.height * scale))),
            ),
            Image.Resampling.LANCZOS,
        )
        x = x0 + (available_width - resized.width) // 2
        y = y0 + (available_height - resized.height) // 2
        canvas.paste(resized, (x, y))

    paste_contained(top_crop, (32, 32, 736, 350))
    paste_contained(layer_crop, (176, 382, 592, 736))
    return _pil_to_tensor(canvas), {
        "top_surface_bbox_normalized": top_box,
        "interior_layer_bbox_normalized": layer_box,
        "outer_container_silhouette_submitted": False,
        "source_container_authority": "none",
    }


def _json_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ADLoadMoodPackage(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_LoadMoodPackage",
            display_name="Load Mood Package",
            category=CATEGORY,
            description="Loads a versioned mood, lighting-sheet and grade-profile contract.",
            inputs=[
                io.String.Input(
                    "mood_package_path",
                    default="presets/moods/direct_sun_white_wall_v1/mood-package.json",
                    tooltip="Path relative to AD_CREATOR_ROOT or an absolute path.",
                )
            ],
            outputs=[
                io.String.Output(display_name="mood_json"),
                io.String.Output(display_name="lighting_sheet_json"),
                io.String.Output(display_name="grade_profile_json"),
            ],
        )

    @classmethod
    def execute(cls, mood_package_path: str) -> io.NodeOutput:
        root = _project_root()
        mood = load_mood_package(root, mood_package_path)
        lighting = load_json(_resolve(mood["lighting_sheet_path"]))
        grade = load_json(_resolve(mood["grade_profile_path"]))
        validate_json(lighting, "lighting-sheet.schema.json", project_root=root)
        validate_json(grade, "grade-profile.schema.json", project_root=root)
        return io.NodeOutput(dump_json(mood), dump_json(lighting), dump_json(grade))


class ADLoadPresetControlBoard(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_LoadPresetControlBoard",
            display_name="Load Preset Control Board",
            category=CATEGORY,
            description=(
                "Loads the sanitized control board declared by the selected mood package "
                "and verifies its pixel hash against the checked-in manifest."
            ),
            inputs=[io.String.Input("mood_json", force_input=True)],
            outputs=[
                io.Image.Output(display_name="control_board"),
                io.String.Output(display_name="control_board_manifest_json"),
                io.String.Output(display_name="control_board_path"),
            ],
        )

    @classmethod
    def execute(cls, mood_json: str) -> io.NodeOutput:
        mood = json.loads(mood_json)
        board_path = mood.get("reference_control_board_path")
        manifest_path = mood.get("reference_control_board_manifest_path")
        if not isinstance(board_path, str) or not board_path.strip():
            raise ValueError("Mood package has no reference_control_board_path")
        if not isinstance(manifest_path, str) or not manifest_path.strip():
            raise ValueError("Mood package has no reference_control_board_manifest_path")
        board = _resolve(board_path)
        manifest = load_json(_resolve(manifest_path))
        artifact_type = manifest.get("artifact_type")
        if artifact_type not in {
            "reference_control_board",
            "sanitized_photographic_scene_hint",
            "controlled_photographic_scene_reference",
        }:
            raise ValueError("Preset control artifact manifest has the wrong artifact_type")
        if artifact_type == "sanitized_photographic_scene_hint":
            if manifest.get("role") != "scene_hint":
                raise ValueError("Photographic scene hint must declare role=scene_hint")
            sanitation = manifest.get("sanitation") or {}
            required_sanitation = {
                "borderless_photo_like_plate": True,
                "technical_panels": False,
                "panel_boundaries": False,
                "visible_labels": False,
                "raw_reference_provider_submission_allowed": False,
            }
            if any(
                sanitation.get(field) is not expected
                for field, expected in required_sanitation.items()
            ):
                raise ValueError("Photographic scene hint sanitation contract is incomplete")
        elif artifact_type == "controlled_photographic_scene_reference":
            if manifest.get("role") != "scene_hint":
                raise ValueError("Controlled photographic scene reference must declare role=scene_hint")
            sanitation = manifest.get("sanitation") or {}
            required_control = {
                "borderless_photo_like_plate": True,
                "technical_panels": False,
                "panel_boundaries": False,
                "visible_labels": True,
                "raw_reference_provider_submission_allowed": True,
            }
            if any(
                sanitation.get(field) is not expected
                for field, expected in required_control.items()
            ):
                raise ValueError("Controlled photographic scene reference contract is incomplete")
            authorized = {
                check.get("evidence", {}).get("exact_text")
                for check in manifest.get("checks", [])
                if check.get("check_id") == "authorized_companion_text_only"
            }
            if authorized != {"CAFE AMERICANO"}:
                raise ValueError("Controlled photographic scene reference has an invalid authorized text contract")
        with Image.open(board) as opened:
            binding = canonical_image_binding(board)
            output = _pil_to_tensor(opened)
        if manifest.get("pixel_sha256") != binding["pixel_sha256"]:
            raise ValueError("Preset control board changed after manifest publication")
        return io.NodeOutput(output, dump_json(manifest), str(board))


class ADLoadPresetWoodMaterial(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_LoadPresetWoodMaterial",
            display_name="Load Preset Wood Material",
            category="ad-creator/v3",
            description=(
                "Loads the preset-bound published WoodMaterialProfile and its sanitized "
                "material-only control board. The profile and pixels are hash checked."
            ),
            inputs=[io.String.Input("mood_json", force_input=True)],
            outputs=[
                io.Image.Output(display_name="wood_control_board"),
                io.String.Output(display_name="wood_material_profile_json"),
                io.String.Output(display_name="control_board_manifest_json"),
                io.String.Output(display_name="control_board_path"),
            ],
        )

    @classmethod
    def execute(cls, mood_json: str) -> io.NodeOutput:
        mood = json.loads(mood_json)
        required = (
            "wood_material_profile_path",
            "wood_material_manifest_path",
            "reference_control_board_path",
            "reference_control_board_manifest_path",
        )
        missing = [key for key in required if not str(mood.get(key) or "").strip()]
        if missing:
            raise ValueError(f"Mood package has no preset wood contract: {missing}")
        profile = validate_wood_material_profile(
            load_json(_resolve(mood["wood_material_profile_path"]))
        )
        if profile.status != "published":
            raise ValueError("Preset wood material profile must be published")
        material_manifest = load_json(_resolve(mood["wood_material_manifest_path"]))
        if material_manifest.get("profile_hash") != wood_material_profile_hash(profile):
            raise ValueError("Preset wood profile changed after material review")
        board = _resolve(mood["reference_control_board_path"])
        board_manifest = load_json(
            _resolve(mood["reference_control_board_manifest_path"])
        )
        validate_reference_control_board_binding(board, board_manifest)
        with Image.open(board) as opened:
            output = _pil_to_tensor(opened)
        return io.NodeOutput(
            output,
            dump_json(profile.to_dict()),
            dump_json(board_manifest),
            str(board),
        )


class ADAttachDiagnosticPilotAuthorization(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_AttachDiagnosticPilotAuthorization",
            display_name="Attach Fresh Paid Diagnostic Authorization",
            category="ad-creator/v3",
            description=(
                "Attaches a short-lived, cost-quoted V3 diagnostic authorization only "
                "when the connected request bytes and case ID exactly match the bundle."
            ),
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.String.Input("bundle_path"),
                io.String.Input("case_id"),
            ],
            outputs=[
                io.String.Output(display_name="authorized_request_json"),
                io.String.Output(display_name="authorization_sha256"),
            ],
        )

    @classmethod
    def execute(
        cls,
        request_json: str,
        bundle_path: str,
        case_id: str,
    ) -> io.NodeOutput:
        request = json.loads(request_json)
        bundle = validate_diagnostic_pilot_bundle(load_json(_resolve(bundle_path)))
        expected_hash = diagnostic_request_hash(request)
        matches = [
            entry
            for entry in bundle["requests"]
            if entry["case_id"] == case_id
            and diagnostic_request_hash(entry["request"]) == expected_hash
        ]
        if len(matches) != 1:
            raise ValueError(
                "Connected request does not exactly match the authorized diagnostic case"
            )
        authorized = matches[0]["request"]
        return io.NodeOutput(
            dump_json(authorized),
            bundle["authorization_sha256"],
            ui={"text": (case_id, bundle["authorization_sha256"])},
        )


class ADSaveV3RequestArtifact(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_SaveV3RequestArtifact",
            display_name="Save Compiled V3 Request",
            category="ad-creator/v3",
            description=(
                "Saves the exact zero-side-effect request compiled by the connected V3 "
                "preset nodes so a paid quote and reproduction bundle can bind to it."
            ),
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.String.Input("output_path"),
            ],
            outputs=[
                io.String.Output(display_name="request_path"),
                io.String.Output(display_name="request_sha256"),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, request_json: str, output_path: str) -> io.NodeOutput:
        request = json.loads(request_json)
        if request.get("schema_version") != "3.0.0":
            raise ValueError("Only GenerationRequestV3 can be saved by this node")
        if "diagnostic_pilot_authorization" in request:
            raise ValueError("Save the base request before attaching paid authorization")
        validate_generation_request(request, maximum_credits=2)
        path = _resolve(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(dump_json(request) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        digest = diagnostic_request_hash(request)
        return io.NodeOutput(
            str(path),
            digest,
            ui={"text": (str(path), digest)},
        )


class ADGeminiProductAnalyze(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_GeminiProductAnalyze",
            display_name="Gemini Product Analysis",
            category="ad-creator/analysis",
            description=(
                "Analyzes the uploaded product, binds the JSON to its pixels, and caches "
                "the result. This must run before request compilation."
            ),
            inputs=[
                io.Image.Input("image"),
                io.String.Input(
                    "analyzer_config_path",
                    default="configs/analyzers.json",
                    extra_dict={"hidden": True},
                ),
                io.Boolean.Input("use_cache", default=True),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="product_analysis_json"),
                io.String.Output(display_name="analysis_status"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        analyzer_config_path: str,
        use_cache: bool,
    ) -> io.NodeOutput:
        root = _project_root()
        load_project_env(root)
        config = load_json(_resolve(analyzer_config_path))
        product_config = config["product"]
        product_path = _save_tensor_input(image, "product_source")
        analyzer = GeminiProductAnalyzer(
            project_root=root,
            cache_root=product_config["cache_root"],
            model=product_config["model"],
            fallback_models=product_config.get("fallback_models", []),
            timeout_seconds=float(product_config["timeout_seconds"]),
            maximum_image_edge=int(product_config["maximum_image_edge"]),
            thinking_level=product_config["thinking_level"],
        )
        analysis, reused = analyzer.analyze(product_path, use_cache=use_cache)
        status = "cache_hit" if reused else "analyzed"
        if analysis["analysis_metadata"].get("binding_reuse"):
            status += ":verified_absent_perceptual_rebind"
        if analysis["analysis_metadata"].get("identity_override"):
            status += ":manual_identity_override"
        return io.NodeOutput(
            image,
            dump_json(analysis),
            status,
            ui={"text": (status,), "analysis": (dump_json(analysis),)},
        )


class ADGeminiProductAnalyzeV3(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_GeminiProductAnalyzeV3",
            display_name="Gemini Product Analysis V3",
            category="ad-creator/v3",
            description=(
                "Analyzes one exact beverage or dessert into ProductAnalysisV3, including "
                "material/application/surface branding observations and a source-pixel binding."
            ),
            inputs=[
                io.Image.Input("image"),
                io.Combo.Input(
                    "product_kind",
                    options=["beverage", "dessert"],
                    default="beverage",
                ),
                io.String.Input(
                    "analyzer_config_path",
                    default="configs/analyzers.json",
                    extra_dict={"hidden": True},
                ),
                io.Boolean.Input("use_cache", default=True),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="product_analysis_v3_json"),
                io.String.Output(display_name="analysis_status"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        product_kind: str,
        analyzer_config_path: str,
        use_cache: bool,
    ) -> io.NodeOutput:
        root = _project_root()
        load_project_env(root)
        config = load_json(_resolve(analyzer_config_path))
        product_config = config["product"]
        product_path = _save_tensor_input(image, "product_source_v3")
        analyzer = GeminiProductAnalyzer(
            project_root=root,
            cache_root=product_config["cache_root"],
            model=product_config["model"],
            fallback_models=product_config.get("fallback_models", []),
            timeout_seconds=float(product_config["timeout_seconds"]),
            maximum_image_edge=int(product_config["maximum_image_edge"]),
            thinking_level=product_config["thinking_level"],
        )
        analysis, reused = analyzer.analyze(
            product_path,
            product_kind=product_kind,
            use_cache=use_cache,
        )
        validate_json(analysis, "product-analysis.schema.json", project_root=root)
        status = "cache_hit_v3" if reused else "analyzed_v3"
        return io.NodeOutput(
            image,
            dump_json(analysis),
            status,
            ui={"text": (status,), "analysis": (dump_json(analysis),)},
        )


class ADLoadReviewedProductAnalysisV3(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_LoadReviewedProductAnalysisV3",
            display_name="Load Reviewed Product Analysis V3",
            category="ad-creator/v3",
            description=(
                "Loads a reviewed ProductAnalysisV3 and proves that it is bound to the "
                "connected product pixels. This avoids analyzer drift in reproducibility runs."
            ),
            inputs=[
                io.Image.Input("image"),
                io.String.Input("product_analysis_path"),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="product_analysis_v3_json"),
                io.String.Output(display_name="analysis_status"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        product_analysis_path: str,
    ) -> io.NodeOutput:
        root = _project_root()
        analysis = load_json(_resolve(product_analysis_path))
        validate_json(analysis, "product-analysis.schema.json", project_root=root)
        if analysis.get("schema_version") != "3.0.0":
            raise ValueError("Reviewed analysis must use ProductAnalysisV3")
        product_path = _save_tensor_input(image, "product_source")
        validate_product_analysis_binding(analysis, product_path)
        status = f"reviewed_v3:{analysis['source_binding']['pixel_sha256']}"
        return io.NodeOutput(
            image,
            dump_json(analysis),
            status,
            ui={"text": (status,), "analysis": (dump_json(analysis),)},
        )


class ADLoadReviewedProductAnalysisV2(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_LoadReviewedProductAnalysisV2",
            display_name="Load Reviewed Product Analysis V2",
            category="ad-creator/analysis",
            description="Loads a reviewed ProductAnalysisV2 and verifies its exact visible-pixel binding.",
            inputs=[
                io.Image.Input("image"),
                io.String.Input("product_analysis_path"),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="product_analysis_json"),
                io.String.Output(display_name="analysis_status"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        product_analysis_path: str,
    ) -> io.NodeOutput:
        root = _project_root()
        analysis = load_json(_resolve(product_analysis_path))
        validate_json(analysis, "product-analysis.schema.json", project_root=root)
        if analysis.get("schema_version") != "2.0.0":
            raise ValueError("Reviewed analysis must use ProductAnalysisV2")
        product_path = _save_tensor_input(image, "product_source")
        validate_product_analysis_binding(analysis, product_path)
        status = f"reviewed_v2:{analysis['source_binding']['pixel_sha256']}"
        return io.NodeOutput(
            image,
            dump_json(analysis),
            status,
            ui={"text": (status,), "analysis": (dump_json(analysis),)},
        )


class ADResolveSceneReference(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_ResolveSceneReference",
            display_name="Resolve Scene Reference",
            category="ad-creator/analysis",
            description=(
                "Looks up a selected reference by pixel hash and analyzes it only when the "
                "catalog has no semantic contract. Scene pixels never reach generation."
            ),
            inputs=[
                io.Image.Input("reference_image"),
                io.String.Input(
                    "catalog_path",
                    default="data/reference-library/catalog.sqlite",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "assignments_path",
                    default="data/reference-library/assignments.json",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "reference_root",
                    default=os.environ.get("AD_CREATOR_REFERENCE_ROOT", ""),
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "analyzer_config_path",
                    default="configs/analyzers.json",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "fallback_mood_package_path",
                    default="presets/moods/soft_diffuse_window_neutral_v2/mood-package.json",
                    extra_dict={"hidden": True},
                ),
            ],
            outputs=[
                io.Image.Output(display_name="reference_image"),
                io.String.Output(display_name="scene_reference_json"),
                io.String.Output(display_name="mood_package_path"),
                io.String.Output(display_name="reference_status"),
            ],
        )

    @classmethod
    def execute(
        cls,
        reference_image: torch.Tensor,
        catalog_path: str,
        assignments_path: str,
        reference_root: str,
        analyzer_config_path: str,
        fallback_mood_package_path: str,
    ) -> io.NodeOutput:
        root = _project_root()
        load_project_env(root)
        saved = _save_tensor_input(reference_image, "scene_reference_lookup")
        lookup = lookup_reference(
            saved,
            catalog_path=_resolve(catalog_path),
            assignments_path=_resolve(assignments_path),
        )
        analysis = lookup.analysis
        status = "catalog_hit"
        if lookup.match_method == "perceptual_dhash":
            status += f":perceptual_dhash={lookup.match_distance}"
        if analysis is None:
            config = load_json(_resolve(analyzer_config_path))["reference"]
            if lookup.relative_path:
                configured_root = (
                    reference_root.strip()
                    or os.environ.get("AD_CREATOR_REFERENCE_ROOT", "").strip()
                )
                if not configured_root:
                    raise ValueError(
                        "The selected catalog asset still needs semantic analysis. Set "
                        "AD_CREATOR_REFERENCE_ROOT in .env and restart ComfyUI, or choose "
                        "an analyzed catalog asset."
                    )
                library_root = Path(configured_root).expanduser().resolve()
                analysis_image = library_root / lookup.relative_path
                analysis_root = library_root
                status = "catalog_analyzed"
            else:
                analysis_image = saved
                analysis_root = saved.parent
                status = "external_analyzed"
            analyzer = GeminiReferenceAnalyzer(
                project_root=root,
                reference_root=analysis_root,
                cache_root=config["cache_root"],
                model=config["model"],
                fallback_models=config.get("fallback_models", []),
                timeout_seconds=float(config["timeout_seconds"]),
                maximum_image_edge=int(config["maximum_image_edge"]),
                thinking_level=config["thinking_level"],
            )
            analysis, reused = analyzer.analyze(analysis_image)
            if reused:
                status += "_cache"
        validate_json(analysis, "reference-asset.schema.json", project_root=root)
        capabilities = derive_reference_capabilities(analysis)
        mood_path = lookup.mood_package_path or fallback_mood_package_path
        if lookup.cluster_id:
            status += f":{lookup.cluster_id}"
        if not capabilities["scene_generation_eligible"]:
            status += ":not_single_product_eligible"
        elif not capabilities["container_adoption_eligible"]:
            status += ":scene_only"
        return io.NodeOutput(
            reference_image,
            dump_json(analysis),
            mood_path,
            status,
            ui={"text": (status,), "reference": (dump_json(analysis),)},
        )


class ADResolveReferenceSceneGraph(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_ResolveReferenceSceneGraph",
            display_name="Resolve Multi-Subject Reference",
            category="ad-creator/analysis",
            description=(
                "Loads a pre-analyzed Scene Graph v2 sidecar for a selected reference. "
                "This node does not call Gemini or submit reference pixels."
            ),
            inputs=[
                io.Image.Input("reference_image"),
                io.String.Input(
                    "catalog_path",
                    default="data/reference-library/catalog.sqlite",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "scene_graph_catalog_path",
                    default="data/reference-library/scene-graphs-v2.jsonl",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "assignments_path",
                    default="data/reference-library/assignments.json",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "fallback_mood_package_path",
                    default="presets/moods/soft_diffuse_window_neutral_v2/mood-package.json",
                    extra_dict={"hidden": True},
                ),
            ],
            outputs=[
                io.Image.Output(display_name="reference_image"),
                io.String.Output(display_name="scene_reference_json"),
                io.String.Output(display_name="scene_graph_json"),
                io.String.Output(display_name="mood_package_path"),
                io.String.Output(display_name="available_slots_json"),
                io.String.Output(display_name="reference_status"),
            ],
        )

    @classmethod
    def execute(
        cls,
        reference_image: torch.Tensor,
        catalog_path: str,
        scene_graph_catalog_path: str,
        assignments_path: str,
        fallback_mood_package_path: str,
    ) -> io.NodeOutput:
        root = _project_root()
        saved = _save_tensor_input(reference_image, "scene_graph_reference_lookup")
        lookup = lookup_reference(
            saved,
            catalog_path=_resolve(catalog_path),
            assignments_path=_resolve(assignments_path),
            scene_graph_catalog_path=_resolve(scene_graph_catalog_path),
        )
        if lookup.asset_id is None:
            raise ValueError(
                "Selected image is not present in the reference catalog. Rebuild the "
                "inventory before using multi-subject placement."
            )
        if lookup.scene_graph is None:
            raise ValueError(
                f"Reference {lookup.asset_id} has no Scene Graph v2 sidecar. Run "
                "scripts/build_reference_scene_graphs.py for this asset first."
            )
        graph = lookup.scene_graph
        validate_scene_graph(graph, project_root=str(root))
        capabilities = derive_scene_graph_capabilities(graph)
        if not capabilities["scene_generation_eligible"]:
            reasons = ", ".join(capabilities["reason_codes"])
            raise ValueError(f"Reference has no safe product slot: {reasons}")
        scene_reference = adapt_scene_graph_to_reference_v1(graph)
        validate_json(scene_reference, "reference-asset.schema.json", project_root=root)
        mood_path = lookup.mood_package_path or fallback_mood_package_path
        slots = {
            "schema_version": "1.0.0",
            "asset_id": graph["asset"]["asset_id"],
            "default_target_slot_id": capabilities["default_target_slot_id"],
            "replaceable_slot_ids": capabilities["replaceable_slot_ids"],
            "cross_kind_slot_ids": capabilities["cross_kind_slot_ids"],
            "safe_insertion_zone_ids": capabilities["safe_insertion_zone_ids"],
        }
        status = f"scene_graph_v2:{graph['scene_mode']}"
        if lookup.match_method == "perceptual_dhash":
            status += f":perceptual_dhash={lookup.match_distance}"
        if lookup.cluster_id:
            status += f":{lookup.cluster_id}"
        if capabilities["requires_scene_simplification"]:
            status += ":runtime_simplification"
        return io.NodeOutput(
            reference_image,
            dump_json(scene_reference),
            dump_json(graph),
            mood_path,
            dump_json(slots),
            status,
            ui={"text": (status,), "slots": (dump_json(slots),)},
        )


class ADLoadBoundSceneGraphV3(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_LoadBoundSceneGraphV3",
            display_name="Load Pixel-Bound Scene Graph V3",
            category="ad-creator/v3",
            description=(
                "Loads the explicitly selected Scene Graph and accepts it only when the "
                "connected human-selected reference pixels match its published binding."
            ),
            inputs=[
                io.Image.Input("reference_image"),
                io.String.Input("scene_graph_path"),
                io.String.Input("mood_package_path"),
            ],
            outputs=[
                io.Image.Output(display_name="reference_image"),
                io.String.Output(display_name="scene_reference_json"),
                io.String.Output(display_name="scene_graph_json"),
                io.String.Output(display_name="mood_package_path"),
                io.String.Output(display_name="available_slots_json"),
                io.String.Output(display_name="reference_status"),
            ],
        )

    @classmethod
    def execute(
        cls,
        reference_image: torch.Tensor,
        scene_graph_path: str,
        mood_package_path: str,
    ) -> io.NodeOutput:
        root = _project_root()
        graph = load_json(_resolve(scene_graph_path))
        validate_scene_graph(graph, project_root=str(root))
        saved = _save_tensor_input(reference_image, "bound_scene_graph_reference")
        binding = canonical_image_binding(saved)
        expected_pixel_hash = graph.get("asset", {}).get("pixel_sha256")
        if binding["pixel_sha256"] != expected_pixel_hash:
            raise ValueError(
                "Selected reference pixels do not match the explicitly bound Scene Graph"
            )
        capabilities = derive_scene_graph_capabilities(graph)
        if not capabilities["scene_generation_eligible"]:
            reasons = ", ".join(capabilities["reason_codes"])
            raise ValueError(f"Bound Scene Graph has no safe product slot: {reasons}")
        scene_reference = adapt_scene_graph_to_reference_v1(graph)
        validate_json(scene_reference, "reference-asset.schema.json", project_root=root)
        slots = {
            "schema_version": "1.0.0",
            "asset_id": graph["asset"]["asset_id"],
            "default_target_slot_id": capabilities["default_target_slot_id"],
            "replaceable_slot_ids": capabilities["replaceable_slot_ids"],
            "cross_kind_slot_ids": capabilities["cross_kind_slot_ids"],
            "safe_insertion_zone_ids": capabilities["safe_insertion_zone_ids"],
        }
        status = f"pixel_bound_scene_graph_v3:{graph['asset']['asset_id']}"
        return io.NodeOutput(
            reference_image,
            dump_json(scene_reference),
            dump_json(graph),
            mood_package_path,
            dump_json(slots),
            status,
            ui={"text": (status,), "slots": (dump_json(slots),)},
        )


class ADCreateProductSpec(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_CreateProductSpec",
            display_name="Create Product Spec V3",
            category="ad-creator/v3",
            description=(
                "Binds one analyzed beverage or dessert to its exact source pixels and "
                "creates one ordered ProductSpec V3. Branding is resolved later against "
                "the selected reference slot."
            ),
            inputs=[
                io.Image.Input("image"),
                io.String.Input(
                    "product_analysis_json",
                    force_input=True,
                    tooltip="ProductAnalysis V2 or V3 bound to this exact image.",
                ),
                io.String.Input("product_id", default="product_01"),
                io.Combo.Input(
                    "product_kind",
                    options=["beverage", "dessert"],
                    default="beverage",
                ),
                io.String.Input(
                    "target_slot_id",
                    default="auto",
                    tooltip="Use auto or an exact slot_id exposed by the Scene Graph.",
                ),
                io.Combo.Input(
                    "placement_mode",
                    options=["replace", "add"],
                    default="replace",
                ),
                io.Combo.Input(
                    "container_mode",
                    options=["preserve_source", "adopt_reference"],
                    default="preserve_source",
                ),
                io.Boolean.Input("cross_kind_replacement", default=False),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="product_spec_json"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        product_analysis_json: str,
        product_id: str,
        product_kind: str,
        target_slot_id: str,
        placement_mode: str,
        container_mode: str,
        cross_kind_replacement: bool,
    ) -> io.NodeOutput:
        root = _project_root()
        analysis = json.loads(product_analysis_json)
        validate_json(analysis, "product-analysis.schema.json", project_root=root)
        product_path = _save_tensor_input(image, "product_source")
        validate_product_analysis_binding(analysis, product_path)
        spec = create_product_spec(
            product_id=product_id,
            product_kind=product_kind,
            source_image=str(product_path),
            target_slot_id=target_slot_id,
            placement_mode=placement_mode,
            cross_kind_replacement=cross_kind_replacement,
            container_policy=container_mode,
            product_analysis=analysis,
        )
        return io.NodeOutput(
            image,
            dump_json(spec),
            ui={"product_spec": (dump_json(spec),)},
        )


class ADAssembleProductSet(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_AssembleProductSet",
            display_name="Assemble Product Set V3",
            category="ad-creator/v3",
            description=(
                "Atomically validates an ordered set of one to three exact products. "
                "Duplicate IDs and a fourth product are never silently accepted."
            ),
            inputs=[
                io.String.Input("product_spec_1_json", force_input=True),
                io.String.Input(
                    "product_spec_2_json",
                    default="",
                    force_input=True,
                    optional=True,
                ),
                io.String.Input(
                    "product_spec_3_json",
                    default="",
                    force_input=True,
                    optional=True,
                ),
            ],
            outputs=[
                io.String.Output(display_name="product_set_json"),
                io.Int.Output(display_name="exact_product_count"),
            ],
        )

    @classmethod
    def execute(
        cls,
        product_spec_1_json: str,
        product_spec_2_json: str = "",
        product_spec_3_json: str = "",
    ) -> io.NodeOutput:
        encoded = [
            value
            for value in (
                product_spec_1_json,
                product_spec_2_json,
                product_spec_3_json,
            )
            if isinstance(value, str) and value.strip()
        ]
        product_set = assemble_product_set([json.loads(value) for value in encoded])
        count = len(product_set["products"])
        return io.NodeOutput(
            dump_json(product_set),
            count,
            ui={"text": (f"{count} exact product(s)",)},
        )


class ADResolveReferenceContracts(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_ResolveReferenceContracts",
            display_name="Resolve Reference Contracts V3",
            category="ad-creator/v3",
            description=(
                "Combines a Scene Graph, optional white-light base+delta and optional "
                "wood profile into hashed ReferenceAnalysisV3 and resolved visual contracts. "
                "No reference pixels or provider calls are used."
            ),
            inputs=[
                io.String.Input(
                    "reference_id",
                    default="",
                    tooltip=(
                        "Stable catalog reference ID. When scene_graph_json is empty, "
                        "the resolver loads Scene Graph, lighting delta and wood profile by ID."
                    ),
                ),
                io.String.Input(
                    "scene_graph_json",
                    default="",
                    force_input=True,
                    optional=True,
                ),
                io.String.Input(
                    "lighting_base_json",
                    default="",
                    force_input=True,
                    optional=True,
                ),
                io.String.Input(
                    "lighting_delta_json",
                    default="",
                    force_input=True,
                    optional=True,
                ),
                io.String.Input(
                    "wood_material_profile_json",
                    default="",
                    force_input=True,
                    optional=True,
                ),
                io.String.Input(
                    "scene_graph_catalog_path",
                    default="data/reference-library/scene-graphs-v2.jsonl",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "lighting_delta_catalog_path",
                    default="data/reference-library/lighting-deltas-v3.jsonl",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "wood_profile_catalog_path",
                    default="data/reference-library/wood-material-profiles-v3.jsonl",
                    extra_dict={"hidden": True},
                ),
            ],
            outputs=[
                io.String.Output(display_name="resolved_reference_contract_json"),
                io.String.Output(display_name="reference_analysis_v3_json"),
                io.String.Output(display_name="resolved_visual_contract_json"),
                io.String.Output(display_name="resolved_contract_sha256"),
            ],
        )

    @classmethod
    def execute(
        cls,
        reference_id: str = "",
        scene_graph_json: str = "",
        lighting_base_json: str = "",
        lighting_delta_json: str = "",
        wood_material_profile_json: str = "",
        scene_graph_catalog_path: str = "data/reference-library/scene-graphs-v2.jsonl",
        lighting_delta_catalog_path: str = (
            "data/reference-library/lighting-deltas-v3.jsonl"
        ),
        wood_profile_catalog_path: str = (
            "data/reference-library/wood-material-profiles-v3.jsonl"
        ),
    ) -> io.NodeOutput:
        if scene_graph_json.strip():
            graph = json.loads(scene_graph_json)
            if reference_id.strip() and graph.get("asset", {}).get("asset_id") != reference_id.strip():
                raise ValueError("reference_id does not match the connected Scene Graph")
            base = json.loads(lighting_base_json) if lighting_base_json.strip() else None
            delta = json.loads(lighting_delta_json) if lighting_delta_json.strip() else None
            wood = (
                json.loads(wood_material_profile_json)
                if wood_material_profile_json.strip()
                else None
            )
            bundle = resolve_reference_contract_bundle(
                scene_graph=graph,
                lighting_base=base,
                lighting_delta=delta,
                wood_material_profile=wood,
            )
        else:
            if any(
                value.strip()
                for value in (
                    lighting_base_json,
                    lighting_delta_json,
                    wood_material_profile_json,
                )
            ):
                raise ValueError(
                    "Direct lighting/wood JSON requires a connected scene_graph_json"
                )
            bundle = resolve_reference_contract_bundle_by_id(
                project_root=_project_root(),
                reference_id=reference_id.strip(),
                scene_graph_catalog_path=scene_graph_catalog_path,
                lighting_delta_catalog_path=(
                    lighting_delta_catalog_path.strip() or None
                ),
                wood_profile_catalog_path=wood_profile_catalog_path.strip() or None,
            )
        analysis = bundle["reference_analysis"]
        validate_json(
            analysis,
            "reference-analysis-v3.schema.json",
            project_root=_project_root(),
        )
        visual = bundle["resolved_visual_contract"]
        digest = bundle["resolved_contract_sha256"]
        return io.NodeOutput(
            dump_json(bundle),
            dump_json(analysis),
            dump_json(visual),
            digest,
            ui={"text": (digest,), "reference_analysis": (dump_json(analysis),)},
        )


class ADBuildMultiProductSceneRequest(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_BuildMultiProductSceneRequest",
            display_name="Build Multi-Product Scene Request V3",
            category="ad-creator/v3",
            description=(
                "Compiles a zero-side-effect natural_compact_v5_multi request from one "
                "to three exact products. Core preflight blocks uncertain branding, unsafe "
                "slots, mismatched control-board manifests and more than four image inputs."
            ),
            inputs=[
                io.String.Input("mood_json", force_input=True),
                io.String.Input("product_set_json", force_input=True),
                io.String.Input("resolved_reference_contract_json", force_input=True),
                io.Combo.Input(
                    "unbound_slot_policy",
                    options=["genericize", "remove"],
                    default="genericize",
                ),
                io.String.Input(
                    "reference_control_board_path",
                    default="",
                    tooltip=(
                        "Optional path to an already sanitized board. It is accepted only "
                        "with its matching manifest; this node never invents attestation."
                    ),
                ),
                io.String.Input(
                    "reference_control_board_manifest_json",
                    default="",
                    force_input=True,
                    optional=True,
                ),
                io.Int.Input(
                    "seed",
                    default=713,
                    min=0,
                    max=2_147_483_647,
                    control_after_generate=False,
                ),
            ],
            outputs=[
                io.String.Output(display_name="prompt"),
                io.String.Output(display_name="request_json"),
                io.String.Output(display_name="request_sha256"),
            ],
        )

    @classmethod
    def execute(
        cls,
        mood_json: str,
        product_set_json: str,
        resolved_reference_contract_json: str,
        unbound_slot_policy: str,
        reference_control_board_path: str,
        reference_control_board_manifest_json: str = "",
        seed: int = 713,
    ) -> io.NodeOutput:
        mood = json.loads(mood_json)
        mood_path = mood.get("_path")
        if not isinstance(mood_path, str) or not mood_path.strip():
            raise ValueError(
                "mood_json must come from AD_LoadMoodPackage and include its resolved path"
            )
        board_path = reference_control_board_path.strip() or None
        board_manifest = (
            json.loads(reference_control_board_manifest_json)
            if reference_control_board_manifest_json.strip()
            else None
        )
        request = build_multi_product_request_from_bundle(
            project_root=_project_root(),
            mood_package_path=mood_path,
            product_set=json.loads(product_set_json),
            resolved_reference_bundle=json.loads(resolved_reference_contract_json),
            seed=seed,
            unbound_slot_policy=unbound_slot_policy,
            control_board_image=board_path,
            control_board_manifest=board_manifest,
        )
        digest = request_hash(request)
        return io.NodeOutput(
            request["generation"]["prompt"],
            dump_json(request),
            digest,
            ui={"text": (digest,), "request": (dump_json(request),)},
        )


class ADMultiProductQualityRoute(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_MultiProductQualityRoute",
            display_name="Multi-Product QA V3",
            category="ad-creator/v3",
            description=(
                "Normalizes typed per-product measurements for one to three exact "
                "products. Missing measurements become needs_review and no paid repair runs."
            ),
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.String.Input(
                    "qa_fixture_path",
                    default="evals/fixtures/multi_product_pass_qa.json",
                    tooltip="Local evaluator/fixture payload; this node makes no provider call.",
                ),
            ],
            outputs=[
                io.String.Output(display_name="multi_product_qa_json"),
                io.String.Output(display_name="quality_status"),
            ],
        )

    @classmethod
    def execute(cls, request_json: str, qa_fixture_path: str) -> io.NodeOutput:
        request = json.loads(request_json)
        payload = load_json(_resolve(qa_fixture_path))
        report = normalize_multi_product_qa(payload, request=request)
        status = report["overall_status"]
        return io.NodeOutput(
            dump_json(report),
            status,
            ui={"text": (status,), "qa": (dump_json(report),)},
        )


class ADV3ImageQualityRoute(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_V3ImageQualityRoute",
            display_name="V3 Image Measurement + QA",
            category="ad-creator/v3",
            description=(
                "Measures the actual generated pixels. Detector evidence is accepted only "
                "when bound to those exact pixels; absent segmentation, OCR or leakage "
                "measurements become needs_review rather than pass."
            ),
            inputs=[
                io.Image.Input("generated_image"),
                io.String.Input("request_json", force_input=True),
                io.String.Input(
                    "detector_evidence_path",
                    default="",
                    tooltip=(
                        "Optional local JSON containing product_region, brand_ocr, "
                        "wood_region and leakage detector envelopes."
                    ),
                ),
                io.Boolean.Input(
                    "use_system_ocr",
                    default=True,
                    tooltip="Use local macOS Vision OCR when no bound brand_ocr envelope is supplied.",
                ),
            ],
            outputs=[
                io.String.Output(display_name="v3_evaluation_report_json"),
                io.String.Output(display_name="quality_status"),
            ],
            is_output_node=True,
        )

    @staticmethod
    def _evidence_hook(
        evidence: dict[str, Any],
        key: str,
    ) -> Any:
        value = evidence.get(key)
        if not isinstance(value, dict):
            return None

        def hook(*args: Any, **kwargs: Any) -> dict[str, Any]:
            # The evaluator independently verifies the embedded exact pixel hash.
            return json.loads(json.dumps(value))

        return hook

    @classmethod
    def execute(
        cls,
        generated_image: torch.Tensor,
        request_json: str,
        detector_evidence_path: str,
        use_system_ocr: bool,
    ) -> io.NodeOutput:
        request = json.loads(request_json)
        validate_generation_request(request, maximum_credits=40)
        if request.get("schema_version") != "3.0.0":
            raise ValueError("AD_V3ImageQualityRoute requires GenerationRequestV3")
        candidate_path = _save_tensor_input(generated_image, "v3_quality_candidate")
        evidence = (
            load_json(_resolve(detector_evidence_path))
            if detector_evidence_path.strip()
            else {}
        )
        report = evaluate_v3_generated_image(
            candidate_path,
            request=request,
            project_root=_project_root(),
            product_region_hook=cls._evidence_hook(evidence, "product_region"),
            brand_evidence_hook=cls._evidence_hook(evidence, "brand_ocr"),
            wood_region_hook=cls._evidence_hook(evidence, "wood_region"),
            leakage_evidence_hook=cls._evidence_hook(evidence, "leakage"),
            use_system_ocr=use_system_ocr,
        )
        validate_json(
            report,
            "v3-image-evaluation-report.schema.json",
            project_root=_project_root(),
        )
        status = report["overall_status"]
        return io.NodeOutput(
            dump_json(report),
            status,
            ui={"text": (status,), "qa": (dump_json(report),)},
        )


class ADRestoreSingleProductBrandV3(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_RestoreSingleProductBrandV3",
            display_name="Restore Exact Brand (Single Product, Once)",
            category="ad-creator/v3",
            description=(
                "Applies a published PNG+mask BrandAsset only when the pixel-bound V3 QA "
                "report says the sole failure is a repairable exact-logo glyph mismatch. "
                "Every pixel outside the connected surface mask remains locked."
            ),
            inputs=[
                io.Image.Input("generated_image"),
                io.Mask.Input("target_surface_mask"),
                io.String.Input("request_json", force_input=True),
                io.String.Input("v3_qa_report_json", force_input=True),
                io.String.Input("brand_asset_json", force_input=True),
                io.String.Input(
                    "target_quad_json",
                    default="[[0.35,0.42],[0.65,0.42],[0.65,0.58],[0.35,0.58]]",
                    tooltip="Four normalized points: top-left, top-right, bottom-right, bottom-left.",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="restored_image"),
                io.String.Output(display_name="restoration_report_json"),
                io.String.Output(display_name="verification_status"),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(
        cls,
        generated_image: torch.Tensor,
        target_surface_mask: torch.Tensor,
        request_json: str,
        v3_qa_report_json: str,
        brand_asset_json: str,
        target_quad_json: str,
    ) -> io.NodeOutput:
        if generated_image.ndim != 4 or generated_image.shape[0] != 1:
            raise ValueError("Brand restoration accepts exactly one generated image")
        if target_surface_mask.ndim != 3 or target_surface_mask.shape[0] != 1:
            raise ValueError("Brand restoration accepts exactly one target surface mask")
        request = json.loads(request_json)
        validate_generation_request(request, maximum_credits=40)
        products = request.get("products")
        if not isinstance(products, list) or len(products) != 1:
            raise ValueError("Brand restoration is allowed for one product only")
        product = products[0]
        product_id = product.get("product_id")
        target_contract = product.get("target_brand_contract")
        if not isinstance(product_id, str) or not isinstance(target_contract, dict):
            raise ValueError("The sole ProductSpec lacks its target brand contract")

        qa_report = validate_v3_image_evaluation_report(json.loads(v3_qa_report_json))
        current_request_sha256 = request_hash(request)
        if qa_report.get("generation_request_sha256") != current_request_sha256:
            raise ValueError("V3 QA report belongs to a different GenerationRequestV3")
        candidate_path = _save_tensor_input(generated_image, "brand_restore_candidate")
        if (
            qa_report.get("evaluated_image_binding", {}).get("pixel_sha256")
            != canonical_image_binding(candidate_path)["pixel_sha256"]
        ):
            raise ValueError("V3 QA report belongs to different generated pixels")
        expected_failure = f"{product_id}.single_product_logo_repair_allowed"
        if qa_report.get("hard_failures") != [expected_failure]:
            raise ValueError(
                "Exact brand restoration requires the sole hard failure to be a "
                "repairable single-product logo mismatch"
            )
        if qa_report.get("missing_measurements"):
            raise ValueError("Brand restoration cannot run while QA measurements are missing")
        matching_result = next(
            (
                item
                for item in qa_report.get("qa", {})
                .get("multi_product", {})
                .get("product_results", [])
                if item.get("product_id") == product_id
            ),
            None,
        )
        brand_result = matching_result.get("brand_result") if isinstance(matching_result, dict) else None
        if not isinstance(brand_result, dict) or brand_result.get("repairable") is not True:
            raise ValueError("V3 QA did not authorize deterministic brand restoration")
        measurements = (
            matching_result.get("measurements")
            if isinstance(matching_result, dict)
            else None
        )
        if not isinstance(measurements, dict):
            raise ValueError("V3 QA product measurements are missing")
        authorized_surface_mask_pixel_sha256 = measurements.get(
            "brand_surface_mask_pixel_sha256"
        )
        authorized_surface_bbox = measurements.get("brand_surface_bbox")
        if not isinstance(authorized_surface_mask_pixel_sha256, str) or not isinstance(
            authorized_surface_bbox, dict
        ):
            raise ValueError(
                "V3 QA did not bind the repair to a measured brand surface mask and bbox"
            )

        mask_array = (
            target_surface_mask[0]
            .detach()
            .to(device="cpu", dtype=torch.float32)
            .clamp(0, 1)
            .numpy()
        )
        surface_mask = Image.fromarray(
            np.rint(mask_array * 255).astype(np.uint8), mode="L"
        )
        base = _tensor_to_pil(generated_image[0])
        if surface_mask.size != base.size:
            raise ValueError("Target surface mask dimensions must match generated image")
        brand_asset = json.loads(brand_asset_json)
        target_quad = json.loads(target_quad_json)
        product_analysis = product.get("product_analysis")
        source_binding = (
            product_analysis.get("source_binding")
            if isinstance(product_analysis, dict)
            else None
        )
        source_image = product.get("source_image")
        if not isinstance(source_binding, dict) or not isinstance(source_image, str):
            raise ValueError("ProductSpec requires a pixel-bound ProductAnalysisV3")
        current_source_binding = canonical_image_binding(_resolve(source_image))
        source_product_pixel_sha256 = source_binding.get("pixel_sha256")
        if source_product_pixel_sha256 != current_source_binding["pixel_sha256"]:
            raise ValueError("ProductAnalysisV3 belongs to different source product pixels")
        result = restore_single_product_brand(
            base,
            brand_asset=brand_asset,
            project_root=_project_root(),
            target_brand_contract=target_contract,
            target_surface_mask=surface_mask,
            target_quad=target_quad,
            product_id=product_id,
            source_product_pixel_sha256=source_product_pixel_sha256,
            authorized_surface_mask_pixel_sha256=(
                authorized_surface_mask_pixel_sha256
            ),
            authorized_surface_bbox=authorized_surface_bbox,
            product_count=1,
            attempt_index=1,
        )
        report = {
            **result.report,
            "source_v3_qa_report_sha256": qa_report["report_sha256"],
            "verification_status": "needs_review",
            "next_required_action": "rerun_exact_logo_ocr_and_position_qa",
        }
        return io.NodeOutput(
            _pil_to_tensor(result.image),
            dump_json(report),
            "needs_review",
            ui={"text": ("needs_review",), "restoration": (dump_json(report),)},
        )


class ADBuildGenerationRequest(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        feature_state = _ui_feature_state()
        container_visibility = _hidden_unless(
            feature_state["container_choice_visible"]
        )
        repair_visibility = _hidden_unless(
            feature_state["auto_paid_repair_visible"]
        )
        return io.Schema(
            node_id="AD_BuildGenerationRequest",
            display_name="Build Natural Capture Request",
            category=CATEGORY,
            description="Compiles product identity and a mood package into one guarded provider request.",
            inputs=[
                io.Image.Input("image"),
                io.String.Input("mood_json", force_input=True),
                io.String.Input(
                    "product_analysis_json",
                    force_input=True,
                    tooltip="Must come from Gemini Product Analysis for this exact image.",
                ),
                io.String.Input(
                    "scene_reference_json",
                    force_input=True,
                    tooltip="Offline abstract scene contract resolved from the selected reference.",
                ),
                io.Combo.Input(
                    "container_mode",
                    options=["preserve_source", "adopt_reference"],
                    default="preserve_source",
                    extra_dict=container_visibility,
                ),
                io.String.Input(
                    "container_design_path",
                    default="",
                    tooltip="Optional developer override; normally derived from the selected reference.",
                    extra_dict=container_visibility,
                ),
                io.Boolean.Input(
                    "auto_paid_repair",
                    default=feature_state["auto_paid_repair_default"],
                    tooltip=(
                        "Makes this request eligible for provider-specific repair. "
                        "OpenAI generation always overrides this to manual review."
                    ),
                    extra_dict=repair_visibility,
                ),
                io.String.Input(
                    "features_path",
                    default=_service_features_path(),
                    tooltip="Server-level feature configuration; restart ComfyUI after changing it.",
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "provider_profile_path",
                    default="",
                    tooltip="Optional provider transport overlay; empty keeps the mood runtime profile.",
                    extra_dict={"hidden": True},
                ),
                io.Int.Input(
                    "seed",
                    default=713,
                    min=0,
                    max=2_147_483_647,
                    control_after_generate=False,
                ),
                io.Combo.Input(
                    "quality_tier",
                    options=["default", "final"],
                    default="default",
                    tooltip="default=GPT Image 2 medium 1k, final=GPT Image 2 high 1k",
                ),
                io.Combo.Input(
                    "reference_control_role",
                    options=[
                        "container_design_only",
                        "structured_only",
                        "sanitized_scene_hint",
                    ],
                    default="container_design_only",
                    tooltip="Declares whether the optional second image is a legacy cup board, absent structured contract, or sanitized photographic scene hint.",
                    extra_dict=container_visibility,
                ),
                io.Combo.Input(
                    "container_design_source",
                    options=["reference", "source"],
                    default="reference",
                    tooltip="Chooses which versioned design contract is reconstructed; pixels are never preserved.",
                    extra_dict=container_visibility,
                ),
                io.Image.Input(
                    "container_reference",
                    optional=True,
                    extra_dict=container_visibility,
                ),
                io.Image.Input("brand_asset", optional=True),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="prompt"),
                io.String.Output(display_name="request_json"),
            ],
        )

    @classmethod
    def _execute_common(
        cls,
        image: torch.Tensor,
        mood_json: str,
        product_analysis_json: str,
        scene_reference_json: str,
        container_mode: str,
        container_design_path: str,
        auto_paid_repair: bool,
        features_path: str,
        provider_profile_path: str,
        seed: int,
        quality_tier: str = "default",
        container_reference: torch.Tensor | None = None,
        brand_asset: torch.Tensor | None = None,
        scene_graph_json: str = "",
        target_slot_id: str = "auto",
        placement_mode: str = "replace",
        product_kind: str = "beverage",
        cross_kind_replacement: bool = False,
        unbound_slot_policy: str = "genericize",
        reference_control_role: str = "container_design_only",
        container_design_source: str = "reference",
    ) -> io.NodeOutput:
        root = _project_root()
        mood = json.loads(mood_json)
        preset = load_json(_resolve(mood["preset_path"]))
        profile = load_json(_resolve(mood["runtime_profile_path"]))
        provider_application = None
        if provider_profile_path.strip():
            provider_application = apply_provider_profile(
                project_root=root,
                runtime_profile=profile,
                provider_profile_path=provider_profile_path.strip(),
            )
            profile = provider_application.runtime_profile
        recipe = load_json(_resolve(mood["scene_recipe_path"]))
        lighting = load_json(_resolve(mood["lighting_sheet_path"]))
        photographic_style_contract = (
            load_json(_resolve(mood["photographic_style_contract_path"]))
            if mood.get("photographic_style_contract_path")
            else None
        )
        analysis = json.loads(product_analysis_json)
        scene_reference = json.loads(scene_reference_json)
        scene_graph = json.loads(scene_graph_json) if scene_graph_json.strip() else None
        slot_bindings = None
        container_reference_contract = scene_reference
        if scene_graph is not None:
            validate_scene_graph(scene_graph, project_root=str(root))
            slot_bindings = [
                {
                    "input_product_id": "product_01",
                    "target_slot_id": target_slot_id,
                    "placement_mode": placement_mode,
                    "product_kind": product_kind,
                    "cross_kind_replacement": cross_kind_replacement,
                }
            ]
            preview = resolve_slot_plan(
                scene_graph,
                slot_bindings,
                unbound_slot_policy=unbound_slot_policy,
            )
            resolved_binding = preview["bindings"][0]
            if resolved_binding["placement_mode"] == "replace":
                container_reference_contract = adapt_scene_graph_to_reference_v1(
                    scene_graph,
                    target_slot_id=resolved_binding["target_slot_id"],
                )
        configured_features_path = _service_features_path()
        if features_path != configured_features_path:
            raise ValueError(
                "Workflow feature settings differ from the server configuration. "
                "Set AD_CREATOR_FEATURES_PATH and restart ComfyUI."
            )
        features = load_service_features(root, configured_features_path)
        resolved_container_design_path = (
            container_design_path.strip()
            or (
                mood.get("container_design_path", "")
                if container_mode == "adopt_reference"
                else ""
            )
        )
        container_design = (
            load_json(_resolve(container_design_path.strip()))
            if container_design_path.strip()
            else (
                load_json(_resolve(mood["container_design_path"]))
                if container_mode == "adopt_reference"
                and mood.get("container_design_path")
                else derive_container_design(container_reference_contract)
                if container_mode == "adopt_reference"
                else None
            )
        )
        validate_json(analysis, "product-analysis.schema.json", project_root=root)
        validate_json(scene_reference, "reference-asset.schema.json", project_root=root)
        validate_json(lighting, "lighting-sheet.schema.json", project_root=root)
        if scene_graph is None:
            capabilities = derive_reference_capabilities(scene_reference)
            if not capabilities["scene_generation_eligible"]:
                reasons = ", ".join(capabilities["reason_codes"])
                raise ValueError(
                    "Selected reference is not compatible with one-product restyling: "
                    f"{reasons}"
                )
            if (
                container_mode == "adopt_reference"
                and not capabilities["container_adoption_eligible"]
            ):
                reasons = ", ".join(capabilities["reason_codes"])
                raise ValueError(f"Selected reference cup cannot be adopted: {reasons}")
        else:
            graph_capabilities = derive_scene_graph_capabilities(scene_graph)
            if not graph_capabilities["scene_generation_eligible"]:
                reasons = ", ".join(graph_capabilities["reason_codes"])
                raise ValueError(f"Selected scene graph has no safe product slot: {reasons}")
        if container_design is not None:
            validate_json(container_design, "container-design.schema.json", project_root=root)

        product_path = _save_tensor_input(image, "product_source")
        validate_product_analysis_binding(analysis, product_path)
        provider_image = image
        provider_product_path = product_path
        provider_input_transform = None
        if (
            preset.get("preset_id") == WOOD_CLOSEUP_PRESET_ID
            and container_mode == "adopt_reference"
        ):
            provider_image, evidence_regions = _adopted_container_beverage_evidence(
                image,
                analysis,
            )
            evidence_path = _save_tensor_input(
                provider_image,
                "beverage_only_evidence",
            )
            provider_product_path = evidence_path
            provider_input_transform = {
                "role": "product_source",
                "policy": "beverage_only_evidence_board",
                "source_path": str(product_path),
                "source_pixel_sha256": hashlib.sha256(product_path.read_bytes()).hexdigest(),
                "provider_path": str(evidence_path),
                "provider_pixel_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                "container_identity_scope": "discard_source_container",
                "camera_pose_authority": "preset",
                **evidence_regions,
            }
        elif preset.get("preset_id") in OVERHEAD_SURFACE_EVIDENCE_PRESETS:
            provider_image, crop_bbox = _beverage_surface_evidence_crop(image, analysis)
            evidence_path = _save_tensor_input(
                provider_image,
                "beverage_surface_evidence",
            )
            provider_input_transform = {
                "role": "product_source",
                "policy": "beverage_surface_crop",
                "source_path": str(product_path),
                "source_pixel_sha256": hashlib.sha256(product_path.read_bytes()).hexdigest(),
                "crop_bbox_normalized": crop_bbox,
                "provider_path": str(evidence_path),
                "provider_pixel_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                "container_identity_scope": (
                    "source_family_and_material_only"
                    if container_mode == "preserve_source"
                    else "discard_source_container"
                ),
                "camera_pose_authority": "preset",
            }
        container_reference_path = (
            _save_tensor_input(
                container_reference,
                (
                    "scene_hint"
                    if reference_control_role == "sanitized_scene_hint"
                    else "container_reference"
                ),
            )
            if container_reference is not None
            else None
        )
        brand_asset_path = (
            _save_tensor_input(brand_asset, "brand_asset") if brand_asset is not None else None
        )
        request = build_generation_request(
            preset=preset,
            runtime_profile=profile,
            input_image=str(provider_product_path),
            product_description=analysis["product_summary"],
            logo_text=verified_logo_text(analysis),
            seed=seed,
            tier=quality_tier,
            product_analysis=analysis,
            scene_reference=scene_reference,
            scene_graph=scene_graph,
            slot_bindings=slot_bindings,
            unbound_slot_policy=unbound_slot_policy,
            scene_recipe=recipe,
            lighting_sheet=lighting,
            photographic_style_contract=photographic_style_contract,
            container_mode=container_mode,
            container_reference_image=(
                str(container_reference_path) if container_reference_path else None
            ),
            container_design=container_design,
            reference_control_role=reference_control_role,
            container_design_source=container_design_source,
            brand_asset_image=str(brand_asset_path) if brand_asset_path else None,
            service_features=features,
            auto_paid_repair=auto_paid_repair,
        )
        request["mood_package_id"] = mood["mood_package_id"]
        request["lighting_sheet"] = {
            "id": lighting["lighting_sheet_id"],
            "sha256": _json_sha256(lighting),
        }
        def contract_record(path_value: str) -> dict[str, str]:
            path = _resolve(path_value)
            return {
                "path": path_value,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        request["resolved_contracts"] = {
            "mood_package": contract_record(mood["_path"]),
            "preset": contract_record(mood["preset_path"]),
            "runtime_profile": contract_record(mood["runtime_profile_path"]),
            "scene_recipe": contract_record(mood["scene_recipe_path"]),
            "lighting_sheet": contract_record(mood["lighting_sheet_path"]),
            "grade_profile": contract_record(mood["grade_profile_path"]),
            "photographic_style_contract": (
                contract_record(mood["photographic_style_contract_path"])
                if mood.get("photographic_style_contract_path")
                else None
            ),
            "container_design": (
                contract_record(resolved_container_design_path)
                if container_mode == "adopt_reference"
                and resolved_container_design_path
                else None
            ),
            "reference_control_board": (
                contract_record(mood["reference_control_board_path"])
                if mood.get("reference_control_board_path")
                else None
            ),
            "reference_control_board_manifest": (
                contract_record(mood["reference_control_board_manifest_path"])
                if mood.get("reference_control_board_manifest_path")
                else None
            ),
        }
        request["resolved_contracts"]["reference_control_submission"] = {
            "role": reference_control_role,
            "submitted": container_reference_path is not None,
            "container_design_source": container_design_source,
            "submitted_pixel_sha256": (
                hashlib.sha256(container_reference_path.read_bytes()).hexdigest()
                if container_reference_path is not None
                else None
            ),
        }
        request["runtime_contracts"] = {
            "runtime_profile_path": mood["runtime_profile_path"],
            "lighting_sheet_path": mood["lighting_sheet_path"],
            "grade_profile_path": mood["grade_profile_path"],
        }
        if provider_application is not None:
            record_provider_profile(request, provider_application)
        request["prompt_compiler_version"] = PROMPT_COMPILER_VERSION
        if provider_input_transform is not None:
            request["provider_input_transform"] = provider_input_transform
        validate_generation_request(request, maximum_credits=4)
        return io.NodeOutput(
            provider_image,
            request["generation"]["prompt"],
            dump_json(request),
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        mood_json: str,
        product_analysis_json: str,
        scene_reference_json: str,
        container_mode: str,
        container_design_path: str,
        auto_paid_repair: bool,
        features_path: str,
        provider_profile_path: str,
        seed: int,
        quality_tier: str = "default",
        container_reference: torch.Tensor | None = None,
        brand_asset: torch.Tensor | None = None,
        reference_control_role: str = "container_design_only",
        container_design_source: str = "reference",
    ) -> io.NodeOutput:
        return cls._execute_common(
            image=image,
            mood_json=mood_json,
            product_analysis_json=product_analysis_json,
            scene_reference_json=scene_reference_json,
            container_mode=container_mode,
            container_design_path=container_design_path,
            auto_paid_repair=auto_paid_repair,
            features_path=features_path,
            provider_profile_path=provider_profile_path,
            seed=seed,
            quality_tier=quality_tier,
            container_reference=container_reference,
            brand_asset=brand_asset,
            reference_control_role=reference_control_role,
            container_design_source=container_design_source,
        )


class ADBuildSceneGenerationRequest(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        feature_state = _ui_feature_state()
        container_visibility = _hidden_unless(
            feature_state["container_choice_visible"]
        )
        repair_visibility = _hidden_unless(
            feature_state["auto_paid_repair_visible"]
        )
        return io.Schema(
            node_id="AD_BuildSceneGenerationRequest",
            display_name="Build Multi-Subject Capture Request",
            category=CATEGORY,
            description=(
                "Binds one exact user product to a deterministic Scene Graph v2 slot. "
                "Unbound products are generalized or removed by policy."
            ),
            inputs=[
                io.Image.Input("image"),
                io.String.Input("mood_json", force_input=True),
                io.String.Input("product_analysis_json", force_input=True),
                io.String.Input("scene_reference_json", force_input=True),
                io.String.Input("scene_graph_json", force_input=True),
                io.Combo.Input(
                    "container_mode",
                    options=["preserve_source", "adopt_reference"],
                    default="preserve_source",
                    extra_dict=container_visibility,
                ),
                io.Combo.Input(
                    "target_slot_id",
                    options=[
                        "auto",
                        "beverage_primary",
                        "beverage_secondary",
                        "beverage_tertiary",
                        "dessert_primary",
                        "dessert_secondary",
                        "dessert_tertiary",
                    ],
                    default="auto",
                    tooltip=(
                        "Choose a slot listed by Resolve Multi-Subject Reference. "
                        "Auto uses the safest primary slot."
                    ),
                ),
                io.Combo.Input(
                    "placement_mode",
                    options=["replace", "add"],
                    default="replace",
                ),
                io.Combo.Input(
                    "product_kind",
                    options=["beverage", "dessert"],
                    default="beverage",
                ),
                io.Boolean.Input("cross_kind_replacement", default=False),
                io.Combo.Input(
                    "unbound_slot_policy",
                    options=["genericize", "remove"],
                    default="genericize",
                ),
                io.String.Input(
                    "container_design_path",
                    default="",
                    tooltip="Optional developer override for a versioned container contract.",
                    extra_dict=container_visibility,
                ),
                io.Boolean.Input(
                    "auto_paid_repair",
                    default=feature_state["auto_paid_repair_default"],
                    extra_dict=repair_visibility,
                ),
                io.String.Input(
                    "features_path",
                    default=_service_features_path(),
                    extra_dict={"hidden": True},
                ),
                io.String.Input(
                    "provider_profile_path",
                    default="",
                    extra_dict={"hidden": True},
                ),
                io.Int.Input(
                    "seed",
                    default=713,
                    min=0,
                    max=2_147_483_647,
                    control_after_generate=False,
                ),
                io.Combo.Input(
                    "quality_tier",
                    options=["default", "final"],
                    default="default",
                    tooltip="default=GPT Image 2 medium 1k, final=GPT Image 2 high 1k",
                ),
                io.Combo.Input(
                    "reference_control_role",
                    options=[
                        "container_design_only",
                        "structured_only",
                        "sanitized_scene_hint",
                    ],
                    default="container_design_only",
                    tooltip="Declares the second-image semantic role for a reproducible provider payload.",
                    extra_dict=container_visibility,
                ),
                io.Combo.Input(
                    "container_design_source",
                    options=["reference", "source"],
                    default="reference",
                    tooltip="Reconstruct the selected JSON design rather than retaining source pixels.",
                    extra_dict=container_visibility,
                ),
                io.Image.Input(
                    "container_reference",
                    optional=True,
                    extra_dict=container_visibility,
                ),
                io.Image.Input("brand_asset", optional=True),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="prompt"),
                io.String.Output(display_name="request_json"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        mood_json: str,
        product_analysis_json: str,
        scene_reference_json: str,
        scene_graph_json: str,
        container_mode: str,
        target_slot_id: str,
        placement_mode: str,
        product_kind: str,
        cross_kind_replacement: bool,
        unbound_slot_policy: str,
        container_design_path: str,
        auto_paid_repair: bool,
        features_path: str,
        provider_profile_path: str,
        seed: int,
        quality_tier: str = "default",
        container_reference: torch.Tensor | None = None,
        brand_asset: torch.Tensor | None = None,
        reference_control_role: str = "container_design_only",
        container_design_source: str = "reference",
    ) -> io.NodeOutput:
        return ADBuildGenerationRequest._execute_common(
            image=image,
            mood_json=mood_json,
            product_analysis_json=product_analysis_json,
            scene_reference_json=scene_reference_json,
            scene_graph_json=scene_graph_json,
            target_slot_id=target_slot_id,
            placement_mode=placement_mode,
            product_kind=product_kind,
            cross_kind_replacement=cross_kind_replacement,
            unbound_slot_policy=unbound_slot_policy,
            container_mode=container_mode,
            container_design_path=container_design_path,
            auto_paid_repair=auto_paid_repair,
            features_path=features_path,
            provider_profile_path=provider_profile_path,
            seed=seed,
            quality_tier=quality_tier,
            container_reference=container_reference,
            brand_asset=brand_asset,
            reference_control_role=reference_control_role,
            container_design_source=container_design_source,
        )


class ADFakeGenerate(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_FakeGenerate",
            display_name="Fake Generate (0 Credits)",
            category=CATEGORY,
            description="Validates the provider boundary without making a paid request.",
            inputs=[
                io.Image.Input("image"),
                io.String.Input("request_json", force_input=True),
                io.String.Input(
                    "fixture_image_path",
                    default="",
                    tooltip="Optional existing generated image used as deterministic provider output.",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="generated_image"),
                io.String.Output(display_name="job_json"),
            ],
        )

    @classmethod
    def execute(cls, image: torch.Tensor, request_json: str, fixture_image_path: str) -> io.NodeOutput:
        request = json.loads(request_json)
        digest = request_hash(request)
        if fixture_image_path.strip():
            fixture = _resolve(fixture_image_path.strip())
            if not fixture.is_file():
                raise FileNotFoundError(f"Fake fixture does not exist: {fixture}")
            with Image.open(fixture) as opened:
                output = _pil_to_tensor(opened)
            fixture_value = str(fixture)
        else:
            output = image.detach().to(device="cpu", dtype=torch.float32).clamp(0, 1)
            fixture_value = "input_passthrough"
        job = {
            "provider": "fake_local",
            "job_id": f"fake-comfy-{digest[:20]}",
            "status": "completed",
            "actual_credits": 0,
            "request_hash": digest,
            "fixture": fixture_value,
        }
        return io.NodeOutput(output, dump_json(job))


class ADFakeQualityRoute(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_FakeQualityRoute",
            display_name="Fake QA + Repair Route (0 Credits)",
            category=CATEGORY,
            description="Validates QA thresholds and paid-repair routing from a fixed fixture.",
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.String.Input("lighting_sheet_json", force_input=True),
                io.String.Input(
                    "qa_fixture_path",
                    default="evals/fixtures/mum_logo_failure_qa.json",
                ),
            ],
            outputs=[
                io.String.Output(display_name="qa_report_json"),
                io.String.Output(display_name="repair_plan_json"),
                io.String.Output(display_name="quality_status"),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(
        cls,
        request_json: str,
        lighting_sheet_json: str,
        qa_fixture_path: str,
    ) -> io.NodeOutput:
        request = json.loads(request_json)
        lighting = json.loads(lighting_sheet_json)
        evaluator = FakeQualityEvaluator(_resolve(qa_fixture_path))
        role_paths = dict(
            zip(
                request["generation"]["image_roles"],
                request["generation"]["image_paths"],
                strict=True,
            )
        )
        payload = evaluator.evaluate(
            generated_image="comfyui-fake-generated",
            original_product_image=role_paths["product_source"],
            request=request,
            lighting_sheet=lighting,
            container_reference_image=(
                role_paths.get("scene_hint")
                or role_paths.get("container_reference")
            ),
        )
        report = normalize_qa_report(
            payload,
            evaluator={
                "provider": evaluator.provider_name,
                "model": evaluator.model_name,
                "mode": evaluator.mode,
            },
            evaluated_image="comfyui-fake-generated",
            request=request,
            lighting_sheet=lighting,
            project_root=_project_root(),
        )
        report, plan = route_repair(
            report,
            request=request,
            project_root=_project_root(),
        )
        return io.NodeOutput(
            dump_json(report),
            dump_json(plan),
            report["overall_status"],
            ui={"text": (report["overall_status"],), "repair_plan": (dump_json(plan),)},
        )


class ADHiggsfieldGenerate(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_HiggsfieldGenerate",
            display_name="Higgsfield Generate + QA",
            category="ad-creator/live",
            description="Runs or resumes one guarded generation, semantic QA and at most one paid repair.",
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.String.Input("lighting_sheet_json", force_input=True),
                io.String.Input("output_root", default="outputs/comfyui-live/runs"),
                io.String.Input("cli_path", default=".tools/higgsfield/bin/higgsfield"),
                io.String.Input("evaluator_config_path", default="configs/evaluator.json"),
                io.Int.Input("timeout_seconds", default=1200, min=30, max=3600),
                io.Int.Input("poll_interval_seconds", default=3, min=1, max=30),
                io.Combo.Input(
                    "repair_execution",
                    options=["manual", "auto"],
                    default="manual",
                    tooltip="manual saves the QA repair plan without submitting a paid repair.",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="generated_image"),
                io.String.Output(display_name="job_json"),
                io.String.Output(display_name="manifest_json"),
            ],
        )

    @classmethod
    def execute(
        cls,
        request_json: str,
        lighting_sheet_json: str,
        output_root: str,
        cli_path: str,
        evaluator_config_path: str,
        timeout_seconds: int,
        poll_interval_seconds: int,
        repair_execution: str = "manual",
    ) -> io.NodeOutput:
        root = _project_root()
        load_project_env(root)
        request = json.loads(request_json)
        lighting = json.loads(lighting_sheet_json)
        validate_generation_request(request, maximum_credits=4)
        validate_json(lighting, "lighting-sheet.schema.json", project_root=root)
        if request["lighting_sheet"]["id"] != lighting["lighting_sheet_id"]:
            raise ValueError("Request and connected lighting sheet IDs do not match")
        if request["lighting_sheet"]["sha256"] != _json_sha256(lighting):
            raise ValueError("Connected lighting sheet changed after request compilation")

        # Fail before provider construction, RunStore writes, cost lookup, or
        # any remote submission. V2 live workflows remain unchanged.
        require_v3_paid_submission_allowed(
            request,
            provider_name=HiggsfieldProvider.name,
        )

        run_root = _resolve(output_root)
        store = RunStore(run_root)
        provider = HiggsfieldProvider(
            run_root / "_higgsfield_provider",
            cli_path=_resolve(cli_path),
            maximum_base_credits=4,
        )
        is_v3 = request.get("schema_version") == "3.0.0"
        if is_v3:
            manifest, _ = execute_diagnostic_pilot_case(
                request,
                provider=provider,
                store=store,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            provider_output = manifest.get("artifacts", {}).get("provider_output")
            if not isinstance(provider_output, str) or not Path(provider_output).is_file():
                raise ValueError("Completed V3 diagnostic has no provider output artifact")
            with Image.open(provider_output) as opened:
                output = _pil_to_tensor(opened)
            job = {
                "provider": provider.name,
                "job_id": manifest["provider"]["job_id"],
                "status": manifest["status"],
                "actual_credits": manifest["cost"].get("actual_credits"),
                "total_credits": manifest["cost"].get(
                    "actual_credits",
                    request["generation"].get("estimated_credits"),
                ),
                "request_hash": manifest["request_hash"],
                "manifest_path": str(
                    store.manifest_path(manifest["request_hash"]).resolve()
                ),
                "repair": None,
                "result_disposition": "manual_review",
            }
            return io.NodeOutput(output, dump_json(job), dump_json(manifest))

        manifest, _ = execute_until_terminal(
            request,
            provider=provider,
            store=store,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        evaluator_config = load_json(_resolve(evaluator_config_path))
        evaluator = GeminiQualityEvaluator(
            model=evaluator_config["model"],
            fallback_models=evaluator_config.get("fallback_models", []),
            timeout_seconds=float(evaluator_config["timeout_seconds"]),
            maximum_image_edge=int(evaluator_config["maximum_image_edge"]),
        )
        runtime_profile = load_json(
            _resolve(request["runtime_contracts"]["runtime_profile_path"])
        )
        role_paths = {
            item["role"]: item["path"]
            for item in ordered_image_inputs(request["generation"])
        }
        quality = evaluate_and_maybe_repair(
            project_root=root,
            request=request,
            manifest=manifest,
            store=store,
            provider=provider,
            evaluator=evaluator,
            runtime_profile=runtime_profile,
            lighting_sheet=lighting,
            original_product_image=role_paths["product_source"],
            container_reference_image=(
                role_paths.get("scene_hint")
                or role_paths.get("container_reference")
            ),
            brand_asset_image=role_paths.get("brand_asset"),
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            allow_paid_repair=repair_execution == "auto",
        )
        manifest = quality.manifest
        with Image.open(quality.final_image) as opened:
            output = _pil_to_tensor(opened)
        job = {
            "provider": provider.name,
            "job_id": manifest["provider"]["job_id"],
            "status": manifest["status"],
            "actual_credits": manifest["cost"].get("actual_credits"),
            "total_credits": manifest["cost"].get("total_credits"),
            "request_hash": manifest["request_hash"],
            "manifest_path": str(store.manifest_path(manifest["request_hash"]).resolve()),
            "repair": manifest.get("repair"),
        }
        return io.NodeOutput(output, dump_json(job), dump_json(manifest))


class ADOpenAIImageGenerate(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_OpenAIImageGenerate",
            display_name="OpenAI GPT Image 1 Mini + Gemini QA",
            category="ad-creator/live",
            description=(
                "Runs one paid OpenAI Images request and Gemini QA. Any repair "
                "remains manual and is never submitted by this node."
            ),
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.String.Input("lighting_sheet_json", force_input=True),
                io.String.Input("output_root", default="outputs/comfyui-openai/runs"),
                io.String.Input(
                    "provider_config_path",
                    default="configs/providers/openai-gpt-image-1-mini.json",
                ),
                io.String.Input("evaluator_config_path", default="configs/evaluator.json"),
                io.Int.Input("timeout_seconds", default=1200, min=30, max=3600),
                io.Combo.Input(
                    "repair_execution",
                    options=["manual"],
                    default="manual",
                    tooltip="OpenAI repair is always reviewed and submitted manually.",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="generated_image"),
                io.String.Output(display_name="job_json"),
                io.String.Output(display_name="manifest_json"),
            ],
        )

    @classmethod
    def execute(
        cls,
        request_json: str,
        lighting_sheet_json: str,
        output_root: str,
        provider_config_path: str,
        evaluator_config_path: str,
        timeout_seconds: int,
        repair_execution: str = "manual",
    ) -> io.NodeOutput:
        if repair_execution != "manual":
            raise ValueError("OpenAI automatic repair is disabled")
        root = _project_root()
        load_project_env(root)
        request = json.loads(request_json)
        lighting = json.loads(lighting_sheet_json)
        validate_generation_request(request, maximum_credits=2)
        validate_json(lighting, "lighting-sheet.schema.json", project_root=root)
        if request["lighting_sheet"]["id"] != lighting["lighting_sheet_id"]:
            raise ValueError("Request and connected lighting sheet IDs do not match")
        if request["lighting_sheet"]["sha256"] != _json_sha256(lighting):
            raise ValueError("Connected lighting sheet changed after request compilation")

        runtime_contracts = request.get("runtime_contracts") or {}
        base_runtime_profile = load_json(
            _resolve(runtime_contracts["runtime_profile_path"])
        )
        application = apply_provider_profile(
            project_root=root,
            runtime_profile=base_runtime_profile,
            provider_profile_path=provider_config_path,
        )
        if runtime_contracts.get("provider_profile_path") != application.profile_path:
            raise ValueError("Request and OpenAI provider profile paths do not match")
        if runtime_contracts.get("provider_profile_sha256") != application.profile_sha256:
            raise ValueError("OpenAI provider profile changed after request compilation")
        generation = request["generation"]
        expected_transport = (
            application.provider_profile["provider"],
            application.provider_profile["model"],
            application.provider_profile["submission_path"],
        )
        actual_transport = (
            generation.get("provider"),
            generation.get("job_type"),
            generation.get("submission_path"),
        )
        if actual_transport != expected_transport:
            raise ValueError("Request does not match the OpenAI provider profile")
        billing_scope = generation.get("billing_not_applicable")
        if (
            not isinstance(billing_scope, dict)
            or billing_scope.get("scope") != "legacy_higgsfield_credit_accounting"
        ):
            raise ValueError("OpenAI request is missing scoped legacy-credit metadata")

        run_root = _resolve(output_root)
        store = RunStore(run_root)
        provider_config = application.provider_profile
        provider = OpenAIImageProvider(
            run_root / "_openai_provider",
            model=provider_config["model"],
            endpoint=provider_config["endpoint"],
            size=provider_config["size"],
            input_fidelity=provider_config["input_fidelity"],
            output_format=provider_config["output_format"],
            moderation=provider_config["moderation"],
            timeout_seconds=min(
                float(timeout_seconds),
                float(provider_config["timeout_seconds"]),
            ),
        )
        manifest, _ = execute_once(request, provider=provider, store=store)

        evaluator_config = load_json(_resolve(evaluator_config_path))
        evaluator = GeminiQualityEvaluator(
            model=evaluator_config["model"],
            fallback_models=evaluator_config.get("fallback_models", []),
            timeout_seconds=float(evaluator_config["timeout_seconds"]),
            maximum_image_edge=int(evaluator_config["maximum_image_edge"]),
        )
        role_paths = dict(
            zip(
                generation["image_roles"],
                generation["image_paths"],
                strict=True,
            )
        )
        quality = evaluate_and_maybe_repair(
            project_root=root,
            request=request,
            manifest=manifest,
            store=store,
            provider=provider,
            evaluator=evaluator,
            runtime_profile=application.runtime_profile,
            lighting_sheet=lighting,
            original_product_image=role_paths["product_source"],
            container_reference_image=(
                role_paths.get("scene_hint")
                or role_paths.get("container_reference")
            ),
            brand_asset_image=role_paths.get("brand_asset"),
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=0,
            allow_paid_repair=False,
        )
        manifest = quality.manifest
        with Image.open(quality.final_image) as opened:
            output = _pil_to_tensor(opened)
        job = {
            "provider": provider.name,
            "job_id": manifest["provider"]["job_id"],
            "status": manifest["status"],
            "actual_credits": None,
            "total_credits": manifest["cost"].get("total_credits"),
            "billing_not_applicable": generation["billing_not_applicable"],
            "usage": manifest["provider"].get("metadata", {}).get("usage", {}),
            "request_hash": manifest["request_hash"],
            "manifest_path": str(
                store.manifest_path(manifest["request_hash"]).resolve()
            ),
            "repair": manifest.get("repair"),
        }
        return io.NodeOutput(output, dump_json(job), dump_json(manifest))


class ADGeminiQualityOnly(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_GeminiQualityOnly",
            display_name="Gemini QA Only (No Paid Repair)",
            category="ad-creator/quality",
            description="Evaluates a generated image and builds a repair plan without submitting a repair.",
            inputs=[
                io.Image.Input("generated_image"),
                io.String.Input("request_json", force_input=True),
                io.String.Input("lighting_sheet_json", force_input=True),
                io.String.Input("evaluator_config_path", default="configs/evaluator.json"),
            ],
            outputs=[
                io.String.Output(display_name="qa_report_json"),
                io.String.Output(display_name="repair_plan_json"),
                io.String.Output(display_name="quality_status"),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(
        cls,
        generated_image: torch.Tensor,
        request_json: str,
        lighting_sheet_json: str,
        evaluator_config_path: str,
    ) -> io.NodeOutput:
        root = _project_root()
        load_project_env(root)
        request = json.loads(request_json)
        lighting = json.loads(lighting_sheet_json)
        validate_generation_request(request, maximum_credits=2)
        validate_json(lighting, "lighting-sheet.schema.json", project_root=root)
        if request["lighting_sheet"]["id"] != lighting["lighting_sheet_id"]:
            raise ValueError("Request and connected lighting sheet IDs do not match")
        if request["lighting_sheet"]["sha256"] != _json_sha256(lighting):
            raise ValueError("Connected lighting sheet changed after request compilation")

        candidate_path = _save_tensor_input(generated_image, "quality_candidate")
        evaluator_config = load_json(_resolve(evaluator_config_path))
        evaluator = GeminiQualityEvaluator(
            model=evaluator_config["model"],
            fallback_models=evaluator_config.get("fallback_models", []),
            timeout_seconds=float(evaluator_config["timeout_seconds"]),
            maximum_image_edge=int(evaluator_config["maximum_image_edge"]),
        )
        role_paths = dict(
            zip(
                request["generation"]["image_roles"],
                request["generation"]["image_paths"],
                strict=True,
            )
        )
        payload = evaluator.evaluate(
            generated_image=candidate_path,
            original_product_image=role_paths["product_source"],
            request=request,
            lighting_sheet=lighting,
            container_reference_image=(
                role_paths.get("scene_hint")
                or role_paths.get("container_reference")
            ),
        )
        report = normalize_qa_report(
            payload,
            evaluator={
                "provider": evaluator.provider_name,
                "model": evaluator.model_name,
                "mode": evaluator.mode,
            },
            evaluated_image=candidate_path,
            request=request,
            lighting_sheet=lighting,
            project_root=root,
        )
        report, plan = route_repair(report, request=request, project_root=root)
        return io.NodeOutput(
            dump_json(report),
            dump_json(plan),
            report["overall_status"],
            ui={
                "text": (report["overall_status"],),
                "qa_report": (dump_json(report),),
                "repair_plan": (dump_json(plan),),
            },
        )


class ADInstagramCrop(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_InstagramCrop",
            display_name="Instagram 4:5 Crop",
            category=CATEGORY,
            description="Center-crops a provider result to a stable 4:5 delivery frame.",
            inputs=[
                io.Image.Input("image"),
                io.Int.Input("target_width", default=880, min=64, max=4096, step=8),
                io.Int.Input("target_height", default=1100, min=64, max=4096, step=8),
            ],
            outputs=[io.Image.Output(display_name="image_4x5")],
        )

    @classmethod
    def execute(cls, image: torch.Tensor, target_width: int, target_height: int) -> io.NodeOutput:
        height, width = image.shape[1:3]
        target_ratio = 4 / 5
        if width / height > target_ratio:
            crop_width = round(height * target_ratio)
            left = (width - crop_width) // 2
            cropped = image[:, :, left : left + crop_width, :]
        else:
            crop_height = round(width / target_ratio)
            top = (height - crop_height) // 2
            cropped = image[:, top : top + crop_height, :, :]
        resized = functional.interpolate(
            cropped.permute(0, 3, 1, 2),
            size=(target_height, target_width),
            mode="bicubic",
            align_corners=False,
        ).permute(0, 2, 3, 1)
        return io.NodeOutput(resized.clamp(0, 1))


class ADProductBBoxProtectionMask(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_ProductBBoxProtectionMask",
            display_name="Product BBox Protection Mask",
            category=CATEGORY,
            description="Builds a feathered post-crop product mask from the compiled request bbox.",
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.Int.Input("target_width", default=880, min=64, max=8192),
                io.Int.Input("target_height", default=1100, min=64, max=8192),
                io.Float.Input("padding_ratio", default=0.025, min=0.0, max=0.15, step=0.005),
                io.Float.Input("feather_ratio", default=0.02, min=0.0, max=0.1, step=0.005),
            ],
            outputs=[io.Mask.Output(display_name="protection_mask")],
        )

    @classmethod
    def execute(
        cls,
        request_json: str,
        target_width: int,
        target_height: int,
        padding_ratio: float,
        feather_ratio: float,
    ) -> io.NodeOutput:
        request = json.loads(request_json)
        bbox = request["sampled_parameters"]["subject_bbox"]
        left, top, right, bottom = (
            float(bbox["left"]),
            float(bbox["top"]),
            float(bbox["right"]),
            float(bbox["bottom"]),
        )
        source_w, source_h = (
            float(value) for value in request["generation"]["aspect_ratio"].split(":")
        )
        source_ratio = source_w / source_h
        target_ratio = target_width / target_height
        if source_ratio < target_ratio:
            retained = source_ratio / target_ratio
            crop_top = (1.0 - retained) / 2.0
            top = (top - crop_top) / retained
            bottom = (bottom - crop_top) / retained
        elif source_ratio > target_ratio:
            retained = target_ratio / source_ratio
            crop_left = (1.0 - retained) / 2.0
            left = (left - crop_left) / retained
            right = (right - crop_left) / retained

        left = max(0.0, left - padding_ratio)
        top = max(0.0, top - padding_ratio)
        right = min(1.0, right + padding_ratio)
        bottom = min(1.0, bottom + padding_ratio)
        x = (torch.arange(target_width, dtype=torch.float32) + 0.5) / target_width
        y = (torch.arange(target_height, dtype=torch.float32) + 0.5) / target_height
        grid_y, grid_x = torch.meshgrid(y, x, indexing="ij")
        feather = max(float(feather_ratio), 1.0 / max(target_width, target_height))
        mask = torch.minimum(
            torch.minimum((grid_x - left) / feather, (right - grid_x) / feather),
            torch.minimum((grid_y - top) / feather, (bottom - grid_y) / feather),
        ).clamp(0.0, 1.0)
        return io.NodeOutput(mask.unsqueeze(0))


class ADApplyMoodGrade(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_ApplyMoodGrade",
            display_name="Apply Mood Grade",
            category=CATEGORY,
            description="Applies a deterministic mood grade at a user-selectable strength.",
            inputs=[
                io.Image.Input("image"),
                io.String.Input("mood_json", force_input=True),
                io.Combo.Input("strength", options=list(GRADE_STRENGTHS), default="natural"),
                io.Mask.Input("protection_mask", optional=True),
            ],
            outputs=[
                io.Image.Output(display_name="graded_image"),
                io.String.Output(display_name="metrics_json"),
            ],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        mood_json: str,
        strength: str,
        protection_mask: torch.Tensor | None = None,
    ) -> io.NodeOutput:
        mood = json.loads(mood_json)
        profile = load_json(_resolve(mood["grade_profile_path"]))
        lighting = load_json(_resolve(mood["lighting_sheet_path"]))
        amount = resolve_grade_strengths(lighting)[strength]
        output_tensors = []
        metrics = []
        for index, frame in enumerate(image):
            mask_image = None
            if protection_mask is not None:
                mask_index = min(index, protection_mask.shape[0] - 1)
                mask_array = (
                    protection_mask[mask_index]
                    .detach()
                    .to(device="cpu", dtype=torch.float32)
                    .clamp(0, 1)
                    .numpy()
                )
                mask_image = Image.fromarray(np.rint(mask_array * 255).astype(np.uint8), mode="L")
            graded = apply_grade(
                _tensor_to_pil(frame),
                profile=profile,
                strength=amount,
                protection_mask=mask_image,
            )
            output_tensors.append(_pil_to_tensor(graded)[0])
            metrics.append(image_metrics(graded))
        report = {
            "grade_profile_id": profile["grade_profile_id"],
            "strength_name": strength,
            "strength": amount,
            "protection_mask_connected": protection_mask is not None,
            "images": metrics,
        }
        return io.NodeOutput(torch.stack(output_tensors), dump_json(report))


class ADSaveRunManifest(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AD_SaveRunManifest",
            display_name="Save Run Manifest",
            category=CATEGORY,
            description="Persists request, provider job, cost and grade metrics without credentials.",
            inputs=[
                io.String.Input("request_json", force_input=True),
                io.String.Input("job_json", force_input=True),
                io.String.Input("metrics_json", force_input=True),
                io.String.Input("output_label", default="ad_creator/local_validation"),
            ],
            outputs=[
                io.String.Output(display_name="manifest_path"),
                io.String.Output(display_name="manifest_json"),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(
        cls,
        request_json: str,
        job_json: str,
        metrics_json: str,
        output_label: str,
    ) -> io.NodeOutput:
        request = json.loads(request_json)
        job = json.loads(job_json)
        metrics = json.loads(metrics_json)
        digest = request_hash(request)
        if job["request_hash"] != digest:
            raise ValueError("Provider job and generation request hashes do not match")
        store = RunStore(_project_root() / "outputs/comfyui-local/runs")
        now = datetime.now(timezone.utc).isoformat()
        if job.get("manifest_path"):
            manifest_path = Path(job["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            store = RunStore(manifest_path.parents[1])
            if manifest["request_hash"] != digest:
                raise ValueError("Core manifest and generation request hashes do not match")
        else:
            manifest, _ = store.prepare(request, job["provider"])
            manifest["provider"].update(
                {
                    "name": job["provider"],
                    "job_id": job["job_id"],
                    "status": job["status"],
                    "submit_started": True,
                    "metadata": {
                        "fixture": job.get("fixture", "input_passthrough"),
                        "comfyui_v3_node": "AD_FakeGenerate",
                    },
                }
            )
            manifest["cost"]["actual_credits"] = job["actual_credits"]
            manifest["status"] = "completed"
        manifest["metrics"]["post_grade"] = metrics
        manifest["artifacts"]["comfyui_output_prefix"] = output_label
        if manifest["status"] == "quality_passed":
            manifest["status"] = "completed"
        if not any(event["type"] == "comfyui_completed" for event in manifest["events"]):
            manifest["events"].append({"at": now, "type": "comfyui_completed", "job_id": job["job_id"]})
        store.save(manifest)
        store.record_cost_once(manifest)
        validate_json(manifest, "run-manifest.schema.json", project_root=_project_root())
        path = store.manifest_path(digest).resolve()
        return io.NodeOutput(
            str(path),
            dump_json(manifest),
            ui={"text": (str(path),), "manifest": (dump_json(manifest),)},
        )


class AdCreatorExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            ADLoadMoodPackage,
            ADLoadPresetControlBoard,
            ADLoadPresetWoodMaterial,
            ADGeminiProductAnalyze,
            ADGeminiProductAnalyzeV3,
            ADLoadReviewedProductAnalysisV2,
            ADLoadReviewedProductAnalysisV3,
            ADResolveSceneReference,
            ADResolveReferenceSceneGraph,
            ADLoadBoundSceneGraphV3,
            ADCreateProductSpec,
            ADAssembleProductSet,
            ADResolveReferenceContracts,
            ADBuildMultiProductSceneRequest,
            ADSaveV3RequestArtifact,
            ADAttachDiagnosticPilotAuthorization,
            ADMultiProductQualityRoute,
            ADV3ImageQualityRoute,
            ADRestoreSingleProductBrandV3,
            ADBuildGenerationRequest,
            ADBuildSceneGenerationRequest,
            ADFakeGenerate,
            ADFakeQualityRoute,
            ADHiggsfieldGenerate,
            ADOpenAIImageGenerate,
            ADGeminiQualityOnly,
            ADInstagramCrop,
            ADProductBBoxProtectionMask,
            ADApplyMoodGrade,
            ADSaveRunManifest,
        ]
