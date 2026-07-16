# GCP 독립 환경 배포

기존 `model-c` 서비스와 완전히 분리된 ComfyUI/Gateway 환경을 설치하는 기준입니다.

## 고정 조건

```text
기존 model-c      0.0.0.0:8001, Gateway는 loopback으로 호출, 기존 바인딩 유지
ComfyUI           127.0.0.1:8188, CPU 전용
Gateway           127.0.0.1:8002, Bearer 인증, Uvicorn worker 1개
외부 진입점       Caddy :443
ComfyUI           v0.28.0 / 700821e1364eaab0e8f21c538a2131719fec57bf
PyTorch CPU       2.6.0+cpu
Python            3.10
실행 사용자       spai0813
```

`model-c` 코드, 브랜치, README, 가상환경, 프로세스와 포트는 수정하지 않습니다. `/opt/venv` 부모나 기존 model-c 경로를 재귀적으로 `chown`, `chmod`, 이동 또는 삭제하지 않습니다.

## 설치 순서

### 1. 사전 확인

```bash
python3 --version | grep '^Python 3\.10\.'
df -h /
curl --fail http://127.0.0.1:8001/health
ss -ltn | grep -E ':(8001|8002|8188|80|443)\b' || true
systemctl status ad-creator-comfyui ad-creator-gateway --no-pager || true
```

### 2. 승인된 패키지 커밋 고정

현재 GCP처럼 `/opt/ad-creator` checkout이 이미 있으면 새로 clone하지 않습니다. 작업 트리가 clean인지 확인한 뒤 승인된 커밋만 detached checkout합니다.

```bash
PACKAGE_COMMIT=COMFYUI_PACKAGE_COMMIT
test -d /opt/ad-creator/.git
test -z "$(sudo -u spai0813 -H git -C /opt/ad-creator status --porcelain)"
sudo -u spai0813 -H git -C /opt/ad-creator fetch origin comfyui
sudo -u spai0813 -H git -C /opt/ad-creator checkout --detach "$PACKAGE_COMMIT"
test "$(sudo -u spai0813 -H git -C /opt/ad-creator rev-parse HEAD)" = "$PACKAGE_COMMIT"
```

신규 서버에서만 `/opt/ad-creator`의 빈 경로를 `spai0813` 소유로 만든 뒤 clone합니다. 기존 checkout 위에 clone하지 않습니다.

### 3. 공식 ComfyUI와 독립 CPU 가상환경

아래 세 경로 자체만 `spai0813` 소유로 사용합니다. `/opt/venv` 부모 소유권은 바꾸지 않습니다.

```bash
sudo install -d -m 0755 -o spai0813 -g spai0813 /opt/comfyui
sudo install -d -m 0755 -o spai0813 -g spai0813 /opt/venv/comfyui
test ! -e /opt/comfyui/ComfyUI
test -z "$(find /opt/venv/comfyui -mindepth 1 -print -quit)"

sudo -u spai0813 -H git clone --branch v0.28.0 --depth 1 \
  https://github.com/Comfy-Org/ComfyUI.git /opt/comfyui/ComfyUI
test "$(sudo -u spai0813 -H git -C /opt/comfyui/ComfyUI rev-parse HEAD)" = \
  "700821e1364eaab0e8f21c538a2131719fec57bf"

sudo -u spai0813 -H python3 -m venv /opt/venv/comfyui
sudo -u spai0813 -H /opt/venv/comfyui/bin/python -m pip install --upgrade pip
sudo -u spai0813 -H /opt/venv/comfyui/bin/python -m pip install --no-cache-dir \
  --index-url https://download.pytorch.org/whl/cpu \
  torch==2.6.0+cpu torchvision==0.21.0+cpu torchaudio==2.6.0+cpu
sudo -u spai0813 -H /opt/venv/comfyui/bin/python -m pip install --no-cache-dir \
  -r /opt/comfyui/ComfyUI/requirements.txt
sudo -u spai0813 -H /opt/venv/comfyui/bin/python -m pip install --no-cache-dir \
  -r /opt/ad-creator/comfyui/gateway/requirements.txt
sudo -u spai0813 -H /opt/venv/comfyui/bin/python -m pip check
sudo -u spai0813 -H sh -c \
  '/opt/venv/comfyui/bin/python -m pip freeze > /opt/comfyui/installed-requirements.txt'
sudo -u spai0813 -H ln -s /opt/ad-creator/comfyui/custom_nodes/ad_creator \
  /opt/comfyui/ComfyUI/custom_nodes/ad_creator
```

