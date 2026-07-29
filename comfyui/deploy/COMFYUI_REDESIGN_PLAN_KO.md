# ComfyUI 전면 재설계 계획

## 1. 결론

12개 조합마다 workflow JSON을 복제하는 구조 대신, 하나의 provider-neutral 그래프가 `preset_id`로 버전 고정된 preset package를 읽도록 재설계합니다. 파일럿은 `upstream/comfyui` 기준선 위에 OpenAI GPT Image 2 저화질 workflow를 병렬 추가하고, 화이트 미디엄과 우드 미디엄 두 프리셋만 공개합니다.

첫 단계의 목표는 서비스 연결을 안전하게 검증하는 것입니다. Gemini QA, 오픈소스 모델, provider fan-out은 같은 인터페이스 뒤에 후속 단계로 추가하며 파일럿의 유료 호출 경로에 섞지 않습니다.

## 2. 현재 구조에서 제거할 결합

1. 로컬 모델의 `background_style`, `composition`, `strength`, `seed`가 provider 입력까지 직접 관통합니다.
2. 서비스의 12개 `reference_id`, 프론트 정적 JSON, 백엔드 JSON, 연구 preset이 서로 다른 source of truth를 가집니다.
3. 모델 이름·quality와 provider별 인자가 workflow/노드에 하드코딩되어 있습니다.
4. 레퍼런스·hint manifest 일부가 개발 Mac의 절대경로와 결합되어 GCP에서 재현되지 않습니다.
5. 런타임 보조 이미지, 오프라인 authoring reference, 품질 검사용 이미지의 역할이 분리되지 않았습니다.
6. 생성과 provider 고유 QA가 한 노드에 묶이면 비용·실패 원인·비교 기준을 분리할 수 없습니다.
7. 한 비율의 생성물을 다른 비율로 중앙 crop해 preset의 구도 계약을 깨뜨립니다.
8. 여러 provider 결과를 한 grid 이미지로 합치면 개별 원본, 메타데이터와 QA를 잃습니다.
9. Gateway health가 기존 model-c의 생존 여부와 결합되어 신규 provider의 준비 상태를 정확히 표현하지 못합니다.

## 3. 브랜치와 이관 원칙

- 배포 기준선은 `upstream/comfyui`입니다.
- 작업 브랜치는 `presets`이며 기존 연구 브랜치 전체를 merge하지 않습니다.
- 연구 브랜치에서는 검수된 preset contract, lighting sheet, sanitized hint/material board와 필요한 최소 로직만 선별 이관합니다.
- `model-c-v1`을 삭제·덮어쓰기 하지 않고 신규 `openai-gpt-image-2-low-v1`을 병렬 등록합니다.
- 배포 전 untracked 자산이 하나라도 preset registry에서 참조되면 실패 처리합니다.

## 4. 단일 source of truth

서비스 선택값의 최상위 키는 frontend `reference_id`와 같은 `preset_id`입니다. 내부 연구 preset ID는 registry가 명시적으로 연결합니다.

```text
natural_white__product_center
  -> instagram_white_diffuse_wall_table_v1

wood__product_center
  -> tokyo_a6_relational_scene_hint_v4

wood medium alternative (unrouted)
  -> instagram_wood_45deg_relational_v3
```

권장 구조는 다음과 같습니다.

```text
comfyui/
  config/
    providers/
      openai-gpt-image-2-low.json
  presets/
    registry.json
    assets/
      white-medium-authoring-reference.jpg
      wood-medium-scene-hint.png
      wood-medium-material-board.png
    natural_white__product_center/
      preset.json
      lighting-sheet.json
      grade-profile.json
      prompt-template.txt
    wood__product_center/
      preset.json
      lighting-sheet.json
      grade-profile.json
      prompt-template.txt
  workflows/
    openai-gpt-image-2-low-v1.api.json
    openai-gpt-image-2-low-v1.ui.json
    registry.json
```

`presets/registry.json`은 12개 서비스 slot의 활성 상태와 내부 contract/bundle을 명시하고, 각 bundle의 `preset.json`이 prompt·lighting·grade·hint의 hash manifest 역할을 합니다.

