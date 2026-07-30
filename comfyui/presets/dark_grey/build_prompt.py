"""
build_prompt.py -- dark-grey-metal 프리셋의 핵심 프롬프트 조립 로직

이 파일은 ad_creator_dark_grey_metal_colab.ipynb 노트북에서 build_prompt() 함수만
그대로 추출한 순수 파이썬 코드입니다. Colab 전용 코드(!pip install, google.colab.userdata,
files.upload(), display() 등)는 전부 제외했습니다 -- 이 파일은 Colab 없이 어떤 파이썬
환경에서도 그대로 import해서 쓸 수 있습니다.

이 함수가 하는 일:
    preset(dict) + shot_variant(구도) + beverage_temp(온도) + container_mode(컵 모드)를
    받아서, 이미지 생성 모델(OpenAI gpt-image-2)에 넣을 최종 텍스트 프롬프트 하나를
    조립해서 문자열로 반환합니다.

preset은 reference-preset.json(instagram_dark_grey_metal_v1)을 그대로 로드한 dict입니다.
이 JSON이 반드시 갖고 있어야 하는 최상위 키:
    shot_variants, cup_shapes, container_modes, prop_plating, beverage_rules,
    lighting, color, scene, capture, tone_contract, prompt_blocks,
    preservation_policy, quality_gates

주의: 이 함수는 프롬프트 "텍스트"만 만듭니다. 실제 이미지 생성 API 호출(OpenAI
images.edit), Vision QA(Gemini) 호출은 포함하지 않습니다 -- 그 부분은 노트북의
generate_image() / vision_qa() 함수를 참고하세요.
"""

from __future__ import annotations


