"""제품 레퍼런스 규칙, 품질/금지 규칙, 강도 규칙 프롬프트."""

PRESERVATION_RULES = (
    "The input image is the source of truth for the beverage product. The generated result "
    "must show the SAME beverage product, not a similar new drink. Preserve the exact product "
    "category and all visible product-defining details: transparent cylindrical glass, tall "
    "slender proportions, rounded rim, thick transparent glass base, pale creamy yellow drink, "
    "irregular caramel/yellow syrup streaks on the inner glass wall, creamy blended texture, "
    "white/yellow ice-cream or cream topping on top, glossy yellow sauce on the topping, and "
    "one thick white or translucent straw entering from the back/upper-left area. Keep the "
    "original no-logo/no-label state. Do not add any logo, label, sticker, badge, typography, "
    "brand mark or printed cup design. Do not change the glass into a paper cup, plastic cup, "
    "takeaway cup, bottle, can, mug or branded package. Do not simplify the drink into a plain "
    "smooth latte; keep the messy syrup swirls and topping details. Keep the product scale, "
    "camera angle and visible top rim close to the input unless the selected composition "
    "absolutely requires a small framing adjustment. Regenerate only the surrounding scene, "
    "surface, background, lighting, shadow and color grading so the product looks naturally "
    "photographed in a better environment."
)

QUALITY_RULES = (
    "Photorealistic product photography with natural materials, physically plausible lighting, "
    "accurate glass transparency, realistic liquid texture, realistic contact shadows, and "
    "high-quality commercial color grading. Exactly one beverage product. Avoid illustration, "
    "painting, cartoon, 3D render, CGI, fake reflections, excessive HDR, extreme blur, invented "
    "brand names, fake readable text, added logos, added labels, changed container material, added plastic lid, added dome lid, added takeaway lid, "
    "changed cup type, added plastic lid, added dome lid, added takeaway lid, covered top, changed straw color, missing straw, missing syrup streaks, missing topping, "
    "duplicated products, floating objects, warped glass, incorrect liquid levels, mismatched "
    "perspective and unrealistic shadows, props that do not match the beverage flavor, coffee beans for fruit smoothies, espresso props for non-coffee drinks, and unrelated ingredient props."
)

STRENGTH_RULES = {
    "low": (
        "Very conservative product-preserving edit. Keep the product almost identical to the "
        "input. Keep the same container, proportions, angle, rim, straw, syrup pattern, topping "
        "and drink color. Change mainly the background, table, lighting and color grading."
    ),
    "medium": (
        "Polish the scene into a professional photoshoot, but the beverage product must still "
        "look almost the same as the input. Do not redesign the drink."
    ),
    "high": (
        "Change the surrounding scene more strongly, but still preserve the same beverage product "
        "identity, glass type, straw, topping, syrup streaks and no-logo state."
    ),
}


# Extra hard product-identity rule injected for open-glass beverages.
OPEN_GLASS_NO_LID_RULE = ("Never add a plastic lid, dome lid, takeaway lid, sealed cap, cover, rim band, or disposable cup top. ""The product is an open transparent glass with visible rim, open top, exposed cream/topping and straw. ""Keep the glass open in every composition, including handheld shots.")