설치 직후 CPU 전용 여부와 고정 커밋을 다시 확인합니다.

```bash
/opt/venv/comfyui/bin/python -c \
  "import torch; print(torch.__version__, torch.cuda.is_available())"
# 2.6.0+cpu False

test "$(git -C /opt/comfyui/ComfyUI rev-parse HEAD)" = \
  "700821e1364eaab0e8f21c538a2131719fec57bf"
```

### 4. 환경변수와 서비스

```bash
sudo install -d -m 0750 -o root -g spai0813 /etc/ad-creator
sudo bash -c '
  set -euo pipefail
  umask 0027
  test ! -e /etc/ad-creator/gateway.env
  test ! -e /etc/ad-creator/comfyui.env
  api_key=$(openssl rand -hex 32)
  signing_key=$(openssl rand -hex 32)
  install -m 0640 -o root -g spai0813 /dev/null /etc/ad-creator/gateway.env
  install -m 0640 -o root -g spai0813 /dev/null /etc/ad-creator/comfyui.env
  printf "%s\n" \
    "COMFYUI_BASE_URL=http://127.0.0.1:8188" \
    "AD_CREATOR_MODEL_C_URL=http://127.0.0.1:8001" \
    "AD_CREATOR_GATEWAY_API_KEY=$api_key" \
    "AD_CREATOR_GENERATION_SIGNING_KEY=$signing_key" \
    "AD_CREATOR_GATEWAY_DB=/var/lib/ad-creator-gateway/gateway.sqlite3" \
    "AD_CREATOR_MAX_QUEUED=3" > /etc/ad-creator/gateway.env
  printf "%s\n" \
    "AD_CREATOR_MODEL_C_URL=http://127.0.0.1:8001" \
    "AD_CREATOR_MODEL_C_TIMEOUT_SECONDS=420" > /etc/ad-creator/comfyui.env
'
sudo install -m 0644 /opt/ad-creator/comfyui/deploy/systemd/*.service /etc/systemd/system/
sudo install -m 0644 /opt/ad-creator/comfyui/deploy/tmpfiles.conf \
  /etc/tmpfiles.d/ad-creator-comfyui.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/ad-creator-comfyui.conf
sudo systemctl daemon-reload
sudo systemctl enable --now ad-creator-comfyui ad-creator-gateway
```

API 인증키와 generation 서명키는 서로 다른 값으로 서버에서 생성합니다. API 키만 백엔드에 안전하게 전달하며, 서명키는 GCP 밖으로 내보내지 않습니다. 키를 Git, 로그 또는 채팅에 출력하지 않습니다. 기존 env 파일이 있으면 설치 명령은 실패합니다.

### 5. 내부 검증

```bash
systemctl is-active ad-creator-comfyui ad-creator-gateway
curl --fail http://127.0.0.1:8188/system_stats
curl --fail http://127.0.0.1:8188/object_info/AdCreatorModelCGenerate
curl --fail http://127.0.0.1:8002/health
curl -i http://127.0.0.1:8002/v1/generations/not-a-token
```

마지막 요청은 `401 Unauthorized`가 정상입니다. 서비스는 Gateway worker 1개를 유지합니다. 프로세스를 여러 개로 늘리면 현재 process-local queue lock이 공유되지 않으므로 먼저 분산 락으로 바꿔야 합니다.

### 6. HTTPS

