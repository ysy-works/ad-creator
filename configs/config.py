import os

BASE_DIR = os.environ.get(
    "PSG_BASE_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

# ── 템플릿 라이브러리 ─────────────────────────────────
# templates_lib/{style_id}/{composition_id}/*.jpg
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates_lib")

STYLES = ["neutral_white_minimal", "wood", "vivid_color"]
COMPOSITIONS = ["product_large", "product_center", "aerial_shot", "handheld_lifestyle"]

STYLE_NAMES = {
    "neutral_white_minimal": "뉴트럴 화이트 미니멀",
    "wood": "우드 디자인",
    "vivid_color": "비비드 컬러",
}
COMPOSITION_NAMES = {
    "product_large": "클로즈업",
    "product_center": "미디엄",
    "aerial_shot": "항공샷",
    "handheld_lifestyle": "손으로 들고 있는 샷",
}

# ── 출력 ─────────────────────────────────────────────
OUTPUTS_DIR = os.environ.get("PSG_OUTPUTS_DIR", os.path.join(BASE_DIR, "outputs"))

# ── 모델 ─────────────────────────────────────────────
# FLUX.1 Kontext dev: 다중 이미지 참조 편집(제품+장면 → 합성) 지원
GEN_MODEL_ID = os.environ.get("PSG_MODEL_ID", "black-forest-labs/FLUX.1-Kontext-dev")
# 상시 가동 + 넉넉한 VRAM(L4 24GB↑)이면 양자화 없이 bf16로 올려 품질↑ 가능.
# VRAM 빠듯하면 "nf4"로. (env PSG_QUANT=nf4)
QUANT = os.environ.get("PSG_QUANT", "nf4")   # "nf4" | "none"

GEN_NUM_STEPS = int(os.environ.get("PSG_STEPS", "30"))
GEN_GUIDANCE = float(os.environ.get("PSG_GUIDANCE", "2.5"))
GEN_MAX_SIDE = int(os.environ.get("PSG_MAX_SIDE", "1024"))

# ── 품질 가드 (negative를 긍정형으로) ────────────────
QUALITY_GUARD = (
    "Keep the product shape sharp and undistorted with no deformation. "
    "High quality, sharp focus, no blur. No watermark, no added text overlay, "
    "no extra unrelated objects. Natural balanced colors, realistic natural lighting."
)

DEFAULT_SEED = None