```json
{
  "provider_profile": "../config/providers/openai-gpt-image-2-low.json",
  "slots": {
    "wood__product_center": {
      "enabled": true,
      "status": "published",
      "family": "wood",
      "composition": "medium",
      "preset_id": "tokyo_a6_relational_scene_hint_v4",
      "bundle": "wood__product_center_a6/preset.json"
    }
  }
}
```

```json
{
  "slot_id": "wood__product_center",
  "preset_id": "tokyo_a6_relational_scene_hint_v4",
  "prompt_template": {"path": "prompt-template.txt", "sha256": "..."},
  "lighting_sheet": {"path": "lighting-sheet.json", "sha256": "..."},
  "grade_profile": {"path": "grade-profile.json", "sha256": "...", "apply_in_pilot": false},
  "hint_images": [
    {"role": "sanitized_a6_scene_hint", "path": "../assets/wood-a6-multi-scene-hint.png", "sha256": "...", "send_to_provider": true}
  ],
  "aspect_ratio_contracts": {
    "4:5": {"generation_size": "1024x1280", "width": 1024, "height": 1280, "safe_crop": "none_exact_4x5"},
    "1:1": {"generation_size": "1024x1024", "width": 1024, "height": 1024, "safe_crop": "none_exact_1x1"}
  }
}
```

실제 schema는 registry 전체 구조에 맞춰 조정하되 다음 불변식은 유지합니다.

- provider에 보내는 이미지 순서는 `role`로 고정합니다. 파일명 정렬이나 폴더 탐색에 의존하지 않습니다.
- 모든 경로는 repository-relative이고 루트 이탈을 거부합니다.
- 자산은 크기와 SHA-256이 일치해야만 로드합니다.
- authoring reference와 raw reference는 `send_to_provider: false`입니다.
- `enabled=false` preset은 prompt 조립 전에 거부합니다.
- Vivid 네 슬롯은 계열 교체 전까지 예약 ID일 뿐 prompt나 자산을 임의 생성하지 않습니다.

프론트·백엔드의 references JSON은 장기적으로 이 registry에서 생성하거나 백엔드의 한 endpoint에서 공급합니다. 같은 ID와 활성 상태를 두 저장소에서 수동 편집하는 방식을 없앱니다.

## 5. Provider-neutral 실행 단계

```text
AD_ResolveRequest
  -> AD_LoadPresetPackage
  -> AD_BuildGenerationRequest
  -> AD_Provider
  -> AD_NormalizeOutput
  -> AD_CommonQA          (후속 단계)
  -> AD_SaveResult
```

### `AD_ResolveRequest`

- `preset_id`, 사용자 이미지, request ID를 받습니다.
- `preset_id`의 활성 여부와 workflow 호환성을 검증합니다.
- 기존 `background_style+composition`은 호환 계층에서만 두 활성 preset으로 변환합니다.
- provider, model, quality를 사용자 입력에서 받지 않습니다.

### `AD_LoadPresetPackage`

- preset, scene recipe, lighting sheet, prompt contract와 asset manifest를 한 번에 검증합니다.
- 경로, checksum, dimension, asset role과 provider 전송 정책을 검사합니다.
- JSON 여러 개의 충돌 값은 묵시적으로 우선순위를 정하지 않고 schema 오류로 처리합니다.

### `AD_BuildGenerationRequest`

- 공통 요청과 provider adapter 요청을 분리합니다.
- 사용자 제품 정체성, 단일 제품 수, 브랜드/텍스트 보존, preset 구도·조명, 금지 조건을 순서가 고정된 prompt block으로 조립합니다.
- 런타임 보조 이미지는 manifest가 허용한 자산만 user product 다음 순서로 추가합니다.
- prompt text, preset version, asset hashes와 provider profile hash를 실행 manifest에 기록합니다.

### `AD_Provider`

provider subgraph는 다음 공통 입력·출력을 지킵니다.

```text
입력: request_id, preset_id, prompt, ordered_image_inputs, provider_profile
출력: provider_id, provider_job_id, image_path, width, height,
      elapsed_ms, cost_metadata, provider_error
```

