# AD Creator 프리셋 작성·검증 AI 인수인계서

이 묶음의 목적은 새 담당자나 AI가 기존 설계를 생략하지 않고 다음 과정을 반복할 수 있게 하는 것이다.

`레퍼런스 선정 → 구조화 분석 → 프리셋·라이팅 시트 작성 → ComfyUI 워크플로 생성 → 0크레딧 검증 → 승인된 샘플 생성 → 정형·미감 평가 → 원인별 수정`

## AI에게 그대로 전달할 지시문

> 이 폴더를 프리셋 작성과 검증의 source of truth로 사용해. 먼저 `VALIDATION_CRITERIA.json`과 `schemas/`를 읽고, A6 v4 다중 우드 기준선과 최근 비교 실험에서 선택한 화이트 확산광 GPT 기준선을 각각 분석해. 새 레퍼런스를 선정한 뒤 동일한 파일 구조로 프리셋, 사진 스타일 계약, 장면 레시피, 라이팅 시트, 장면 그래프와 필요한 안전한 control input을 작성해. 그다음 OpenAI API용 ComfyUI workflow를 생성하고 0크레딧 검증을 먼저 실행해. 유료 생성은 별도 승인된 예산 안에서만 실행하며 자동 유료 수리는 금지해. 생성물은 정형 수치와 도쿄 편집숍 바이어·라이프스타일 MD 패널로 각각 평가하고, 실패 원인을 하나의 변수군으로 좁혀 한 번에 하나씩 수정해. 필수 측정이 없으면 pass가 아니라 `needs_review`로 남겨. 기존 스키마, 브랜드 계약, hot/cold 상태, 입력 4장 상한과 해시 기록을 임의로 생략하거나 변경하지 마.

## 대표 프리셋 1: 다중 우드 A6

대표 예시는 `tokyo_a6_relational_scene_hint_v4`다. 한 장의 사용자 말차 이미지와 비식별화된 장면 힌트를 사용해 다음을 재현한다.

- 우측 앞: 사용자 말차 1잔만 exact product
- 좌측 앞: 무로고 generic 음료 1개
- 뒤 중앙: 무로고 카라페 1개
- 전체 관계: 흰 원형 테이블 위 완전한 짙은 우드 원형 트레이
- 컵: 레퍼런스의 곡선형 풋 글라스와 흰 받침접시를 픽셀 복사 없이 재생성
- 빛: 먼 실내에는 건축적인 직사광, 앞쪽 트레이에는 열린 그늘과 넓은 반사광
- 브랜드: 최종 무로고

대표 실행 arm은 `sanitized_scene_hint + reference container design`이다. `structured_only`는 GPT Image 2가 트레이 군집을 크게 확대하는 경향이 확인되어 기본값으로 사용하지 않는다.

## 대표 프리셋 2: 화이트 기본 OpenAI 인수인계

화이트 기본 예시는 최근 5모델 비교에 사용한 `ref_white_diffuse_wall_table` (`ref_edbb2b01b3166422`)이다.

- 흰 테이블과 큰 warm-neutral 흰 벽
- 좌측의 매우 큰 확산 창광 하나
- 프레임 높이의 16~24%인 작은 단일 제품
- 최소 68%의 조용한 여백
- 제품 높이 또는 아주 약간 높은 50~60mm 환산 시점
- 최근 비교 실험의 GPT Image 2 대표 결과와 정확한 최종 prompt

정확한 실행 범위·결과·한계는 `WHITE_BASIC_OPENAI_REVIEW_KO.md`를 따른다. 대표 이미지는 Higgsfield 경유 GPT Image 2 결과이고, 팀원은 OpenAI API를 사용한다. 따라서 시각 기준선과 실제 프롬프트 증거를 유지하되, OpenAI API용 ComfyUI workflow에서 새 request hash·job ID·QA를 기록하고 다시 검증해야 한다.

## 파일 권위 순서

충돌이 있으면 다음 순서로 판단한다.

1. `VALIDATION_CRITERIA.json`의 hard-fail 규칙
2. JSON Schema
3. 제품·브랜드·서빙 상태 계약
4. Scene Graph의 활성 슬롯과 관계
5. 사진 스타일 계약과 reference preset의 구도·화각
6. Lighting Sheet의 광원·그림자·화이트밸런스
7. Material profile의 색·결·마감
8. 생성 프롬프트
9. 참고 이미지의 픽셀 인상

프롬프트는 상위 계약을 요약한 실행물이지 독립적인 권위가 아니다.

## ComfyUI JSON 사용법

- `workflows/*_api.json`: 자동 실행과 재현의 기준 파일이다.
- `workflows/*_gui.json`: 사람이 ComfyUI에서 구조를 확인하고 수정할 때 사용한다.
- `workflows/*_fake_api.json`: 공급자 호출 없이 연결·스키마·QA 경로를 확인한다.

ComfyUI JSON만 전달하면 안 된다. 노드가 참조하는 프리셋, 라이팅, 장면 그래프, container design, control input과 설정 파일을 함께 유지해야 한다. 공급자 어댑터는 교체할 수 있지만 `request.json`, 입력 역할, 해시, QA와 manifest 계약은 유지한다.

