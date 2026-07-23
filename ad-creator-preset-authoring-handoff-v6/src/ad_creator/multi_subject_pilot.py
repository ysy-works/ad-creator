from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .jsonio import load_json
from .multi_pipeline import prepare_multi_product_request
from .prompting import create_product_spec


A6_REFERENCE_ID = "ref_381224f47976e566"
B3_REFERENCE_ID = "ref_7c0c3fe1ce76794e"
A6_SCENE_GRAPH_PATH = (
    "data/reference-library/scene-graphs-v2/ref_381224f47976e566_relational_v4.json"
)
B3_SCENE_GRAPH_PATH = (
    "data/reference-library/scene-graphs-v2/ref_7c0c3fe1ce76794e.json"
)
A6_MOOD_PACKAGE_PATH = (
    "presets/moods/tokyo_a6_relational_scene_hint_v4/mood-package.json"
)
B3_MOOD_PACKAGE_PATH = (
    "presets/moods/tokyo_pale_wood_book_single_v2/mood-package.json"
)


PRODUCTS = (
    {
        "product_id": "p01_matcha_branded",
        "source_image": ".tools/ComfyUI/input/ad_creator_original_input_01.jpg",
        "analysis_path": (
            "outputs/v3-quality-matrix-4x5/product-analysis/p01_matcha_brand.json"
        ),
        "description": (
            "exact iced matcha latte with pale-green and milk marbling, visible "
            "ice and its verified source brand"
        ),
        "target_slot_id": "beverage_secondary",
    },
    {
        "product_id": "p02_strawberry_milk_unbranded",
        "source_image": ".tools/ComfyUI/input/ad_creator_original_input_02.jpg",
        "analysis_path": (
            "outputs/v3-quality-matrix-4x5/product-analysis/p02_strawberry_plain.json"
        ),
        "description": (
            "exact cold unbranded strawberry milk with irregular red side layers, "
            "diced strawberry and one mint leaf topping"
        ),
        "target_slot_id": "beverage_primary",
    },
    {
        "product_id": "p04_marbled_latte_unbranded",
        "source_image": ".tools/ComfyUI/input/다운로드.jpeg",
        "analysis_path": (
            "outputs/v3-quality-matrix-4x5/product-analysis/p04_marbled_latte.json"
        ),
        "description": (
            "exact iced unbranded coffee-and-milk drink with dark top, white base, "
            "vertical marbling and large irregular clear ice"
        ),
        "target_slot_id": "beverage_tertiary",
    },
)


REQUIRED_PROMPT_AUTHORITIES = {
    "style_primary_authority": "[PHOTOGRAPHIC STYLE CONTRACT - PRIMARY AUTHORITY]",
    "camera_geometry": "[CAMERA GEOMETRY - HARD LOCK]",
    "composition_geometry": "[COMPOSITION GEOMETRY - HARD LOCK]",
    "controlled_variation": "[CONTROLLED VARIATION - ANTI-TEMPLATE]",
    "lighting_geometry": "[LIGHT ON SCREEN - HARD LOCK]",
    "tone_and_finish": "[COLOR, TONE AND FINISH - HARD LOCK]",
    "native_product_integration": "[PRODUCT-SCENE INTEGRATION - HARD LOCK]",
    "no_source_boundary_reuse": "never reuse source boundary or shading",
    "anti_sticker": "Reject any sticker, pasted cutout, white fringe",
    "topology_only_scene_graph": (
        "topology-only; camera comes exclusively from the photographic style contract"
    ),
    "matcha_iced": "serving-contract={temperature=iced, ice=present",
    "strawberry_cold": "serving-contract={temperature=cold, ice=absent",
    "strawberry_topping": "toppings=required, side-visibility=required",
    "latte_identity": "P3 p04_marbled_latte_unbranded",
    "verified_matcha_brand": 'render only exact target text "ATWOSOME PLACE"',
    "unbranded_products": (
        "target is unbranded; render no text, logo, label, symbol or pseudo-brand"
    ),
    "three_exact_products": "Exactly 3 user products must remain recognizable",
    "sanitized_reference_only": (
        "The sanitized non-identifying control board may supply only abstract camera geometry"
    ),
}

