from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router

app = FastAPI()

# React 개발 서버 및 배포된 프론트엔드에서 오는 요청을 허용.
# - localhost:5173 (PC에서 로컬 개발)
# - 192.168.x.x:5173, 10.x.x.x:5173 (같은 Wi-Fi의 휴대폰에서 로컬 개발 서버 접속)
# - https://*.vercel.app (Vercel에 배포된 실제 프론트엔드)
#   Vercel은 배포할 때마다 매번 다른 서브도메인(예: frontend-xxxx-ad-creator.vercel.app)을
#   추가로 만들어주기 때문에, 특정 주소 하나만 고정하지 않고 *.vercel.app 패턴 전체를 허용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}):5173|https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
