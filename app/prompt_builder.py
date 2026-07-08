
def build_swap_prompt(
    product_desc: str = "the product",
    extra_instruction: str = "",
    quality_guard: str = "",
) -> str:
    """
    Args:
        product_desc: 사용자 제품을 가리키는 짧은 설명(선택). 예: "a plastic cup of iced drink"
        extra_instruction: 추가 지시(선택)
        quality_guard: 공통 품질 가드(선택)

    Returns:
        Kontext용 편집 프롬프트(영어). (참조 이미지 2장은 파이프라인에서 전달)
    """
    parts = [
        # 첫 이미지=사용자 제품, 둘째=템플릿 장면 이라는 전제로 지시
        f"Replace the product in the scene with {product_desc} shown in the reference image. "
        "Place the user's product naturally into the exact same scene, "
        "matching the scene's camera angle, framing, lighting direction, shadows and color mood, "
        "so it looks like the user's product was originally photographed there.",

        # 로고/디테일 보존 — 접근 Y 약점 방어
        "Preserve the user's product exactly: keep its real shape, label, logo, text and colors "
        "unchanged and clearly readable. Do not redraw or restyle the logo or text.",

        # 배경은 템플릿 그대로
        "Keep the background scene, surface, props and overall composition from the scene image unchanged; "
        "only the product itself is swapped.",

        "The result must look like a single real photograph taken by a professional photographer, "
        "not a collage or CGI render.",
    ]
    if extra_instruction:
        parts.append(extra_instruction)
    if quality_guard:
        parts.append(quality_guard)
    return " ".join(p for p in parts if p)
