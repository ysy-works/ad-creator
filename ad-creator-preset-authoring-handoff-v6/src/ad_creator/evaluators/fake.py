from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


class FakeQualityEvaluator:
    provider_name = "fake_evaluator"
    model_name = "fixed_fixture_v1"
    mode = "fake"

    def __init__(self, payload: dict[str, Any] | list[dict[str, Any]] | str | Path) -> None:
        if isinstance(payload, dict):
            self._payloads = [copy.deepcopy(payload)]
        elif isinstance(payload, list):
            if not payload:
                raise ValueError("Fake evaluator payload sequence must not be empty")
            self._payloads = copy.deepcopy(payload)
        else:
            self._payloads = [json.loads(Path(payload).read_text(encoding="utf-8"))]
        self.call_count = 0

    def evaluate(
        self,
        *,
        generated_image: str | Path,
        original_product_image: str | Path,
        request: dict[str, Any],
        lighting_sheet: dict[str, Any],
        container_reference_image: str | Path | None = None,
    ) -> dict[str, Any]:
        del generated_image, original_product_image, request, lighting_sheet, container_reference_image
        index = min(self.call_count, len(self._payloads) - 1)
        self.call_count += 1
        return copy.deepcopy(self._payloads[index])