OpenAI 구현은 `gpt-image-2`, `quality=low`를 유지하며 4:5는 `1024x1280` 생성 결과를 축소·크롭 없이 그대로 전달하고, 1:1은 처음부터 `1024x1024`로 생성합니다. 입력 원본은 기본 긴 변 1536px 상한이며 확대하지 않습니다. `3072`는 승인된 OCR·identity·usage 비교 실험에서만 사용합니다. `gpt-image-2`에는 별도 `input_fidelity` 옵션을 보내지 않습니다.

### `AD_NormalizeOutput`

- provider 결과를 요청 비율의 전달 크기(4:5 `1024x1280`, 1:1 `1024x1024`) 계약으로 검증하고 형식만 정규화합니다.
- provider부터 요청 비율의 정확한 canvas를 요청하고 제품 전체, 그림자와 preset 여백을 crop 없이 보존합니다. provider가 다른 크기·비율을 반환하면 자르지 않고 실패합니다.
- 백엔드가 추가로 정사각형 크롭하지 않도록 output manifest에 크기와 aspect ratio를 기록합니다.
- 원본 provider 결과와 전달 결과를 서로 다른 파일로 저장해 회귀 원인을 추적합니다.

### `AD_SaveResult`

- provider별 이미지는 독립 파일로 저장합니다.
- 비교용 grid 이미지를 만들지 않습니다.
- request manifest에 preset/provider/model/profile, 자산 hash, prompt hash, latency, 비용, QA 결과를 연결합니다.

## 6. 두 파일럿 preset package

### 화이트 미디엄

```text
service preset_id       natural_white__product_center
internal contract       instagram_white_diffuse_wall_table_v1
runtime provider input  사용자 제품 원본만
authoring reference      오프라인 측정·검수 전용, provider 제출 금지
lighting                 큰 좌측 확산 창광, 저대비, 연결된 부드러운 그림자
composition              작은 단일 제품, 상단 중심의 넓은 여백, 4:5
```

화이트의 checked-in authoring image를 scene hint로 가장해 보내지 않습니다. 향후 runtime hint가 필요하면 원본을 재사용하지 말고 비식별화된 별도 hint와 manifest를 만들고 유료 재검수합니다.

### 우드 미디엄

```text
service preset_id       wood__product_center
internal contract       tokyo_a6_relational_scene_hint_v4
runtime provider input  사용자 제품 + sanitized A6 scene hint
lighting                 먼 방의 단단한 건축광, 전경 open shade와 넓은 반사광
composition              완전한 원형 어두운 tray 위 3개 피사체의 A6 관계형 구도
```

scene hint는 원본 음료·로고를 제거한 승인 버전만 사용합니다. 기존 45도 contract는 삭제하지 않고 `available_not_routed` 대안으로 보존합니다. 각 역할은 manifest와 checksum으로 고정합니다.

## 7. 현재 파일럿 그래프와 다음 분리점

파일럿 그래프는 작고 명시적으로 유지합니다.

배포 기준의 현재 top-level 그래프는 최소 노드로 유지하고, provider 노드 내부에서 아래 단계를 명시적으로 수행합니다.

```text
LoadImage(user product)
  -> AdCreatorOpenAIImageGenerate
       [ResolvePreset -> VerifyAssets -> BuildRequest
        -> OpenAIProvider(quality=low, retries=0)
        -> Verify requested aspect -> Normalize without crop
        -> Save provider raw + audit sidecar]
  -> SaveImage
```

CommonQA와 두 번째 provider를 붙이는 단계에서 내부 단계들을 `AD_ResolvePreset`, `AD_BuildGenerationRequest`, `AD_Provider`, `AD_NormalizeOutput`의 독립 노드 또는 subgraph로 승격합니다. 파일럿에서는 아직 존재하지 않는 QA 노드를 그래프에 있는 것처럼 표시하지 않습니다.

- `preset_id`만 바뀌고 graph topology는 같습니다.
- 프리셋마다 workflow JSON을 복제하지 않습니다.
- UI workflow와 API workflow는 같은 node topology/contract에서 생성·검증합니다.
- 최종 `output_node_id`는 provider 원본이 아니라 정규화 뒤 `SaveImage`를 가리킵니다.
- 이번 단계에는 Gemini QA를 넣지 않습니다. OpenAI 호출 성공과 CommonQA 통과를 같은 의미로 기록하지 않습니다.
- Gateway job ID를 node `request_id`로 전달하며, provider 원본과 sidecar의 `run_id`로 Comfy prompt·delivery 결과를 역추적합니다. sidecar에는 prompt 본문·비밀키·원본 경로를 넣지 않습니다.

