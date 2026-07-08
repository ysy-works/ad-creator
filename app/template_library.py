import os
import random

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def category_dir(style_id: str, composition_id: str) -> str:
    return os.path.join(config.TEMPLATES_DIR, style_id, composition_id)


def list_templates(style_id: str, composition_id: str) -> list[str]:
    """해당 카테고리 폴더 안의 템플릿 이미지 경로 목록."""
    d = category_dir(style_id, composition_id)
    if not os.path.isdir(d):
        return []
    return [
        os.path.join(d, f)
        for f in sorted(os.listdir(d))
        if os.path.splitext(f)[1].lower() in IMAGE_EXTS
    ]


def pick_template(
    style_id: str,
    composition_id: str,
    template_name: str | None = None,
    seed: int | None = None,
) -> str:
    """
    카테고리에서 템플릿 1장 선택.
      - template_name 지정 시 그 파일 사용(파일명 일치)
      - 아니면 랜덤 선택 (seed로 재현 가능)
    """
    templates = list_templates(style_id, composition_id)
    if not templates:
        raise FileNotFoundError(
            f"템플릿이 없습니다: {category_dir(style_id, composition_id)} "
            f"(이 폴더에 사진을 넣어주세요)"
        )
    if template_name:
        for t in templates:
            if os.path.basename(t) == template_name:
                return t
        raise FileNotFoundError(
            f"'{template_name}' 템플릿을 찾을 수 없습니다. "
            f"available: {[os.path.basename(t) for t in templates]}"
        )
    rng = random.Random(seed)
    return rng.choice(templates)


def library_status() -> list[dict]:
    """
    12개 카테고리별 템플릿 보유 현황.
    (어느 폴더가 비었는지 점검용)
    """
    out = []
    for style_id in config.STYLES:
        for composition_id in config.COMPOSITIONS:
            n = len(list_templates(style_id, composition_id))
            out.append({
                "style_id": style_id,
                "composition_id": composition_id,
                "count": n,
            })
    return out
