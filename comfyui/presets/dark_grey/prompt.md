# `dark_grey` -- 사용한 프롬프트 (프롬프트 길이 초과 수정판)

OpenAI `/v1/images/edits` 32,000자 제한 초과 문제를 해결한 버전입니다. 핵심 규칙(구도/조명/컵모드)은 그대로 두고 중복 문장만 압축했습니다. `beverage_temp="ice"` 기준, 4구도 x 2컵모드 = 8개 조합입니다.

## container_mode = `user_cup`

### medium / ice / user_cup (10975자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 사용자 컵 버전 (user_cup)
The full original photo (cup + beverage) is sent. Cup shape/material/color/handle/lid/logo are reconstructed faithfully from the user's own photo -- this preset's cup_shapes color/handle/saucer rules do NOT apply in this mode; the user's own cup is the source of truth.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 미디엄 컷 (1층 창가 바 좌석) (medium, ice)
A ground-floor window-bar-seat composition: the viewer is seated at a black bar counter along a glass wall, looking out at a soft-focus daytime street-level scene -- referencing the light_sample photo's exterior (a street-level plaza, blurred building facades, natural daylight), not a night skyline. Lighting is natural daylight passing through the glass, with no interior lamp or pendant fixture of any kind -- referencing the glass_background sample photo's bar-counter-to-exterior ratio and its non-beverage props (a bare folded-open magazine (nothing resting on it), a small potted plant).

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
A full glass wall/window with slim black mullions, at ground-floor street level (not a high-rise). Beyond it: a soft-focus DAYTIME street scene -- light paving, blurred building facades in muted warm-neutral tones, maybe an outdoor bistro table/stool -- never sharp or legible. No text/signage on the glass. No interior pendant/lamp/bulb/wire-cage fixture visible anywhere. CRITICAL: brightness here must MATCH the other three shots (close_up, aerial, handheld) -- not darker; the space reads as an open, currently-lit cafe, never closed/unlit..
Surface: a black-stained wood bar-height counter/table running along the base of the glass wall, narrower than a full windowsill -- the kind of counter with bar stools where a single person sits facing the window..

### CAMERA + FRAMING FOR THIS SHOT
Camera: 35-50mm equivalent, 15-35 degrees downward, camera at seated bar-stool eye height (~110-130cm).
The product occupies roughly 30-40% of frame width in the lower-right area, standing directly on the black bar counter with nothing beneath it. Following the glass_background sample's ratio, the black bar counter/tabletop fills roughly the lower 35-45% of the frame, and the glass wall with its soft-focus exterior view fills the remaining upper 55-65% as quiet negative space.