FORBIDDEN_PROMPT_CONFLICTS = {
    "legacy_reference_camera": "camera=slightly_above/downward/phone_normal",
    "smartphone_goal": "[NATURAL SMARTPHONE CAFE PHOTO",
}


def _rooted(root: Path, value: str) -> Path:
    return (root / value).resolve()


def _selection_manifest(root: Path) -> dict[str, Any]:
    path = root / "configs/validation/experimental-reference-candidates-v1.json"
    value = load_json(path)
    if value.get("selection_status") != "selected" or value.get(
        "selected_candidates"
    ) != {"A": "A6", "B": "B3"}:
        raise ValueError("Multi-subject pilot requires the user-selected A6/B3 manifest")
    return value


def build_product_specs(
    project_root: str | Path,
    *,
    container_modes: Mapping[str, str],
    automatic_targets: bool = False,
) -> list[dict[str, Any]]:
    root = Path(project_root).resolve()
    expected_ids = {item["product_id"] for item in PRODUCTS}
    if set(container_modes) != expected_ids:
        raise ValueError("Every exact product requires one explicit container mode")
    specs: list[dict[str, Any]] = []
    for item in PRODUCTS:
        source = _rooted(root, item["source_image"])
        analysis = load_json(_rooted(root, item["analysis_path"]))
        specs.append(
            create_product_spec(
                product_id=item["product_id"],
                product_kind="beverage",
                source_image=str(source),
                description=item["description"],
                target_slot_id=("auto" if automatic_targets else item["target_slot_id"]),
                placement_mode="replace",
                container_policy=container_modes[item["product_id"]],
                product_analysis=analysis,
            )
        )
    return specs


def _prepare(
    root: Path,
    *,
    scene_graph_path: str,
    mood_package_path: str = A6_MOOD_PACKAGE_PATH,
    products: list[dict[str, Any]],
    seed: int,
    curated_preset: str | None = None,
) -> dict[str, Any]:
    graph = load_json(_rooted(root, scene_graph_path))
    if curated_preset is not None:
        graph = _curate_three_product_graph(graph, preset=curated_preset)
    return prepare_multi_product_request(
        project_root=root,
        mood_package_path=mood_package_path,
        products=products,
        scene_graph=graph,
        seed=seed,
        tier="default",
        unbound_slot_policy="remove",
    )


def _bbox(left: float, top: float, right: float, bottom: float) -> dict[str, Any]:
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "confidence": 0.98,
    }


def _curated_object(
    template: Mapping[str, Any],
    *,
    slot_id: str,
    role: str,
    bbox: tuple[float, float, float, float],
    description: str,
    container: Mapping[str, Any],
    depth_order: int,
) -> dict[str, Any]:
    value = copy.deepcopy(dict(template))
    box = _bbox(*bbox)
    value.update(
        {
            "slot_id": slot_id,
            "role": role,
            "kind": "beverage",
            "description": description,
            "container": copy.deepcopy(dict(container)),
            "body_bbox": box,
            "full_bbox": copy.deepcopy(box),
            "depth_order": depth_order,
            "interaction": "resting",
            "occlusion_fraction": 0.0,
            "replaceable": True,
            "crop_safe": True,
            "allowed_kinds": ["beverage", "dessert"],
            "support_surface_id": "surface_table",
            "brand_or_watermark_state": "absent",
            "visible_text": [],
            "straw": {
                "present": False,
                "bbox": None,
                "centerline": None,
                "emergence_point": None,
                "angle_degrees": None,
            },
        }
    )
    return value


