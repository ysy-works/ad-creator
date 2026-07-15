"""구도별 프롬프트 프리셋."""

COMPOSITION_PROMPTS = {
    "closeup": (
        "HIGHEST PRIORITY COMPOSITION: EXTREME CLOSE-UP PRODUCT DETAIL SHOT. "
        "The beverage must fill 85 to 95 percent of the frame height. Crop tightly. "
        "Show large visible details: rim, straw, topping, syrup, glass texture, highlights. "
        "Only hints of background. This must look dramatically closer than medium shot. "
        "Use one consistent front-facing or slightly high camera angle for the entire glass. The glass body must remain straight and vertical, with parallel sides and a physically consistent elliptical rim. Do not mix front view body with overhead rim perspective. No wide table scene, no top-down view, no hand."
    ),
    "medium": (
        "HIGHEST PRIORITY COMPOSITION: STEP-BACK MEDIUM ENVIRONMENTAL PRODUCT SHOT. "
        "Photograph the beverage as if the camera stepped one pace backward from the product. "
        "The beverage must occupy only 18 to 30 percent of the frame height, clearly smaller "
        "than close-up. Keep the full product visible, centered or slightly off-center, with "
        "generous table surface, background layers, props, negative space, window light, and "
        "Instagram cafe/studio atmosphere visible around it. The scene should feel wider, "
        "more spacious, and more environmental, while the product remains the main subject. "
        "Use one consistent front-facing or slightly high camera angle for the entire glass. The glass body must remain straight and vertical, with parallel sides and a physically consistent elliptical rim. Do not mix front view body with overhead rim perspective. No tight crop, no top-down view, no hand."
    ),
    "aerial": (
        "HIGHEST PRIORITY COMPOSITION: TRUE OVERHEAD AERIAL FLAT LAY. "
        "Camera is directly above the drink at 90 degrees. The rim must appear circular from top view. "
        "The tall glass side wall should be mostly hidden by overhead perspective. "
        "Show tabletop layout, props around the drink, shadows falling outward on the surface. "
        "This must not be a raised front view or three-quarter view. No hand."
    ),
    "handheld": (
        "HIGHEST PRIORITY COMPOSITION: HANDHELD LIFESTYLE PHOTO. "
        "A single realistic hand must hold the beverage. The drink is lifted or naturally held, not standing alone. "
        "Show hand, wrist, natural grip, skin texture, contact shadows. "
        "Keep the drink visible. No face, no body, no top-down flat lay."
    ),
}
