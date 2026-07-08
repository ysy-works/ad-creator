"""
FastAPI 서버 (GCP GPU VM 상시 가동용).

부팅 시 모델을 상주(warmup)시키고, 요청마다 제품 교체를 수행한다.

실행:
  uvicorn app.server:app --host 0.0.0.0 --port 8080

엔드포인트:
  GET  /health           서버/모델 상태
  GET  /categories       스타일/구도 목록
  GET  /library-status   12개 카테고리 템플릿 보유 현황
  POST /swap             제품 사진 업로드 + 스타일/구도 → 결과
  GET  /result/{job_id}  결과 이미지 파일
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from configs import config
from app import pipeline
from app import template_library as tl

app = FastAPI(title="Product Swap API")


@app.on_event("startup")
def _warmup():
    # 상시 가동: 부팅 때 모델을 미리 올려 첫 요청 지연 제거
    if os.environ.get("PSG_WARMUP", "1") == "1":
        print("[server] warming up model...")
        pipeline.get_generator()
        print("[server] model ready.")


@app.get("/health")
def health():
    loaded = pipeline._GENERATOR is not None
    return {"status": "ok", "model_loaded": loaded, "model": config.GEN_MODEL_ID}


@app.get("/categories")
def categories():
    return pipeline.list_categories()


@app.get("/library-status")
def library_status():
    return {"categories": tl.library_status()}


@app.post("/swap")
async def swap(
    product_image: UploadFile = File(...),
    style_id: str = Form(...),
    composition_id: str = Form(...),
    template_name: str = Form(None),
    product_desc: str = Form("the product"),
    seed: int = Form(None),
    extra_instruction: str = Form(""),
):
    # 업로드 파일을 임시 저장
    suffix = os.path.splitext(product_image.filename or "")[1] or ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(product_image.file, tmp)
        tmp.close()
        meta = pipeline.run_swap(
            product_image_path=tmp.name,
            style_id=style_id,
            composition_id=composition_id,
            template_name=template_name or None,
            product_desc=product_desc,
            seed=seed,
            extra_instruction=extra_instruction,
        )
    except (KeyError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"generation failed: {e}")
    finally:
        os.unlink(tmp.name)

    # 결과 이미지 URL 경로 포함해 반환
    return JSONResponse({
        "job_id": meta["job_id"],
        "style_id": meta["style_id"],
        "composition_id": meta["composition_id"],
        "template_used": os.path.basename(meta["template_used"]),
        "seed": meta["seed"],
        "result_url": f"/result/{meta['job_id']}",
        "prompt": meta["prompt"],
    })


@app.get("/result/{job_id}")
def get_result(job_id: str):
    path = os.path.join(config.OUTPUTS_DIR, job_id, "result.png")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="result not found")
    return FileResponse(path, media_type="image/png")
