from __future__ import annotations

import argparse
import json
from pathlib import Path

from .jsonio import dump_json
from .multi_pipeline import (
    prepare_multi_product_request_from_paths,
    run_local_multi_pipeline,
)
from .pipeline import (
    evaluate_existing_higgsfield_run,
    preflight_higgsfield_pipeline,
    run_higgsfield_pipeline,
    run_local_pipeline,
    run_openai_pipeline,
)
from .provider_profiles import OPENAI_PROVIDER_PROFILE_PATH
from .providers.higgsfield import HiggsfieldProvider


def _add_generation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default=str(Path.cwd()))
    parser.add_argument(
        "--mood-package",
        default="presets/moods/direct_sun_white_wall_v1/mood-package.json",
    )
    parser.add_argument("--product-analysis", default="examples/product-analysis/input_01.json")
    parser.add_argument(
        "--scene-reference",
        help="Path to an analyzed reference-asset JSON contract.",
    )
    parser.add_argument(
        "--scene-graph",
        help="Path to one Scene Graph v2 JSON contract.",
    )
    parser.add_argument(
        "--target-slot-id",
        default="auto",
        help="Stable Scene Graph slot ID; auto selects the safest compatible slot.",
    )
    parser.add_argument(
        "--placement-mode",
        choices=["replace", "add"],
        default="replace",
    )
    parser.add_argument(
        "--product-kind",
        choices=["beverage", "dessert"],
        default="beverage",
    )
    parser.add_argument(
        "--cross-kind-replacement",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--unbound-slot-policy",
        choices=["genericize", "remove"],
        default="genericize",
    )
    parser.add_argument("--input-image", required=True)
    parser.add_argument("--seed", type=int, default=713)
    parser.add_argument("--features", default="configs/service-features.json")
    parser.add_argument(
        "--container-mode",
        choices=["preserve_source", "adopt_reference"],
        default="preserve_source",
    )
    parser.add_argument("--container-reference")
    parser.add_argument("--container-design")
    parser.add_argument("--brand-asset")
    parser.add_argument(
        "--auto-paid-repair",
        action=argparse.BooleanOptionalAction,
        default=None,
    )


