from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evaluators.base import QualityEvaluator
from .evaluators.gemini import EvaluatorError, EvaluatorUnavailable
from .prompting import build_identity_repair_request
from .providers.base import GenerationProvider
from .qa import normalize_qa_report, route_repair
from .request_validation import validate_repair_request
from .runs import RunStore, execute_until_terminal


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def _write_qa_artifact(
    run_dir: Path,
    filename: str,
    value: dict[str, Any],
) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    canonical_path = run_dir / filename
    history_dir = run_dir / "qa-history"
    if canonical_path.is_file():
        previous = json.loads(canonical_path.read_text(encoding="utf-8"))
        _write_json(
            history_dir / f"{Path(filename).stem}-{timestamp}-previous.json",
            previous,
        )
    canonical = _write_json(canonical_path, value)
    history = _write_json(
        history_dir / f"{Path(filename).stem}-{timestamp}.json",
        value,
    )
    return canonical, history


@dataclass(frozen=True)
class QualityWorkflowResult:
    manifest: dict[str, Any]
    initial_report: dict[str, Any] | None
    repair_plan: dict[str, Any] | None
    repaired_report: dict[str, Any] | None
    final_image: Path


def _evaluator_metadata(evaluator: QualityEvaluator) -> dict[str, str]:
    return {
        "provider": evaluator.provider_name,
        "model": evaluator.model_name,
        "mode": evaluator.mode,
    }


def _mark_evaluator_unavailable(
    *,
    manifest: dict[str, Any],
    store: RunStore,
    run_dir: Path,
    evaluator: QualityEvaluator,
    error: Exception,
) -> QualityWorkflowResult:
    artifact = _write_json(
        run_dir / "qa-evaluator-error.json",
        {
            "schema_version": "1.0.0",
            "evaluator": _evaluator_metadata(evaluator),
            "decision": "needs_review",
            "paid_repair_triggered": False,
            "error": str(error),
        },
    )
    manifest["artifacts"]["qa_evaluator_error"] = str(artifact.resolve())
    manifest["metrics"]["quality"] = {
        "status": "needs_review",
        "reason": "semantic_evaluator_unavailable",
    }
    manifest["repair"] = {
        "enabled": bool(manifest["request"]["repair_policy"]["auto_paid_repair"]),
        "attempts": 0,
        "status": "needs_review",
        "request_hash": None,
        "manifest": None,
    }
    manifest["cost"]["repair_credits"] = 0
    manifest["cost"]["total_credits"] = manifest["cost"].get("actual_credits")
    manifest["status"] = "needs_review"
    manifest["events"].append(
        {"at": _utc_now(), "type": "qa_unavailable", "reason": str(error)}
    )
    store.save(manifest)
    return QualityWorkflowResult(
        manifest=manifest,
        initial_report=None,
        repair_plan=None,
        repaired_report=None,
        final_image=Path(manifest["artifacts"]["provider_output"]),
    )


