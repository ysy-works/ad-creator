from __future__ import annotations

import base64
import io
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

import certifi
from PIL import Image, ImageOps


class GeminiUnavailable(RuntimeError):
    pass


class GeminiAPIError(RuntimeError):
    pass


class GeminiRateLimitError(GeminiAPIError):
    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float,
        quota_kind: str = "unknown",
        model: str | None = None,
        quota_ids: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.quota_kind = quota_kind
        self.model = model
        self.quota_ids = tuple(quota_ids)


class GeminiAllModelsExhausted(GeminiRateLimitError):
    def __init__(self, errors: Sequence[GeminiRateLimitError]) -> None:
        if not errors:
            raise ValueError("GeminiAllModelsExhausted requires at least one error")
        kinds = {error.quota_kind for error in errors}
        quota_kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
        models = tuple(error.model or "unknown" for error in errors)
        quota_ids = tuple(
            dict.fromkeys(
                quota_id for error in errors for quota_id in error.quota_ids
            )
        )
        super().__init__(
            "Gemini model candidates exhausted by rate limits: " + ", ".join(models),
            retry_after_seconds=min(error.retry_after_seconds for error in errors),
            quota_kind=quota_kind,
            quota_ids=quota_ids,
        )
        self.errors = tuple(errors)
        self.exhausted_models = models


Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


class GeminiInteractionsClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-3.5-flash",
        model_candidates: Sequence[str] | None = None,
        timeout_seconds: float = 180,
        maximum_image_edge: int = 1024,
        thinking_level: str = "low",
        transport: Transport | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model
        candidates = list(model_candidates or ())
        if model not in candidates:
            candidates.insert(0, model)
        self.model_candidates = tuple(dict.fromkeys(candidates))
        if not self.model_candidates:
            raise ValueError("At least one Gemini model candidate is required")
        self.last_used_model: str | None = None
        self.last_rate_limit_errors: tuple[GeminiRateLimitError, ...] = ()
        self.timeout_seconds = timeout_seconds
        self.maximum_image_edge = maximum_image_edge
        if thinking_level not in {"minimal", "low", "medium", "high"}:
            raise ValueError(f"Unsupported Gemini thinking level: {thinking_level}")
        self.thinking_level = thinking_level
        self._transport = transport or self._post

    @property
    def actual_model(self) -> str:
        return self.last_used_model or self.model

    @staticmethod
    def _retry_delay_seconds(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.fullmatch(r"\s*([0-9.]+)s\s*", value)
            return float(match.group(1)) if match else None
        if isinstance(value, dict):
            try:
                return float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
            except (TypeError, ValueError):
                return None
        return None

    @classmethod
    def _parse_rate_limit(
        cls,
        body: str,
        *,
        model: str | None,
        retry_after_header: str | None = None,
    ) -> GeminiRateLimitError:
        quota_ids: list[str] = []
        quota_evidence: list[str] = []
        retry_after: float | None = None
        if retry_after_header:
            retry_after = cls._retry_delay_seconds(retry_after_header)
            if retry_after is None:
                try:
                    retry_after = float(retry_after_header)
                except ValueError:
                    pass
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        error_payload = payload.get("error", {})
        if not isinstance(error_payload, dict):
            error_payload = {}
        details = error_payload.get("details", [])
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                parsed_delay = cls._retry_delay_seconds(
                    detail.get("retryDelay") or detail.get("retry_delay")
                )
                if parsed_delay is not None:
                    retry_after = parsed_delay
                violations = detail.get("violations", [])
                if not isinstance(violations, list):
                    continue
                for violation in violations:
                    if not isinstance(violation, dict):
                        continue
                    quota_id = violation.get("quotaId") or violation.get("quota_id")
                    if isinstance(quota_id, str) and quota_id:
                        quota_ids.append(quota_id)
                    for field in (
                        "quotaMetric",
                        "quota_metric",
                        "quotaId",
                        "quota_id",
                        "description",
                    ):
                        value = violation.get(field)
                        if isinstance(value, str):
                            quota_evidence.append(value)
                    dimensions = violation.get("quotaDimensions") or violation.get(
                        "quota_dimensions"
                    )
                    if isinstance(dimensions, dict):
                        quota_evidence.extend(str(value) for value in dimensions.values())
        if retry_after is None:
            match = re.search(
                r"retry(?:\s+in|\s+after|delay[\"':\s]+)\s*([0-9.]+)s",
                body,
                re.IGNORECASE,
            )
            retry_after = float(match.group(1)) if match else 60.0

        evidence = " ".join(quota_evidence + [body]).lower()
        compact = re.sub(r"[^a-z0-9]+", "", evidence)
        if "requestsperday" in compact or "perday" in compact or "rpd" in compact:
            quota_kind = "rpd"
        elif "tokensperminute" in compact or "tpm" in compact:
            quota_kind = "tpm"
        elif "requestsperminute" in compact or "rpm" in compact:
            quota_kind = "rpm"
        else:
            quota_kind = "unknown"
        return GeminiRateLimitError(
            f"Gemini HTTP 429: {body[:2000]}",
            retry_after_seconds=retry_after,
            quota_kind=quota_kind,
            model=model,
            quota_ids=tuple(dict.fromkeys(quota_ids)),
        )

    def _post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=context,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                retry_after_header = (
                    exc.headers.get("Retry-After") if exc.headers is not None else None
                )
                raise self._parse_rate_limit(
                    body,
                    model=str(payload.get("model")) if payload.get("model") else None,
                    retry_after_header=retry_after_header,
                ) from exc
            raise GeminiAPIError(f"Gemini HTTP {exc.code}: {body[:2000]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GeminiAPIError(f"Gemini request failed: {exc}") from exc

    def image_content(self, path: str | Path) -> dict[str, str]:
        image_path = Path(path).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"Gemini image does not exist: {image_path}")
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail(
                (self.maximum_image_edge, self.maximum_image_edge),
                Image.Resampling.LANCZOS,
            )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88, optimize=True)
        return {
            "type": "image",
            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "mime_type": "image/jpeg",
        }

    @staticmethod
    def output_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        fragments: list[str] = []
        for step in payload.get("steps", []):
            if step.get("type") != "model_output":
                continue
            for content in step.get("content", []):
                if content.get("type") == "text" and isinstance(content.get("text"), str):
                    fragments.append(content["text"])
        if not fragments:
            raise GeminiAPIError("Gemini response contained no text output")
        return "".join(fragments)

    def generate_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        images: list[tuple[str, str | Path]],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise GeminiUnavailable("GEMINI_API_KEY is not configured")
        inputs: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for label, image_path in images:
            inputs.append({"type": "text", "text": label})
            inputs.append(self.image_content(image_path))
        self.last_used_model = None
        rate_limit_errors: list[GeminiRateLimitError] = []
        response: dict[str, Any] | None = None
        for candidate in self.model_candidates:
            payload = {
                "model": candidate,
                "input": inputs,
                "generation_config": {"thinking_level": self.thinking_level},
                "response_format": {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                },
            }
            try:
                response = self._transport(
                    "https://generativelanguage.googleapis.com/v1beta/interactions",
                    {"Content-Type": "application/json", "x-goog-api-key": self.api_key},
                    payload,
                )
            except GeminiRateLimitError as exc:
                if exc.model is None:
                    exc.model = candidate
                rate_limit_errors.append(exc)
                continue
            self.last_used_model = candidate
            break
        self.last_rate_limit_errors = tuple(rate_limit_errors)
        if response is None:
            raise GeminiAllModelsExhausted(rate_limit_errors)
        try:
            result = json.loads(self.output_text(response))
        except json.JSONDecodeError as exc:
            raise GeminiAPIError("Gemini returned invalid structured JSON") from exc
        if not isinstance(result, dict):
            raise GeminiAPIError("Gemini structured output must be a JSON object")
        return result
