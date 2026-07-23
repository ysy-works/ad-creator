from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class QualityEvaluator(Protocol):
    provider_name: str
    model_name: str
    mode: str

    def evaluate(
        self,
        *,
        generated_image: str | Path,
        original_product_image: str | Path,
        request: dict[str, Any],
        lighting_sheet: dict[str, Any],
        container_reference_image: str | Path | None = None,
    ) -> dict[str, Any]:
        ...
