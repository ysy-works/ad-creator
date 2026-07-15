"""
제품 보존 우선 모드 (미디엄 / 클로즈업).

흐름:
  1. 입력에서 제품을 세그멘테이션(rembg)으로 오려냄 → 로고 픽셀 그대로 보존
  2. Kontext로 '제품 없는' 배경/구도 장면을 생성 (build_background_only_prompt)
  3. 생성된 배경에 제품을 자연스러운 크기/위치로 합성
  4. 약한 재생성(harmonize)으로 경계·조명만 녹임 (제품 실루엣 보호)

"""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config
from app import preprocessing
from app.prompt_builder import build_background_only_prompt

_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session()
    return _SESSION


def cutout(image: Image.Image, alpha_threshold: int = 150) -> Image.Image:
    """배경 제거 → RGBA. 반투명(그림자) 잔상은 잘라낸다."""
    from rembg import remove
    rgba = remove(image.convert("RGB"), session=_session()).convert("RGBA")
    arr = np.array(rgba)
    a = arr[..., 3].astype(np.float32)
    a[a < alpha_threshold] = 0
    a[a >= alpha_threshold] = 255
    arr[..., 3] = a.astype(np.uint8)
    out = Image.fromarray(arr, "RGBA")
    # 가장자리 살짝 부드럽게
    soft = out.split()[-1].filter(ImageFilter.GaussianBlur(1))
    out.putalpha(soft)
    return out


def _alpha_bbox(rgba):
    a = np.array(rgba.split()[-1])
    ys, xs = np.where(a > 10)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _contact_shadow(size, blur, opacity=110):
    """제품 발밑 접촉 그림자(타원). 캔버스를 넉넉히 잡아 잘리지 않게."""
    w, h = size
    ell_w, ell_h = int(w * 1.02), max(12, int(h * 0.10))
    margin = blur * 3 + 4
    cw, ch = ell_w + margin * 2, ell_h + margin * 2
    s = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(s).ellipse(
        [margin, margin, margin + ell_w, margin + ell_h], fill=(0, 0, 0, opacity)
    )
    return s.filter(ImageFilter.GaussianBlur(blur))


def _silhouette_mask(size, box, silhouette, feather=20):
    """제품 실루엣 보호 마스크(흰색=보호). 사각형이 아닌 실제 모양."""
    m = Image.new("L", size, 0)
    if box is None or silhouette is None:
        return m
    l, t, r, b = box
    a = silhouette.split()[-1].resize((max(1, r - l), max(1, b - t)), Image.LANCZOS)
    m.paste(a, (l, t))
    m = m.filter(ImageFilter.MinFilter(5))         # 살짝 수축(경계는 재생성이 녹이게)
    return m.filter(ImageFilter.GaussianBlur(max(2, feather // 3)))


def run_preserve(pipe, image, image_path, full_prompt,
                 composition, background_style, strength,
                 seed, guidance_scale, num_inference_steps, width, height):
    """
    Returns: (result_image, used_seed)
    """
    import torch

    # seed
    if seed is None:
        seed = int(torch.randint(0, 2**31 - 1, (1,)).item())
    gen = torch.Generator(device="cpu").manual_seed(seed)

    w16, h16 = preprocessing.to_multiple_of_16(width, height)

    # 1. 제품 컷아웃 (로고 보존)
    product_rgba = cutout(image)
    pbox = _alpha_bbox(product_rgba)
    if pbox is None:
        # 컷아웃 실패 시: 전체 재생성으로 폴백
        with torch.inference_mode():
            out = pipe(image=image, prompt=full_prompt, width=w16, height=h16,
                       num_inference_steps=num_inference_steps,
                       guidance_scale=guidance_scale, generator=gen).images[0]
        return out, seed
    product = product_rgba.crop(pbox)

    # 2. 제품 없는 배경 장면 생성
    bg_prompt = build_background_only_prompt(background_style, composition)
    with torch.inference_mode():
        scene = pipe(image=image, prompt=bg_prompt, width=w16, height=h16,
                     num_inference_steps=num_inference_steps,
                     guidance_scale=guidance_scale, generator=gen).images[0]
    scene = scene.convert("RGBA")

    # 3. 제품 배치 (구도별 크기 비율)
    tW, tH = scene.size
    frac = 0.72 if composition == "closeup" else 0.45   # 화면 대비 제품 높이 비율
    target_h = int(tH * frac)
    target_w = int(product.width * (target_h / product.height))
    if target_w > tW * 0.9:
        target_w = int(tW * 0.9)
        target_h = int(product.height * (target_w / product.width))

    cx = tW // 2
    baseline = int(tH * (0.9 if composition == "closeup" else 0.82))  # 바닥 기준선
    paste_x = cx - target_w // 2
    paste_y = baseline - target_h

    product_scaled = product.resize((target_w, target_h), Image.LANCZOS)

    result = scene.copy()
    shadow = _contact_shadow((target_w, target_h), blur=max(6, target_w // 12))
    sx = cx - shadow.width // 2
    sy = baseline - shadow.height // 2
    result.alpha_composite(shadow, (sx, sy))
    result.alpha_composite(product_scaled, (paste_x, paste_y))
    result = result.convert("RGB")

    placed_box = (paste_x, paste_y, paste_x + target_w, paste_y + target_h)

    # 4. 약한 재생성으로 경계·조명 녹이기 (제품 실루엣 보호)
    result = _harmonize(
        pipe, result, placed_box, product_scaled,
        blend=0.35, protect=0.85, steps=12, guidance=2.0,
        seed=seed, max_side=max(w16, h16),
    )
    return result, seed


def _harmonize(pipe, composite, box, silhouette,
               blend, protect, steps, guidance, seed, max_side):
    """합성본을 약하게 재생성해 조명/경계를 녹임. 제품 영역은 원본 보존."""
    import torch

    orig = composite.convert("RGB")
    W, H = orig.size
    s = min(max_side / max(W, H), 1.0)
    w16, h16 = preprocessing.to_multiple_of_16(int(W * s), int(H * s))
    work = orig.resize((w16, h16), Image.LANCZOS)

    prompt = (
        "Blend the single beverage product into the scene so it looks naturally "
        "photographed there: match the scene's lighting direction, keep the existing soft "
        "shadow under it, harmonize color temperature and contrast. Exactly ONE product. "
        "Do not add a second cup, duplicate, reflection or ghost copy. The shadow stays a "
        "plain soft shadow with no object inside. Keep the product's logo, label and text "
        "exactly as they are. Photorealistic, single real photograph, no collage seams."
    )
    gen = torch.Generator(device="cpu").manual_seed(seed)
    with torch.inference_mode():
        regen = pipe(image=work, prompt=prompt, width=w16, height=h16,
                     num_inference_steps=steps, guidance_scale=guidance,
                     generator=gen).images[0]
    regen = regen.resize((W, H), Image.LANCZOS)

    a = np.asarray(orig, np.float32)
    b = np.asarray(regen, np.float32)
    blended = a * (1 - blend) + b * blend

    if box is not None and protect > 0:
        mask = _silhouette_mask((W, H), box, silhouette)
        m = np.asarray(mask, np.float32)[..., None] / 255.0 * protect
        blended = blended * (1 - m) + a * m

    return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))