def _curate_three_product_graph(
    source: Mapping[str, Any],
    *,
    preset: str,
) -> dict[str, Any]:
    """Convert a selected reference into a non-copying three-product layout contract.

    A6 contributes cafe depth and window direction, not its centered round tray.
    B3 contributes pale wood, quiet wall and diffuse light, not its book or solo layout.
    """

    graph = copy.deepcopy(dict(source))
    templates = graph["objects"]
    if not templates:
        raise ValueError("Curated multi-product graph requires a source object template")
    primary_template = templates[0]
    if preset == "a6_asymmetric_depth_v2":
        secondary_template = next(
            (item for item in templates if item.get("slot_id") == "beverage_secondary"),
            primary_template,
        )
        tertiary_template = next(
            (item for item in templates if item.get("slot_id") == "beverage_tertiary"),
            primary_template,
        )
        objects = [
            _curated_object(
                primary_template,
                slot_id="beverage_primary",
                role="primary",
                bbox=(0.55, 0.50, 0.70, 0.75),
                description="open cold-service clear curved glass on the cafe table",
                container={
                    "class": "open glass tumbler",
                    "material": "clear glass",
                    "silhouette": "gently curved cylindrical",
                    "components": ["wide open rim", "clear glass body"],
                },
                depth_order=2,
            ),
            _curated_object(
                secondary_template,
                slot_id="beverage_secondary",
                role="secondary",
                bbox=(0.36, 0.39, 0.49, 0.68),
                description="narrow stoppered glass bottle position retained only as a compatibility guard",
                container={
                    "class": "glass bottle",
                    "material": "clear glass",
                    "silhouette": "narrow neck bottle",
                    "components": ["cork stopper", "narrow neck"],
                },
                depth_order=1,
            ),
            _curated_object(
                tertiary_template,
                slot_id="beverage_tertiary",
                role="secondary",
                bbox=(0.17, 0.56, 0.34, 0.80),
                description="open cold-service clear cylindrical glass on the cafe table",
                container={
                    "class": "open glass tumbler",
                    "material": "clear glass",
                    "silhouette": "straight cylindrical",
                    "components": ["wide open rim", "clear glass body"],
                },
                depth_order=3,
            ),
        ]
        relations = [
            {
                "from_slot_id": "beverage_tertiary",
                "predicate": "left_of",
                "to_slot_id": "beverage_secondary",
                "confidence": 0.96,
            },
            {
                "from_slot_id": "beverage_secondary",
                "predicate": "left_of",
                "to_slot_id": "beverage_primary",
                "confidence": 0.96,
            },
            {
                "from_slot_id": "beverage_tertiary",
                "predicate": "in_front_of",
                "to_slot_id": "beverage_secondary",
                "confidence": 0.90,
            },
            {
                "from_slot_id": "beverage_primary",
                "predicate": "in_front_of",
                "to_slot_id": "beverage_secondary",
                "confidence": 0.86,
            },
        ]
        graph["composition"].update(
            {
                "asymmetry_source": "unequal_depth_and_spacing",
                "camera_height": "slightly_above",
                "camera_pitch": "slight_down",
                "crop_character": "loose",
                "lens_character": "phone_mild_tele",
                "negative_space": "upper_room_and_right_field",
                "subject_position": "lower_left_asymmetric",
            }
        )
        graph["depth"].update(
            {
                "foreground": "front_table_product",
                "midground": "two_staggered_table_products",
                "product_plane": "direct_table_contacts",
                "perspective_cues": ["unequal_scale", "base_offsets", "table_recession"],
            }
        )
        graph["taxonomy"].update(
            {"scene_complexity": "set", "scene_complexity": "set"}
        )
        support_description = "pale matte cafe table without a tray, board, coaster or saucer"
    elif preset == "b3_quiet_wall_v1":
        clear_container = {
            "class": "open glass tumbler",
            "material": "clear glass",
            "silhouette": "straight cylindrical",
            "components": ["thin open rim", "clear glass body", "flat base"],
        }
        objects = [
            _curated_object(
                primary_template,
                slot_id="beverage_primary",
                role="primary",
                bbox=(0.55, 0.69, 0.69, 0.89),
                description="open cold-service clear cylindrical glass on pale oak",
                container=clear_container,
                depth_order=2,
            ),
            _curated_object(
                primary_template,
                slot_id="beverage_secondary",
                role="secondary",
                bbox=(0.34, 0.60, 0.47, 0.84),
                description="open cold-service clear cylindrical glass on pale oak",
                container=clear_container,
                depth_order=1,
            ),
            _curated_object(
                primary_template,
                slot_id="beverage_tertiary",
                role="secondary",
                bbox=(0.14, 0.67, 0.29, 0.88),
                description="open cold-service clear cylindrical glass on pale oak",
                container=clear_container,
                depth_order=2,
            ),
        ]
        relations = [
            {
                "from_slot_id": "beverage_tertiary",
                "predicate": "left_of",
                "to_slot_id": "beverage_secondary",
                "confidence": 0.97,
            },
            {
                "from_slot_id": "beverage_secondary",
                "predicate": "left_of",
                "to_slot_id": "beverage_primary",
                "confidence": 0.97,
            },
            {
                "from_slot_id": "beverage_secondary",
                "predicate": "behind",
                "to_slot_id": "beverage_primary",
                "confidence": 0.84,
            },
        ]
        graph["composition"].update(
            {
                "asymmetry_source": "unequal_spacing_and_base_height",
                "camera_height": "product_level",
                "camera_pitch": "slight_down",
                "crop_character": "wide",
                "lens_character": "phone_mild_tele",
                "negative_space": "large_quiet_wall",
                "subject_position": "lower_left_to_midfield",
            }
        )
        graph["depth"].update(
            {
                "foreground": "pale_oak_table_edge",
                "midground": "three_small_staggered_products",
                "background": "warm_neutral_white_wall",
                "product_plane": "direct_table_contacts",
                "perspective_cues": ["unequal_scale", "base_offsets", "table_edge"],
                "plane_count": 3,
                "far_plane_softness": "subtle",
                "atmospheric_separation": "mild",
            }
        )
        graph["taxonomy"].update(
            {"scene_complexity": "set", "camera_angle": "eye_level"}
        )
        support_description = "pale low-saturation oak table without a book, tray, coaster or decorative prop"
    else:
        raise ValueError(f"Unknown curated multi-product preset: {preset}")

    graph["objects"] = objects
    graph["relations"] = relations
    graph["support_surfaces"] = [
        {
            "surface_id": "surface_table",
            "kind": "table",
            "plane_description": support_description,
            "bbox": _bbox(0.0, 0.42 if preset.startswith("a6") else 0.58, 1.0, 1.0),
            "perspective_scale": [0.92, 1.08],
            "supports_objects": True,
        }
    ]
    graph["protected_regions"] = []
    graph["insertion_zones"] = []
    graph["object_inventory_complete"] = True
    graph["observed_major_subject_count"] = 3
    graph["scene_mode"] = "set"
    graph["runtime_policy"].update(
        {
            "maximum_exact_products": 3,
            "maximum_generic_companions": 1,
            "maximum_major_subjects": 3,
            "maximum_props": 2,
            "scene_pixels_allowed": False,
            "container_pixels_allowed": True,
        }
    )
    graph["analysis_metadata"].update(
        {
            "provider": "manual_contract_curation",
            "model": "local_human_review_v2",
            "prompt_version": "reference_scene_graph_v2",
            "confidence": 0.99,
        }
    )
    return graph


