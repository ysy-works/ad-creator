"""
12조합 매트릭스 생성 스크립트.

한 입력 이미지에 대해 4구도 × 3배경 = 12조합을 동일 seed로 생성.
결과를 한눈에 보는 컨택트시트도 만든다.

사용 예:
  python scripts/generate_matrix.py input/drink.jpg
  python scripts/generate_matrix.py input/drink.jpg --seed 42 --strength medium
  python scripts/generate_matrix.py input/drink.jpg --only-mode recreate
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config
from app.inference import generate_beverage_image


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--strength", default="medium", choices=config.STRENGTHS)
    p.add_argument("--only-mode", default=None, choices=["recreate"],
                   help="특정 모드 조합만 생성")
    p.add_argument("--sheet", action="store_true", help="컨택트시트 생성")
    args = p.parse_args()

    combos = []
    for comp in config.COMPOSITIONS:
        if args.only_mode and config.mode_for(comp) != args.only_mode:
            continue
        for bg in config.BACKGROUND_STYLES:
            combos.append((comp, bg))

    print(f"총 {len(combos)}조합 생성 (seed={args.seed})\n")

    results = []
    for i, (comp, bg) in enumerate(combos, 1):
        print(f"[{i}/{len(combos)}] {config.COMPOSITION_NAMES[comp]} / "
              f"{config.BACKGROUND_NAMES[bg]} ...", flush=True)
        tune = {
            "closeup": {"strength": "low", "guidance_scale": 2.3, "num_inference_steps": 30},
            "medium": {"strength": "medium", "guidance_scale": 3.2, "num_inference_steps": 34},
            "aerial": {"strength": "high", "guidance_scale": 4.0, "num_inference_steps": 36},
            "handheld": {"strength": "medium", "guidance_scale": 3.0, "num_inference_steps": 34},
        }[comp]

        r = generate_beverage_image(
            image_path=args.image,
            composition=comp,
            background_style=bg,
            strength=tune["strength"],
            seed=args.seed,
            guidance_scale=tune["guidance_scale"],
            num_inference_steps=tune["num_inference_steps"],
        )
        results.append(r)
        if r.get("success"):
            print(f"    ✓ {r['elapsed_seconds']}초  {r['output_path']}")
        else:
            print(f"    ✗ {r['error_code']}")

    ok = [r for r in results if r.get("success")]
    print(f"\n완료: {len(ok)}/{len(combos)} 성공")
    if ok:
        avg = sum(r["elapsed_seconds"] for r in ok) / len(ok)
        print(f"평균 {avg:.1f}초/장")

    if args.sheet and ok:
        _make_sheet(ok, args.image)


def _make_sheet(results, src):
    from PIL import Image, ImageDraw
    cell, pad, label_h = 360, 8, 30
    cols = 3
    rows = (len(results) + cols - 1) // cols
    W = cols * (cell + pad) + pad
    H = rows * (cell + label_h + pad) + pad
    sheet = Image.new("RGB", (W, H), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(results):
        rr, cc = divmod(i, cols)
        x, y = pad + cc * (cell + pad), pad + rr * (cell + label_h + pad)
        im = Image.open(r["output_path"]).convert("RGB")
        im.thumbnail((cell, cell), Image.LANCZOS)
        sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        txt = f"{config.COMPOSITION_NAMES[r['composition']]}/{config.BACKGROUND_NAMES[r['background_style']]}"
        d.text((x + 2, y + cell + 6), txt, fill=(230, 230, 230))
    out = os.path.join(config.OUTPUT_DIR, "matrix_sheet.png")
    sheet.save(out)
    print(f"컨택트시트: {out}")


if __name__ == "__main__":
    main()
