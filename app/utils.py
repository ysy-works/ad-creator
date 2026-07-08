"""결과 저장 / 유틸."""
import json
import os
import uuid
from datetime import datetime, timezone
from PIL import Image


def new_job_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def save_json(obj: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_result(output_dir, job_id, result_image, input_image, template_image, metadata) -> dict:
    job_dir = os.path.join(output_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)

    result_path = os.path.join(job_dir, "result.png")
    input_path = os.path.join(job_dir, "input.png")
    template_path = os.path.join(job_dir, "template.png")
    meta_path = os.path.join(job_dir, "meta.json")

    result_image.save(result_path)
    input_image.convert("RGB").save(input_path)
    template_image.convert("RGB").save(template_path)

    metadata = {
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
        "files": {
            "result": result_path,
            "input": input_path,
            "template": template_path,
            "meta": meta_path,
        },
    }
    save_json(metadata, meta_path)
    return metadata
