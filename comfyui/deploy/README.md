# GCP 독립 환경 배포

이 문서는 기존 `model-c` 서비스와 완전히 분리된 ComfyUI/Gateway 환경을 설치하는 기준입니다.

## 고정 조건

```text
기존 model-c      127.0.0.1:8001, 기존 사용자/가상환경 유지
ComfyUI           127.0.0.1:8188, CPU 전용
Gateway           127.0.0.1:8002, Bearer 인증
외부 진입점       Caddy :443
ComfyUI           v0.28.0 / 700821e1364eaab0e8f21c538a2131719fec57bf
PyTorch CPU       2.6.0+cpu
Python            3.10
```

`model-c` 코드, 브랜치, README, 가상환경, 프로세스와 포트는 수정하지 않습니다.

## 설치 순서

1. 사전 확인

```bash
df -h /
curl --fail http://127.0.0.1:8001/health
ss -ltn | grep -E ':(8001|8002|8188|80|443)\b' || true
```

2. 소스와 독립 가상환경

```bash
sudo install -d -o spai0813 -g spai0813 \
  /opt/ad-creator /opt/comfyui /opt/venv/comfyui
git clone --branch comfyui --single-branch https://github.com/ysy-works/ad-creator.git /opt/ad-creator
git clone --branch v0.28.0 --depth 1 https://github.com/Comfy-Org/ComfyUI.git /opt/comfyui/ComfyUI
python3 -m venv /opt/venv/comfyui
/opt/venv/comfyui/bin/python -m pip install --upgrade pip
/opt/venv/comfyui/bin/python -m pip install --no-cache-dir \
  --index-url https://download.pytorch.org/whl/cpu \
  torch==2.6.0+cpu torchvision==0.21.0+cpu torchaudio==2.6.0+cpu
/opt/venv/comfyui/bin/python -m pip install --no-cache-dir \
  -r /opt/comfyui/ComfyUI/requirements.txt
/opt/venv/comfyui/bin/python -m pip install --no-cache-dir \
  -r /opt/ad-creator/comfyui/gateway/requirements.txt
ln -s /opt/ad-creator/comfyui/custom_nodes/ad_creator \
  /opt/comfyui/ComfyUI/custom_nodes/ad_creator
```

설치 직후 다음 값이 나와야 합니다.

```bash
/opt/venv/comfyui/bin/python -c \
  "import torch; print(torch.__version__, torch.cuda.is_available())"
# 2.6.0+cpu False

git -C /opt/comfyui/ComfyUI rev-parse HEAD
# 700821e1364eaab0e8f21c538a2131719fec57bf
```

3. 환경변수와 서비스

```bash
sudo install -d -m 0750 -o root -g spai0813 /etc/ad-creator
sudo install -m 0644 /opt/ad-creator/comfyui/deploy/systemd/*.service /etc/systemd/system/
sudo install -m 0644 /opt/ad-creator/comfyui/deploy/tmpfiles.conf \
  /etc/tmpfiles.d/ad-creator-comfyui.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/ad-creator-comfyui.conf
sudo systemctl daemon-reload
sudo systemctl enable --now ad-creator-comfyui ad-creator-gateway
```

실제 `/etc/ad-creator/*.env`는 예시 파일을 복사해 만들되, Gateway 키는 서버에서
`openssl rand -hex 32`로 생성합니다. 키를 Git, 로그 또는 채팅에 출력하지 않습니다.

4. 내부 검증

```bash
curl --fail http://127.0.0.1:8188/system_stats
curl --fail http://127.0.0.1:8188/object_info/AdCreatorModelCGenerate
curl --fail http://127.0.0.1:8002/health
curl -i http://127.0.0.1:8002/v1/generations/not-a-token
```

마지막 요청은 `401 Unauthorized`가 정상입니다.

5. HTTPS

Caddy의 공식 Debian/Ubuntu 저장소로 Caddy를 설치하고 `Caddyfile.example`의 호스트명을
실제 공개 호스트명으로 바꿉니다. GCP 방화벽에서는 80/443만 허용하고 8001/8002/8188은
외부에 공개하지 않습니다.

## 백엔드 연동 원칙

- 기존 백엔드 DB에 `generation_id`, `workflow_id`, 상태와 결과 URL을 저장합니다.
- Gateway는 별도 DB를 사용하지 않습니다.
- 생성 `POST`는 자동 재시도하면 중복 작업이 생길 수 있으므로, 연결 결과가 불명확할 때는
  사용자에게 상태를 확인시키거나 명시적으로 재시도합니다.
- 상태 조회는 2~3초 간격으로 시작해 최대 5초 간격으로 폴링합니다.
- Gateway 비밀키는 Render의 서버 환경변수에만 저장하고 프론트엔드로 전달하지 않습니다.

## 롤백

ComfyUI/Gateway만 중지합니다. 기존 `model-c`는 중지하거나 재시작하지 않습니다.

```bash
sudo systemctl disable --now ad-creator-gateway ad-creator-comfyui
```

삭제가 필요할 때도 `/opt/ad-creator`, `/opt/comfyui`, `/opt/venv/comfyui`,
`/etc/ad-creator`만 대상이며 `/opt/venv/product_swap`, `/opt/hf_cache`,
기존 `model-c` 작업 디렉터리는 대상이 아닙니다.
