from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.runtime import execute_product_transforms, resolve_preset_contract


def _cli() -> Path:
    configured = os.environ.get("HIGGSFIELD_CLI_BIN", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend(
        sorted(
            (
                Path.home()
                / "Library/pnpm/store/v11/links/@higgsfield/cli"
            ).glob("*/*/node_modules/@higgsfield/cli/vendor/hf"),
            reverse=True,
        )
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise FileNotFoundError(
        "Higgsfield CLI was not found. Set HIGGSFIELD_CLI_BIN to the hf executable."
    )


def _json_command(command: list[str], timeout: int) -> dict[str, Any] | list[Any]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, (dict, list)):
        raise RuntimeError("Higgsfield returned a non-object JSON response.")
    return value


def _result_record(value: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict) and item.get("result_url"):
                return item
        if len(value) == 1 and isinstance(value[0], dict):
            return value[0]
        raise RuntimeError(f"Higgsfield result is ambiguous: {value!r}")
    return value


def _cost_value(value: dict[str, Any] | list[Any]) -> float | None:
    record = _result_record(value)
    for key in ("credits", "cost", "estimated_credits", "credit_cost"):
        candidate = record.get(key)
        if isinstance(candidate, (int, float)):
            return float(candidate)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile one validated preset through preset-runtime-v1 and run a Higgsfield visual smoke."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--preset-slot", required=True)
    parser.add_argument(
        "--container-mode",
        choices=("adopt_reference", "reconstruct_source"),
        required=True,
    )
    parser.add_argument(
        "--serving-temperature",
        choices=("auto", "iced", "cold", "ambient", "hot"),
        default="auto",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="gpt_image_2")
    parser.add_argument("--quality", choices=("medium", "high"), default="medium")
    parser.add_argument("--resolution", default="1k")
    parser.add_argument("--approve-paid", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        raise SystemExit(f"Source image is missing: {source}")
    contract = resolve_preset_contract(
        args.preset_slot,
        aspect_ratio="4:5",
        container_mode=args.container_mode,
        serving_temperature=args.serving_temperature,
        registry_path=COMFYUI_DIR / "presets" / "registry.json",
        allowed_statuses=("validated",),
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with execute_product_transforms(
        source,
        contract.declared_transforms,
    ) as (prepared_source, transform_audit):
        if prepared_source == source:
            resolved_source = source
        else:
            resolved_source = output_dir / f"{args.run_id}.prepared-source.png"
            resolved_source.write_bytes(prepared_source.read_bytes())
    references = [resolved_source, *contract.provider_image_paths]
    if len(references) > 4:
        raise SystemExit("Resolved request exceeds the four-image input cap.")

    # Higgsfield GPT Image 2 currently exposes 3:4 but not 4:5. Keep this output
    # explicitly non-publishable and record the adaptation instead of pretending
    # it validates the production canvas.
    provider_aspect_ratio = "3:4"
    adaptation = (
        "\n\n[HIGGSFIELD VISUAL-SMOKE CANVAS ADAPTATION]\n"
        "The provider canvas is native 3:4 because this Higgsfield model does not expose 4:5. "
        "Recompose the declared 4:5 relationships inside the 3:4 frame without cropping any "
        "required product, support or companion. This output is visual-smoke evidence only and "
        "must not be marked published or used as exact 4:5 geometry validation."
    )
    prompt = contract.prompt + adaptation
    if len(prompt) > 12_000:
        raise SystemExit(f"Provider-adapted prompt exceeds 12,000 characters: {len(prompt)}")

    prompt_path = output_dir / f"{args.run_id}.prompt.txt"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    cli = _cli()
    common = [
        str(cli),
        args.model,
        "--prompt",
        prompt,
        "--resolution",
        args.resolution,
        "--aspect-ratio",
        provider_aspect_ratio,
    ]
    if args.model == "gpt_image_2":
        common.extend(("--quality", args.quality))
    for reference in references:
        common.extend(("--image-references", str(reference)))

    cost_response = _json_command(
        [str(cli), "generate", "cost", *common[1:], "--json"], timeout=300
    )
    estimated_cost = _cost_value(cost_response)
    base_manifest = {
        "schema_version": 1,
        "run_id": args.run_id,
        "validation_class": "higgsfield_3x4_visual_smoke_not_publishable_4x5_qa",
        "preset_slot_id": contract.slot_id,
        "preset_id": contract.preset_id,
        "preset_status": contract.status,
        "compiler_version": contract.compiler_version,
        "container_mode": contract.container_mode,
        "serving_temperature": contract.serving_temperature,
        "temperature_resolution_source": contract.temperature_resolution_source,
        "brand_input_enabled": contract.brand_input_enabled,
        "brand_default_mode": contract.brand_default_mode,
        "brand_policy_sha256": contract.brand_policy_sha256,
        "companion_policy": contract.companion_policy,
        "model": args.model,
        "quality": args.quality if args.model == "gpt_image_2" else None,
        "resolution": args.resolution,
        "preset_aspect_ratio": "4:5",
        "provider_aspect_ratio": provider_aspect_ratio,
        "input_count": len(references),
        "input_roles": ["product_source", *contract.provider_image_roles],
        "declared_transform_audit": transform_audit,
        "input_sha256": [
            hashlib.sha256(path.read_bytes()).hexdigest() for path in references
        ],
        "base_prompt_sha256": contract.prompt_sha256,
        "provider_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_characters": len(prompt),
        "estimated_credits": estimated_cost,
        "cost_response": cost_response,
    }
    manifest_path = output_dir / f"{args.run_id}.manifest.json"
    if not args.approve_paid:
        base_manifest["status"] = "cost_checked_not_submitted"
        manifest_path.write_text(
            json.dumps(base_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(base_manifest, ensure_ascii=False))
        return 0

    created = _json_command(
        [
            str(cli),
            "generate",
            "create",
            *common[1:],
            "--wait",
            "--wait-timeout",
            "20m",
            "--wait-interval",
            "5s",
            "--json",
        ],
        timeout=1320,
    )
    result = _result_record(created)
    result_url = result.get("result_url")
    if not isinstance(result_url, str) or not result_url:
        raise RuntimeError(f"Higgsfield returned no result_url: {created!r}")
    image_path = output_dir / f"{args.run_id}.png"
    with urllib.request.urlopen(result_url, timeout=180) as response:
        image_path.write_bytes(response.read())
    base_manifest.update(
        {
            "status": "completed",
            "job": result,
            "output": image_path.name,
            "output_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        }
    )
    manifest_path.write_text(
        json.dumps(base_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(base_manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
