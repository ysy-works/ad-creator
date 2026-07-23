#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from build_comfy_workflows import (
    A6_MOOD,
    A6_REFERENCE_IMAGE,
    A6_RELATIONAL_V4_MOOD,
    A6_RELATIONAL_V4_SCENE_GRAPH,
    WORKFLOW_ROOT,
    _write,
    build_api_workflow,
    build_gui_workflow,
)


SOURCE_DESIGN = "presets/container_designs/p01_source_tapered_glass_reconstruct_v1.json"


ARMS = (
    {
        "stem": "17_a6_relational_v4_structured_reference_cup",
        "reference_control_role": "structured_only",
        "container_design_source": "reference",
        "container_design_path": "",
        "preset_control_board": False,
    },
    {
        "stem": "18_a6_relational_v4_scene_hint_reference_cup",
        "reference_control_role": "sanitized_scene_hint",
        "container_design_source": "reference",
        "container_design_path": "",
        "preset_control_board": True,
    },
    {
        "stem": "19_a6_relational_v4_scene_hint_source_cup",
        "reference_control_role": "sanitized_scene_hint",
        "container_design_source": "source",
        "container_design_path": SOURCE_DESIGN,
        "preset_control_board": True,
        "fake_qa_fixture_path": "evals/fixtures/unbranded_source_reconstructed_scene_pass_qa.json",
    },
)


def build_all() -> list[Path]:
    written: list[Path] = []
    common = {
        "scene_graph": True,
        "reference_image": A6_REFERENCE_IMAGE,
        "fallback_mood": A6_MOOD,
        "scene_graph_catalog_path": A6_RELATIONAL_V4_SCENE_GRAPH,
        "auto_paid_repair": False,
        "mood_package_override": A6_RELATIONAL_V4_MOOD,
    }
    for arm in ARMS:
        options = {
            **common,
            "reference_control_role": arm["reference_control_role"],
            "container_design_source": arm["container_design_source"],
            "container_design_path": arm["container_design_path"],
            "preset_control_board": arm["preset_control_board"],
            "fake_qa_fixture_path": arm.get("fake_qa_fixture_path"),
        }
        for provider, suffix in (("higgsfield", "higgsfield"), ("fake", "local_fake")):
            gui_path = WORKFLOW_ROOT / f"{arm['stem']}_{suffix}.json"
            _write(
                gui_path,
                build_gui_workflow(
                    "adopt_reference",
                    provider=provider,
                    **options,
                ),
            )
            written.append(gui_path)
            path = WORKFLOW_ROOT / f"{arm['stem']}_{suffix}_api.json"
            _write(
                path,
                build_api_workflow(
                    "adopt_reference",
                    provider=provider,
                    **options,
                ),
            )
            written.append(path)
    return written


def main() -> int:
    for path in build_all():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
