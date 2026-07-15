import os
import sys
import time
import uuid
from datetime import datetime, timezone

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config
from app import model_loader
from app import preprocessing
from app.prompt_builder import build_prompt


def _new_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def _generator(seed):
    import torch
    if seed is None:
        seed = int(torch.randint(0, 2**31 - 1, (1,)).item())
    return torch.Generator(device="cpu").manual_seed(seed), seed


def _run_kontext(pipe, image, prompt, seed, steps, guidance, w, h):
    import torch
    gen, used_seed = _generator(seed)
    w, h = preprocessing.to_multiple_of_16(w, h)
    with torch.inference_mode():
        out = pipe(
            image=image, prompt=prompt,
            width=w, height=h,
            num_inference_steps=steps, guidance_scale=guidance,
            generator=gen,
        ).images[0]
    return out, used_seed


def generate_beverage_image(
    image_path: str,
    composition: str,
    background_style: str,
    strength: str = "medium",
    seed: int = None,
    guidance_scale: float = None,
    num_inference_steps: int = None,
    width: int = None,
    height: int = None,
    output_dir: str = None,
) -> dict:

    t0 = time.time()
    output_dir = output_dir or config.OUTPUT_DIR
    guidance_scale = guidance_scale or config.DEFAULT_GUIDANCE
    num_inference_steps = num_inference_steps or config.DEFAULT_STEPS
    width = width or config.DEFAULT_WIDTH
    height = height or config.DEFAULT_HEIGHT

    try:
        # 옵션 검증
        if composition not in config.COMPOSITIONS:
            raise config.PipelineError(
                config.ErrorCode.UNSUPPORTED_COMPOSITION, composition)
        if background_style not in config.BACKGROUND_STYLES:
            raise config.PipelineError(
                config.ErrorCode.UNSUPPORTED_BACKGROUND_STYLE, background_style)
        if strength not in config.STRENGTHS:
            raise config.PipelineError(
                config.ErrorCode.UNSUPPORTED_STRENGTH, strength)

        # 전처리 (EXIF/RGB/비율유지)
        image = preprocessing.load_and_prepare(image_path, width, height)

        # 프롬프트
        prompt = build_prompt(composition, background_style, strength)

        # 모델
        pipe = model_loader.load_pipeline()

        mode = config.mode_for(composition)

        # 전체 재생성: 제품 픽셀을 붙여넣지 않고, 입력 제품을 시각 레퍼런스로 사용한다.
        result_img, used_seed = _run_kontext(
            pipe, image, prompt, seed,
            num_inference_steps, guidance_scale, width, height,
        )

        # 저장
        job_id = _new_id()
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"{job_id}.png")
        try:
            result_img.save(out_path)
        except Exception as e:
            raise config.PipelineError(config.ErrorCode.OUTPUT_SAVE_FAILED, str(e))

        return {
            "success": True,
            "output_path": out_path,
            "composition": composition,
            "background_style": background_style,
            "strength": strength,
            "seed": used_seed,
            "width": result_img.width,
            "height": result_img.height,
            "elapsed_seconds": round(time.time() - t0, 2),
            "model": config.MODEL_ID,
            "mode": mode,
            "postprocess": {
                "logo_overlay_recommended": True,
                "note": (
                    "Generated logo/text may be approximate. If an exact brand mark is "
                    "required, overlay the original logo shape in a later postprocess step."
                ),
            },
        }

    except config.PipelineError as e:
        return {"success": False, "error_code": e.code, "error_message": e.message}
    except Exception as e:
        # CUDA OOM 별도 분류
        name = type(e).__name__
        if "OutOfMemory" in name or "out of memory" in str(e).lower():
            _try_recover_oom()
            return {"success": False,
                    "error_code": config.ErrorCode.CUDA_OUT_OF_MEMORY,
                    "error_message": str(e)}
        return {"success": False,
                "error_code": config.ErrorCode.GENERATION_FAILED,
                "error_message": f"{name}: {e}"}


def _try_recover_oom():
    """OOM 후 캐시 정리."""
    try:
        import torch, gc
        gc.collect()
        torch.cuda.empty_cache()
    except Exception:
        pass
