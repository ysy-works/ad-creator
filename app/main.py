from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router

app = FastAPI()

# React 개발 서버에서 오는 요청을 허용.
# - localhost:5173 (PC에서 접속)
# - 192.168.x.x:5173, 10.x.x.x:5173 등 같은 Wi-Fi(사설망) IP:5173 (휴대폰에서 접속)
# IP는 Wi-Fi가 바뀔 때마다 달라질 수 있어서, 특정 IP 하나를 고정하지 않고
# 정규식으로 "사설망 대역 + 5173포트" 패턴 전체를 허용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}):5173",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
