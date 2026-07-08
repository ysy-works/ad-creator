import os
import sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config
from app import template_library as tl
from app.prompt_builder import build_swap_prompt
from app.utils import new_job_id, save_result

_GENERATOR = None


def get_generator():
    """서버 부팅 시 미리 호출해 모델을 상주시키기."""
    global _GENERATOR
    if _GENERATOR is None:
        from app.generator import ProductSwapGenerator
        _GENERATOR = ProductSwapGenerator(config.GEN_MODEL_ID, quant=config.QUANT)
    return _GENERATOR


def list_categories() -> dict:
    """프론트 선택 UI용: 스타일/구도 목록 + 이름."""
    return {
        "styles": [
            {"style_id": s, "name": config.STYLE_NAMES.get(s, s)}
            for s in config.STYLES
        ],
        "compositions": [
            {"composition_id": c, "name": config.COMPOSITION_NAMES.get(c, c)}
            for c in config.COMPOSITIONS
        ],
    }


def run_swap(
    product_image_path: str,
    style_id: str,
    composition_id: str,
    template_name: str | None = None,
    product_desc: str = "the product",
    seed: int | None = None,
    extra_instruction: str = "",
    num_inference_steps: int | None = None,
    output_dir: str | None = None,
) -> dict:
    """
    Args:
        product_image_path: 사용자 업로드 제품 사진
        style_id:           neutral_white_minimal / wood / vivid_color
        composition_id:     product_large / product_center / aerial_shot / handheld_lifestyle
        template_name:      특정 템플릿 파일명 지정(선택). 없으면 랜덤
        product_desc:       제품 짧은 설명(선택), 예: "a plastic cup of iced yuzu smoothie"
        seed, extra_instruction, num_inference_steps, output_dir: 선택

    Returns:
        meta dict (files.result 등 포함)
    """
    if style_id not in config.STYLES:
        raise KeyError(f"style_id '{style_id}' invalid. {config.STYLES}")
    if composition_id not in config.COMPOSITIONS:
        raise KeyError(f"composition_id '{composition_id}' invalid. {config.COMPOSITIONS}")

    output_dir = output_dir or config.OUTPUTS_DIR
    steps = num_inference_steps or config.GEN_NUM_STEPS

    # 1. 템플릿 선택
    template_path = tl.pick_template(style_id, composition_id, template_name, seed)

    # 2. 프롬프트
    prompt = build_swap_prompt(
        product_desc=product_desc,
        extra_instruction=extra_instruction,
        quality_guard=config.QUALITY_GUARD,
    )

    # 3. 생성
    product_image = Image.open(product_image_path).convert("RGB")
    scene_image = Image.open(template_path).convert("RGB")
    gen = get_generator()
    result_image, used_seed = gen.swap(
        product_image=product_image,
        scene_image=scene_image,
        prompt=prompt,
        seed=seed if seed is not None else config.DEFAULT_SEED,
        num_inference_steps=steps,
        guidance_scale=config.GEN_GUIDANCE,
        max_side=config.GEN_MAX_SIDE,
    )

    # 4. 저장
    job_id = new_job_id()
    meta = save_result(
        output_dir=output_dir,
        job_id=job_id,
        result_image=result_image,
        input_image=product_image,
        template_image=scene_image,
        metadata={
            "style_id": style_id,
            "style_name": config.STYLE_NAMES.get(style_id, style_id),
            "composition_id": composition_id,
            "composition_name": config.COMPOSITION_NAMES.get(composition_id, composition_id),
            "template_used": template_path,
            "prompt": prompt,
            "product_desc": product_desc,
            "seed": used_seed,
            "params": {
                "model": config.GEN_MODEL_ID,
                "quant": config.QUANT,
                "num_inference_steps": steps,
                "guidance_scale": config.GEN_GUIDANCE,
                "max_side": config.GEN_MAX_SIDE,
                "extra_instruction": extra_instruction,
            },
        },
    )
    return meta