### CUP / VESSEL SHAPE
Reconstruct the EXACT cup/container shown in the user's uploaded photo -- its shape, material, color, handle (if any), and lid (if any) -- faithfully and natively for this new camera and light. Do NOT apply this preset's reference mug/glass color, handle, or saucer rules in this mode -- the user's own original cup design is the source of truth for the vessel's appearance.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
Use only: one small matte black ceramic plate with one croissant-type pastry or cake and a simple fork+knife (handles toward the viewer), per the shared prop_plating rule; optional one folded-open magazine or notebook, referencing the glass_background sample -- the magazine/notebook page itself must be completely bare, with NOTHING resting on top of it (no spoon, no utensil, no other object); optional one small potted plant with large, broad leaves (e.g. a rubber-plant/peperomia type, per the pot sample photo), softly out of focus, at the far edge of frame.
Prop plating rule (always applies): No metal tray, no napkin, anywhere. Food prop (croissant-type pastry/cake only, never cookie) sits with a fork+knife on one small plate, nothing underneath. Plate: porcelain/ceramic only (plastic forbidden), black or dark charcoal-grey. Hot beverage: plate color is the OPPOSITE of the mug+saucer color (never matching). Iced: either plate color is fine. Fork+knife: fully visible beside the pastry (never under it), handles toward viewer, tines/blade away, NOT rigidly parallel (avoid a stiff '11' look) -- head plus roughly half the handle rests on the plate, at most the far half may extend past the rim.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.
Shot-specific: No rough grey concrete wall here -- background is the glass wall above. No night skyline or city lights -- must read as DAYTIME. No harsh direct sunlight. No metal tray. No cookie as the food prop.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```

### close_up / ice / user_cup (10180자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 사용자 컵 버전 (user_cup)
The full original photo (cup + beverage) is sent. Cup shape/material/color/handle/lid/logo are reconstructed faithfully from the user's own photo -- this preset's cup_shapes color/handle/saucer rules do NOT apply in this mode; the user's own cup is the source of truth.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 클로즈업 (close_up, ice)
A tight, intimate crop on the beverage as it stands directly on the counter (no tray). The wall and counter are still the same rough dark-grey concrete family, but now mostly soft-focus at the edges of frame rather than a large negative-space plane -- the product itself is the dominant subject.

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
an interior cafe corner: a tall, bare, rough-troweled dark-grey concrete or lime-plaster wall with fine aggregate speckle, occasional small pitting, faint vertical water-stain streaks and one faint natural moisture mark for authenticity, meeting a coarser dark-grey stone/concrete counter below. This is unmistakably an indoor cafe environment, never an outdoor street, sidewalk, pavement, curb, parking lot or exterior wall..
Below the wall, on a soft horizontal seam, there is no metal tray anywhere -- the beverage stands directly on a coarse dark-grey stone/concrete counter (or, per shot-specific overrides, a black window table or black bistro table). Any food prop sits separately, plated on a small black ceramic plate.. This surface is a different, slightly coarser grey texture family than the wall above it.

### CAMERA + FRAMING FOR THIS SHOT
Camera: 60-90mm equivalent macro-leaning lens, 20-35 degrees downward, camera height ~40-60cm above the counter.
The beverage fills roughly 55-70% of frame width and 45-60% of frame height, centered slightly right of frame, standing directly on the counter with nothing beneath it. Only slivers of the concrete wall (upper corner) and stone counter (lower edge) remain visible, both softly defocused. Shallow depth of field resolves the glass/cup, ice, and counter surface crisply while the wall texture behind blurs into soft grey bokeh.

### CUP / VESSEL SHAPE
Reconstruct the EXACT cup/container shown in the user's uploaded photo -- its shape, material, color, handle (if any), and lid (if any) -- faithfully and natively for this new camera and light. Do NOT apply this preset's reference mug/glass color, handle, or saucer rules in this mode -- the user's own original cup design is the source of truth for the vessel's appearance.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
Use only: at most one small matte black ceramic plate (croissant-type pastry or cake, per the shared prop_plating rule) partially visible at the frame edge, softly out of focus.
Prop plating rule (always applies): No metal tray, no napkin, anywhere. Food prop (croissant-type pastry/cake only, never cookie) sits with a fork+knife on one small plate, nothing underneath. Plate: porcelain/ceramic only (plastic forbidden), black or dark charcoal-grey. Hot beverage: plate color is the OPPOSITE of the mug+saucer color (never matching). Iced: either plate color is fine. Fork+knife: fully visible beside the pastry (never under it), handles toward viewer, tines/blade away, NOT rigidly parallel (avoid a stiff '11' look) -- head plus roughly half the handle rests on the plate, at most the far half may extend past the rim.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```