## 8. CommonQA 후속 설계

모든 provider 결과 뒤에 같은 QA subgraph를 붙입니다.

```text
AD_CommonQA
  ├─ BiRefNet: 제품 영역, crop, LUT 보호 mask 보조
  ├─ OCR: 핵심 로고·라벨 텍스트 보존
  ├─ DINOv2: 전체 제품·로고·뚜껑·음료 층 identity
  └─ bbox QA: 크기·중심·여백·잘림·복제
```

BiRefNet은 생성 입력을 강제로 전처리하는 노드가 아닙니다. 기본 생성 입력은 사용자 원본이며, BiRefNet은 생성 후 검출·crop·보호 mask에만 사용합니다. 투명 컵 분할 실패 가능성이 있으므로 BiRefNet 실패만으로 결과를 탈락시키지 않습니다.

점수를 단순 평균하지 않습니다.

| 종류 | 판정 |
| --- | --- |
| OCR 핵심 텍스트 불일치 | hard gate |
| DINOv2 identity 불일치 | hard gate |
| 제품 잘림·복제·누락 | hard gate |
| preset이 정한 크기·여백 범위 위반 | preset별 gate 또는 명시적 review |
| 자연스러움·무드 일치 | 비교 점수 |
| 시간·VRAM·API 비용 | 운영 점수 |

threshold는 임의 상수로 바로 출시하지 않습니다. 승인된 화이트·우드 결과와 실패 샘플로 preset별 calibration을 수행하고 version을 붙입니다. QA가 아직 shadow mode일 때는 사용자 결과를 자동 차단하지 않고 관측값만 기록합니다.

## 9. Provider fan-out 후속 설계

OpenAI와 오픈소스 모델을 비교할 때 같은 resolved request를 복제해 provider subgraph로 보냅니다.

```text
AD_ResolveRequest
  ├─ AD_OpenAIProvider
  ├─ AD_OpenSourceProvider
  └─ AD_ExperimentalProvider
       -> 각 결과를 독립 파일로 저장
       -> 동일 AD_CommonQA
       -> UI에서 나란히 비교
```

- 입력 이미지, preset version, 공통 prompt blocks와 QA version을 동일하게 고정합니다.
- provider adapter에 꼭 필요한 번역만 별도 기록합니다.
- 결과 grid를 생성하지 않습니다. UI가 각 원본 이미지와 메타데이터를 나란히 보여줍니다.
- 비교 UI에는 provider별 이미지, identity, 로고, 구도, 무드, 시간, 비용을 표시합니다.
- 오픈소스 provider는 RTX 4060 8GB와 Colab L4 프로파일을 분리해 VRAM, cold start, 평균·p95 시간을 기록합니다.
- provider 하나의 실패가 다른 provider의 원본 결과를 삭제하지 않도록 부분 성공 상태를 지원합니다.

## 10. API와 데이터 계약의 버전 전략

파일럿에서는 기존 단일 이미지 API를 유지합니다. fan-out과 QA metadata를 현재 `{result_image}` 응답에 억지로 넣지 않습니다.

후속 비교 API는 새 버전으로 설계합니다.

```json
{
  "request_id": "...",
  "preset_id": "wood__product_center",
  "status": "completed",
  "results": [
    {
      "provider_id": "openai-gpt-image-2-low",
      "image_url": "...",
      "gate_status": "pass",
      "qa": {},
      "latency_ms": 0,
      "cost": {}
    }
  ]
}
```

이미지 URL은 각 provider 원본을 가리키며 grid URL을 반환하지 않습니다. 현재 Gateway의 idempotency와 상태 모델은 유지하되, 다중 결과는 신규 workflow/API version에서 명시적으로 확장합니다.

## 11. 단계별 실행 계획

### 단계 0 — 두 preset 연결

