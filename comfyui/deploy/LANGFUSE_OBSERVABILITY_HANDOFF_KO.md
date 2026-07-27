# Langfuse 관측 연동 인계

## 적용 범위

`langfuse` 브랜치는 `model-c` 코드를 수정하지 않고 다음만 추가한다.

- Gateway: 익명 `X-Session-ID`, 생성 시작·완료 시각 저장
- Collector: 완료 작업과 OpenAI 감사 manifest를 읽어 Langfuse v4로 전송
- GCP: 외부 포트를 열지 않는 1분 주기 systemd timer

수집 항목:

- workflow, 성공/실패 상태
- Gateway 관측 소요 시간
- OpenAI 호출 소요 시간
- 모델, 품질, preset ID
- 텍스트 입력·이미지 입력·이미지 출력 토큰
- 공식 단가 기준 USD 비용
- 익명 세션 ID

수집하지 않는 항목:

- 업로드 이미지와 결과 이미지
- 원문 프롬프트
- 이미지 경로·이미지 해시
- 이메일, 이름, IP
- API 키

`Gateway 관측 소요 시간`은 Gateway가 요청을 받은 시점부터 백엔드 폴링으로
완료 상태를 처음 확인한 시점까지다. 따라서 폴링 간격이 포함되며 브라우저 렌더링
시간과는 다르다.

## 프론트엔드 담당 전달사항

수정 대상: `frontend/src/PicmoodTool.jsx` 1개

1. 최초 접속 시 `crypto.randomUUID()`로 익명 세션 ID를 만들고
   `localStorage`에 저장한다.
2. `/generate` 요청에만 아래 헤더를 추가한다.

```text
X-Session-ID: <저장된 UUID>
```

주의:

- 이메일·닉네임·파일명은 세션 ID로 사용하지 않는다.
- 세션 ID는 8~128자의 영문·숫자·점·밑줄·콜론·하이픈만 허용된다.
- Langfuse 키는 프론트에 절대 넣지 않는다.

## 백엔드 담당 전달사항

수정 대상:

- `app/api/router.py`
- `app/model/model.py`

작업:

1. `/generate`에서 `X-Session-ID` 요청 헤더를 선택값으로 받는다.
2. `generate_styled_image(...)`와 실제 Gateway 호출 함수까지 `session_id`를
   인자로 전달한다.
3. Gateway의 `POST /v1/generations` 요청 헤더에 값이 있을 때만 다음을 추가한다.

```text
X-Session-ID: <프론트에서 받은 값>
```

4. 기존 `Authorization`, `Idempotency-Key`, 재시도·폴링 로직은 변경하지 않는다.
5. 세션 ID를 로그에 출력하지 않는다.

검증:

- 헤더가 없는 기존 요청도 정상 생성
- 유효한 UUID 요청은 정상 생성
- 공백이 든 세션 ID는 Gateway에서 400
- 동일 세션의 여러 생성이 Langfuse Sessions에서 묶여 표시

브라우저 업로드부터 결과 렌더링까지의 정확한 체감 시간은 별도 프론트 telemetry가
필요하다. 현재 MVP에서는 비용, 모델 호출 시간, Gateway 전체 생성 시간을 우선
수집하며 이 추가 endpoint는 만들지 않는다.

## GCP 설치

실제 키는 채팅·Git·로그에 출력하지 않고
`/etc/ad-creator/observability.env`에만 저장한다.

```bash
sudo install -d -m 0755 -o spai0813 -g spai0813 /opt/venv/observability
sudo -u spai0813 -H python3 -m venv /opt/venv/observability
sudo -u spai0813 -H /opt/venv/observability/bin/python -m pip install \
  --no-cache-dir -r /opt/ad-creator/comfyui/observability/requirements.txt
sudo -u spai0813 -H /opt/venv/observability/bin/python -m pip check

test ! -e /etc/ad-creator/observability.env
sudo install -m 0640 -o root -g spai0813 \
  /opt/ad-creator/comfyui/deploy/observability.env.example \
  /etc/ad-creator/observability.env
# /etc/ad-creator/observability.env에 실제 Langfuse 키·리전 URL·release SHA 입력

sudo install -m 0644 \
  /opt/ad-creator/comfyui/deploy/systemd/ad-creator-langfuse.service \
  /etc/systemd/system/ad-creator-langfuse.service
sudo install -m 0644 \
  /opt/ad-creator/comfyui/deploy/systemd/ad-creator-langfuse.timer \
  /etc/systemd/system/ad-creator-langfuse.timer
sudo systemctl daemon-reload
```

먼저 전송 없는 검증:

```bash
sudo -u spai0813 -H bash -c \
  'set -a; source /etc/ad-creator/observability.env; set +a; \
  /opt/venv/observability/bin/python -B -m comfyui.observability.collector --dry-run'
```

실제 데이터가 없는 canary 1회:

```bash
sudo -u spai0813 -H bash -c \
  'set -a; source /etc/ad-creator/observability.env; set +a; \
  /opt/venv/observability/bin/python -B -m comfyui.observability.collector --canary'
```

Langfuse에서 canary의 상하위 span과 시간이 정상인지 확인한 뒤 실제 완료 작업을
한 번 전송하고 timer를 켠다.

```bash
sudo systemctl start ad-creator-langfuse.service
sudo systemctl status ad-creator-langfuse.service --no-pager
sudo journalctl -u ad-creator-langfuse.service -n 50 --no-pager
sudo systemctl enable --now ad-creator-langfuse.timer
systemctl list-timers ad-creator-langfuse.timer --no-pager
```

## 장애·롤백

Collector는 Gateway DB와 감사 manifest를 읽기만 하며 생성 요청 경로에서 실행되지
않는다. Langfuse 장애가 이미지 생성에 영향을 주지 않는다.

```bash
sudo systemctl disable --now ad-creator-langfuse.timer
```

Timer만 끄면 관측 전송이 중단된다. ComfyUI, Gateway, `model-c`는 중지하거나
재시작하지 않는다. 정상 전송으로 확인된 job ID는 별도 state DB에 기록되어
중복 전송을 방지한다.