압축을 저장소 루트에 풀면 `presets/`, `data/`, `configs/`, `schemas/`, `scripts/`, `workflows/` 경로가 그대로 맞는다. `comfyui-inputs/`의 두 파일은 ComfyUI 입력 폴더에 업로드한 뒤 다음 이름으로 사용한다.

- `다운로드.jpeg`: GUI workflow가 기본으로 읽는 말차 제품 예시
- `ad_creator_original_input_01.jpg`: 캠페인 실행 스크립트가 사용하는 동일 말차 제품 예시
- `ad_creator_reference_a6.jpg`: reference ID와 Scene Graph를 해석하기 위한 오프라인 기준 이미지

화이트 기본 GPT 예시는 `example/white-basic-openai/`에 별도로 묶었다.

- `inputs/`: 대표 사용자 제품과 실제 화이트 레퍼런스
- `output/`: GPT Image 2 대표 결과
- `reproduction/`: 정확한 ledger case와 최종 prompt
- `evaluation/`: 해당 결과의 심사 패널 report 및 전체 화이트 실험 요약

팀원 실행 기준은 `workflows/20_white_basic_adopt_reference_openai_api.json`이다. 이 workflow는 `instagram_white_diffuse_wall_table_v1` mood package를 직접 읽는다. 현재 OpenAI adapter의 기본 모델은 `gpt-image-1-mini`이므로 기존 GPT Image 2 결과와 동일하다고 가정하지 않는다. 팀의 실제 모델 설정을 확정하고 컴파일 prompt를 역사적 `prompt.txt`와 대조한 뒤 같은 입력 역할·구도·조명 계약으로 재검증한다.

A6 원본 레퍼런스는 내부 인수인계와 오프라인 분석용으로만 포함했다. 사용 권리를 확인하지 않은 외부 재배포를 금지하며, A6에서 공급자에게 전달되는 런타임 장면 입력은 `data/reference-library/control-boards/a6-relational-scene-hint-v4/scene-hint.png`만 사용한다. 화이트 대표는 최근 실험과 동일하게 명시적인 두 번째 reference input을 사용하며, 역할·hash·복제 금지 계약을 manifest에 기록한다.

## 새 프리셋 작성 순서

1. 레퍼런스가 표현할 장면·빛·재질·피사체 관계를 한 문장으로 정의한다.
2. 레퍼런스에서 제품 정체성과 복제 금지 요소를 분리한다.
3. Scene Graph에 활성 슬롯, bbox, 받침 관계, occlusion과 support surface를 기록한다.
4. `reference-preset.json`에는 카메라·구도·여백·톤과 보존/수정 범위를 기록한다.
5. `photographic-style-contract.json`에는 화각, 촬영거리, 카메라 높이, pitch와 금지 인상을 기록한다.
6. `lighting-sheet.json`에는 광원의 종류·방향·크기·hardness·shadow density·WB를 기록한다.
7. `scene-recipe.json`에는 슬롯 사이의 결합 규칙과 실패 복구 순서를 기록한다.
8. 재질은 조명과 분리한다. 우드 색·결·마감은 material profile 또는 비식별화된 material board가 담당한다.
9. 이미지 입력은 역할과 순서를 고정하고 4장을 넘지 않는다.
10. API·GUI·fake API workflow를 생성하고 hash가 있는 실행 묶음을 남긴다.

## 검증 순서

1. 모든 JSON을 schema로 검사한다.
2. 파일 경로와 SHA-256을 검사한다.
3. fake provider로 ComfyUI 전체 경로를 실행한다.
4. prompt 길이, 입력 수, 모델·품질·seed와 비용 상한을 검사한다.
5. 승인 후 동일 조건으로 생성한다.
6. exact 제품 수, 정체성, hot/cold, bbox, 관계, 받침, 로고와 누출을 측정한다.
7. 정형 hard fail이 없을 때만 미감 패널을 실행한다.
8. 실패 원인을 `composition scale`, `camera`, `lighting`, `grade`, `container`, `brand`, `material` 중 하나로 분류한다.
9. 한 번에 한 변수군만 수정하고 나머지 조건은 고정한다.

## A6 v4에서 확인된 핵심 교훈

- bbox 숫자와 프롬프트만으로는 다중 피사체 크기가 강제되지 않았다.
- 트레이 군집을 0.76배로 선축소한 비식별 장면 힌트를 함께 주자 원본 A6에 가까운 크기가 나왔다.
- 따라서 다중 피사체 기본 경로는 `product_source + sanitized_scene_hint`다.
- 사용자 컵도 픽셀 경계를 보존하지 않고 디자인 계약으로 재생성해야 합성·스티커 느낌이 줄어든다.
- 대표 생성물은 현재 기준선이며 자동 QA 상태가 `needs_review`이면 사람의 최종 검토 없이 published로 승격하지 않는다.

## 제출물 체크리스트

- 새 프리셋 JSON 세트
- API·GUI·fake API ComfyUI workflow
- 입력 역할과 해시
- 최종 컴파일 프롬프트와 request
- 생성 이미지와 provider job/비용
- 정형 QA 및 미감 패널 결과
- 실패 원인과 수정한 단일 변수군
- 재현 manifest