Caddy 2.10 이상의 공식 Debian/Ubuntu 저장소 패키지를 설치합니다.

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
  | gpg --dearmor \
  | sudo tee /usr/share/keyrings/caddy-stable-archive-keyring.gpg >/dev/null
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
CADDY_VERSION=$(caddy version | sed 's/^v//; s/ .*//')
dpkg --compare-versions "$CADDY_VERSION" ge 2.10.0
```

`Caddyfile.example`의 호스트명을 실제 공개 호스트명으로 바꿉니다.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

신규 ComfyUI/Gateway용 방화벽 규칙에는 80/443만 허용하고 8002/8188은 외부에 공개하지 않습니다. 기존 model-c 8001의 바인딩·네트워크 태그·방화벽 규칙은 변경하지 않습니다. 공개 후 외부에서 `https://HOST/health`의 `200` 응답과 API 키가 없는 생성 요청의 인증 실패 `401`을 확인합니다.

## 백엔드 연동 원칙

- 사용자 생성 동작마다 UUID `Idempotency-Key`를 발급하고 기존 백엔드 DB에 요청과 함께 저장합니다.
- 동일 요청의 네트워크 재시도에는 같은 키와 같은 이미지·옵션을 사용합니다. 명시적 재생성만 새 키를 사용합니다.
- 같은 키에 다른 입력을 보내면 `409`입니다. prompt 제출 결과가 불명확한 `unknown` 작업은 자동 재실행하지 않습니다.
- Gateway SQLite에는 idempotency 정보, ComfyUI prompt, 작업 상태와 완료 결과 파일 위치를 저장합니다.
- ComfyUI/VM 재시작 시 실행 중 작업은 복구되지 않으며 `unknown` 상태가 될 수 있습니다.
- 완료 이미지는 7일 후 정리되므로 백엔드는 성공 직후 영구 저장소로 복사합니다.
- 상태 조회는 2~3초 간격으로 시작해 최대 5초 간격으로 폴링합니다.
- Gateway API 키만 백엔드 서버 환경변수에 저장하고 프론트엔드로 전달하지 않습니다.

세부 요청·응답 계약은 `BACKEND_HANDOFF.md`를 따릅니다.

## API 키 안전 전달

서명키는 복사하지 않고 API 키만 0600 임시 파일로 전달합니다. 아래 예시는 현재 GCP SSH 사용자 `soyeon` 기준이며, 파일 내용은 터미널이나 채팅에 출력하지 않습니다.

```bash
sudo bash -c '
  set -euo pipefail
  umask 0077
  {
    printf "%s\n" "COMFYUI_GATEWAY_BASE_URL=https://GATEWAY_HOSTNAME"
    sed -n "s/^AD_CREATOR_GATEWAY_API_KEY=/COMFYUI_GATEWAY_API_KEY=/p" \
      /etc/ad-creator/gateway.env
    printf "%s\n" "COMFYUI_WORKFLOW_ID=model-c-v1"
  } > /home/soyeon/ad-creator-gateway-handoff.env
  chown soyeon:soyeon /home/soyeon/ad-creator-gateway-handoff.env
'
# 로컬 PC로 SCP한 뒤 서버 임시 파일을 삭제합니다.
```

## 롤백

ComfyUI/Gateway만 중지합니다. 기존 `model-c`는 중지하거나 재시작하지 않습니다.

```bash
sudo systemctl disable --now ad-creator-gateway ad-creator-comfyui
```

HTTPS까지 적용했다면 Caddy route 제거와 80/443 방화벽 규칙 회수도 롤백 범위에 포함합니다. 완전 삭제는 `/opt/ad-creator`, `/opt/comfyui`, `/opt/venv/comfyui`, `/etc/ad-creator`, `/var/lib/ad-creator-gateway`, `/etc/tmpfiles.d/ad-creator-comfyui.conf`, `/etc/systemd/system/ad-creator-{comfyui,gateway}.service`만 대상으로 별도 승인 후 수행합니다. `/opt/venv/product_swap`, `/opt/hf_cache`, 기존 `model-c` 작업 디렉터리는 대상이 아닙니다.