def prepare_a6_multi_subject_pilot(
    project_root: str | Path,
    *,
    seed: int = 713,
) -> dict[str, Any]:
    """Build two canonical three-product requests and expected rejection evidence."""

    root = Path(project_root).resolve()
    selection = _selection_manifest(root)
    preserve_modes = {item["product_id"]: "preserve_source" for item in PRODUCTS}
    hybrid_modes = {
        "p01_matcha_branded": "preserve_source",
        "p02_strawberry_milk_unbranded": "adopt_reference",
        "p04_marbled_latte_unbranded": "preserve_source",
    }
    all_adopt_modes = {item["product_id"]: "adopt_reference" for item in PRODUCTS}

    requests = {
        "a6_3exact_preserve": _prepare(
            root,
            scene_graph_path=A6_SCENE_GRAPH_PATH,
            mood_package_path=A6_MOOD_PACKAGE_PATH,
            products=build_product_specs(root, container_modes=preserve_modes),
            seed=seed,
            curated_preset="a6_asymmetric_depth_v2",
        ),
        "a6_3exact_compatible_hybrid": _prepare(
            root,
            scene_graph_path=A6_SCENE_GRAPH_PATH,
            mood_package_path=A6_MOOD_PACKAGE_PATH,
            products=build_product_specs(root, container_modes=hybrid_modes),
            seed=seed,
            curated_preset="a6_asymmetric_depth_v2",
        ),
    }

    expected_rejections: dict[str, str] = {}
    try:
        _prepare(
            root,
            scene_graph_path=A6_SCENE_GRAPH_PATH,
            mood_package_path=A6_MOOD_PACKAGE_PATH,
            products=build_product_specs(root, container_modes=all_adopt_modes),
            seed=seed,
            curated_preset="a6_asymmetric_depth_v2",
        )
    except ValueError as exc:
        expected_rejections["a6_3exact_all_adopt"] = str(exc)
    else:
        raise AssertionError("A6 all-adopt must reject the stoppered bottle assignment")

    try:
        _prepare(
            root,
            scene_graph_path=B3_SCENE_GRAPH_PATH,
            products=build_product_specs(
                root,
                container_modes=preserve_modes,
                automatic_targets=True,
            ),
            seed=seed,
        )
    except ValueError as exc:
        expected_rejections["b3_3exact_no_safe_slots"] = str(exc)
    else:
        raise AssertionError("B3 must atomically reject three products in one slot")

    summaries: dict[str, Any] = {}
    for case_id, request in requests.items():
        products = request["products"]
        image_inputs = request["generation"]["image_inputs"]
        slot_plan = request["scene_graph_contract"]["slot_plan"]
        prompt = request["generation"]["prompt"]
        authority_checks = {
            check_id: fragment in prompt
            for check_id, fragment in REQUIRED_PROMPT_AUTHORITIES.items()
        }
        authority_checks["two_independent_iced_servings"] = (
            prompt.count("serving-contract={temperature=iced, ice=present") == 2
        )
        conflict_checks = {
            check_id: fragment not in prompt
            for check_id, fragment in FORBIDDEN_PROMPT_CONFLICTS.items()
        }
        failed_authorities = [
            check_id
            for check_id, passed in {**authority_checks, **conflict_checks}.items()
            if not passed
        ]
        if failed_authorities:
            raise AssertionError(
                f"{case_id} prompt authority audit failed: {failed_authorities}"
            )
        summaries[case_id] = {
            "schema_version": request["schema_version"],
            "prompt_compiler_version": request["prompt_compiler_version"],
            "product_ids": [item["product_id"] for item in products],
            "container_modes": {
                item["product_id"]: item["container_policy"] for item in products
            },
            "target_brand_states": {
                item["product_id"]: item["target_brand_contract"]["state"]
                for item in products
            },
            "serving_actions": {
                item["product_id"]: item["serving_compatibility_resolution"]["action"]
                for item in products
            },
            "slot_bindings": copy.deepcopy(slot_plan["bindings"]),
            "active_relations": copy.deepcopy(slot_plan["active_relations"]),
            "exact_product_count": len(products),
            "generic_companion_count": slot_plan["generic_companion_count"],
            "image_input_count": len(image_inputs),
            "image_input_roles": [item["role"] for item in image_inputs],
            "runtime_reference_pixels_submitted": request["scene_graph_contract"][
                "runtime_reference_pixels_submitted"
            ],
            "prompt_characters": len(prompt),
            "prompt_character_limit": request["generation"][
                "prompt_character_limit"
            ],
            "prompt_limit_policy_id": request["generation"][
                "prompt_limit_policy_id"
            ],
            "prompt_limit_verification_state": request["generation"][
                "prompt_limit_verification_state"
            ],
            "prompt_authority_checks": authority_checks,
            "prompt_conflict_checks": conflict_checks,
            "estimated_credits": request["generation"]["estimated_credits"],
        }
    return {
        "schema_version": "1.0.0",
        "artifact_type": "v3_multi_subject_zero_credit_preflight",
        "selection_status": selection["selection_status"],
        "selected_candidates": copy.deepcopy(selection["selected_candidates"]),
        "reference_id": A6_REFERENCE_ID,
        "product_count": 3,
        "case_count": len(requests),
        "requests": requests,
        "summaries": summaries,
        "expected_rejections": expected_rejections,
        "paid_generation_calls": 0,
    }


