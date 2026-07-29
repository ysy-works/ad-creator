from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.adapters.openai_image import run_openai_image


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicitly approved GPT Image 2 low white-overhead review image."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approve-paid", action="store_true")
    args = parser.parse_args()
    if not args.approve_paid:
        raise SystemExit("Refusing paid generation without --approve-paid.")

    image, metadata = run_openai_image(
        image_path=args.input.resolve(),
        preset_slot_id="natural_white__aerial_shot",
        container_mode="adopt_reference",
        aspect_ratio="4:5",
        allowed_statuses=("validated",),
        run_id=args.run_id,
        audit_dir=args.audit_dir.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, format="PNG")
    report = {
        "status": "completed",
        "output": str(args.output.resolve()),
        "metadata": metadata,
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