### aerial / ice / user_cup (10862자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 사용자 컵 버전 (user_cup)
The full original photo (cup + beverage) is sent. Cup shape/material/color/handle/lid/logo are reconstructed faithfully from the user's own photo -- this preset's cup_shapes color/handle/saucer rules do NOT apply in this mode; the user's own cup is the source of truth.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 항공샷 (완전 수직, 음료·빵 윗면만) (aerial, ice)
Strict perfectly-vertical (90-degree) top-down view above a black round table: only top surfaces of beverage and food prop are visible, no side profile of either. No metal tray -- both stand directly on the table. Center: a small potted plant (per the pot reference) with a round candle (~1/3 the pot's size) beside it in a clear transparent case, for safety.

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
no wall is visible at all in this strict vertical overhead angle -- only the plain black round table fills the frame, with perhaps the faintest soft-focus hint of a dark chair leg or floor right at the extreme edge of frame..
Surface: a black round bistro table (or the visible portion of one), matte finish, filling most of the frame with generous bare table space around the beverage and plate..

### CAMERA + FRAMING FOR THIS SHOT
Camera: Exactly 90 degrees from horizontal, camera pointing straight down into the mouth of the glass/cup from directly above -- only the top surface (rim, ice, garnish) of the beverage and the top of the food prop are visible. No side profile of the glass, pastry, or any wall.
Follow the layout_sample photo's DIAMOND arrangement on the black table (never a straight line): (1) potted plant upper-center-left; (2) candle (clear case) to the plant's right, similar height; (3) beverage (top view only) lower-left, clearly below the plant; (4) food plate (pastry+fork+knife, handles toward viewer, nothing underneath) lower-right, similar height to the beverage but offset right, larger footprint than the cup. Plant+candle = upper pair, beverage+plate = lower pair; every element offset from every other on both axes. All four together occupy a MINORITY (roughly 35-45%) of the frame, with the bare black table filling clearly more of the background.

### CUP / VESSEL SHAPE
Reconstruct the EXACT cup/container shown in the user's uploaded photo -- its shape, material, color, handle (if any), and lid (if any) -- faithfully and natively for this new camera and light. Do NOT apply this preset's reference mug/glass color, handle, or saucer rules in this mode -- the user's own original cup design is the source of truth for the vessel's appearance.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
Use only: one croissant-type pastry or cake (top view only), plated on a small black ceramic plate per the prop_plating rule; one simple fork and knife laid fully visible beside the pastry on the same plate, handles toward the viewer; one small potted plant at the table center (top view), referencing the pot sample photo; one round pillar candle (about 1/3 the size of the pot) beside the plant, fully enclosed in a clear transparent case/holder -- no exposed flame.
Prop plating rule (always applies): No metal tray, no napkin, anywhere. Food prop (croissant-type pastry/cake only, never cookie) sits with a fork+knife on one small plate, nothing underneath. Plate: porcelain/ceramic only (plastic forbidden), black or dark charcoal-grey. Hot beverage: plate color is the OPPOSITE of the mug+saucer color (never matching). Iced: either plate color is fine. Fork+knife: fully visible beside the pastry (never under it), handles toward viewer, tines/blade away, NOT rigidly parallel (avoid a stiff '11' look) -- head plus roughly half the handle rests on the plate, at most the far half may extend past the rim.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.
Shot-specific: No marble or white/light stone surface. No cosmetic-looking or reference-photo prop/text/logo besides the user's own cup logo. CRITICAL: the candle must NEVER show an open/exposed flame or bare wick -- always fully enclosed in its clear case. No bright/airy/well-lit tabletop -- keep it dark and low-key.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```

### handheld / ice / user_cup (10122자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 사용자 컵 버전 (user_cup)
The full original photo (cup + beverage) is sent. Cup shape/material/color/handle/lid/logo are reconstructed faithfully from the user's own photo -- this preset's cup_shapes color/handle/saucer rules do NOT apply in this mode; the user's own cup is the source of truth.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 손으로 든 샷 (온도별 구도 분기) (handheld, ice)
Two distinct compositions depending on the beverage's temperature, both set in the same black-table cafe-lounge context referenced from black_table_chair.png, selected at prompt-build time via beverage_temp.
Hand: a single, clearly feminine hand (slender fingers, smooth clean nails, no rings or jewelry) holds or rests near the cup. A shirt or sweater cuff/sleeve fully covers the wrist and lower forearm, so no bare wrist skin is visible at all -- the sleeve hem sits right at or past the wrist joint. No face, no other body part, and no identifying marks (tattoos, scars) are visible -- hand and sleeve only.
The iced beverage in its glass is lifted OFF the table, held up in the air by the hand at roughly chest-to-shoulder height. CRITICAL: the glass must be held perfectly UPRIGHT and VERTICAL -- its base and rim stay level and straight, with no tilt, lean, or angle in any direction, as if it were still standing on an invisible flat surface. Do not tilt the glass toward the camera or to either side. The dark grey concrete wall fills the soft-focus background behind the raised glass.

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
the SAME tall, bare, rough-troweled dark-grey concrete wall used in the close_up shot -- a deliberate return to the concrete backdrop specifically for this iced handheld composition, not the black table interior used for the hot version or the aerial shot..
Surface: only a sliver of the grey stone counter edge at the very bottom of frame, with a small prop (e.g. cookies) plated on a small black ceramic plate resting on it..

### CAMERA + FRAMING FOR THIS SHOT
Camera: 50-70mm equivalent, near eye-level to slightly above, camera close to the subject (~30-50cm).

### CUP / VESSEL SHAPE
Reconstruct the EXACT cup/container shown in the user's uploaded photo -- its shape, material, color, handle (if any), and lid (if any) -- faithfully and natively for this new camera and light. Do NOT apply this preset's reference mug/glass color, handle, or saucer rules in this mode -- the user's own original cup design is the source of truth for the vessel's appearance.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
CRITICAL: this shot must include NO food prop of any kind -- no bread, pastry, cake, cookie, plate, or napkin anywhere in frame. Only the beverage (and, if this is a handheld shot, the hand holding or resting near it) appear.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.
Shot-specific: CRITICAL: this shot must include NO food prop of any kind -- no pastry, cake, cookie, plate, or napkin anywhere in frame. Only the beverage and the hand/sleeve holding or resting near it. No visible logo, wordmark, or embossed brand text anywhere. No metal tray anywhere. No identifiable person, face, or distinguishing personal detail -- hand and sleeve only, generic and unbranded. No bare wrist skin visible under any circumstance -- the cuff must cover it. No bright, airy, or well-lit look -- keep the whole frame dark and low-key.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```

## container_mode = `reference_cup`

### medium / ice / reference_cup (11795자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 레퍼런스 컵 버전 (reference_cup)
Cup shape/material/color/handle/lid always follow this preset's own cup_shapes (by beverage_temp), never the user's cup. Only the beverage's own color/ice/foam comes from the user's photo. One input photo is used for all 4 shots; crop out the cup body/logo where practical so the model anchors less on it. Each shot's own camera angle (incl. aerial's strict vertical) is fully text-driven, independent of the input photo's angle.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 미디엄 컷 (1층 창가 바 좌석) (medium, ice)
A ground-floor window-bar-seat composition: the viewer is seated at a black bar counter along a glass wall, looking out at a soft-focus daytime street-level scene -- referencing the light_sample photo's exterior (a street-level plaza, blurred building facades, natural daylight), not a night skyline. Lighting is natural daylight passing through the glass, with no interior lamp or pendant fixture of any kind -- referencing the glass_background sample photo's bar-counter-to-exterior ratio and its non-beverage props (a bare folded-open magazine (nothing resting on it), a small potted plant).

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
A full glass wall/window with slim black mullions, at ground-floor street level (not a high-rise). Beyond it: a soft-focus DAYTIME street scene -- light paving, blurred building facades in muted warm-neutral tones, maybe an outdoor bistro table/stool -- never sharp or legible. No text/signage on the glass. No interior pendant/lamp/bulb/wire-cage fixture visible anywhere. CRITICAL: brightness here must MATCH the other three shots (close_up, aerial, handheld) -- not darker; the space reads as an open, currently-lit cafe, never closed/unlit..
Surface: a black-stained wood bar-height counter/table running along the base of the glass wall, narrower than a full windowsill -- the kind of counter with bar stools where a single person sits facing the window..

### CAMERA + FRAMING FOR THIS SHOT
Camera: 35-50mm equivalent, 15-35 degrees downward, camera at seated bar-stool eye height (~110-130cm).
The product occupies roughly 30-40% of frame width in the lower-right area, standing directly on the black bar counter with nothing beneath it. Following the glass_background sample's ratio, the black bar counter/tabletop fills roughly the lower 35-45% of the frame, and the glass wall with its soft-focus exterior view fills the remaining upper 55-65% as quiet negative space.

### CUP / VESSEL SHAPE
A clear DOUBLE-WALL glass tumbler (visible air gap, per the ice_glass reference) -- required, not optional; this is the cup's defining feature vs. an ordinary single-wall glass. Body is thick and substantial, not slender. Rim and double-wall edges are crisp and sharp with real glass reflections/highlights -- never soft or film-like. Beverage color/condensation/ice show through the inner wall. Straight/tapered, no handle.
This is the PRESET's own reference cup design -- it is deliberately NOT the user's original cup. The input image has been cropped down to the beverage's own content (its color, ice, foam, layering), with little to no original cup structure visible, specifically so this reference cup design can be applied cleanly without fighting the original cup's shape.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.
CRITICAL, applies to every shot type: an iced beverage must NEVER sit on a saucer, coaster, or plate underneath the glass -- the glass sits directly on the table/counter/windowsill surface with nothing beneath it (no tray, no coaster, no saucer).

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
Use only: one small matte black ceramic plate with one croissant-type pastry or cake and a simple fork+knife (handles toward the viewer), per the shared prop_plating rule; optional one folded-open magazine or notebook, referencing the glass_background sample -- the magazine/notebook page itself must be completely bare, with NOTHING resting on top of it (no spoon, no utensil, no other object); optional one small potted plant with large, broad leaves (e.g. a rubber-plant/peperomia type, per the pot sample photo), softly out of focus, at the far edge of frame.
Prop plating rule (always applies): No metal tray, no napkin, anywhere. Food prop (croissant-type pastry/cake only, never cookie) sits with a fork+knife on one small plate, nothing underneath. Plate: porcelain/ceramic only (plastic forbidden), black or dark charcoal-grey. Hot beverage: plate color is the OPPOSITE of the mug+saucer color (never matching). Iced: either plate color is fine. Fork+knife: fully visible beside the pastry (never under it), handles toward viewer, tines/blade away, NOT rigidly parallel (avoid a stiff '11' look) -- head plus roughly half the handle rests on the plate, at most the far half may extend past the rim.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.
Shot-specific: No rough grey concrete wall here -- background is the glass wall above. No night skyline or city lights -- must read as DAYTIME. No harsh direct sunlight. No metal tray. No cookie as the food prop.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```

### close_up / ice / reference_cup (11000자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 레퍼런스 컵 버전 (reference_cup)
Cup shape/material/color/handle/lid always follow this preset's own cup_shapes (by beverage_temp), never the user's cup. Only the beverage's own color/ice/foam comes from the user's photo. One input photo is used for all 4 shots; crop out the cup body/logo where practical so the model anchors less on it. Each shot's own camera angle (incl. aerial's strict vertical) is fully text-driven, independent of the input photo's angle.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 클로즈업 (close_up, ice)
A tight, intimate crop on the beverage as it stands directly on the counter (no tray). The wall and counter are still the same rough dark-grey concrete family, but now mostly soft-focus at the edges of frame rather than a large negative-space plane -- the product itself is the dominant subject.

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
an interior cafe corner: a tall, bare, rough-troweled dark-grey concrete or lime-plaster wall with fine aggregate speckle, occasional small pitting, faint vertical water-stain streaks and one faint natural moisture mark for authenticity, meeting a coarser dark-grey stone/concrete counter below. This is unmistakably an indoor cafe environment, never an outdoor street, sidewalk, pavement, curb, parking lot or exterior wall..
Below the wall, on a soft horizontal seam, there is no metal tray anywhere -- the beverage stands directly on a coarse dark-grey stone/concrete counter (or, per shot-specific overrides, a black window table or black bistro table). Any food prop sits separately, plated on a small black ceramic plate.. This surface is a different, slightly coarser grey texture family than the wall above it.

