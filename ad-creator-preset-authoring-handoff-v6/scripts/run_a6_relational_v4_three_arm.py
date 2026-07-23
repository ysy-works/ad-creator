#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from ad_creator.image_contracts import canonical_image_binding

from run_comfyui_live_api import run_live


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/validation/a6-relational-v4-scale-controlled-medium-three-arm.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_manifest_input(transport_identity: Any) -> tuple[Path, dict[str, Any]]:
    """Resolve and verify the exact bytes submitted to the provider.

    RunStore deliberately replaces runtime paths with content identities before
    persisting a manifest. ComfyUI stores the corresponding deterministic PNG
    under outputs/comfyui-inputs, so a reproduction bundle can recover and
    verify the submitted bytes without leaking a machine-specific input path.
    """
    if isinstance(transport_identity, str):
        path = Path(transport_identity).expanduser().resolve()
    else:
        if not isinstance(transport_identity, dict):
            raise TypeError("Manifest image input must be a path or artifact identity")
        name = transport_identity.get("name")
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError("Unsafe or missing manifest artifact name")
        path = (ROOT / "outputs/comfyui-inputs" / name).resolve()

    if not path.is_file():
        raise FileNotFoundError(f"Submitted input artifact does not exist: {path}")
    if isinstance(transport_identity, dict):
        expected_sha = transport_identity.get("sha256")
        expected_size = transport_identity.get("size")
        if not isinstance(expected_sha, str) or expected_size is None:
            raise ValueError("Manifest artifact identity is incomplete")
        if _sha256(path) != expected_sha:
            raise ValueError("Submitted input bytes do not match run manifest")
        if path.stat().st_size != int(expected_size):
            raise ValueError("Submitted input size does not match run manifest")
        identity = dict(transport_identity)
    else:
        identity = {
            "name": path.name,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    return path, identity


def _can_resume(report_path: Path, campaign: dict[str, Any], case: dict[str, Any]) -> bool:
    if not report_path.is_file():
        return False
    report = _load(report_path)
    output = Path(str(report.get("output_image", "")))
    control = report.get("reference_control") or {}
    return bool(
        report.get("status") == "passed"
        and report.get("prompt_compiler_version") == campaign["prompt_compiler_version"]
        and report.get("quality") == campaign["provider"]["quality"]
        and control.get("role") == case["reference_control_role"]
        and control.get("container_design_source") == case["container_design_source"]
        and output.is_file()
        and Path(str(report.get("manifest", ""))).is_file()
    )


def _materialize(
    *,
    campaign: dict[str, Any],
    case: dict[str, Any],
    report_path: Path,
    workflow_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    report = _load(report_path)
    manifest_path = Path(report["manifest"])
    manifest = _load(manifest_path)
    request = manifest["request"]

    deliverable = output_root / "images" / f"{case['case_id']}.png"
    deliverable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(report["output_image"]), deliverable)

    bundle_root = output_root / "repro-bundles" / case["case_id"]
    _write(bundle_root / "request.json", request)
    (bundle_root / "prompt.txt").write_text(
        request["generation"]["prompt"] + "\n", encoding="utf-8"
    )
    image_inputs = []
    for index, (role, transport_identity) in enumerate(zip(
        request["generation"]["image_roles"],
        request["generation"]["image_paths"],
        strict=True,
    ), start=1):
        submitted_path, identity = _resolve_manifest_input(transport_identity)
        suffix = submitted_path.suffix.lower() or ".bin"
        bundled_input = bundle_root / "inputs" / f"{index:02d}-{role}{suffix}"
        bundled_input.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(submitted_path, bundled_input)
        image_inputs.append(
            {
                "role": role,
                "path": str(bundled_input.relative_to(ROOT)),
                "transport_artifact": identity,
                **canonical_image_binding(bundled_input),
            }
        )
    bundle = {
        "schema_version": "1.0.0",
        "campaign_id": campaign["campaign_id"],
        "case_id": case["case_id"],
        "comparison_invariant": {
            "product_id": campaign["product"]["product_id"],
            "reference_asset_id": campaign["reference"]["asset_id"],
            "model": campaign["provider"]["model"],
            "quality": campaign["provider"]["quality"],
            "resolution": campaign["provider"]["resolution"],
            "seed": campaign["seed"],
        },
        "experimental_variable": request["reference_control"],
        "source_product": {
            "path": campaign["product"]["path"],
            **canonical_image_binding(ROOT / campaign["product"]["path"]),
        },
        "reference": campaign["reference"],
        "workflow": {
            "path": str(workflow_path.relative_to(ROOT)),
            "sha256": _sha256(workflow_path),
        },
        "image_inputs": image_inputs,
        "prompt": {
            "path": str((bundle_root / "prompt.txt").relative_to(ROOT)),
            "compiler_version": report["prompt_compiler_version"],
            "sha256": report["prompt_sha256"],
            "characters": report["prompt_characters"],
        },
        "request": {
            "path": str((bundle_root / "request.json").relative_to(ROOT)),
            "hash": report["request_hash"],
        },
        "resolved_contracts": report["resolved_contracts"],
        "provider": {
            "adapter": campaign["provider"]["adapter"],
            "model": campaign["provider"]["model"],
            "job_id": report["provider_job_id"],
            "credits": report["total_credits"],
        },
        "deliverable": {
            "path": str(deliverable.relative_to(ROOT)),
            **canonical_image_binding(deliverable),
        },
        "run_manifest": str(manifest_path.relative_to(ROOT)),
        "qa_report": (
            str(Path(report["qa_report"]).relative_to(ROOT))
            if report.get("qa_report")
            else None
        ),
    }
    _write(bundle_root / "bundle.json", bundle)
    report.update(
        {
            "case_id": case["case_id"],
            "deliverable_image": str(deliverable),
            "repro_bundle": str(bundle_root / "bundle.json"),
        }
    )
    _write(report_path, report)
    return report


async def run_campaign(
    *,
    config_path: Path,
    server: str,
    reference_image: Path,
    confirmed_total_credits: float,
    resume: bool,
) -> dict[str, Any]:
    campaign = _load(config_path)
    if confirmed_total_credits != float(campaign["expected_total_credits"]):
        raise ValueError("--confirm-total-credits must exactly match expected_total_credits")
    if canonical_image_binding(reference_image)["pixel_sha256"] != campaign["reference"]["pixel_sha256"]:
        raise ValueError("A6 reference pixels do not match the campaign contract")

    product_path = (ROOT / campaign["product"]["path"]).resolve()
    output_root = ROOT / campaign["output_root"]
    reports: list[dict[str, Any]] = []
    invocation_credits = 0.0
    for case in campaign["cases"]:
        workflow_path = (ROOT / case["workflow"]).resolve()
        report_path = output_root / "reports" / f"{case['case_id']}.json"
        reused = resume and _can_resume(report_path, campaign, case)
        if not reused:
            report = await run_live(
                server=server,
                workflow_path=workflow_path,
                input_image=product_path,
                reference_image=reference_image,
                report_path=report_path,
                confirmed_max_credits=float(campaign["credits_per_case"]),
                quality_tier=campaign["quality_tier"],
            )
            invocation_credits += float(report["total_credits"])
        report = _materialize(
            campaign=campaign,
            case=case,
            report_path=report_path,
            workflow_path=workflow_path,
            output_root=output_root,
        )
        report["reused_existing"] = reused
        reports.append(report)
        print(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "roles": report["image_roles"],
                    "credits": report["total_credits"],
                    "deliverable": report["deliverable_image"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    total = sum(float(report["total_credits"]) for report in reports)
    if len(reports) != campaign["expected_generation_count"] or total != float(
        campaign["expected_total_credits"]
    ):
        raise RuntimeError("Completed campaign does not match its count/credit contract")
    summary = {
        "schema_version": "1.0.0",
        "campaign_id": campaign["campaign_id"],
        "status": "completed",
        "generation_count": len(reports),
        "matrix_credits": total,
        "invocation_reported_credits": invocation_credits,
        "prompt_compiler_version": campaign["prompt_compiler_version"],
        "cases": [
            {
                "case_id": report["case_id"],
                "image_roles": report["image_roles"],
                "reference_control": report["reference_control"],
                "request_hash": report["request_hash"],
                "prompt_sha256": report["prompt_sha256"],
                "provider_job_id": report["provider_job_id"],
                "deliverable_image": report["deliverable_image"],
                "repro_bundle": report["repro_bundle"],
                "core_status": report["core_status"],
            }
            for report in reports
        ],
    }
    _write(output_root / "campaign-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reproducible A6 v4 scale-controlled three-arm medium experiment.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--server", default="http://127.0.0.1:8190")
    parser.add_argument("--reference-image", type=Path, required=True)
    parser.add_argument("--confirm-total-credits", type=float, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    summary = asyncio.run(
        run_campaign(
            config_path=args.config.resolve(),
            server=args.server.rstrip("/"),
            reference_image=args.reference_image.resolve(),
            confirmed_total_credits=args.confirm_total_credits,
            resume=args.resume,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
