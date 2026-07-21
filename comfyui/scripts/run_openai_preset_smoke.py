import argparse
import json
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
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    image, metadata = run_openai_image(
        image_path=args.image.resolve(),
        preset_slot_id=args.preset,
        run_id=f"smoke-{uuid.uuid4()}",
        audit_dir=output_dir / "audit",
    )
    image_path = output_dir / f"{args.preset}.png"
    metadata_path = output_dir / f"{args.preset}.metadata.json"
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