- `openai-gpt-image-2-low-v1`을 병렬 등록합니다.
- 두 preset mapping, lighting sheet, prompt contract, 허용 자산과 checksum을 Git에 고정합니다.
- 나머지 10개를 명시적으로 비활성화합니다.
- provider를 mock한 무비용 통합 테스트 뒤 화이트·우드 각 1회 실제 low smoke test를 수행합니다.
- 4:5 결과를 backend/frontend에서 끝까지 보존합니다.

### 단계 1 — 12-slot authoring 체계

- preset package schema와 authoring validator를 고정합니다.
- 새 preset은 `draft -> review -> enabled` 승격만 허용합니다.
- 프론트·백엔드 references를 registry에서 생성합니다.
- Vivid 교체 계열은 최종 이름과 네 프리셋이 승인될 때 한 번에 새 family version으로 등록합니다.

### 단계 2 — CommonQA shadow mode

- OCR, DINOv2, bbox, BiRefNet을 생성 뒤 독립 단계로 추가합니다.
- 승인/실패 샘플로 threshold를 보정하고 QA version을 실행 manifest에 남깁니다.
- hard gate를 실제 사용자 차단에 적용하기 전 오탐·미탐을 검수합니다.

### 단계 3 — 오픈소스 fan-out

- 동일 request에서 OpenAI와 오픈소스 provider를 병렬 실행합니다.
- 이미지별 독립 저장과 동일 QA를 적용합니다.
- 품질뿐 아니라 RTX 4060 8GB/L4 VRAM, 시간, 장애율, 운영비를 함께 비교합니다.

### 단계 4 — GCS 자산 전환

- manifest와 preset ID는 유지하고 asset resolver만 교체합니다.
- Git의 작은 JSON 계약은 계속 version control에 둡니다.
- 바이너리는 versioned GCS object + checksum + 로컬 캐시로 전환합니다.
- 다운로드 실패나 checksum 불일치는 provider 호출 전에 실패시킵니다.

## 12. 검증 매트릭스

| 계층 | 필수 검증 |
| --- | --- |
| Registry | schema, enabled 상태, ID 유일성, 지원 2개/미지원 10개 |
| Assets | repository-relative path, 루트 이탈 차단, 존재, 크기, SHA-256, 역할·전송 정책 |
| Prompt | preset별 snapshot, 제품 수 1, 보존·금지 조건, asset 순서 |
| Provider | model/quality/size 고정, `input_fidelity` 미전송, timeout, secret redaction, retries 0 |
| Workflow | API/UI topology, binding, 최종 output node, legacy `model-c-v1` 보존 |
| Gateway | canonical `preset_id`, legacy 두 조합 fallback, 나머지 400, idempotency |
| Output | 4:5 `1024x1280` 또는 1:1 `1024x1024`, 제품·그림자·여백 무크롭·무리사이즈 |
| Backend | workflow·비율 allowlist, 요청 비율 보존, 임의 crop 차단, rollback |
| Frontend | 두 카드만 선택 가능, 10개 준비 중, 요청 비율 표시; 1:1은 QA 전 숨김 |
| Paid smoke | 화이트·우드 각 1회, 독립 파일, 시간·오류·prompt ID 기록 |

실제 API 키가 없는 환경에서는 mock E2E까지 완료하고 `실제 생성 미검증`을 명확히 남깁니다. mock 성공을 실제 OpenAI 성공으로 보고하지 않습니다.

## 13. 완료 조건

- 두 서비스 ID가 정확한 내부 preset contract로만 해석됩니다.
- lighting sheet, preset, hint/material 역할과 checksum이 모두 재현 가능합니다.
- OpenAI model과 quality가 profile에서 고정되고 레거시 `strength`와 분리됩니다.
- 요청 비율이 ComfyUI, Gateway, backend, frontend, 다운로드까지 보존됩니다.
- 나머지 10개는 provider 비용이 발생하기 전에 차단됩니다.
- `model-c-v1`은 독립적으로 계속 동작하며 환경변수 하나로 롤백할 수 있습니다.
- 실제 화이트·우드 low smoke test와 결과 검수 기록이 남습니다.
- 다음 preset 추가는 graph 복제가 아니라 registry/package 추가로 끝납니다.
- CommonQA와 provider fan-out을 현재 서비스 계약을 깨지 않고 붙일 수 있습니다.
