# Pickmood

> 사용자가 촬영한 제품 사진을 카페 SNS 광고 이미지와 게시 문구로 변환하는 생성형 AI 서비스

Pickmood는 단순히 보기 좋은 이미지를 새로 만드는 서비스가 아닙니다. 카페 운영자가 직접 촬영한 음료 사진에서 제품의 종류·색상·서빙 상태와 컵의 특징을 읽고, 미리 설계한 장면 규칙과 시각 힌트를 적용해 광고에 활용할 수 있는 라이프스타일 이미지로 변환합니다. 생성 결과와 함께 SNS 게시 문구도 제공합니다.

## 프로젝트 산출물

- [최종 보고서 PDF 다운로드](./Pickmood_REPORT.pdf)
- [협업일지](https://docs.google.com/spreadsheets/d/1LIsT5yt4gG0rQubbrsNlXbZtpIVoe3cvaPBu6_kfPlU/)  
  문서 하단의 탭을 선택하면 팀원별 협업일지를 조회할 수 있습니다.
- [발표자료 PPT](https://docs.google.com/presentation/d/1TxUqSi-ZDf_O5U87WIIesu-YChhfhHB48nWH5gY5WiQ/edit?usp=drive_link)

## 핵심 차별점

- 긴 프롬프트 없이 프리셋을 선택해 카메라·빛·구도·배치·재질 규칙을 적용합니다.
- 제품 정체성과 장면 정보를 분리해, 제품은 유지하면서 배경과 촬영 조건을 바꿉니다.
- 텍스트로 전달하기 어려운 컵 형태·손의 각도·재질·빛·배치는 힌트 이미지로 보완합니다.
- 프리셋마다 실행 그래프를 복제하지 않고 하나의 ComfyUI 공용 런타임에서 처리합니다.
- 이미지 생성뿐 아니라 인스타그램 게시 목적에 맞는 문구까지 한 흐름으로 제공합니다.

## 주요 기능

### 12개 장면 프리셋

약 700장의 카페 SNS 레퍼런스를 분류해 3개 무드와 4개 촬영 구도의 조합을 설계했습니다.

| 구분 | 선택지 |
| --- | --- |
| 무드 | 뉴트럴 화이트 · 우드 · 다크 그레이 |
| 촬영 구도 | 클로즈업 · 미디엄 · 오버헤드 · 핸드헬드 |
| 컵 모드 | 사용자 컵 유지 · 레퍼런스 컵 적용 |
| 출력 비율 | 4:5 · 1:1 |
| 생성 품질 | low · medium · high |

서비스 기본 품질은 비용·속도·시각 품질의 균형을 고려해 `gpt-image-2`의 `medium`으로 설정했습니다.

### 구조화된 프리셋 패키지

프리셋은 하나의 프롬프트 파일이 아닙니다. 라우팅과 정책, 장면·조명 규칙, 프롬프트 템플릿, 시각 힌트를 역할별 파일로 분리하고 공용 조립 모듈이 적용 범위와 우선순위를 확인한 뒤 최종 프롬프트를 구성합니다.

### 시각 힌트

컵 형태, 손과 컵의 각도, 재질, 빛, 사물 배치처럼 텍스트만으로 안정적으로 전달하기 어려운 정보는 보조 이미지로 입력합니다. 필요한 영역은 크롭하고 직접 복제될 수 있는 영역은 블러 처리해 의도한 형태 정보만 전달합니다.

### SNS 문구 생성

선택한 무드와 구도, 사용자가 입력한 메뉴 정보를 바탕으로 결과 이미지와 함께 사용할 게시 문구를 생성합니다.

## 서비스 흐름

```text
사용자
  │  제품 사진 업로드 · 프리셋/컵/비율 선택
  ▼
React/Vite 프론트엔드
  ▼
FastAPI 백엔드
  │  요청 검증 · 이미지/옵션 전달 · 게시 문구 생성
  ▼
Generation Gateway
  │  인증 · 중복 요청 방지 · 작업 상태 관리
  ▼
ComfyUI 공용 런타임
  │  preset_id 해석 · 프리셋 조립 · 모델 호출
  ▼
OpenAI Images API (gpt-image-2)
  │
  └─ 생성 결과 반환 ──► 사용자

Gateway · ComfyUI · OpenAI 실행 기록
  └─► Langfuse 관측
```

프론트엔드, 백엔드, Gateway, ComfyUI 공용 런타임은 GCP 환경에 배포했습니다. 이미지 파일용 별도 GCS 저장 구조는 현재 범위에 포함하지 않았습니다.

## 관측 지표

Langfuse에서 익명 세션을 기준으로 모델·프리셋·품질·비율·성공 여부·비용을 추적합니다. 시간은 목적이 다른 두 지표로 분리합니다.

- **모델 생성 시간:** AI가 이미지를 생성하는 데 걸린 시간
- **사용자 체감 완료 시간:** 사용자가 생성을 클릭한 뒤 결과를 화면에서 확인하기까지 걸린 전체 시간

## 검증 범위

12개 프리셋 × 2개 컵 모드 × 3개 품질의 총 72개 조합을 유료 생성으로 검증했습니다. 또한 프리셋·워크플로 레지스트리, Gateway, 모델 어댑터, Langfuse 수집기와 프론트엔드 완료 시간 전달 경로를 자동 테스트로 확인합니다.

이 검증은 등록된 실행 조합이 정상 작동하는지 확인한 것으로, 모든 사용자 입력에서 동일한 품질을 보장한다는 의미는 아닙니다.

## 저장소 구조

```text
Pickmood/
├─ frontend/                         # React/Vite 사용자 화면
├─ app/                              # FastAPI 백엔드, 문구 생성, Gateway 연동
├─ comfyui/
│  ├─ config/providers/              # 모델 제공자 설정
│  ├─ presets/                       # 12개 프리셋 패키지와 레지스트리
│  ├─ workflows/                     # UI용·API용 ComfyUI 워크플로
│  ├─ custom_nodes/ad_creator/       # 공용 생성 노드와 모델 어댑터
│  ├─ orchestrator/                  # 프리셋·워크플로 라우팅
│  ├─ gateway/                       # 인증·작업 상태·중복 요청 방지
│  ├─ observability/                 # Langfuse 수집과 비용 계산
│  ├─ deploy/                        # GCP 배포 설정과 운영 문서
│  ├─ scripts/                       # 레지스트리 검증·실행 도구
│  └─ tests/                         # 공용 런타임 자동 테스트
├─ comfyui_nodes/                    # 외부 제공자 연동 노드
├─ requirements.txt                  # 백엔드 Python 의존성
└─ README.md                         # 프로젝트 전체 안내
```

하위 README는 각 컴포넌트 담당자가 작성한 원문이며, 최종 통합 과정에서 수정하지 않았습니다.

## 브랜치 운영 기준

| 브랜치 | 역할 |
| --- | --- |
| `main` | 검증을 통과한 최종 통합본이자 릴리스 기준 |
| `backend` · `frontend` · `presets` · `serving` · `langfuse` | 담당 영역의 개발·검증 이력 보존 |
| `model-c` | 오픈소스 모델 실험과 FastAPI 어댑터 이력 보존 |

각 담당 영역의 변경 사항은 검증 후 Pull Request를 통해 `main`에 통합하며, `main`을 최종 소스 기준으로 사용합니다. 임시 통합 브랜치였던 `deploy`는 최종 병합 후 삭제되어 장기 운영 브랜치로 유지하지 않습니다. 담당 영역 브랜치와 `model-c`는 개발·연구 이력을 보존하기 위해 최종 서비스 소스와 분리합니다.

## 로컬 실행

### 백엔드

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

`app/.env.example`을 참고해 서버 환경 변수를 설정합니다. 이미지 생성은 `COMFYUI_GATEWAY_BASE_URL`과 `COMFYUI_GATEWAY_API_KEY`가 필요하며, API 키는 프론트엔드에 노출하지 않습니다.

### 프론트엔드

```bash
cd frontend
npm ci
npm run dev
```

### 공용 런타임 검증

```bash
python comfyui/scripts/validate_workflows.py
python comfyui/scripts/validate_presets.py
python -B -m unittest discover -s comfyui/tests -v
```

세부 실행·배포 방법은 [`comfyui/README.md`](comfyui/README.md)와 [`comfyui/deploy/README.md`](comfyui/deploy/README.md)를 참고합니다.

## 현재 한계와 확장 방향

- 레퍼런스 분석과 프리셋 제작·품질 평가는 아직 수작업 비중이 큽니다.
- 생성 결과의 제품 잘림, 문자 오류, 정체성 변형을 자동 검사하는 평가 체계가 더 필요합니다.
- 다중 작업 처리, 외부 저장소, 장애 복구를 포함한 운영 구조 고도화가 필요합니다.
- 로고 합성, 선택 영역 재생성, 부분 편집 기능은 후속 과제입니다.
- 향후 음료에서 디저트·베이커리·음식으로 확장하고, 매장별 색감·구도·문구 스타일과 인테리어를 반영한 전용 프리셋을 제공할 수 있습니다.