def _add_multi_generation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default=str(Path.cwd()))
    parser.add_argument(
        "--mood-package",
        default="presets/moods/direct_sun_white_wall_v1/mood-package.json",
    )
    parser.add_argument("--product-set", required=True)
    parser.add_argument("--scene-graph", required=True)
    parser.add_argument("--control-board-image")
    parser.add_argument("--control-board-manifest")
    parser.add_argument("--lighting-base")
    parser.add_argument("--lighting-delta")
    parser.add_argument("--wood-material-profile")
    parser.add_argument("--seed", type=int, default=713)
    parser.add_argument(
        "--unbound-slot-policy",
        choices=["genericize", "remove"],
        default="genericize",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ad-creator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    local = subparsers.add_parser("local-validate", help="Run the zero-credit local pipeline")
    _add_generation_arguments(local)
    local.add_argument("--fixture-image")
    local.add_argument("--output-root", default="outputs/local-validation/runs")
    multi_build = subparsers.add_parser(
        "multi-build",
        help="Compile and validate a zero-side-effect GenerationRequestV3",
    )
    _add_multi_generation_arguments(multi_build)
    multi_build.add_argument(
        "--output-request",
        help="Optional path for the compiled request; stdout is always emitted.",
    )
    multi_local = subparsers.add_parser(
        "multi-local-validate",
        help="Run the zero-credit fake-provider pipeline for one to three products",
    )
    _add_multi_generation_arguments(multi_local)
    multi_local.add_argument("--fixture-image")
    multi_local.add_argument("--output-root", default="outputs/local-validation-v3/runs")
    live = subparsers.add_parser(
        "higgsfield-run",
        help="Run or resume a paid Higgsfield generation within the configured credit limit",
    )
    _add_generation_arguments(live)
    live.add_argument("--output-root", default="outputs/higgsfield/runs")
    live.add_argument("--cli-path", default=".tools/higgsfield/bin/higgsfield")
    live.add_argument("--timeout-seconds", type=float, default=1200)
    live.add_argument("--poll-interval-seconds", type=float, default=3)
    openai = subparsers.add_parser(
        "openai-run",
        help="Run one paid GPT Image 1 Mini request and Gemini QA without automatic repair",
    )
    _add_generation_arguments(openai)
    openai.add_argument("--output-root", default="outputs/openai/runs")
    openai.add_argument(
        "--provider-profile",
        default=OPENAI_PROVIDER_PROFILE_PATH,
    )
    openai.add_argument("--evaluator-config", default="configs/evaluator.json")
    openai.add_argument("--timeout-seconds", type=float, default=1200)
    preflight = subparsers.add_parser(
        "higgsfield-preflight",
        help="Validate and quote a Higgsfield request without submitting it",
    )
    _add_generation_arguments(preflight)
    preflight.add_argument("--output-root", default="outputs/higgsfield/preflight")
    preflight.add_argument("--cli-path", default=".tools/higgsfield/bin/higgsfield")
    reconcile = subparsers.add_parser(
        "higgsfield-reconcile",
        help="Attach an already-submitted Higgsfield job to a local request hash",
    )
    reconcile.add_argument("--project-root", default=str(Path.cwd()))
    reconcile.add_argument("--output-root", required=True)
    reconcile.add_argument("--cli-path", default=".tools/higgsfield/bin/higgsfield")
    reconcile.add_argument("--request-hash", required=True)
    reconcile.add_argument("--job-id", required=True)
    reconcile.add_argument("--estimated-credits", type=float, default=2)
    reconcile.add_argument("--credits-before", type=float, required=True)
    evaluate = subparsers.add_parser(
        "higgsfield-evaluate",
        help="Evaluate an existing Higgsfield result without generating or repairing",
    )
    evaluate.add_argument("--project-root", default=str(Path.cwd()))
    evaluate.add_argument("--manifest", required=True)
    evaluate.add_argument("--mood-package", required=True)
    evaluate.add_argument("--input-image", required=True)
    evaluate.add_argument("--container-reference")
    evaluate.add_argument("--evaluator-config", default="configs/evaluator.json")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command in {"multi-build", "multi-local-validate"}:
        root = Path(args.project_root).resolve()
        request = prepare_multi_product_request_from_paths(
            project_root=root,
            mood_package_path=args.mood_package,
            product_set_path=args.product_set,
            scene_graph_path=args.scene_graph,
            control_board_image=args.control_board_image,
            control_board_manifest_path=args.control_board_manifest,
            lighting_base_path=args.lighting_base,
            lighting_delta_path=args.lighting_delta,
            wood_material_profile_path=args.wood_material_profile,
            seed=args.seed,
            unbound_slot_policy=args.unbound_slot_policy,
        )
        if args.command == "multi-build":
            if args.output_request:
                output_path = Path(args.output_request).expanduser()
                if not output_path.is_absolute():
                    output_path = root / output_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(dump_json(request), encoding="utf-8")
            print(dump_json(request))
            return 0

        output_root = Path(args.output_root).expanduser()
        if not output_root.is_absolute():
            output_root = root / output_root
        fixture_image = args.fixture_image
        if fixture_image:
            fixture_path = Path(fixture_image).expanduser()
            if not fixture_path.is_absolute():
                fixture_path = root / fixture_path
            fixture_image = str(fixture_path.resolve())
        result = run_local_multi_pipeline(
            request=request,
            output_root=output_root.resolve(),
            fixture_image=fixture_image,
        )
        print(
            json.dumps(
                {
                    "request_hash": result.manifest["request_hash"],
                    "manifest": str(result.manifest_path),
                    "reused_provider_job": result.reused_provider_job,
                    "status": result.manifest["status"],
                    "output": str(result.output_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "higgsfield-reconcile":
        root = Path(args.project_root).resolve()
        output_root = Path(args.output_root)
        if not output_root.is_absolute():
            output_root = root / output_root
        cli_path = Path(args.cli_path)
        if not cli_path.is_absolute():
            cli_path = root / cli_path
        provider = HiggsfieldProvider(
            output_root.resolve() / "_higgsfield_provider",
            cli_path=cli_path.resolve(),
            maximum_base_credits=2,
        )
        job = provider.reconcile_submitted_job(
            idempotency_key=args.request_hash,
            job_id=args.job_id,
            estimated_credits=args.estimated_credits,
            credits_before=args.credits_before,
        )
        print(
            json.dumps(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "actual_credits": job.actual_credits,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "higgsfield-evaluate":
        result = evaluate_existing_higgsfield_run(
            project_root=args.project_root,
            manifest_path=args.manifest,
            mood_package_path=args.mood_package,
            input_image=args.input_image,
            container_reference_image=args.container_reference,
            evaluator_config_path=args.evaluator_config,
        )
        print(
            json.dumps(
                {
                    "status": result.manifest["status"],
                    "qa_report": result.manifest["artifacts"].get("qa_initial"),
                    "repair_plan": result.manifest["artifacts"].get("repair_plan"),
                    "repair_status": result.manifest.get("repair", {}).get("status"),
                    "repair_credits": result.manifest["cost"].get("repair_credits", 0),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "higgsfield-preflight":
        result = preflight_higgsfield_pipeline(
            project_root=args.project_root,
            mood_package_path=args.mood_package,
            product_analysis_path=args.product_analysis,
            scene_reference_path=args.scene_reference,
            scene_graph_path=args.scene_graph,
            target_slot_id=args.target_slot_id,
            placement_mode=args.placement_mode,
            product_kind=args.product_kind,
            cross_kind_replacement=args.cross_kind_replacement,
            unbound_slot_policy=args.unbound_slot_policy,
            input_image=args.input_image,
            output_root=args.output_root,
            cli_path=args.cli_path,
            seed=args.seed,
            features_path=args.features,
            container_mode=args.container_mode,
            container_reference_image=args.container_reference,
            container_design_path=args.container_design,
            brand_asset_image=args.brand_asset,
            auto_paid_repair=args.auto_paid_repair,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    common = {
        "project_root": args.project_root,
        "mood_package_path": args.mood_package,
        "product_analysis_path": args.product_analysis,
        "scene_reference_path": args.scene_reference,
        "scene_graph_path": args.scene_graph,
        "target_slot_id": args.target_slot_id,
        "placement_mode": args.placement_mode,
        "product_kind": args.product_kind,
        "cross_kind_replacement": args.cross_kind_replacement,
        "unbound_slot_policy": args.unbound_slot_policy,
        "input_image": args.input_image,
        "output_root": args.output_root,
        "seed": args.seed,
        "features_path": args.features,
        "container_mode": args.container_mode,
        "container_reference_image": args.container_reference,
        "container_design_path": args.container_design,
        "brand_asset_image": args.brand_asset,
        "auto_paid_repair": args.auto_paid_repair,
    }
    if args.command == "local-validate":
        result = run_local_pipeline(fixture_image=args.fixture_image, **common)
    elif args.command == "higgsfield-run":
        result = run_higgsfield_pipeline(
            cli_path=args.cli_path,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            **common,
        )
    elif args.command == "openai-run":
        if args.auto_paid_repair is True:
            raise ValueError("OpenAI automatic repair is disabled; review QA manually")
        common.pop("auto_paid_repair")
        result = run_openai_pipeline(
            provider_profile_path=args.provider_profile,
            evaluator_config_path=args.evaluator_config,
            timeout_seconds=args.timeout_seconds,
            **common,
        )
    else:
        raise AssertionError(f"Unsupported command: {args.command}")
    print(
        json.dumps(
            {
                "request_hash": result.request_hash,
                "run_dir": str(result.run_dir),
                "manifest": str(result.manifest_path),
                "reused_provider_job": result.reused_provider_job,
                "status": result.status,
                "outputs": {name: str(path) for name, path in result.outputs.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
