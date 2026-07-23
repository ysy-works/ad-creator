from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from ..generation_inputs import ordered_image_inputs
from .base import ProviderJob


class FakeGenerationProvider:
    """Deterministic, zero-credit provider used to validate orchestration."""

    name = "fake_local"
    is_zero_credit = True

    def __init__(self, output_dir: str | Path, *, fixture_image: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fixture_image = Path(fixture_image) if fixture_image else None
        self.submit_count = 0

    def _record_path(self, job_id: str) -> Path:
        return self.output_dir / f"{job_id}.json"

    def _load_job(self, job_id: str) -> ProviderJob:
        record = json.loads(self._record_path(job_id).read_text(encoding="utf-8"))
        output_path = Path(record["output_path"]) if record.get("output_path") else None
        return ProviderJob(
            job_id=job_id,
            status=record["status"],
            output_path=output_path,
            actual_credits=record.get("actual_credits"),
            metadata=record.get("metadata"),
        )

    def submit(self, request: dict[str, Any], *, idempotency_key: str) -> ProviderJob:
        job_id = f"fake-{idempotency_key[:20]}"
        record_path = self._record_path(job_id)
        if record_path.exists():
            return self._load_job(job_id)

        self.submit_count += 1
        source_path = self.fixture_image
        if source_path is None:
            image_inputs = ordered_image_inputs(request["generation"])
            if not image_inputs:
                raise ValueError("Fake provider needs a fixture image or generation image input")
            source_path = Path(image_inputs[0]["path"])
        if not source_path.exists():
            raise FileNotFoundError(f"Fake provider source image does not exist: {source_path}")

        output_path = self.output_dir / f"{job_id}.png"
        with Image.open(source_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            if self.fixture_image is None:
                target_width = min(image.width, 880)
                target_height = round(target_width * 4 / 3)
                image = ImageOps.pad(
                    image,
                    (target_width, target_height),
                    method=Image.Resampling.LANCZOS,
                    color=(242, 241, 238),
                    centering=(0.5, 0.55),
                )
            image.save(output_path, format="PNG", optimize=True)

        source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        record = {
            "job_id": job_id,
            "status": "completed",
            "output_path": str(output_path.resolve()),
            "actual_credits": 0,
            "metadata": {
                "provider": self.name,
                "source_sha256": source_digest,
                "fixture_mode": self.fixture_image is not None,
            },
        }
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return self._load_job(job_id)

    def get(self, job_id: str) -> ProviderJob:
        record_path = self._record_path(job_id)
        if not record_path.exists():
            raise KeyError(f"Unknown fake provider job: {job_id}")
        return self._load_job(job_id)
