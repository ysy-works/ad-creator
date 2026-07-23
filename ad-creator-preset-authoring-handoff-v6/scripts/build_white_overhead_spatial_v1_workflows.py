from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / "workflows"


def build_workflow(
    *,
    input_image: str,
    container_mode: str,
    container_design_source: str,
    seed: int,
    output_stem: str,
) -> dict[str, object]:
    container_design_path = (
        "presets/container_designs/white_ceramic_mug_visible_handle_overhead_v1.json"
        if container_mode == "adopt_reference"
        else ""
    )
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": input_image},
        },
        "2": {
            "class_type": "AD_GeminiProductAnalyze",
            "inputs": {
                "image": ["1", 0],
                "analyzer_config_path": "configs/analyzers.json",
                "use_cache": True,
            },
        },
        "3": {
            "class_type": "LoadImage",
            "inputs": {"image": "ad_creator_white_overhead_reference_v1.png"},
        },
        "4": {
            "class_type": "AD_ResolveReferenceSceneGraph",
            "inputs": {
                "reference_image": ["3", 0],
                "catalog_path": "data/reference-library/catalog.sqlite",
                "scene_graph_catalog_path": "data/reference-library/scene-graphs-v2/ref_499763da87e8bf0e.json",
                "assignments_path": "data/reference-library/unused_assignments.json",
                "fallback_mood_package_path": "presets/moods/instagram_white_neutral_overhead_spatial_v1/mood-package.json",
            },
        },
        "5": {
            "class_type": "AD_LoadMoodPackage",
            "inputs": {
                "mood_package_path": "presets/moods/instagram_white_neutral_overhead_spatial_v1/mood-package.json"
            },
        },
        "6": {
            "class_type": "AD_BuildSceneGenerationRequest",
            "inputs": {
                "image": ["2", 0],
                "mood_json": ["5", 0],
                "product_analysis_json": ["2", 1],
                "scene_reference_json": ["4", 1],
                "scene_graph_json": ["4", 2],
                "container_mode": container_mode,
                "target_slot_id": "auto",
                "placement_mode": "replace",
                "product_kind": "beverage",
                "cross_kind_replacement": False,
                "unbound_slot_policy": "remove",
                "container_design_path": container_design_path,
                "auto_paid_repair": False,
                "features_path": "configs/service-features.json",
                "provider_profile_path": "",
                "seed": seed,
                "quality_tier": "default",
                "reference_control_role": "structured_only",
                "container_design_source": container_design_source,
            },
        },
        "7": {
            "class_type": "HiggsfieldImageGenerate",
            "inputs": {
                "prompt": ["6", 1],
                "model": "GPT Image 2",
                "image": ["6", 0],
                "aspect_ratio": "3:4",
                "resolution": "1k",
            },
        },
        "8": {
            "class_type": "AD_InstagramCrop",
            "inputs": {
                "image": ["7", 0],
                "target_width": 880,
                "target_height": 1100,
            },
        },
        "9": {
            "class_type": "AD_ApplyMoodGrade",
            "inputs": {
                "image": ["8", 0],
                "mood_json": ["5", 0],
                "strength": "natural",
            },
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["9", 0],
                "filename_prefix": f"ad_creator/white_overhead_spatial_v1/{output_stem}",
            },
        },
        "11": {
            "class_type": "SaveHiggsfieldMetadata",
            "inputs": {
                "metadata": ["7", 1],
                "filename_prefix": f"ad_creator/white_overhead_spatial_v1/{output_stem}_job",
            },
        },
    }


