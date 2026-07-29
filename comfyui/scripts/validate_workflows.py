import argparse
import json
from pathlib import Path
from typing import Any


class WorkflowValidationError(ValueError):
    pass


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowValidationError(f"Cannot read JSON: {path}: {exc}") from exc


def _safe_workflow_path(workflows_dir: Path, relative_path: str) -> Path:
    candidate = (workflows_dir / relative_path).resolve()
    try:
        candidate.relative_to(workflows_dir.resolve())
    except ValueError as exc:
        raise WorkflowValidationError(f"Workflow path escapes its directory: {relative_path}") from exc
    if not candidate.is_file():
        raise WorkflowValidationError(f"Workflow file not found: {candidate}")
    return candidate


def _validate_api_workflow(workflow: Any, workflow_id: str) -> set[str]:
    if not isinstance(workflow, dict) or not workflow:
        raise WorkflowValidationError(f"{workflow_id}: API workflow must be a non-empty object.")

    node_types: set[str] = set()
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            raise WorkflowValidationError(f"{workflow_id}: node {node_id} must be an object.")
        class_type = node.get("class_type")
        inputs = node.get("inputs")
        if not isinstance(class_type, str) or not class_type:
            raise WorkflowValidationError(f"{workflow_id}: node {node_id} has no class_type.")
        if not isinstance(inputs, dict):
            raise WorkflowValidationError(f"{workflow_id}: node {node_id} inputs must be an object.")
        node_types.add(class_type)

        for value in inputs.values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                if value[0] not in workflow:
                    raise WorkflowValidationError(
                        f"{workflow_id}: node {node_id} links to missing node {value[0]}."
                    )
    return node_types


def _validate_ui_workflow(workflow: Any, workflow_id: str) -> set[str]:
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
        raise WorkflowValidationError(f"{workflow_id}: UI workflow must contain a nodes list.")
    node_types = {
        node.get("type")
        for node in workflow["nodes"]
        if isinstance(node, dict) and isinstance(node.get("type"), str)
    }
    if not node_types:
        raise WorkflowValidationError(f"{workflow_id}: UI workflow contains no valid nodes.")
    return node_types


def validate_registry(registry_path: Path) -> list[str]:
    registry_path = registry_path.resolve()
    workflows_dir = registry_path.parent
    registry = _load_json(registry_path)
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        raise WorkflowValidationError("registry.json requires schema_version 1.")

    workflows = registry.get("workflows")
    default_id = registry.get("default_workflow_id")
    if not isinstance(workflows, dict) or not workflows:
        raise WorkflowValidationError("registry.json contains no workflows.")
    if default_id not in workflows:
        raise WorkflowValidationError("default_workflow_id is not registered.")
    if not workflows[default_id].get("enabled"):
        raise WorkflowValidationError("The default workflow is disabled.")

    validated: list[str] = []
    for workflow_id, entry in workflows.items():
        if not isinstance(entry, dict):
            raise WorkflowValidationError(f"{workflow_id}: registry entry must be an object.")

        api_path = _safe_workflow_path(workflows_dir, str(entry.get("api_workflow", "")))
        ui_path = _safe_workflow_path(workflows_dir, str(entry.get("ui_workflow", "")))
        api_workflow = _load_json(api_path)
        ui_workflow = _load_json(ui_path)
        api_types = _validate_api_workflow(api_workflow, workflow_id)
        ui_types = _validate_ui_workflow(ui_workflow, workflow_id)

        for custom_type in entry.get("custom_node_types", []):
            if custom_type not in api_types or custom_type not in ui_types:
                raise WorkflowValidationError(
                    f"{workflow_id}: custom node {custom_type} is missing from an API or UI workflow."
                )

        output_node_id = str(entry.get("output_node_id", ""))
        if output_node_id not in api_workflow:
            raise WorkflowValidationError(f"{workflow_id}: output_node_id is missing from API workflow.")

        bindings = entry.get("input_bindings", {})
        if not isinstance(bindings, dict):
            raise WorkflowValidationError(
                f"{workflow_id}: input_bindings must be an object."
            )
        for binding_name, binding in bindings.items():
            if not isinstance(binding, dict):
                raise WorkflowValidationError(
                    f"{workflow_id}: input binding {binding_name} must be an object."
                )
            node_id = str(binding.get("node_id", ""))
            input_name = binding.get("input")
            if node_id not in api_workflow or input_name not in api_workflow[node_id]["inputs"]:
                raise WorkflowValidationError(
                    f"{workflow_id}: invalid input binding {binding_name}."
                )
        required_inputs = entry.get("required_inputs", ["source_image"])
        if not isinstance(required_inputs, list) or any(
            not isinstance(name, str) or name not in bindings
            for name in required_inputs
        ):
            raise WorkflowValidationError(
                f"{workflow_id}: required_inputs must reference declared bindings."
            )
        validated.append(workflow_id)
    return validated


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Ad Creator ComfyUI workflow files.")
    parser.add_argument(
        "registry",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "workflows" / "registry.json",
    )
    args = parser.parse_args()
    workflows = validate_registry(args.registry)
    print(f"Validated {len(workflows)} workflow(s): {', '.join(workflows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
