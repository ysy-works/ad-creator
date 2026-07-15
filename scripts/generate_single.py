"""
단일 이미지 생성 스크립트.

사용 예:
  python scripts/generate_single.py input/drink.jpg --comp medium --bg wood
  python scripts/generate_single.py input/drink.jpg --comp closeup --bg white --strength high --seed 42
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config
from app.inference import generate_beverage_image


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image", help="입력 음료 사진 경로")
    p.add_argument("--comp", default="medium", choices=config.COMPOSITIONS)
    p.add_argument("--bg", default="wood", choices=config.BACKGROUND_STYLES)
    p.add_argument("--strength", default="medium", choices=config.STRENGTHS)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--guidance", type=float, default=None)
    args = p.parse_args()

    result = generate_beverage_image(
        image_path=args.image,
        composition=args.comp,
        background_style=args.bg,
        strength=args.strength,
        seed=args.seed,
        num_inference_steps=args.steps,
        guidance_scale=args.guidance,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("success"):
        print(f"\n✓ 저장: {result['output_path']}  ({result['elapsed_seconds']}초, {result['mode']} 모드)")
    else:
        print(f"\n✗ 실패: {result['error_code']} - {result.get('error_message','')}")


if __name__ == "__main__":
    main()
