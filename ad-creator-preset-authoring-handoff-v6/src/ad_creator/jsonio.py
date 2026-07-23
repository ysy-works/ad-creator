from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {source}")
    return value


def validate_json(
    value: dict[str, Any],
    schema: str | Path,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> None:
    schema_path = Path(schema)
    if not schema_path.is_absolute():
        schema_path = Path(project_root) / "schemas" / schema_path
    schema_value = load_json(schema_path)
    validator = Draft202012Validator(schema_value)
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if not errors:
        return
    details = []
    for error in errors[:8]:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        details.append(f"{location}: {error.message}")
    suffix = f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""
    raise ValueError(f"Schema validation failed for {schema_path.name}: {'; '.join(details)}{suffix}")


def dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