def build_prompt(
    preset: dict,
    shot_variant: str,
    beverage_temp: str = "ice",
    container_mode: str = "user_cup",
    product_note: str = "",
    extra_notes: str = "",
) -> str:
    """preset(dict) + shot_variant(str) + beverage_temp("hot"|"ice") + container_mode로 상세한 텍스트 프롬프트를 조립한다.

    shot_variant: "medium" | "close_up" | "aerial" | "handheld"
    beverage_temp: "hot" | "ice" -- handheld 구도 분기 및 (reference_cup 모드일 때) 컵 모양 선택에 사용
    container_mode: "reference_cup" | "user_cup" -- 컵 디자인을 프리셋 레퍼런스에서 가져올지, 사용자 원본에서 가져올지
    """
    if shot_variant not in preset["shot_variants"]:
        raise ValueError(f"Unknown shot_variant: {shot_variant!r}. Choose from {list(preset['shot_variants'])}")
    if beverage_temp not in ("hot", "ice"):
        raise ValueError(f"beverage_temp must be 'hot' or 'ice', got {beverage_temp!r}")
    if container_mode not in ("reference_cup", "user_cup"):
        raise ValueError(f"container_mode must be 'reference_cup' or 'user_cup', got {container_mode!r}")

    variant = preset["shot_variants"][shot_variant]
    light = preset["lighting"]
    color = preset["color"]
    scene = preset["scene"]
    capture = preset["capture"]
    tone = preset["tone_contract"]
    blocks = preset["prompt_blocks"]
    lock = preset["preservation_policy"]
    gates = preset["quality_gates"]
    cup = preset["cup_shapes"][beverage_temp]
    plating_rule = preset["prop_plating"]["rule"]
    modes = preset["container_modes"]

    # handheld는 온도별로 environment_override / props가 dict로 갈라져 있음
    env_override = variant.get("environment_override")
    if env_override is None and "environment_override_by_temp" in variant:
        env_override = variant["environment_override_by_temp"][beverage_temp]

    props = variant.get("props")
    if isinstance(props, dict):
        props = props[beverage_temp]

    lines = []
    lines.append("### ROLE")
    lines.append(
        "You are compositing ONE real user beverage photo into a brand-new, fully "
        "photorealistic cafe environment. The output must look like a single unedited "
        "phone/camera photo taken in one real room under one real light source -- "
        "never a collage, never a sticker-on-background look."
    )

    lines.append("\n### INPUT IMAGE MODE: " + modes[container_mode]["display_name"] + f" ({container_mode})")
    lines.append(modes[container_mode]["description"])
    lines.append(modes["shared_rule"])

    lines.append("\n### SHOT TYPE: " + variant["display_name"] + f" ({shot_variant}, {beverage_temp})")
    lines.append(variant["description"])
    if "hand_description" in variant:
        lines.append("Hand: " + variant["hand_description"])
    if env_override and "composition" in env_override:
        lines.append(env_override["composition"])

    lines.append("\n### OVERALL LOOK (shared mood across shot types)")
    lines.append(blocks["look"])
    lines.append(capture["look"] + ".")
    lines.append("Realism requirement: " + capture["realism"] + ".")

    lines.append("\n### ENVIRONMENT: WALL/BACKGROUND + SURFACE")
    if env_override:
        lines.append(env_override["wall_or_background"] + ".")
        lines.append("Surface: " + env_override["surface"] + ".")
        if "lighting_note" in env_override:
            lines.append(env_override["lighting_note"] + ".")
    else:
        lines.append(scene["background"] + ".")
        lines.append(
            "Below the wall, on a soft horizontal seam, there is " + scene["surface"] + ". "
            "This surface is a different, slightly coarser grey texture family than the wall above it."
        )

    lines.append("\n### CAMERA + FRAMING FOR THIS SHOT")
    lines.append("Camera: " + variant["camera"])
    if "framing" in variant:
        lines.append(variant["framing"])

    lines.append("\n### CUP / VESSEL SHAPE")
    if container_mode == "reference_cup":
        lines.append(cup["vessel"])
        if beverage_temp == "hot" and "color_by_shot" in cup:
            color_rule = cup["color_by_shot"].get(shot_variant, cup["color_by_shot"]["other"])
            lines.append(color_rule)
        lines.append(
            "This is the PRESET's own reference cup design -- it is deliberately NOT the user's original cup. "
            "Image 1 may still visibly contain the user's original cup; treat that source container as excluded "
            "evidence and do not reproduce its silhouette, material, rim, base, handle, lid, straw, sleeve, "
            "label, logo or text. Transfer only the beverage's own color, opacity, ice, foam, layering, garnish "
            "and serving state into this preset vessel."
        )
        lines.append(
            "Keep the adopted preset vessel unbranded. Do not copy any logo, wordmark, label or text from the "
            "user's original cup or from a reference image, and never invent new branding."
        )
    else:  # user_cup
        lines.append(
            "Reconstruct the EXACT cup/container shown in Image 1 -- its class, material, silhouette, color, "
            "rim, base, handle, lid, straw, attached sleeve or wrap, and every other visible component -- "
            "faithfully and natively for this new camera and light. Preserve component presence as well as "
            "appearance: keep a handle, lid, straw, sleeve or wrap only when it is visible in Image 1, and "
            "never add one when it is absent. Do NOT apply this preset's reference mug/glass color, handle, "
            "straw, sleeve, label or saucer rules in this mode; Image 1 is the source of truth for the vessel."
        )
        lines.append(
            "Hard lock: preserve the source-visible straw and lid state exactly; retain each one only when visible in "
            "Image 1, and never delete, substitute or invent either component."
        )
        lines.append(
            "Preserve the source-visible immediate serving assembly too, including a saucer, coaster or spoon "
            "when present. A handheld shot may move that assembly naturally to the supporting surface rather "
            "than placing it inside the gripping hand, but must not redesign it."
        )
        lines.append(
            "Preserve every real source-visible logo, wordmark or label exactly as it appears on that same "
            "cup surface, with matching placement, scale and orientation. If it is camera-visible in Image 1, "
            "keep it camera-visible after reconstruction rather than rotating, blanking, hiding or replacing "
            "it. If no branding is visible in Image 1, add none. Never invent or copy reference-image branding."
        )
    if cup.get("no_straw") and container_mode == "reference_cup":
        lines.append(preset["beverage_rules"]["no_straw_for_ice"])
    if cup.get("no_saucer") and container_mode == "reference_cup":
        lines.append(preset["beverage_rules"]["no_saucer_for_ice"])

    # 이 구도가 자기만의 조명(lighting_note)을 갖고 있으면(예: medium의 저녁 실내조명),
    # 공용 '자연광' 섹션은 건너뛴다 -- 안 그러면 '자연광이다'와 '실내조명이다'가 동시에 들어가 모순됨
    has_own_lighting = bool(env_override and "lighting_note" in env_override)
    if not has_own_lighting:
        lines.append("\n### LIGHTING (shared natural light unless this shot overrides it above)")
        lines.append(
            light["type"] + ", arriving from the " + light["direction"]
            + " (azimuth ~" + str(light["azimuth_degrees"]) + " degrees, elevation ~"
            + str(light["elevation_degrees"]) + " degrees). Intensity: " + light["intensity"]
            + ". Contrast: " + light["contrast"] + ". Shadow behaviour: " + light["shadow"] + ". "
            + light["highlight_control"] + "."
        )

    lines.append("\n### COLOR & GRADE (shared)")
    lines.append(
        "White balance approximately " + str(color["white_balance_kelvin"]) + "K, " + color["temperature"] + ". "
        "Black point: " + color["black_point"] + ". Contrast character: " + color["contrast"] + ". "
        "Saturation: " + color["saturation"] + ". "
        "Approximate palette (for reference, do not render as flat color blocks): "
        + ", ".join(color["palette_hex"]) + "."
    )

    lines.append("\n### TEXTURE / MATERIALS (shared)")
    lines.append(scene["texture"] + ".")
    lines.append("Fine-grain realism: " + capture["grain"] + ".")
    lines.append("Include tiny natural imperfections such as: " + "; ".join(capture["imperfections"]) + ".")

    lines.append("\n### PROPS FOR THIS SHOT")
    if props:
        lines.append("Use only: " + "; ".join(props) + ".")
        lines.append("Prop plating rule (always applies): " + plating_rule)
    else:
        lines.append(
            "CRITICAL: this shot must include NO food prop of any kind -- no bread, pastry, cake, cookie, "
            "plate, or napkin anywhere in frame. Only the beverage (and, if this is a handheld shot, the hand "
            "holding or resting near it) appear."
        )

    lines.append("\n### PRODUCT / IDENTITY PRESERVATION (hard constraints)")
    lines.append("- " + "\n- ".join(lock["hard_lock"]))
    if container_mode == "reference_cup":
        lines.append(
            "- active mode identity: reconstruct the selected preset vessel natively and discard all source "
            "container geometry, components, serving assembly and branding; preserve only the source beverage "
            "and serving state; obey the preset vessel's own hot-saucer or iced-no-saucer rule"
        )
    else:
        lines.append(
            "- active mode identity: reconstruct the complete Image 1 vessel natively, including the presence "
            "or absence of each handle, lid, straw, sleeve, wrap, immediate serving assembly and source-visible "
            "label; never substitute, simplify, rotate away or blank those properties"
        )
    lines.append(blocks["preservation"])

    lines.append("\n### WHAT TO AVOID (shared)")
    lines.append(blocks["negative"])
    lines.append("Forbidden surface readings: " + ", ".join(tone["forbidden_surface_reading"]) + ".")
    if "negative_extra" in variant:
        lines.append("Shot-specific: " + variant["negative_extra"])

    lines.append("\n### QUALITY BAR (self-check before finalizing)")
    lines.append("- " + "\n- ".join(gates.values()))

    if product_note:
        lines.append("\n### PRODUCT NOTE FROM USER")
        lines.append(product_note)

    if extra_notes:
        lines.append("\n### REVISION NOTES (apply these on top of everything above)")
        lines.append(extra_notes)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 사용 예시
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import sys

    # 사용법: python build_prompt.py path/to/reference-preset.json [shot_variant] [beverage_temp] [container_mode]
    preset_path = sys.argv[1] if len(sys.argv) > 1 else "reference-preset.json"
    shot_variant = sys.argv[2] if len(sys.argv) > 2 else "medium"
    beverage_temp = sys.argv[3] if len(sys.argv) > 3 else "ice"
    container_mode = sys.argv[4] if len(sys.argv) > 4 else "user_cup"

    with open(preset_path, "r", encoding="utf-8") as f:
        preset = json.load(f)

    prompt = build_prompt(
        preset,
        shot_variant,
        beverage_temp=beverage_temp,
        container_mode=container_mode,
        product_note="사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지",
    )

    print(f"=== {shot_variant} / {beverage_temp} / {container_mode} ===")
    print(prompt)
