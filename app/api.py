import asyncio
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.inference import generate_beverage_image


app = FastAPI(title="KH V2 Beverage Image API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("BVS_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(config.BASE_DIR)
INPUT_DIR = Path(config.INPUT_DIR)
OUTPUT_DIR = Path(config.OUTPUT_DIR)

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# One FLUX generation at a time per GPU/process.
generation_lock = asyncio.Lock()


def log(message: str):
    print(f"[kh-v2-api] {message}", flush=True)


@app.get("/")
def root():
    return {
        "ok": True,
        "service": "KH V2 Beverage Image API",
        "health": "/health",
        "docs": "/docs",
        "generate": "/generate",
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "model": config.MODEL_ID,
        "compositions": config.COMPOSITIONS,
        "background_styles": config.BACKGROUND_STYLES,
        "strengths": config.STRENGTHS,
    }


@app.post("/generate")
async def generate(
    image: UploadFile = File(...),
    composition: str = Form(...),
    background_style: str = Form("wood"),
    strength: str = Form("medium"),
    seed: Optional[int] = Form(None),
):
    request_id = uuid.uuid4().hex[:8]
    started_at = time.time()

    log(
        f"{request_id} request received | "
        f"filename={image.filename} | "
        f"composition={composition} | "
        f"background_style={background_style} | "
        f"strength={strength} | "
        f"seed={seed}"
    )

    if composition not in config.COMPOSITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported composition: {composition}")
    if background_style not in config.BACKGROUND_STYLES:
        raise HTTPException(status_code=400, detail=f"Unsupported background_style: {background_style}")
    if strength not in config.STRENGTHS:
        raise HTTPException(status_code=400, detail=f"Unsupported strength: {strength}")

    ext = Path(image.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".png"

    input_path = INPUT_DIR / f"upload_{request_id}_{uuid.uuid4().hex}{ext}"

    log(f"{request_id} saving upload -> {input_path}")
    with input_path.open("wb") as f:
        shutil.copyfileobj(image.file, f)

    log(f"{request_id} waiting for generation lock")

    async with generation_lock:
        log(f"{request_id} generation started")
        log(f"{request_id} model may take a while on first request")

        result = await asyncio.to_thread(
            generate_beverage_image,
            image_path=str(input_path),
            composition=composition,
            background_style=background_style,
            strength=strength,
            seed=seed,
            output_dir=str(OUTPUT_DIR),
        )

        log(f"{request_id} generation function returned")

    if not result.get("success"):
        log(f"{request_id} generation failed | {result}")
        raise HTTPException(status_code=500, detail=result)

    output_path = Path(result["output_path"])
    output_url = f"/outputs/{output_path.name}"

    elapsed = round(time.time() - started_at, 2)

    log(
        f"{request_id} generation complete | "
        f"output={output_path} | "
        f"elapsed={elapsed}s | "
        f"seed={result.get('seed')}"
    )

    return {
        "success": True,
        "image_url": output_url,
        "output_path": str(output_path),
        "composition": result.get("composition"),
        "background_style": result.get("background_style"),
        "strength": result.get("strength"),
        "seed": result.get("seed"),
        "elapsed_seconds": result.get("elapsed_seconds", elapsed),
    }


@app.get("/outputs/{filename}")
def get_output(filename: str):
    path = OUTPUT_DIR / filename

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Output image not found")

    return FileResponse(path)
