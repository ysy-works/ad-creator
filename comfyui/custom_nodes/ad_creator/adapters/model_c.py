import importlib
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any


_GENERATION_LOCK = threading.Lock()


class ModelCExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, result: dict[str, Any] | None = None):
        self.code = code
        self.result = result or {}
        super().__init__(f"[{code}] {message}")


def _repo_root() -> Path:
    configured = os.environ.get("AD_CREATOR_REPO_ROOT")
    root = Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[4]
    if not (root / "app" / "inference.py").is_file():
        raise ModelCExecutionError(
            "MODEL_C_NOT_FOUND",
            "Set AD_CREATOR_REPO_ROOT to the ad-creator repository root.",
        )
    return root


def _load_inference_module() -> ModuleType:
    root = _repo_root()
    existing_app = sys.modules.get("app")
    if existing_app is not None:
        app_file = getattr(existing_app, "__file__", None)
        if app_file is None or root not in Path(app_file).resolve().parents:
            raise ModelCExecutionError(
                "MODEL_C_IMPORT_CONFLICT",
                "Another Python package named 'app' is already loaded. Run model-c in an isolated ComfyUI process.",
            )

    root_text = str(root)
    if root_text in sys.path:
        sys.path.remove(root_text)
    sys.path.insert(0, root_text)
    return importlib.import_module("app.inference")


def _output_dir() -> Path:
    configured = os.environ.get("AD_CREATOR_COMFYUI_OUTPUT_DIR")
    path = Path(configured).expanduser().resolve() if configured else _repo_root() / "comfyui" / "runtime" / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_model_c(
    *,
    image_path: str | Path,
    composition: str,
    background_style: str,
    strength: str,
    seed: int | None,
    guidance_scale: float,
    num_inference_steps: int,
    width: int,
    height: int,
) -> dict[str, Any]:
    source = Path(image_path).resolve()
    if not source.is_file():
        raise ModelCExecutionError("INVALID_IMAGE", f"Input image not found: {source}")

    inference = _load_inference_module()
    output_dir = _output_dir()
    with _GENERATION_LOCK:
        result = inference.generate_beverage_image(
            image_path=str(source),
            composition=composition,
            background_style=background_style,
            strength=strength,
            seed=seed,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            width=width,
            height=height,
            output_dir=str(output_dir),
        )

    if not isinstance(result, dict):
        raise ModelCExecutionError("INVALID_MODEL_RESPONSE", "model-c returned a non-object response.")
    if not result.get("success"):
        raise ModelCExecutionError(
            str(result.get("error_code") or "GENERATION_FAILED"),
            str(result.get("error_message") or "model-c generation failed."),
            result,
        )

    output_path = Path(str(result.get("output_path", ""))).resolve()
    if not output_path.is_file():
        raise ModelCExecutionError(
            "OUTPUT_NOT_FOUND",
            f"model-c reported a missing output file: {output_path}",
            result,
        )
    try:
        output_path.relative_to(output_dir)
    except ValueError as exc:
        raise ModelCExecutionError(
            "OUTPUT_OUTSIDE_RUNTIME",
            f"model-c returned an output outside the adapter runtime: {output_path}",
            result,
        ) from exc
    return result
