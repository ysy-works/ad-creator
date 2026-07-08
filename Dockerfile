# GCP GPU VM / Container 배포용. 
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 python3-pip git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

# HF_TOKEN은 런타임에 -e HF_TOKEN=... 로 주입
ENV PSG_QUANT=nf4 \
    PSG_STEPS=30 \
    PSG_GUIDANCE=2.5 \
    PSG_WARMUP=1

EXPOSE 8080
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080"]
