from __future__ import annotations

import base64
import io
import json
import os
import ssl
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

import certifi
from PIL import Image, ImageOps

from ..gemini_api import GeminiInteractionsClient, GeminiRateLimitError
from ..qa import qa_check_codes


class EvaluatorUnavailable(RuntimeError):
    pass


class EvaluatorError(RuntimeError):
    pass


Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _check_schema(check_codes: Sequence[str]) -> dict[str, Any]:
    # A property per check duplicates the same nested schema up to 16 times and
    # exceeds Gemini Flash Lite's structured-output complexity limit. Keep the
    # wire schema shallow, then canonicalize this array to the service's map.
    return {
        "type": "object",
        "properties": {
            "checks": {
                "type": "array",
                "minItems": len(check_codes),
                "maxItems": len(check_codes),
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "enum": list(check_codes)},
                        "status": {
                            "type": "string",
                            "enum": ["pass", "warning", "fail"],
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "evidence": {
                            "type": "string",
                        },
                        "measurements_json": {"type": "string"},
                    },
                    "required": [
                        "code",
                        "status",
                        "confidence",
                        "evidence",
                        "measurements_json",
                    ],
                },
            }
        },
        "required": ["checks"],
    }


def _canonicalize_checks(
    payload: dict[str, Any],
    *,
    expected_codes: Sequence[str],
) -> dict[str, Any]:
    raw_checks = payload.get("checks")
    if isinstance(raw_checks, dict):
        return payload
    if not isinstance(raw_checks, list):
        raise EvaluatorError("Gemini evaluator result must contain checks")

    checks: dict[str, Any] = {}
    for item in raw_checks:
        if not isinstance(item, dict):
            raise EvaluatorError("Gemini evaluator check must be an object")
        code = item.get("code")
        if not isinstance(code, str) or code not in expected_codes:
            raise EvaluatorError(f"Gemini evaluator returned an unknown check code: {code}")
        if code in checks:
            raise EvaluatorError(f"Gemini evaluator returned duplicate check code: {code}")
        evidence = item.get("evidence")
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, list) or not evidence:
            raise EvaluatorError(f"Gemini evaluator returned invalid evidence for {code}")

        measurements = item.get("measurements")
        if not isinstance(measurements, dict):
            raw_measurements = item.get("measurements_json", "{}")
            try:
                measurements = json.loads(raw_measurements)
            except (TypeError, json.JSONDecodeError) as exc:
                raise EvaluatorError(
                    f"Gemini evaluator returned invalid measurements JSON for {code}"
                ) from exc
        if not isinstance(measurements, dict):
            raise EvaluatorError(f"Gemini evaluator measurements must be an object for {code}")
        checks[code] = {
            "status": item.get("status"),
            "confidence": item.get("confidence"),
            "evidence": evidence,
            "measurements": measurements,
        }

    missing = [code for code in expected_codes if code not in checks]
    if missing:
        raise EvaluatorError(f"Gemini evaluator omitted check codes: {missing}")
    return {**payload, "checks": checks}


