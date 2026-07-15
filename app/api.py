import asyncio
import os
import shutil
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

# FLUX generation is heavy. Keep one generation active per process/GPU.
generation_lock = asyncio.Lock()


@app.get("/health")
def health():
    return {
        "ok": True,
        "model": config.MODEL_ID,
        "compositions": config.COMPOSITIONS,
        "background_styles": config.BACKGROUND_STYLES,
    }


@app.post("/generate")
async def generate(
    image: UploadFile = File(...),
    composition: str = Form(...),
    background_style: str = Form("wood"),
    strength: str = Form("medium"),
    seed: Optional[int] = Form(None),
):
    if composition not in config.COMPOSITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported composition: {composition}")
    if background_style not in config.BACKGROUND_STYLES:
        raise HTTPException(status_code=400, detail=f"Unsupported background_style: {background_style}")
    if strength not in config.STRENGTHS:
        raise HTTPException(status_code=400, detail=f"Unsupported strength: {strength}")

    ext = Path(image.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".png"

    input_path = INPUT_DIR / f"upload_{uuid.uuid4().hex}{ext}"
    with input_path.open("wb") as f:
        shutil.copyfileobj(image.file, f)

    async with generation_lock:
        result = await asyncio.to_thread(
            generate_beverage_image,
            image_path=str(input_path),
            composition=composition,
            background_style=background_style,
            strength=strength,
            seed=seed,
            output_dir=str(OUTPUT_DIR),
        )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result)

    output_path = Path(result["output_path"])
    try:
        output_url = f"/outputs/{output_path.name}"
    except Exception:
        output_url = None

    return {
        "success": True,
        "image_url": output_url,
        "output_path": str(output_path),
        "composition": result.get("composition"),
        "background_style": result.get("background_style"),
        "strength": result.get("strength"),
        "seed": result.get("seed"),
        "elapsed_seconds": result.get("elapsed_seconds"),
    }


@app.get("/outputs/{filename}")
def get_output(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Output image not found")
    return FileResponse(path)
