import torch
from PIL import Image


def _resize_keep_ratio(image: Image.Image, max_side: int) -> Image.Image:
    w, h = image.size
    scale = min(max_side / max(w, h), 1.0)
    new_w = max(16, int(w * scale) // 16 * 16)
    new_h = max(16, int(h * scale) // 16 * 16)
    return image.resize((new_w, new_h), Image.LANCZOS)


def stitch_side_by_side(
    product: Image.Image, scene: Image.Image, gap: int = 16
) -> tuple[Image.Image, int]:
    """
    [제품 | 장면]을 같은 높이로 좌우 결합. 흰 여백 gap으로 구분.
    Returns: (합쳐진 이미지, 장면이 시작되는 x좌표)
    """
    target_h = min(product.height, scene.height)
    def _fit_h(im):
        r = target_h / im.height
        return im.resize((max(16, int(im.width * r)), target_h), Image.LANCZOS)
    p = _fit_h(product.convert("RGB"))
    s = _fit_h(scene.convert("RGB"))
    W = p.width + gap + s.width
    canvas = Image.new("RGB", (W, target_h), (255, 255, 255))
    canvas.paste(p, (0, 0))
    canvas.paste(s, (p.width + gap, 0))
    return canvas, p.width + gap


class ProductSwapGenerator:
    """[제품, 장면] 참조 → 제품이 교체된 장면 이미지."""

    def __init__(self, model_id: str, quant: str = "nf4"):
        from diffusers import FluxKontextPipeline

        if quant == "nf4":
            from diffusers import FluxTransformer2DModel
            from diffusers import BitsAndBytesConfig as DiffBnb
            from transformers import T5EncoderModel
            from transformers import BitsAndBytesConfig as TfBnb

            print("[gen] loading transformer (nf4)...")
            transformer = FluxTransformer2DModel.from_pretrained(
                model_id, subfolder="transformer",
                quantization_config=DiffBnb(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                ),
                torch_dtype=torch.bfloat16,
            )
            print("[gen] loading T5 (4bit)...")
            text_encoder_2 = T5EncoderModel.from_pretrained(
                model_id, subfolder="text_encoder_2",
                quantization_config=TfBnb(load_in_4bit=True),
                torch_dtype=torch.bfloat16,
            )
            self.pipe = FluxKontextPipeline.from_pretrained(
                model_id, transformer=transformer, text_encoder_2=text_encoder_2,
                torch_dtype=torch.bfloat16,
            )
            self.pipe.enable_model_cpu_offload()
        else:
            print("[gen] loading full bf16...")
            self.pipe = FluxKontextPipeline.from_pretrained(
                model_id, torch_dtype=torch.bfloat16
            ).to("cuda")

        print("[gen] ready.")

    @torch.inference_mode()
    def swap(
        self,
        product_image: Image.Image,
        scene_image: Image.Image,
        prompt: str,
        seed: int | None = None,
        num_inference_steps: int = 30,
        guidance_scale: float = 2.5,
        max_side: int = 1024,
    ) -> tuple[Image.Image, int]:
        """
        Returns: (결과 이미지, 사용된 seed)
        결과는 스티치 이미지에서 '장면 쪽'만 잘라내 반환.
        """
        stitched, scene_x = stitch_side_by_side(product_image, scene_image)
        stitched = _resize_keep_ratio(stitched, max_side)

        if seed is None:
            seed = int(torch.randint(0, 2**31 - 1, (1,)).item())
        generator = torch.Generator(device="cpu").manual_seed(seed)

        result = self.pipe(
            image=stitched,
            prompt=prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=generator,
        ).images[0]

        # [디버그] 크롭하지 않고 모델이 만든 전체 결과를 그대로 반환
        # (스티치 입력에 대해 Kontext가 실제로 무엇을 출력하는지 눈으로 확인)
        return result, seed

    def unload(self):
        del self.pipe
        torch.cuda.empty_cache()
