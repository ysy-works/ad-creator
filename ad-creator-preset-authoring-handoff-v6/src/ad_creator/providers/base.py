from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderJob:
    job_id: str
    status: str
    output_path: Path | None = None
    actual_credits: float | None = None
    metadata: dict[str, Any] | None = None


class GenerationProvider(Protocol):
    name: str

    def submit(self, request: dict[str, Any], *, idempotency_key: str) -> ProviderJob:
        ...

    def get(self, job_id: str) -> ProviderJob:
        ...