### CAMERA + FRAMING FOR THIS SHOT
Camera: 60-90mm equivalent macro-leaning lens, 20-35 degrees downward, camera height ~40-60cm above the counter.
The beverage fills roughly 55-70% of frame width and 45-60% of frame height, centered slightly right of frame, standing directly on the counter with nothing beneath it. Only slivers of the concrete wall (upper corner) and stone counter (lower edge) remain visible, both softly defocused. Shallow depth of field resolves the glass/cup, ice, and counter surface crisply while the wall texture behind blurs into soft grey bokeh.

### CUP / VESSEL SHAPE
A clear DOUBLE-WALL glass tumbler (visible air gap, per the ice_glass reference) -- required, not optional; this is the cup's defining feature vs. an ordinary single-wall glass. Body is thick and substantial, not slender. Rim and double-wall edges are crisp and sharp with real glass reflections/highlights -- never soft or film-like. Beverage color/condensation/ice show through the inner wall. Straight/tapered, no handle.
This is the PRESET's own reference cup design -- it is deliberately NOT the user's original cup. The input image has been cropped down to the beverage's own content (its color, ice, foam, layering), with little to no original cup structure visible, specifically so this reference cup design can be applied cleanly without fighting the original cup's shape.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.
CRITICAL, applies to every shot type: an iced beverage must NEVER sit on a saucer, coaster, or plate underneath the glass -- the glass sits directly on the table/counter/windowsill surface with nothing beneath it (no tray, no coaster, no saucer).

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
Use only: at most one small matte black ceramic plate (croissant-type pastry or cake, per the shared prop_plating rule) partially visible at the frame edge, softly out of focus.
Prop plating rule (always applies): No metal tray, no napkin, anywhere. Food prop (croissant-type pastry/cake only, never cookie) sits with a fork+knife on one small plate, nothing underneath. Plate: porcelain/ceramic only (plastic forbidden), black or dark charcoal-grey. Hot beverage: plate color is the OPPOSITE of the mug+saucer color (never matching). Iced: either plate color is fine. Fork+knife: fully visible beside the pastry (never under it), handles toward viewer, tines/blade away, NOT rigidly parallel (avoid a stiff '11' look) -- head plus roughly half the handle rests on the plate, at most the far half may extend past the rim.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```

### aerial / ice / reference_cup (11682자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 레퍼런스 컵 버전 (reference_cup)
Cup shape/material/color/handle/lid always follow this preset's own cup_shapes (by beverage_temp), never the user's cup. Only the beverage's own color/ice/foam comes from the user's photo. One input photo is used for all 4 shots; crop out the cup body/logo where practical so the model anchors less on it. Each shot's own camera angle (incl. aerial's strict vertical) is fully text-driven, independent of the input photo's angle.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 항공샷 (완전 수직, 음료·빵 윗면만) (aerial, ice)
Strict perfectly-vertical (90-degree) top-down view above a black round table: only top surfaces of beverage and food prop are visible, no side profile of either. No metal tray -- both stand directly on the table. Center: a small potted plant (per the pot reference) with a round candle (~1/3 the pot's size) beside it in a clear transparent case, for safety.

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
no wall is visible at all in this strict vertical overhead angle -- only the plain black round table fills the frame, with perhaps the faintest soft-focus hint of a dark chair leg or floor right at the extreme edge of frame..
Surface: a black round bistro table (or the visible portion of one), matte finish, filling most of the frame with generous bare table space around the beverage and plate..

### CAMERA + FRAMING FOR THIS SHOT
Camera: Exactly 90 degrees from horizontal, camera pointing straight down into the mouth of the glass/cup from directly above -- only the top surface (rim, ice, garnish) of the beverage and the top of the food prop are visible. No side profile of the glass, pastry, or any wall.
Follow the layout_sample photo's DIAMOND arrangement on the black table (never a straight line): (1) potted plant upper-center-left; (2) candle (clear case) to the plant's right, similar height; (3) beverage (top view only) lower-left, clearly below the plant; (4) food plate (pastry+fork+knife, handles toward viewer, nothing underneath) lower-right, similar height to the beverage but offset right, larger footprint than the cup. Plant+candle = upper pair, beverage+plate = lower pair; every element offset from every other on both axes. All four together occupy a MINORITY (roughly 35-45%) of the frame, with the bare black table filling clearly more of the background.

### CUP / VESSEL SHAPE
A clear DOUBLE-WALL glass tumbler (visible air gap, per the ice_glass reference) -- required, not optional; this is the cup's defining feature vs. an ordinary single-wall glass. Body is thick and substantial, not slender. Rim and double-wall edges are crisp and sharp with real glass reflections/highlights -- never soft or film-like. Beverage color/condensation/ice show through the inner wall. Straight/tapered, no handle.
This is the PRESET's own reference cup design -- it is deliberately NOT the user's original cup. The input image has been cropped down to the beverage's own content (its color, ice, foam, layering), with little to no original cup structure visible, specifically so this reference cup design can be applied cleanly without fighting the original cup's shape.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.
CRITICAL, applies to every shot type: an iced beverage must NEVER sit on a saucer, coaster, or plate underneath the glass -- the glass sits directly on the table/counter/windowsill surface with nothing beneath it (no tray, no coaster, no saucer).

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
Use only: one croissant-type pastry or cake (top view only), plated on a small black ceramic plate per the prop_plating rule; one simple fork and knife laid fully visible beside the pastry on the same plate, handles toward the viewer; one small potted plant at the table center (top view), referencing the pot sample photo; one round pillar candle (about 1/3 the size of the pot) beside the plant, fully enclosed in a clear transparent case/holder -- no exposed flame.
Prop plating rule (always applies): No metal tray, no napkin, anywhere. Food prop (croissant-type pastry/cake only, never cookie) sits with a fork+knife on one small plate, nothing underneath. Plate: porcelain/ceramic only (plastic forbidden), black or dark charcoal-grey. Hot beverage: plate color is the OPPOSITE of the mug+saucer color (never matching). Iced: either plate color is fine. Fork+knife: fully visible beside the pastry (never under it), handles toward viewer, tines/blade away, NOT rigidly parallel (avoid a stiff '11' look) -- head plus roughly half the handle rests on the plate, at most the far half may extend past the rim.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.
Shot-specific: No marble or white/light stone surface. No cosmetic-looking or reference-photo prop/text/logo besides the user's own cup logo. CRITICAL: the candle must NEVER show an open/exposed flame or bare wick -- always fully enclosed in its clear case. No bright/airy/well-lit tabletop -- keep it dark and low-key.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```