class GeminiQualityEvaluator:
    provider_name = "gemini_interactions"
    mode = "live"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        fallback_models: Sequence[str] | None = None,
        timeout_seconds: float = 120,
        maximum_image_edge: int = 1280,
        transport: Transport | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model or os.environ.get(
            "GEMINI_EVALUATOR_MODEL", "gemini-3.1-flash-lite"
        )
        configured_fallbacks = (
            list(fallback_models)
            if fallback_models is not None
            else ["gemini-2.5-flash-lite"]
        )
        self.model_candidates = tuple(
            dict.fromkeys([self.model_name, *configured_fallbacks])
        )
        self.last_rate_limit_errors: tuple[GeminiRateLimitError, ...] = ()
        self.timeout_seconds = timeout_seconds
        self.maximum_image_edge = maximum_image_edge
        self._transport = transport or self._post

    def _post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            tls_context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=tls_context,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                retry_after_header = (
                    exc.headers.get("Retry-After") if exc.headers is not None else None
                )
                raise GeminiInteractionsClient._parse_rate_limit(
                    body,
                    model=None,
                    retry_after_header=retry_after_header,
                ) from exc
            raise EvaluatorError(f"Gemini evaluator HTTP {exc.code}: {body[:1000]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EvaluatorError(f"Gemini evaluator request failed: {exc}") from exc

    def _image_content(self, path: str | Path) -> dict[str, str]:
        image_path = Path(path)
        if not image_path.is_file():
            raise FileNotFoundError(f"Evaluator image does not exist: {image_path}")
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail(
                (self.maximum_image_edge, self.maximum_image_edge),
                Image.Resampling.LANCZOS,
            )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90, optimize=True)
        return {
            "type": "image",
            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "mime_type": "image/jpeg",
        }

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        fragments: list[str] = []
        for step in payload.get("steps", []):
            if step.get("type") != "model_output":
                continue
            for content in step.get("content", []):
                if content.get("type") == "text" and isinstance(content.get("text"), str):
                    fragments.append(content["text"])
        if not fragments:
            raise EvaluatorError("Gemini evaluator response contained no text output")
        return "".join(fragments)

    def evaluate(
        self,
        *,
        generated_image: str | Path,
        original_product_image: str | Path,
        request: dict[str, Any],
        lighting_sheet: dict[str, Any],
        container_reference_image: str | Path | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise EvaluatorUnavailable(
                "GEMINI_API_KEY is not configured; semantic QA cannot safely trigger paid repair"
            )
        container_mode = request["identity_policy"]["container"]
        reference_control = request.get("reference_control") or {
            "role": "container_design_only",
            "container_design_source": "reference",
        }
        reference_control_role = reference_control.get(
            "role", "container_design_only"
        )
        container_design_source = reference_control.get(
            "container_design_source", "reference"
        )
        if (
            container_mode == "adopt_reference"
            and reference_control_role != "structured_only"
            and not container_reference_image
        ):
            raise ValueError(
                f"{reference_control_role} QA requires its declared reference control image"
            )
        identity = request["product_analysis"]["identity"]
        final_brand = request.get("target_brand_contract") or request.get(
            "brand_contract", {}
        )
        logo = (
            final_brand.get("allowed_main_text")
            if final_brand.get("state") == "verified_present"
            else None
        )
        thresholds = lighting_sheet["shadow_contract"]["qa_ratios"]
        composition = request["sampled_parameters"]["subject_bbox"]
        scene_graph_contract = request.get("scene_graph_contract")
        check_codes = qa_check_codes(request)
        wood_closeup = request.get("preset_id") == "instagram_wood_calm_window_closeup_v1"
        authorized_non_brand_text = (
            ["CAFE AMERICANO", "cafe"]
            if wood_closeup and container_mode == "adopt_reference"
            else ["CAFE AMERICANO"] if wood_closeup else []
        )
        context = {
            "beverage": identity["beverage"],
            "logo_text": logo,
            "logo_text_authority": (
                "final target brand contract; do not replace it with OCR from Image 2"
                if logo
                else "final target is verified unbranded"
            ),
            "authorized_non_brand_text": authorized_non_brand_text,
            "container_mode": container_mode,
            "container_design": request.get("container_design"),
            "reference_control_role": reference_control_role,
            "container_design_source": container_design_source,
            "target_product_bbox": composition,
            "negative_space_ratio": request["sampled_parameters"]["negative_space_ratio"],
            "lighting_sheet_id": lighting_sheet["lighting_sheet_id"],
            "lighting_source": lighting_sheet["key_light"],
            "qa_ratio_thresholds": thresholds,
            "spatial_depth_contract": request.get("capture_contract", {}).get(
                "spatial_depth"
            ),
            "scene_graph_contract": scene_graph_contract,
        }
        scene_rules = ""
        if scene_graph_contract is not None:
            scene_rules = """
- scene_slot_adherence compares the bound user product against its target_bbox and fails when it is missing, assigned to a different slot, or materially intrudes into another active slot.
- scene_subject_count compares visible beverage and dessert counts with slot_plan actions: bind_product and genericize are active; remove is absent.
- scene_support_contact verifies that every active subject, including props, rests on its specified support surface without floating, sinking, or impossible contact. A plant assigned to the white window sill fails if it emerges from a frame seam, rail, crack, gap, cup or table instead.
- scene_relational_consistency verifies left/right, front/behind, overlap, depth order, occlusion and shared shadow logic against the compact relations and slot plan.
- Record normalized observed bboxes, active subject counts and violated slot IDs in measurements whenever estimable.
"""
        if reference_control_role == "structured_only":
            control_image_rule = (
                "- No Image 3 is expected. In adopt_reference mode, validate the newly rendered cup "
                "against context.container_design alone; do not require pixel similarity to an image.\n"
                "- reference_brand_leakage fails for any invented text, logo or pseudo-branding."
            )
            image_three_description = "No Image 3 is supplied."
        elif reference_control_role == "sanitized_scene_hint":
            design_rule = (
                "Preserve the complete product and container from Image 2 while requiring new scene-native optics, perspective, reflections, contacts and shadows; Image 3 must not redesign it."
                if container_mode == "preserve_source"
                else (
                    "Compare abstract cup design features with Image 2 while requiring new scene-native optics, perspective, reflections and edges; pixel or outline similarity is neither required nor desirable."
                    if container_design_source == "source"
                    else "Use context.container_design as the final cup-design authority; Image 3 may support only its low-frequency assembly occupancy."
                )
            )
            control_image_rule = (
                "- Image 3 is a sanitized photographic scene hint. Evaluate only the low-frequency "
                "camera scale, active-slot relations, support contacts, negative-space rhythm, broad "
                "palette and light topology declared by context.scene_graph_contract. Do not treat "
                "Image 3 as a container-only reference or require undeclared A6-specific objects.\n"
                f"- {design_rule}\n"
                "- reference_brand_leakage fails if Image 3 text, branding, beverage identity, exact "
                "pixels, exact object identity or identifiable background detail is copied. Transferring "
                "only its declared spatial relationships, support geometry, palette and light topology "
                "is required, not leakage."
            )
            image_three_description = "Image 3 is a sanitized photographic scene hint."
        else:
            control_image_rule = (
                "- In adopt_reference mode, a pass requires the generated silhouette and ratio to be "
                "perceptually closer to Image 3 than Image 2; do not pass merely because all images contain a glass.\n"
                "- reference_brand_leakage fails if any Image 3 brand, beverage, prop, background or arrangement leaks into Image 1."
            )
            image_three_description = "Image 3, when present, is a container-design reference only."
        prompt = f"""You are a strict visual QA evaluator for a cafe photo-restyling service.
Image 1 is the generated result. Image 2 is the user's original product identity source. {image_three_description}
Evaluate all required checks independently against this machine contract:
{json.dumps(context, ensure_ascii=False, indent=2)}

Rules:
- pass means clearly compliant; warning means a small usable deviation; fail means a clear contract breach.
- Confidence is confidence in the status, not a beauty score. Do not use fail when evidence is ambiguous.
- beverage_identity compares drink category, color, layers, toppings and ice to Image 2.
- container_policy preserves Image 2 container in preserve_source mode. In adopt_reference mode, compare Image 1 against context.container_design: material, class, silhouette, rim/lid/sleeve components and height-to-width range are required, while reference color, glaze, decoration and exact pixels are not unless explicitly present in that contract. A newly regenerated unbranded cup is expected, not a failure.
- In adopt_reference mode, estimate the generated cup body's physical pixel height-to-width ratio, excluding straw, garnish, foam, hand and cast shadow. Record it as measurements.generated_height_to_width_ratio and record the contract range as measurements.target_height_to_width_ratio.
{control_image_rule}
- logo_text evaluates branding only, not authorized editorial scene copy. context.logo_text is the authoritative brand contract; never replace it using OCR from Image 2. Text listed in context.authorized_non_brand_text is required design copy and is not a logo: when no other brand-like mark exists, record measurements_json.generated_logo_text=null and measurements_json.brand_detected=false. In the wood close-up preset also verify CAFE AMERICANO on the curved rear paper cup; verify lowercase cafe plus tiny English body copy on the primary rectangular paper label only in adopt_reference mode, and verify that primary label is absent in preserve_source mode. Any other readable phrase is a fail.
- product_composition measures the cup-body bbox in normalized 0..1 coordinates, excluding hand and straw, and compares position, scale and negative space.
- wrist_exposure uses the exact measurement key wrist_length_to_cup_height when estimable.
- cast_shadow uses the exact measurement key cast_area_to_cup_bbox when estimable.
- transmitted_light uses the exact measurement key transparent_lift_inside_shadow only for transparent glass or clear plastic. Opaque ceramic, paper, metal and stone containers require no through-body transmitted light and should pass when their opacity is physically correct.
- contact_shadow, cast_shadow and transmitted_light use selected lighting-sheet ratios relative to the cup bbox, never fixed pixels.
- lighting_physical_consistency checks that highlights, reflections, transmitted light and shadows describe one source. For transparent products, fail pasted/sticker appearance unless the window source passes coherently through cup wall, irregular ice and translucent liquid, milk scattering and fruit color bleed remain local, condensation interrupts highlights, and the base shares table bounce plus attached contact and cast shadow.
- smartphone_naturalness rejects studio/catalog/CGI appearance, malformed hand anatomy and overprocessed HDR. When spatial_depth_contract is present, it also fails uniform blur, portrait cutout edges, DSLR-like razor-thin focus, or missing physical plane and distance cues.
{scene_rules}
- Return one concise visible-fact evidence string per check. measurements_json must be a JSON object encoded as a string; include normalized ratios or bounding boxes when estimable, otherwise use "{{}}".
Return only the requested JSON structure."""
        inputs: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "text", "text": "Image 1: generated result"},
            self._image_content(generated_image),
            {"type": "text", "text": "Image 2: original product identity source"},
            self._image_content(original_product_image),
        ]
        if container_reference_image:
            inputs.extend(
                [
                    {"type": "text", "text": image_three_description},
                    self._image_content(container_reference_image),
                ]
            )
        response: dict[str, Any] | None = None
        rate_limit_errors: list[GeminiRateLimitError] = []
        for candidate in self.model_candidates:
            payload = {
                "model": candidate,
                "input": inputs,
                "generation_config": {"thinking_level": "low"},
                "response_format": {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": _check_schema(check_codes),
                },
            }
            try:
                response = self._transport(
                    "https://generativelanguage.googleapis.com/v1beta/interactions",
                    {"Content-Type": "application/json", "x-goog-api-key": self.api_key},
                    payload,
                )
            except GeminiRateLimitError as exc:
                if exc.model is None:
                    exc.model = candidate
                rate_limit_errors.append(exc)
                continue
            self.model_name = candidate
            break
        self.last_rate_limit_errors = tuple(rate_limit_errors)
        if response is None:
            models = ", ".join(error.model or "unknown" for error in rate_limit_errors)
            raise EvaluatorError(
                f"Gemini evaluator model candidates exhausted by rate limits: {models}"
            )
        try:
            result = json.loads(self._output_text(response))
        except json.JSONDecodeError as exc:
            raise EvaluatorError("Gemini evaluator returned invalid structured JSON") from exc
        if not isinstance(result, dict):
            raise EvaluatorError("Gemini evaluator result must be a JSON object")
        return _canonicalize_checks(result, expected_codes=check_codes)
