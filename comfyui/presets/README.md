# ComfyUI 프리셋

이 폴더는 서비스의 12개 광고 이미지 프리셋과 실행 계약을 보관합니다. 코드에 프리셋별 분기를 추가하지 않고, 공용 런타임이 JSON bundle을 해석합니다.

## 단일 권위

- `registry.json`: 슬롯, 공개 상태, 기본값, provider profile
- `<slot>/preset.json`: 컵 모드, 온도, 힌트 라우팅, 출력 비율, QA 계약
- `<slot>/prompt-template-*.txt`: 모드별 프롬프트
- `<slot>/container-design.json`: 레퍼런스 컵 설계가 필요한 경우
- `<slot>/mood/`, `<slot>/editorial/`: 조명·색감·구도 계약
- `assets/`: provider에 전송할 힌트 이미지
- `passed-presets.json`: 시각 QA 통과 기록

프리셋의 실제 상태는 README가 아니라 `registry.json`과 각 bundle을 기준으로 판단합니다.

## 슬롯

```text
natural_white__product_large
natural_white__product_center
natural_white__aerial_shot
natural_white__handheld_lifestyle
wood__product_large
wood__product_center
wood__aerial_shot
wood__handheld_lifestyle
vivid__product_large
vivid__product_center
vivid__aerial_shot
vivid__handheld_lifestyle
```

## 컵 모드

- `adopt_reference`: 사용자 음료는 유지하고 프리셋이 선언한 레퍼런스 컵을 채택
- `reconstruct_source`: 사용자 이미지의 컵 계열·재질·구조를 장면 안에서 다시 생성
- `default`: 각 프리셋의 `default_container_mode`로 해석

픽셀을 잘라 붙이는 방식은 사용하지 않습니다. 모드별 힌트가 있는 프리셋은 `provider_hint_role`과 `container_mode_scope`로 정확히 한 장만 선택합니다.

## 프리셋 추가·수정 절차

1. 기존 12개 슬롯 중 대상 슬롯을 확인합니다. 새 서비스 선택지가 합의되지 않았다면 슬롯을 임의로 늘리지 않습니다.
2. 힌트 이미지를 `assets/`에 넣고 크기와 SHA-256을 `preset.json`에 기록합니다.
3. 사용자 컵과 레퍼런스 컵이 다른 힌트를 쓰면 각각 별도 role과 mode scope를 선언합니다.
4. `4:5=1024x1280`, `1:1=1024x1024`, 기본 품질 `medium` 계약을 유지합니다.
5. 프롬프트·asset hash·모드 라우팅 테스트를 함께 수정합니다.
6. 정적 검증 후 필요한 조합만 실제 생성하여 시각 QA합니다. 12×2×2 전체를 반복 호출하지 않습니다.
7. 통과한 경우에만 registry와 `passed-presets.json`의 상태를 일치시킵니다.

```bash
python comfyui/scripts/validate_presets.py
python comfyui/scripts/validate_workflows.py
python -m unittest discover -s comfyui/tests -v
```

## 화이트 항공샷

`natural_white__aerial_shot`은 컵 복제를 막기 위해 모드별 힌트를 분리합니다.

- 레퍼런스 컵: `white-overhead-reference-cup-evidence-board-v4.png`
- 사용자 컵: `white-overhead-source-cup-evidence-board-v4.png`

두 파일을 동시에 전송하지 않으며 사용자 제품 1장과 선택된 힌트 1장만 provider에 제출합니다.

## 과거 제작 자료

최종 런타임에 병합하지 않은 제작 이력은 태그로 보존합니다. 현재 런타임과의 대응 관계는 [`AUTHORING_PROVENANCE.md`](AUTHORING_PROVENANCE.md)에 기록합니다.