def main() -> None:
    cases = [
        (
            "21a_white_overhead_matcha_reference_cup_higgsfield_api.json",
            "white_overhead_matcha_source.png",
            "adopt_reference",
            "reference",
            713,
            "matcha_reference_cup_gpt_image_2_medium",
        ),
        (
            "21b_white_overhead_matcha_source_cup_higgsfield_api.json",
            "white_overhead_matcha_source.png",
            "preserve_source",
            "source",
            713,
            "matcha_source_cup_gpt_image_2_medium",
        ),
        (
            "21c_white_overhead_strawberry_reference_cup_higgsfield_api.json",
            "white_overhead_strawberry_source.jpg",
            "adopt_reference",
            "reference",
            829,
            "strawberry_reference_cup_gpt_image_2_medium",
        ),
        (
            "21d_white_overhead_strawberry_source_cup_higgsfield_api.json",
            "white_overhead_strawberry_source.jpg",
            "preserve_source",
            "source",
            829,
            "strawberry_source_cup_gpt_image_2_medium",
        ),
    ]
    WORKFLOW_ROOT.mkdir(parents=True, exist_ok=True)
    for filename, image, mode, design_source, seed, output_stem in cases:
        payload = build_workflow(
            input_image=image,
            container_mode=mode,
            container_design_source=design_source,
            seed=seed,
            output_stem=output_stem,
        )
        target = WORKFLOW_ROOT / filename
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(target.relative_to(ROOT).as_posix())

    fake = build_workflow(
        input_image="white_overhead_matcha_source.png",
        container_mode="adopt_reference",
        container_design_source="reference",
        seed=713,
        output_stem="smoke_matcha_reference_cup",
    )
    fake["7"] = {
        "class_type": "AD_FakeGenerate",
        "inputs": {
            "image": ["6", 0],
            "request_json": ["6", 2],
            "fixture_image_path": "",
        },
    }
    fake["10"]["inputs"]["filename_prefix"] = (
        "ad_creator/white_overhead_spatial_v1/smoke_matcha_reference_cup"
    )
    fake["11"] = {
        "class_type": "AD_SaveRunManifest",
        "inputs": {
            "request_json": ["6", 2],
            "job_json": ["7", 1],
            "metrics_json": ["9", 1],
            "output_label": "ad_creator/white_overhead_spatial_v1/smoke_matcha_reference_cup",
        },
    }
    fake["12"] = {
        "class_type": "AD_FakeQualityRoute",
        "inputs": {
            "request_json": ["6", 2],
            "lighting_sheet_json": ["5", 1],
            "qa_fixture_path": "evals/fixtures/white_overhead_reference_mug_pass_qa.json",
        },
    }
    fake_target = WORKFLOW_ROOT / "21_white_overhead_spatial_v1_local_fake_api.json"
    fake_target.write_text(
        json.dumps(fake, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(fake_target.relative_to(ROOT).as_posix())

    preserve_fake = build_workflow(
        input_image="white_overhead_matcha_source.png",
        container_mode="preserve_source",
        container_design_source="source",
        seed=713,
        output_stem="smoke_preserve_source",
    )
    preserve_fake["7"] = {
        "class_type": "AD_FakeGenerate",
        "inputs": {
            "image": ["6", 0],
            "request_json": ["6", 2],
            "fixture_image_path": "",
        },
    }
    preserve_fake["10"]["inputs"]["filename_prefix"] = (
        "ad_creator/white_overhead_spatial_v1/smoke_preserve_source"
    )
    preserve_fake["11"] = {
        "class_type": "AD_SaveRunManifest",
        "inputs": {
            "request_json": ["6", 2],
            "job_json": ["7", 1],
            "metrics_json": ["9", 1],
            "output_label": "ad_creator/white_overhead_spatial_v1/smoke_preserve_source",
        },
    }
    preserve_fake["12"] = {
        "class_type": "AD_FakeQualityRoute",
        "inputs": {
            "request_json": ["6", 2],
            "lighting_sheet_json": ["5", 1],
            "qa_fixture_path": "evals/fixtures/unbranded_scene_pass_qa.json",
        },
    }
    preserve_fake_target = (
        WORKFLOW_ROOT / "21_white_overhead_spatial_v1_preserve_source_local_fake_api.json"
    )
    preserve_fake_target.write_text(
        json.dumps(preserve_fake, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(preserve_fake_target.relative_to(ROOT).as_posix())

    branded_preserve_fake = json.loads(json.dumps(preserve_fake))
    branded_preserve_fake["12"]["inputs"]["qa_fixture_path"] = (
        "evals/fixtures/branded_matcha_preserve_pass_qa.json"
    )
    branded_preserve_fake["10"]["inputs"]["filename_prefix"] = (
        "ad_creator/white_overhead_spatial_v1/smoke_matcha_preserve_source"
    )
    branded_preserve_fake["11"]["inputs"]["output_label"] = (
        "ad_creator/white_overhead_spatial_v1/smoke_matcha_preserve_source"
    )
    branded_preserve_target = (
        WORKFLOW_ROOT
        / "21_white_overhead_spatial_v1_matcha_preserve_source_local_fake_api.json"
    )
    branded_preserve_target.write_text(
        json.dumps(branded_preserve_fake, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(branded_preserve_target.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
