import argparse
import json
import os
import sys
import uuid
from pathlib import Path


COMFYUI_DIR = Path(__file__).resolve().parents[1]
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
sys.path.insert(0, str(CUSTOM_NODES_DIR))

from ad_creator.adapters.openai_image import run_openai_image


PUBLISHED_PRESETS = (
    "natural_white__product_center",
    "wood__product_center",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicit paid OpenAI low smoke image for a published preset."
    )
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--preset", required=True, choices=PUBLISHED_PRESETS)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--aspect-ratio", choices=("4:5", "1:1"), default="4:5")
    parser.add_argument("--source-max-edge", choices=(1536, 3072), default=1536, type=int)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AD_CREATOR_OPENAI_SOURCE_MAX_EDGE"] = str(args.source_max_edge)
    image, metadata = run_openai_image(
        image_path=args.image.resolve(),
        preset_slot_id=args.preset,
        aspect_ratio=args.aspect_ratio,
        run_id=f"smoke-{uuid.uuid4()}",
        audit_dir=output_dir / "audit",
    )
    suffix = args.aspect_ratio.replace(":", "x")
    image_path = output_dir / f"{args.preset}.{suffix}.{args.source_max_edge}.png"
    metadata_path = output_dir / f"{args.preset}.{suffix}.{args.source_max_edge}.metadata.json"
    image.save(image_path, format="PNG")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "image": str(image_path),
                "metadata": str(metadata_path),
                "model": metadata["model"],
                "quality": metadata["quality"],
                "aspect_ratio": metadata["aspect_ratio"],
                "source_max_edge": metadata["source_preprocessing"]["max_long_edge"],
                "delivery_dimensions": metadata["delivery_dimensions"],
                "request_id": metadata["request_id"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
