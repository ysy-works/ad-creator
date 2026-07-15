"""
결과 품질 검증 / 평가 지표.

문서 요구: 예쁘다는 주관 판단만으로 끝내지 말고 항목별 점수화.
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 사람이 채점할 항목 (benchmark CSV 헤더)
EVAL_FIELDS = [
    "product_identity_recognizable", # 원본 제품 정체성 유지
    "logo_overlay_ready",            # 후처리 로고 합성 위치/면 형태가 자연스러움
    "beverage_color_preserved",      # 음료 색상 보존
    "toppings_straw_preserved",      # 토핑/빨대 보존
    "composition_match",             # 선택 구도 반영
    "background_match",              # 선택 배경 반영
    "photorealism",                  # 실제 사진 같은 자연스러움
    "shadow_reflection_accuracy",    # 그림자/반사 정확성
    "no_ai_artifacts",               # AI 왜곡 없음
    "would_post_on_instagram",       # 실제 업로드 의향
]


def color_preservation_score(original_path: str, result_path: str) -> float:
    try:
        from app.preserve_mode import cutout, _alpha_bbox
        o = cutout(Image.open(original_path))
        r = cutout(Image.open(result_path))
        ob, rb = _alpha_bbox(o), _alpha_bbox(r)
        if not ob or not rb:
            return float("nan")

        def mean_rgb(img, box):
            arr = np.asarray(img.crop(box).convert("RGBA"), np.float32)
            m = arr[..., 3] > 10
            return arr[..., :3][m].mean(axis=0)

        oc, rc = mean_rgb(o, ob), mean_rgb(r, rb)
        dist = np.linalg.norm(oc - rc)
        return round(float(max(0.0, 1.0 - dist / 441.67)), 3)  # 441=sqrt(255^2*3)
    except Exception:
        return float("nan")


def make_eval_row(meta: dict, original_path: str) -> dict:
    """
    자동 지표 + 사람 채점용 빈 칸을 합친 한 행(dict).
    """
    row = {
        "output_path": meta.get("output_path", ""),
        "composition": meta.get("composition", ""),
        "background_style": meta.get("background_style", ""),
        "strength": meta.get("strength", ""),
        "mode": meta.get("mode", ""),
        "seed": meta.get("seed", ""),
        "elapsed_seconds": meta.get("elapsed_seconds", ""),
        "auto_color_preservation": color_preservation_score(
            original_path, meta.get("output_path", "")
        ) if meta.get("success") else "",
    }
    for f in EVAL_FIELDS:
        row[f] = ""   # 사람이 1~5로 채움
    return row


def eval_csv_header() -> list[str]:
    base = ["output_path", "composition", "background_style", "strength",
            "mode", "seed", "elapsed_seconds", "auto_color_preservation"]
    return base + EVAL_FIELDS
