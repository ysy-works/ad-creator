"""
모델 로더 — FLUX.1 Kontext dev.

서버 시작/첫 요청 시 1회만 로드하고 캐시해서 재사용
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config

_PIPE = None


def _load_dotenv():
    """Load kh_v2/.env into environment variables without overwriting existing values."""
    env_path = os.path.join(config.BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _hf_token():
    _load_dotenv()
    return (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or os.environ.get("HF_API_TOKEN")
    )


def _dtype():
    import torch
    return torch.bfloat16 if config.TORCH_DTYPE == "bfloat16" else torch.float16


def load_pipeline():
    global _PIPE
    if _PIPE is not None:
        return _PIPE

    import torch
    try:
        from diffusers import FluxKontextPipeline
        token = _hf_token()

        if config.QUANT == "nf4":
            from diffusers import FluxTransformer2DModel
            from diffusers import BitsAndBytesConfig as DiffBnb
            from transformers import T5EncoderModel
            from transformers import BitsAndBytesConfig as TfBnb

            print("[loader] transformer (nf4)...")
            transformer = FluxTransformer2DModel.from_pretrained(
                config.MODEL_ID, subfolder="transformer",
                quantization_config=DiffBnb(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=_dtype(),
                ),
                torch_dtype=_dtype(),
                token=token,
            )
            print("[loader] T5 (4bit)...")
            text_encoder_2 = T5EncoderModel.from_pretrained(
                config.MODEL_ID, subfolder="text_encoder_2",
                quantization_config=TfBnb(load_in_4bit=True),
                torch_dtype=_dtype(),
                token=token,
            )
            pipe = FluxKontextPipeline.from_pretrained(
                config.MODEL_ID, transformer=transformer,
                text_encoder_2=text_encoder_2, torch_dtype=_dtype(),
                token=token,
            )
        else:
            pipe = FluxKontextPipeline.from_pretrained(
                config.MODEL_ID, torch_dtype=_dtype(), token=token
            )

        # 메모리 최적화
        if config.ENABLE_SEQUENTIAL_OFFLOAD:
            pipe.enable_sequential_cpu_offload()
        elif config.ENABLE_MODEL_CPU_OFFLOAD:
            pipe.enable_model_cpu_offload()
        else:
            pipe = pipe.to("cuda")

        if config.ENABLE_VAE_SLICING:
            pipe.vae.enable_slicing()
        if config.ENABLE_VAE_TILING:
            pipe.vae.enable_tiling()

        print("[loader] ready.")
        _PIPE = pipe
        return _PIPE

    except torch.cuda.OutOfMemoryError as e:
        raise config.PipelineError(config.ErrorCode.MODEL_LOAD_FAILED, f"OOM: {e}")
    except Exception as e:
        raise config.PipelineError(config.ErrorCode.MODEL_LOAD_FAILED, str(e))


def unload():
    global _PIPE
    if _PIPE is not None:
        del _PIPE
        _PIPE = None
        import torch
        torch.cuda.empty_cache()
