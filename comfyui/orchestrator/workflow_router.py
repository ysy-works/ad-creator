import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "workflows" / "registry.json"


class WorkflowRouterError(RuntimeError):
    pass


class UnknownWorkflowError(WorkflowRouterError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowRouterError(f"Cannot read workflow configuration: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowRouterError(f"Workflow configuration must be an object: {path}")
    return value


def _safe_child(parent: Path, relative_path: str) -> Path:
    candidate = (parent / relative_path).resolve()
    try:
        candidate.relative_to(parent.resolve())
    except ValueError as exc:
        raise WorkflowRouterError(f"Workflow path escapes its directory: {relative_path}") from exc
    return candidate


def build_prompt(
    *,
    workflow_id: str | None = None,
    values: dict[str, Any],
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    registry_path = Path(registry_path).resolve()
    registry = _read_json(registry_path)
    selected_id = workflow_id or registry.get("default_workflow_id")
    workflows = registry.get("workflows")
    if not isinstance(workflows, dict) or selected_id not in workflows:
        raise UnknownWorkflowError(f"Unknown workflow_id: {selected_id}")

    entry = workflows[selected_id]
    if not isinstance(entry, dict) or not entry.get("enabled"):
        raise UnknownWorkflowError(f"Disabled workflow_id: {selected_id}")

    api_path = _safe_child(registry_path.parent, str(entry.get("api_workflow", "")))
    prompt = _read_json(api_path)
    bindings = entry.get("input_bindings")
    if not isinstance(bindings, dict):
        raise WorkflowRouterError(f"Workflow has no input bindings: {selected_id}")

    unknown_values = set(values) - set(bindings)
    if unknown_values:
        raise WorkflowRouterError(f"Unsupported workflow values: {', '.join(sorted(unknown_values))}")

    for name, value in values.items():
        binding = bindings[name]
        node_id = str(binding["node_id"])
        input_name = str(binding["input"])
        try:
            prompt[node_id]["inputs"][input_name] = value
        except KeyError as exc:
            raise WorkflowRouterError(f"Invalid binding for {name} in {selected_id}") from exc

    source_binding = bindings.get("source_image")
    if source_binding is not None:
        source_node = prompt[str(source_binding["node_id"])]["inputs"]
        source_value = source_node[str(source_binding["input"])]
        if not isinstance(source_value, str) or not source_value or source_value == "__INPUT_IMAGE__":
            raise WorkflowRouterError("source_image must be the filename returned by ComfyUI /upload/image.")

    return {
        "workflow_id": selected_id,
        "prompt": prompt,
        "output_node_id": str(entry["output_node_id"]),
    }


def submit_prompt(
    *,
    server_url: str,
    resolved_workflow: dict[str, Any],
    client_id: str | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": resolved_workflow["prompt"]}
    if client_id:
        payload["client_id"] = client_id

    request = urllib.request.Request(
        f"{server_url.rstrip('/')}/prompt",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WorkflowRouterError(f"ComfyUI prompt submission failed: {exc}") from exc

    if not isinstance(result, dict) or not result.get("prompt_id"):
        raise WorkflowRouterError("ComfyUI response does not contain prompt_id.")
    return result