def evaluate_and_maybe_repair(
    *,
    project_root: str | Path,
    request: dict[str, Any],
    manifest: dict[str, Any],
    store: RunStore,
    provider: GenerationProvider | None,
    evaluator: QualityEvaluator,
    runtime_profile: dict[str, Any] | None,
    lighting_sheet: dict[str, Any],
    original_product_image: str | Path,
    container_reference_image: str | Path | None = None,
    brand_asset_image: str | Path | None = None,
    timeout_seconds: float = 1200,
    poll_interval_seconds: float = 3,
    allow_paid_repair: bool = True,
    force_re_evaluation: bool = False,
) -> QualityWorkflowResult:
    root = Path(project_root).resolve()
    request_products = request.get("products")
    is_multi_product_v3 = (
        request.get("schema_version") == "3.0.0"
        or isinstance(request_products, list)
    )
    if is_multi_product_v3:
        # v3 requests are evaluated per product and never receive an automatic
        # second paid submission. A single-logo repair may be prepared for
        # manual approval by the v3 QA route, but is not executed here.
        allow_paid_repair = False
    run_dir = store.run_dir(manifest["request_hash"])
    initial_image = Path(manifest["artifacts"]["provider_output"])
    repair_state = manifest.get("repair", {})
    terminal_quality_state = (
        manifest["status"] in {"completed", "quality_passed", "rejected"}
        or (
            manifest["status"] == "needs_review"
            and (
                repair_state.get("attempts") == 1
                or repair_state.get("status") in {"disabled", "rejected", "failed"}
            )
        )
    )
    if (
        not force_re_evaluation
        and terminal_quality_state
        and manifest["artifacts"].get("qa_initial")
    ):
        initial_report = json.loads(
            Path(manifest["artifacts"]["qa_initial"]).read_text(encoding="utf-8")
        )
        repair_plan = json.loads(
            Path(manifest["artifacts"]["repair_plan"]).read_text(encoding="utf-8")
        )
        repaired_report = (
            json.loads(Path(manifest["artifacts"]["qa_repaired"]).read_text(encoding="utf-8"))
            if manifest["artifacts"].get("qa_repaired")
            else None
        )
        return QualityWorkflowResult(
            manifest=manifest,
            initial_report=initial_report,
            repair_plan=repair_plan,
            repaired_report=repaired_report,
            final_image=initial_image,
        )
    manifest["status"] = "evaluating"
    manifest["events"].append({"at": _utc_now(), "type": "qa_started"})
    store.save(manifest)

    try:
        payload = evaluator.evaluate(
            generated_image=initial_image,
            original_product_image=original_product_image,
            request=request,
            lighting_sheet=lighting_sheet,
            container_reference_image=container_reference_image,
        )
        initial_report = normalize_qa_report(
            payload,
            evaluator=_evaluator_metadata(evaluator),
            evaluated_image=initial_image,
            request=request,
            lighting_sheet=lighting_sheet,
            project_root=root,
        )
        initial_report, repair_plan = route_repair(
            initial_report,
            request=request,
            project_root=root,
        )
    except (EvaluatorUnavailable, EvaluatorError, ValueError) as exc:
        return _mark_evaluator_unavailable(
            manifest=manifest,
            store=store,
            run_dir=run_dir,
            evaluator=evaluator,
            error=exc,
        )

    stale_evaluator_error = manifest["artifacts"].pop("qa_evaluator_error", None)
    if stale_evaluator_error:
        manifest["events"].append(
            {
                "at": _utc_now(),
                "type": "qa_evaluator_error_superseded",
                "artifact": stale_evaluator_error,
            }
        )

    initial_report_path, initial_history_path = _write_qa_artifact(
        run_dir, "qa-initial.json", initial_report
    )
    repair_plan_path, plan_history_path = _write_qa_artifact(
        run_dir, "repair-plan.json", repair_plan
    )
    manifest["artifacts"].update(
        {
            "qa_initial": str(initial_report_path.resolve()),
            "repair_plan": str(repair_plan_path.resolve()),
            "qa_initial_history_latest": str(initial_history_path.resolve()),
            "repair_plan_history_latest": str(plan_history_path.resolve()),
        }
    )
    manifest["metrics"]["quality"] = {
        "initial_status": initial_report["overall_status"],
        "hard_failures": initial_report["hard_failures"],
        "warnings": initial_report["warnings"],
        "repair_decision": repair_plan["decision"],
    }

    decision = repair_plan["decision"]
    if decision == "repair" and not allow_paid_repair:
        base_credits = manifest["cost"].get("actual_credits")
        manifest["status"] = "needs_review"
        manifest["repair"] = {
            "enabled": True,
            "attempts": 0,
            "status": "awaiting_approval",
            "request_hash": None,
            "manifest": None,
        }
        manifest["cost"]["repair_credits"] = 0
        manifest["cost"]["total_credits"] = base_credits
        manifest["events"].append(
            {"at": _utc_now(), "type": "repair_awaiting_explicit_approval"}
        )
        store.save(manifest)
        return QualityWorkflowResult(
            manifest=manifest,
            initial_report=initial_report,
            repair_plan=repair_plan,
            repaired_report=None,
            final_image=initial_image,
        )

    if decision == "repair" and evaluator.mode == "live":
        try:
            confirmation_payload = evaluator.evaluate(
                generated_image=initial_image,
                original_product_image=original_product_image,
                request=request,
                lighting_sheet=lighting_sheet,
                container_reference_image=container_reference_image,
            )
            confirmation_report = normalize_qa_report(
                confirmation_payload,
                evaluator=_evaluator_metadata(evaluator),
                evaluated_image=initial_image,
                request=request,
                lighting_sheet=lighting_sheet,
                project_root=root,
            )
            confirmation_report, confirmation_plan = route_repair(
                confirmation_report,
                request=request,
                project_root=root,
            )
        except (EvaluatorUnavailable, EvaluatorError, ValueError) as exc:
            manifest["status"] = "needs_review"
            manifest["repair"] = {
                "enabled": True,
                "attempts": 0,
                "status": "needs_review",
                "request_hash": None,
                "manifest": None,
            }
            manifest["cost"]["repair_credits"] = 0
            manifest["cost"]["total_credits"] = manifest["cost"].get("actual_credits")
            manifest["events"].append(
                {"at": _utc_now(), "type": "repair_confirmation_unavailable", "reason": str(exc)}
            )
            store.save(manifest)
            return QualityWorkflowResult(
                manifest=manifest,
                initial_report=initial_report,
                repair_plan=repair_plan,
                repaired_report=None,
                final_image=initial_image,
            )

        confirmation_path, confirmation_history_path = _write_qa_artifact(
            run_dir, "qa-confirmation.json", confirmation_report
        )
        confirmation_plan_path, confirmation_plan_history_path = _write_qa_artifact(
            run_dir, "repair-confirmation-plan.json", confirmation_plan
        )
        manifest["artifacts"].update(
            {
                "qa_confirmation": str(confirmation_path.resolve()),
                "repair_confirmation_plan": str(confirmation_plan_path.resolve()),
                "qa_confirmation_history_latest": str(confirmation_history_path.resolve()),
                "repair_confirmation_plan_history_latest": str(
                    confirmation_plan_history_path.resolve()
                ),
            }
        )
        first_issues = {issue["check"] for issue in repair_plan["issues"]}
        confirmed_issues = {issue["check"] for issue in confirmation_plan["issues"]}
        consistent = (
            confirmation_plan["decision"] == "repair"
            and first_issues == confirmed_issues
        )
        manifest["metrics"]["quality"]["repair_confirmation"] = {
            "consistent": consistent,
            "first_issues": sorted(first_issues),
            "confirmed_issues": sorted(confirmed_issues),
            "confirmation_decision": confirmation_plan["decision"],
        }
        if not consistent:
            manifest["status"] = "needs_review"
            manifest["repair"] = {
                "enabled": True,
                "attempts": 0,
                "status": "needs_review",
                "request_hash": None,
                "manifest": None,
            }
            manifest["cost"]["repair_credits"] = 0
            manifest["cost"]["total_credits"] = manifest["cost"].get("actual_credits")
            manifest["events"].append(
                {"at": _utc_now(), "type": "repair_confirmation_inconsistent"}
            )
            store.save(manifest)
            return QualityWorkflowResult(
                manifest=manifest,
                initial_report=initial_report,
                repair_plan=repair_plan,
                repaired_report=None,
                final_image=initial_image,
            )
    if decision != "repair":
        status_map = {
            "no_repair": "quality_passed",
            "needs_review": "needs_review",
            "reject": "rejected",
        }
        repair_status = {
            "no_repair": "not_required",
            "needs_review": (
                "disabled" if not repair_plan["auto_paid_repair_enabled"] else "needs_review"
            ),
            "reject": "rejected",
        }
        manifest["status"] = status_map[decision]
        manifest["repair"] = {
            "enabled": repair_plan["auto_paid_repair_enabled"],
            "attempts": 0,
            "status": repair_status[decision],
            "request_hash": None,
            "manifest": None,
        }
        manifest["cost"]["repair_credits"] = 0
        manifest["cost"]["total_credits"] = manifest["cost"].get("actual_credits")
        manifest["events"].append({"at": _utc_now(), "type": f"qa_{decision}"})
        store.save(manifest)
        return QualityWorkflowResult(
            manifest=manifest,
            initial_report=initial_report,
            repair_plan=repair_plan,
            repaired_report=None,
            final_image=initial_image,
        )

    base_credits = float(
        manifest["cost"].get("actual_credits")
        if manifest["cost"].get("actual_credits") is not None
        else manifest["cost"]["estimated_credits"]
    )
    if provider is None or runtime_profile is None:
        raise RuntimeError("Paid repair requires a generation provider and runtime profile")
    if base_credits + float(repair_plan["estimated_credits"]) > 4:
        manifest["status"] = "needs_review"
        manifest["repair"] = {
            "enabled": True,
            "attempts": 0,
            "status": "needs_review",
            "request_hash": None,
            "manifest": None,
        }
        manifest["cost"]["repair_credits"] = 0
        manifest["cost"]["total_credits"] = base_credits
        manifest["events"].append({"at": _utc_now(), "type": "repair_budget_blocked"})
        store.save(manifest)
        return QualityWorkflowResult(
            manifest=manifest,
            initial_report=initial_report,
            repair_plan=repair_plan,
            repaired_report=None,
            final_image=initial_image,
        )

    failed_checks = [issue["check"] for issue in repair_plan["issues"]]
    repair_request = build_identity_repair_request(
        runtime_profile=runtime_profile,
        generated_image=str(initial_image.resolve()),
        original_product_image=str(Path(original_product_image).resolve()),
        logo_text=request.get("brand_contract", {}).get("allowed_main_text"),
        failed_details=[issue["instruction"] for issue in repair_plan["issues"]],
        failed_checks=failed_checks,
        container_mode=request["identity_policy"]["container"],
        brand_asset_image=(str(Path(brand_asset_image).resolve()) if brand_asset_image else None),
    )
    repair_request.update(
        {
            "parent_request_hash": manifest["request_hash"],
            "lighting_sheet": copy.deepcopy(request["lighting_sheet"]),
            "repair_plan": copy.deepcopy(repair_plan),
            "prompt_compiler_version": "conditional_repair_v2",
        }
    )
    validate_repair_request(repair_request, maximum_credits=2)
    manifest["status"] = "repairing"
    manifest["events"].append({"at": _utc_now(), "type": "repair_started"})
    store.save(manifest)

    repair_manifest, _ = execute_until_terminal(
        repair_request,
        provider=provider,
        store=store,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    repair_hash = repair_manifest["request_hash"]
    manifest["repair"] = {
        "enabled": True,
        "attempts": 1,
        "status": "submitted",
        "request_hash": repair_hash,
        "manifest": str(store.manifest_path(repair_hash).resolve()),
    }
    if repair_manifest["status"] != "provider_completed":
        manifest["status"] = "needs_review"
        manifest["repair"]["status"] = "failed"
        manifest["events"].append({"at": _utc_now(), "type": "repair_provider_failed"})
        store.save(manifest)
        return QualityWorkflowResult(
            manifest=manifest,
            initial_report=initial_report,
            repair_plan=repair_plan,
            repaired_report=None,
            final_image=initial_image,
        )

    repair_image = Path(repair_manifest["artifacts"]["provider_output"])
    repair_credits = float(
        repair_manifest["cost"].get("actual_credits")
        if repair_manifest["cost"].get("actual_credits") is not None
        else repair_manifest["cost"]["estimated_credits"]
    )
    manifest["cost"]["repair_credits"] = repair_credits
    manifest["cost"]["total_credits"] = base_credits + repair_credits
    manifest["artifacts"]["repair_provider_output"] = str(repair_image.resolve())

    try:
        repaired_payload = evaluator.evaluate(
            generated_image=repair_image,
            original_product_image=original_product_image,
            request=request,
            lighting_sheet=lighting_sheet,
            container_reference_image=container_reference_image,
        )
        repaired_report = normalize_qa_report(
            repaired_payload,
            evaluator=_evaluator_metadata(evaluator),
            evaluated_image=repair_image,
            request=request,
            lighting_sheet=lighting_sheet,
            project_root=root,
        )
    except (EvaluatorUnavailable, EvaluatorError, ValueError) as exc:
        manifest["status"] = "needs_review"
        manifest["repair"]["status"] = "needs_review"
        manifest["events"].append(
            {"at": _utc_now(), "type": "repair_qa_unavailable", "reason": str(exc)}
        )
        store.save(manifest)
        return QualityWorkflowResult(
            manifest=manifest,
            initial_report=initial_report,
            repair_plan=repair_plan,
            repaired_report=None,
            final_image=initial_image,
        )

    repaired_report_path, repaired_history_path = _write_qa_artifact(
        run_dir, "qa-repaired.json", repaired_report
    )
    manifest["artifacts"]["qa_repaired"] = str(repaired_report_path.resolve())
    manifest["artifacts"]["qa_repaired_history_latest"] = str(
        repaired_history_path.resolve()
    )
    remaining_failures = set(repaired_report["hard_failures"])
    new_failures = remaining_failures - set(initial_report["hard_failures"])
    manifest["metrics"]["quality"].update(
        {
            "repaired_status": repaired_report["overall_status"],
            "repaired_hard_failures": sorted(remaining_failures),
            "new_hard_failures": sorted(new_failures),
        }
    )
    if remaining_failures:
        manifest["status"] = "needs_review"
        manifest["repair"]["status"] = "rejected"
        manifest["events"].append({"at": _utc_now(), "type": "repair_result_rejected"})
        final_image = initial_image
    else:
        manifest["artifacts"]["original_provider_output"] = str(initial_image.resolve())
        manifest["artifacts"]["provider_output"] = str(repair_image.resolve())
        manifest["status"] = "quality_passed"
        manifest["repair"]["status"] = "accepted"
        manifest["events"].append({"at": _utc_now(), "type": "repair_result_accepted"})
        final_image = repair_image
    store.save(manifest)
    return QualityWorkflowResult(
        manifest=manifest,
        initial_report=initial_report,
        repair_plan=repair_plan,
        repaired_report=repaired_report,
        final_image=final_image,
    )
