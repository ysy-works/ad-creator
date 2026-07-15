"""12개 카테고리별 최종 생성 프롬프트.

공통 조합식 프롬프트보다 우선 적용된다.
제품 보존보다 구도와 스타일 구분이 먼저 살아나도록 각 조합별로 완성 문장화한다.
"""

CATEGORY_PROMPTS = {
    ("closeup", "vivid"): (
        "Create an extreme close-up Instagram beverage product photo in a vivid editorial studio set. "
        "The drink fills 85-95% of the frame height, cropped tightly with large visible rim, straw, topping, syrup streaks and glass texture. "
        "Use bold saturated paper backdrops, colorful geometric blocks, acrylic shapes, coral, teal, yellow, orange and pink accents, crisp directional light and graphic shadows. "
        "Only hints of background are visible because the product is very close. No hand, no top-down view."
    ),
    ("closeup", "wood"): (
        "Create an extreme close-up Instagram cafe beverage product photo. "
        "The drink fills 85-95% of the frame height, cropped tightly with large visible rim, straw, topping, syrup streaks and glass texture. "
        "Use warm wood tones, cozy cafe depth, soft window side light, gentle bokeh, warm highlights, linen or ceramic hints in the blurred background. "
        "Only a small amount of background is visible. No hand, no top-down view."
    ),
    ("closeup", "white"): (
        "Create an extreme close-up premium minimal white studio beverage product photo. "
        "The drink fills 85-95% of the frame height, cropped tightly with large visible rim, straw, topping, syrup streaks and glass texture. "
        "Use white, ivory and pale gray matte surfaces, subtle marble or acrylic texture, soft diffused light, delicate gray shadows and airy negative space. "
        "Only hints of background are visible. No hand, no top-down view."
    ),

    ("medium", "vivid"): (
        "Create a step-back medium Instagram product photo in a vivid colorful studio set. "
        "The drink occupies only 18-30% of the frame height, clearly smaller than close-up, with generous space around it. "
        "Show full product, table surface, layered saturated paper backdrops, colorful geometric blocks, acrylic props, playful editorial styling, crisp directional light, and bold cast shadows. "
        "This must NOT look like a cafe, wood table scene, window cafe photo, or white minimal studio. No hand, no top-down view."
    ),
    ("medium", "wood"): (
        "Create a step-back medium Instagram cafe product photo in a warm wood lifestyle scene. "
        "The drink occupies only 18-30% of the frame height, clearly smaller than close-up, with generous space around it. "
        "Show full product on a natural wooden table with cafe background depth, window side light, soft bokeh, linen napkin, ceramic dish, product-matching fruit or ingredient props, spoon or tray. "
        "Use warm brown tones and cozy premium cafe atmosphere. This must NOT look like a vivid colorful studio or white minimal studio. No hand, no top-down view."
    ),
    ("medium", "white"): (
        "Create a step-back medium Instagram product photo in a bright minimal white studio. "
        "The drink occupies only 18-30% of the frame height, clearly smaller than close-up, with generous clean negative space around it. "
        "Show full product on white, ivory, pale gray, marble or matte acrylic surface with subtle fabric, delicate props, soft diffused light, gentle gray shadows and premium airy mood. "
        "This must NOT look like a cafe, wood table scene, brown interior, or vivid colorful block studio. No hand, no top-down view."
    ),

    ("aerial", "vivid"): (
        "Create a true 90-degree overhead aerial flat-lay Instagram beverage photo in a vivid editorial studio set. "
        "The camera looks directly down; the rim appears circular from above and the drink surface, topping, syrup pattern and straw entry are visible. "
        "Arrange colorful paper backdrops, geometric blocks, acrylic props and bold saturated surfaces around the drink. "
        "Use graphic shadows and playful social-media styling. No front view, no side view, no hand."
    ),
    ("aerial", "wood"): (
        "Create a true 90-degree overhead aerial flat-lay Instagram cafe beverage photo on a warm wooden table. "
        "The camera looks directly down; the rim appears circular from above and the drink surface, topping, syrup pattern and straw entry are visible. "
        "Arrange linen, spoon, product-matching fruit or ingredient props, ceramic dish or tray around the drink with cozy cafe styling and natural window light. "
        "No front view, no side view, no hand."
    ),
    ("aerial", "white"): (
        "Create a true 90-degree overhead aerial flat-lay Instagram beverage photo in a clean white minimal studio. "
        "The camera looks directly down; the rim appears circular from above and the drink surface, topping, syrup pattern and straw entry are visible. "
        "Use white marble, ivory matte surface, pale gray fabric, delicate props, clean negative space and soft diffused shadows. "
        "No front view, no side view, no hand."
    ),

    ("handheld", "vivid"): (
        "Create a handheld lifestyle Instagram beverage photo in a vivid colorful studio set. "
        "A single realistic hand holds the drink naturally; the drink is lifted and not standing alone. "
        "Use bold colorful paper backdrops, geometric blocks, saturated coral, teal, yellow, orange and pink accents, crisp studio light and graphic shadows. "
        "No face, no body, no top-down flat lay."
    ),
    ("handheld", "wood"): (
        "Create a handheld lifestyle Instagram cafe beverage photo in a warm wood scene. "
        "A single realistic hand holds the drink naturally; the drink is lifted and not standing alone. "
        "Use warm wooden table or cafe background, window side light, cozy bokeh, linen, ceramic or product-matching ingredient props in the environment. "
        "No face, no body, no top-down flat lay."
    ),
    ("handheld", "white"): (
        "Create a handheld lifestyle Instagram beverage photo in a bright minimal white studio. "
        "A single realistic hand holds the drink naturally; the drink is lifted and not standing alone. "
        "Use white, ivory, pale gray, marble or matte acrylic surfaces, soft diffused light, clean negative space and delicate shadows. "
        "No face, no body, no top-down flat lay."
    ),
}


# Extra hard product-identity rule injected for open-glass beverages.
OPEN_GLASS_NO_LID_RULE = ("Never add a plastic lid, dome lid, takeaway lid, sealed cap, cover, rim band, or disposable cup top. ""The product is an open transparent glass with visible rim, open top, exposed cream/topping and straw. ""Keep the glass open in every composition, including handheld shots.")