def prepare_multi_subject_preset_comparison(
    project_root: str | Path,
    *,
    seed: int = 713,
) -> dict[str, Any]:
    """Build the user-selected A6/B3 x two cup-policy comparison requests."""

    root = Path(project_root).resolve()
    selection = _selection_manifest(root)
    preserve_modes = {item["product_id"]: "preserve_source" for item in PRODUCTS}
    hybrid_modes = {
        "p01_matcha_branded": "preserve_source",
        "p02_strawberry_milk_unbranded": "adopt_reference",
        "p04_marbled_latte_unbranded": "preserve_source",
    }
    definitions = (
        (
            "a6_asymmetric_depth",
            A6_SCENE_GRAPH_PATH,
            A6_MOOD_PACKAGE_PATH,
            "a6_asymmetric_depth_v2",
        ),
        (
            "b3_quiet_pale_wood",
            B3_SCENE_GRAPH_PATH,
            B3_MOOD_PACKAGE_PATH,
            "b3_quiet_wall_v1",
        ),
    )
    requests: dict[str, dict[str, Any]] = {}
    for prefix, graph_path, mood_path, curated_preset in definitions:
        for mode_name, container_modes in (
            ("preserve", preserve_modes),
            ("compatible_hybrid", hybrid_modes),
        ):
            case_id = f"{prefix}__{mode_name}"
            request = _prepare(
                root,
                scene_graph_path=graph_path,
                mood_package_path=mood_path,
                products=build_product_specs(root, container_modes=container_modes),
                seed=seed,
                curated_preset=curated_preset,
            )
            prompt = request["generation"]["prompt"]
            if len(prompt) > 12_000:
                raise ValueError(f"{case_id} prompt exceeds 12,000 characters")
            image_inputs = request["generation"]["image_inputs"]
            if len(image_inputs) != 4:
                raise ValueError(
                    f"{case_id} must submit three product images and one sanitized control board"
                )
            if [item["role"] for item in image_inputs] != [
                "product_source",
                "product_source",
                "product_source",
                "reference_control_board",
            ]:
                raise ValueError(f"{case_id} has an invalid ordered image-input contract")
            if request["scene_graph_contract"]["runtime_reference_pixels_submitted"]:
                raise ValueError(f"{case_id} must not submit raw reference pixels")
            forbidden_fragments = (
                "Round wooden tray",
                "compact triangular service cluster",
                "shared pale table and restrained round wood support",
            )
            conflicts = [item for item in forbidden_fragments if item in prompt]
            if conflicts:
                raise ValueError(f"{case_id} retains failed layout conflicts: {conflicts}")
            requests[case_id] = request
    return {
        "schema_version": "1.0.0",
        "artifact_type": "v3_multi_subject_preset_model_comparison_base",
        "selected_candidates": copy.deepcopy(selection["selected_candidates"]),
        "preset_count": 2,
        "container_policy_count": 2,
        "product_count": 3,
        "base_case_count": len(requests),
        "requests": requests,
        "paid_generation_calls": 0,
    }
