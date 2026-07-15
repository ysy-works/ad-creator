import os

# ── 경로 ─────────────────────────────────────────────
BASE_DIR = os.environ.get(
    "BVS_BASE_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.environ.get("BVS_OUTPUT_DIR", os.path.join(BASE_DIR, "output"))

# ── 모델 ─────────────────────────────────────────────
MODEL_ID = os.environ.get("BVS_MODEL_ID", "black-forest-labs/FLUX.1-Kontext-dev")
QUANT = os.environ.get("BVS_QUANT", "nf4")          
TORCH_DTYPE = "bfloat16"                              

# 메모리 최적화 토글
ENABLE_MODEL_CPU_OFFLOAD = True     # 우선 사용
ENABLE_SEQUENTIAL_OFFLOAD = False   # OOM 시 최후 수단
ENABLE_VAE_SLICING = True
ENABLE_VAE_TILING = True

# ── 추론 기본값 ──────────────────────────────────────
# 인스타 피드용 4:5 세로. L4 메모리 고려 832x1040 시작점.
DEFAULT_WIDTH = 832
DEFAULT_HEIGHT = 1040
DEFAULT_STEPS = 28
DEFAULT_GUIDANCE = 2.5              
DEFAULT_STRENGTH = "medium"
DEFAULT_SEED = None

# ── 구도 / 배경 옵션 ─────────────────────────────────
COMPOSITIONS = ["closeup", "medium", "aerial", "handheld"]
BACKGROUND_STYLES = ["vivid", "wood", "white"]
STRENGTHS = ["low", "medium", "high"]

COMPOSITION_NAMES = {
    "closeup": "클로즈업",
    "medium": "미디움샷",
    "aerial": "항공샷",
    "handheld": "손에 들고 있는 샷",
}
BACKGROUND_NAMES = {
    "vivid": "비비드 색감",
    "wood": "우드 색감",
    "white": "화이트 계열",
}

# ── 생성 모드 ────────────────────────────────────────
PRESERVE_MODE_COMPOSITIONS = set()
RECREATE_MODE_COMPOSITIONS = set(COMPOSITIONS)
DEFAULT_MODE = "recreate"


def mode_for(composition: str) -> str:
    if composition in COMPOSITIONS:
        return DEFAULT_MODE
    return "unsupported"


# ── 오류 코드 (백엔드 공유) ──────────────────────────
class ErrorCode:
    INVALID_IMAGE = "INVALID_IMAGE"
    UNSUPPORTED_COMPOSITION = "UNSUPPORTED_COMPOSITION"
    UNSUPPORTED_BACKGROUND_STYLE = "UNSUPPORTED_BACKGROUND_STYLE"
    UNSUPPORTED_STRENGTH = "UNSUPPORTED_STRENGTH"
    CUDA_OUT_OF_MEMORY = "CUDA_OUT_OF_MEMORY"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    GENERATION_FAILED = "GENERATION_FAILED"
    OUTPUT_SAVE_FAILED = "OUTPUT_SAVE_FAILED"


class PipelineError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message or code
        super().__init__(f"[{code}] {self.message}")
