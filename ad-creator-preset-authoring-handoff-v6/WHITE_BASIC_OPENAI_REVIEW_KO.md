# 화이트 기본 대표 프리셋: OpenAI API 인수인계

## 선정 기준

화이트 기본 대표는 최근 모델 비교에서 사용한 `ref_white_diffuse_wall_table` (`ref_edbb2b01b3166422`)의 GPT Image 2 arm을 기준으로 한다. 다른 모델의 차이는 팀 인수인계 범위에서 제외한다.

- 원본 레퍼런스: `45d43a2ace2d8cff291eec9395be7c16.jpg`
- 대표 제품: 무로고 딸기우유
- 컵 정책: `adopt_reference`
- 대표 결과: `p02_strawberry_milk_unbranded__ref_white_diffuse_wall_table__adopt_reference__gpt_image_2`
- 판정: 보완 후 재심

## 프리셋 계약

- 장면: 흰 테이블과 큰 warm-neutral 흰 벽
- 제품: 완전한 단일 음료 1개
- 제품 높이: 프레임의 16~24%
- 제품 폭: 프레임의 18% 이하
- 의미 있는 흰 벽·테이블 여백: 최소 68%
- 벽·테이블 경계: 프레임 높이의 80~84% 부근
- 카메라: 제품 높이 또는 아주 약간 높은 시점, 50~60mm 환산 normal perspective
- 조명: 좌측의 매우 큰 확산 창광 하나, 저대비, 부드럽게 붙은 접지 그림자
- 색: 낮은 채도와 절제된 warm-neutral white
- 컵: 무로고 짧은 직선형 세로 골 유리잔, 얇은 원형 림과 평평한 바닥
- 금지: 직사광 빔, 그래픽한 하드 섀도, 영웅형 제품 확대, 스튜디오 무영광, 인물 모드 블러, 가짜 글자·로고, AI 미니멀 템플릿

## 팀에 전달하는 실행 자료

`example/white-basic-openai/`에 다음을 넣는다.

- 실제 사용자 제품 입력
- 실제 화이트 레퍼런스 입력
- GPT Image 2 대표 결과
- 해당 결과에 사용한 정확한 최종 prompt
- 입력 hash, prompt hash, 모델 파라미터와 provider job ID가 있는 원본 ledger case
- 해당 결과의 심사 패널 report

정식 구조화 파일은 다음과 같다.

- `presets/editorial/instagram_white_diffuse_wall_table_v1/reference-preset.json`
- `presets/editorial/instagram_white_diffuse_wall_table_v1/photographic-style-contract.json`
- `presets/moods/instagram_white_diffuse_wall_table_v1/mood-package.json`
- `presets/moods/instagram_white_diffuse_wall_table_v1/lighting-sheet.json`
- `presets/moods/instagram_white_diffuse_wall_table_v1/scene-recipe.json`

`workflows/20_white_basic_adopt_reference_openai_api.json`은 위 mood package와 화이트 대표 입력을 직접 읽는 OpenAI API용 ComfyUI 기준 파일이다. API workflow가 source of truth이고 같은 번호의 GUI workflow는 확인·수정용이다.

## 재현성 주의

대표 이미지는 Higgsfield를 통해 GPT Image 2에 제출한 결과다. 팀원은 OpenAI API를 사용하므로 provider 경로는 다르다. 동일한 프리셋·입력 역할·품질·출력 크기·후처리 계약을 유지하되, ComfyUI가 새 구조화 계약에서 컴파일한 prompt를 역사적 `prompt.txt`와 먼저 비교하고 차이를 기록한다. 새 OpenAI job ID와 request hash도 별도로 남긴다.

현재 저장소의 OpenAI adapter 기본 모델은 `gpt-image-1-mini`다. 따라서 첨부한 OpenAI ComfyUI JSON은 API 연결 구조의 기준이지, 기존 GPT Image 2 결과와 픽셀 수준으로 동일하다는 증거가 아니다. 실행 전 팀의 실제 OpenAI 모델·quality 지원 범위를 provider config에서 확정하고 fake workflow와 0크레딧 검증을 먼저 통과시킨다.

## 현재 평가와 수정 목표

화이트 톤과 확산광은 안정적이지만 엄격 채택 결과는 아니다. 가장 큰 수정 목표는 다음 세 가지다.

1. 제품 bbox를 실제 측정해 16~24% 높이와 18% 폭 상한을 강제한다.
2. 흰 벽·흰 테이블이 반복적인 AI 미니멀 템플릿으로 보이지 않도록 제한된 구도 delta와 미세한 생활 흔적을 추가한다.
3. 현재 구조화한 preset + Lighting Sheet를 전체 레퍼런스 입력 arm과 구조화-only arm으로 A/B 검증해 레퍼런스 픽셀 의존도를 줄인다.

## 팀 공유 문구

“최근 비교 실험의 화이트 확산광 프리셋에서 가장 안정적이었던 GPT 결과를 기준선으로 전달합니다. 첨부된 프리셋 계약, 실제 입력, 최종 프롬프트와 평가를 유지하고 OpenAI API용 ComfyUI workflow로 재실행한 뒤 bbox·여백·조명·AI 티를 검증해 수정해 주세요.”