### handheld / ice / reference_cup (10942자)

```text
### ROLE
You are compositing ONE real user beverage photo into a brand-new, fully photorealistic cafe environment. The output must look like a single unedited phone/camera photo taken in one real room under one real light source -- never a collage, never a sticker-on-background look.

### INPUT IMAGE MODE: 레퍼런스 컵 버전 (reference_cup)
Cup shape/material/color/handle/lid always follow this preset's own cup_shapes (by beverage_temp), never the user's cup. Only the beverage's own color/ice/foam comes from the user's photo. One input photo is used for all 4 shots; crop out the cup body/logo where practical so the model anchors less on it. Each shot's own camera angle (incl. aerial's strict vertical) is fully text-driven, independent of the input photo's angle.
Regardless of container_mode, beverage type/temperature/recipe/ice-or-foam state always comes from the user's own photo, never from any reference photo or preset assumption.

### SHOT TYPE: 손으로 든 샷 (온도별 구도 분기) (handheld, ice)
Two distinct compositions depending on the beverage's temperature, both set in the same black-table cafe-lounge context referenced from black_table_chair.png, selected at prompt-build time via beverage_temp.
Hand: a single, clearly feminine hand (slender fingers, smooth clean nails, no rings or jewelry) holds or rests near the cup. A shirt or sweater cuff/sleeve fully covers the wrist and lower forearm, so no bare wrist skin is visible at all -- the sleeve hem sits right at or past the wrist joint. No face, no other body part, and no identifying marks (tattoos, scars) are visible -- hand and sleeve only.
The iced beverage in its glass is lifted OFF the table, held up in the air by the hand at roughly chest-to-shoulder height. CRITICAL: the glass must be held perfectly UPRIGHT and VERTICAL -- its base and rim stay level and straight, with no tilt, lean, or angle in any direction, as if it were still standing on an invisible flat surface. Do not tilt the glass toward the camera or to either side. The dark grey concrete wall fills the soft-focus background behind the raised glass.

### OVERALL LOOK (shared mood across shot types)
Natural but art-directed Instagram cafe observation in a dark, moody industrial register: matte cool-grey concrete, brushed steel, restrained daylight, finite acuity.
quiet, moody, industrial-editorial cafe photograph; considered but not overly art-directed.
Realism requirement: one camera, one exposure, one light system connects wall, counter, plate and vessel.

### ENVIRONMENT: WALL/BACKGROUND + SURFACE
the SAME tall, bare, rough-troweled dark-grey concrete wall used in the close_up shot -- a deliberate return to the concrete backdrop specifically for this iced handheld composition, not the black table interior used for the hot version or the aerial shot..
Surface: only a sliver of the grey stone counter edge at the very bottom of frame, with a small prop (e.g. cookies) plated on a small black ceramic plate resting on it..

### CAMERA + FRAMING FOR THIS SHOT
Camera: 50-70mm equivalent, near eye-level to slightly above, camera close to the subject (~30-50cm).

### CUP / VESSEL SHAPE
A clear DOUBLE-WALL glass tumbler (visible air gap, per the ice_glass reference) -- required, not optional; this is the cup's defining feature vs. an ordinary single-wall glass. Body is thick and substantial, not slender. Rim and double-wall edges are crisp and sharp with real glass reflections/highlights -- never soft or film-like. Beverage color/condensation/ice show through the inner wall. Straight/tapered, no handle.
This is the PRESET's own reference cup design -- it is deliberately NOT the user's original cup. The input image has been cropped down to the beverage's own content (its color, ice, foam, layering), with little to no original cup structure visible, specifically so this reference cup design can be applied cleanly without fighting the original cup's shape.
Preserve any real logo or wordmark exactly as it appears on the user's original cup photo, rendered clearly and legibly on the reconstructed vessel. NEVER invent, generate, or design a new logo of any kind. If no logo is visible in the input image, the output must also show no logo -- do not add one.
CRITICAL, applies to every shot type: an iced beverage must NEVER include a straw of any kind -- no straw, no lid with a straw hole, no straw wrapper. The drink is sipped directly from the glass rim.
CRITICAL, applies to every shot type: an iced beverage must NEVER sit on a saucer, coaster, or plate underneath the glass -- the glass sits directly on the table/counter/windowsill surface with nothing beneath it (no tray, no coaster, no saucer).

### LIGHTING (shared natural light unless this shot overrides it above)
single soft natural daylight source, window-diffused, no visible fixture -- from a time of day when the sun is gentle and the room reads dim and moody: early morning, late afternoon, or an overcast/cloudy moment, NEVER a bright high midday sun and never an airy bright exposure, arriving from the upper-left, shallow angle across the wall and counter (azimuth ~300 degrees, elevation ~35 degrees). Intensity: extremely low, very deeply dim and moody -- roughly HALF as bright as the already-dim exposure used previously (so about a quarter of a normal soft-light exposure overall), a heavily underexposed, almost silhouette-leaning look across the whole frame, with just enough light to make out shapes and textures -- not a bright airy look under any circumstance. Contrast: medium: the wall texture reads clearly but shadow edges stay soft, never a hard sharp sun-shadow. Shadow behaviour: one soft short contact shadow beneath the cup, edges diffused. soft rim highlight on the cup only; never let the wall clip to white.

### COLOR & GRADE (shared)
White balance approximately 5600K, cool-neutral daylight, no warm filter. Black point: deep neutral charcoal with visible concrete grain, never a crushed pure black. Contrast character: weighted lower-mid shadow falloff, soft highlight shoulder on cup and plate. Saturation: near-monochrome room and surfaces; the exact user beverage is the only saturated color note from the product itself. EXCEPTION: any potted plant's leaves in the scene keep a vivid, healthy, natural green saturation -- do NOT desaturate the plant's foliage to match the muted palette; the leaves should look alive and richly green, not faded, dusty, or grey-green.. Approximate palette (for reference, do not render as flat color blocks): #4A4B4D, #6B6C6E, #8C8D8F, #B9BABC, #2E2F31.

### TEXTURE / MATERIALS (shared)
hand-trowelled concrete grain (wall), coarser pitted stone grain (counter), matte ceramic (cup, plate), finite social-photo acuity throughout.
Fine-grain realism: faint low-contrast luminance texture with finite twelve-to-sixteen-megapixel acuity.
Include tiny natural imperfections such as: subtle concrete speckle variation; one faint water-mark on the wall; slightly unequal plate-to-cup spacing; gentle far-corner microcontrast loss; CRITICAL: no bright/white/transparent gap-line where the vessel base touches the surface -- the contact shadow is tight and dark, the vessel reads as resting on it, never floating or pasted..

### PROPS FOR THIS SHOT
CRITICAL: this shot must include NO food prop of any kind -- no bread, pastry, cake, cookie, plate, or napkin anywhere in frame. Only the beverage (and, if this is a handheld shot, the hand holding or resting near it) appear.

### PRODUCT / IDENTITY PRESERVATION (hard constraints, shared)
- exact user product count one
- beverage recipe/color/temperature/serving state exactly as in the product photo (ice+no-straw if iced; foam/latte-art if hot -- never invent the opposite temperature)
- source cup semantics reconstructed natively, never pasted or traced from any reference
- the beverage stands directly on the surface -- no metal tray and no saucer/coaster beneath it, in every shot
- target brand contract
- product width 0.30-0.40 and height 0.16-0.22 of frame
- never invent a logo, for hot or iced. Only reproduce the exact logo visible in the user's photo, legibly, on the new vessel; if the photo shows no logo, show none. Vessel shape may adapt (mug/glass) but logo content is never invented, altered, or added.
Reconstruct the user's cup/container design natively for the new camera and light; never paste, trace or preserve any source boundary. Preserve beverage and serving semantics and obey only the target brand contract. CRITICAL, anti-composite rule: the beverage's surface highlights, reflections, and any visible sheen on the glass or ceramic must be re-rendered as if lit by THIS scene's own light source (the dim, moody interior light or the evening window light described above) -- do NOT copy over the bright, even, studio-style highlights or reflections from the user's original product photo. If the original photo's lighting looks brighter or more evenly lit than this scene, the beverage's highlights must be dimmed and reshaped to match this scene's darker, more directional light, so the drink and its environment read as one single continuous photograph under one light source, never as a brighter object pasted onto a darker background.

### WHAT TO AVOID (shared)
No extra beverage, no metal tray or napkin, no saucer/coaster under an iced drink, no glossy/bright wall, no warm-beige cast, no legible card/window/signage text, no busy sharp background furniture, no oversized product, no crushed blacks or blown highlights, no invented logo, no cookie as the food prop. This is an INDOOR cafe corner (or the medium shot's glass wall) -- never outdoor pavement, curb, parking lot, sky, or building facades; the wall must read as the specified rough dark-grey concrete or glass, not a different material or exterior surface.
Forbidden surface readings: warm beige or brown wall cast, polished/glossy poured concrete, colorful or patterned tile, bright white studio backdrop, any metal serving tray of any kind (no tray anywhere in this preset), visible large-format aggregate or brick joints.
Shot-specific: CRITICAL: this shot must include NO food prop of any kind -- no pastry, cake, cookie, plate, or napkin anywhere in frame. Only the beverage and the hand/sleeve holding or resting near it. No visible logo, wordmark, or embossed brand text anywhere. No metal tray anywhere. No identifiable person, face, or distinguishing personal detail -- hand and sleeve only, generic and unbranded. No bare wrist skin visible under any circumstance -- the cuff must cover it. No bright, airy, or well-lit look -- keep the whole frame dark and low-key.

### QUALITY BAR (self-check before finalizing)
- lens/pitch/surface/tone match this shot's spec above
- one beverage, recipe/serving state and cup reconstruction match the rules above
- no unauthorized logo/text
- no violations of the WHAT TO AVOID list above

### PRODUCT NOTE FROM USER
사용자가 업로드한 음료 사진의 색/온도/얼음 상태를 그대로 유지
```
