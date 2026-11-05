from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from .analytical_checker import ThermalAnalyticalChecker
from .model_ir import ModelIR
from .output_registry import OutputRegistry


class GeneratedSimulationResultCritic:
    """Deterministic evidence and plausibility checks for generated-model runs."""

    critic_version = "generated-simulation-result-critic-v2"

    def critique(self, execution: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        evidence = execution.get("evidence") if isinstance(execution.get("evidence"), Mapping) else {}
        outputs = execution.get("outputs") if isinstance(execution.get("outputs"), Mapping) else {}
        generated_result = execution.get("generated_result") if isinstance(execution.get("generated_result"), Mapping) else None
        if not bool(execution.get("executed")) or execution.get("status") != "completed":
            issues.append(_issue("CRITIC_EXECUTION_NOT_COMPLETED", "error", "The generated-model simulation did not complete."))
        for field, code in (
            ("generation_id", "CRITIC_GENERATION_MISMATCH"),
            ("model_ir_hash", "CRITIC_MODEL_HASH_MISMATCH"),
            ("artifact_id", "CRITIC_ARTIFACT_MISMATCH"),
        ):
            if str(evidence.get(field) or "") != str(record.get(field) or ""):
                issues.append(_issue(code, "error", f"Execution evidence does not match {field}."))
        for path, value in _numeric_outputs(outputs):
            if not isfinite(value):
                issues.append(_issue("CRITIC_NON_FINITE_OUTPUT", "error", f"Output is non-finite: {path}"))
            elif path.casefold().endswith(("temperature_k", "_temp_k")) and value < 0:
                issues.append(_issue("CRITIC_TEMPERATURE_BELOW_ABSOLUTE_ZERO", "error", f"Temperature output is below 0 K: {path}"))

        model_ir = record.get("model_ir") if isinstance(record.get("model_ir"), Mapping) else {}
        parsed_model = ModelIR.from_dict(model_ir) if model_ir else None
        requested = parsed_model.requested_outputs if parsed_model else ()
        expected = [item.id for item in requested]
        analytical_check: dict[str, Any] = {
            "status": "NOT_APPLICABLE", "cross_check": None, "reason": "No structured result.",
        }
        if generated_result is not None:
            if generated_result.get("solver_status") != "completed":
                issues.append(_issue(
                    "CRITIC_SOLVER_STATUS_INVALID", "error", "Generated result has no successful solver status.",
                ))
            structured = generated_result.get("outputs") if isinstance(generated_result.get("outputs"), list) else []
            by_id = {
                str(item.get("logical_output_id") or ""): item
                for item in structured
                if isinstance(item, Mapping)
            }
            output_registry = OutputRegistry.default()
            for name in expected:
                item = by_id.get(name)
                if item is None or item.get("status") == "missing":
                    issues.append(_issue("CRITIC_EXPECTED_OUTPUT_MISSING", "error", f"Expected output was not captured: {name}"))
                elif item.get("status") == "non_finite":
                    issues.append(_issue("CRITIC_NON_FINITE_OUTPUT", "error", f"Output is non-finite: {name}"))
                elif item.get("status") != "ok":
                    issues.append(_issue("CRITIC_OUTPUT_INVALID", "error", f"Output is invalid: {name}"))
                else:
                    request = next(value for value in requested if value.id == name)
                    expected_unit = output_registry.require(request.type).canonical_unit
                    if item.get("unit") != expected_unit:
                        issues.append(_issue("CRITIC_UNIT_MISMATCH", "error", f"Output unit is invalid: {name}"))
                    numeric = item.get("value")
                    if numeric is None:
                        series = item.get("series") if isinstance(item.get("series"), list) else []
                        numeric = series[-1].get("value") if series and isinstance(series[-1], Mapping) else None
                    if isinstance(numeric, (int, float)) and not isinstance(numeric, bool):
                        numeric_value = float(numeric)
                        if not isfinite(numeric_value):
                            issues.append(_issue("CRITIC_NON_FINITE_OUTPUT", "error", f"Output is non-finite: {name}"))
                        elif request.type == "temperature" and numeric_value < 0.0:
                            issues.append(_issue(
                                "CRITIC_TEMPERATURE_BELOW_ABSOLUTE_ZERO", "error",
                                f"Temperature output is below 0 K: {name}",
                            ))
            if parsed_model is not None:
                analytical_check = ThermalAnalyticalChecker().check(parsed_model, generated_result)
                if analytical_check.get("status") == "FAIL":
                    issues.append(_issue(
                        "CRITIC_ANALYTICAL_CHECK_FAILED",
                        "error",
                        "Independent analytical cross-check failed.",
                    ))
        else:
            legacy_expected = [
                str(item.get("variable") or "")
                for item in (model_ir.get("requested_outputs") or [])
                if isinstance(item, Mapping) and item.get("variable")
            ]
            expected = legacy_expected
            for name in expected:
                if name not in outputs:
                    issues.append(_issue("CRITIC_EXPECTED_OUTPUT_MISSING", "error", f"Expected output was not captured: {name}"))
        errors = [item for item in issues if item["severity"] == "error"]
        verdict = "fail" if errors else "warning" if issues else "pass"
        return {
            "critic_version": self.critic_version,
            "verdict": verdict,
            "accepted": verdict != "fail",
            "issues": issues,
            "checked_output_count": (
                len(generated_result.get("outputs") or []) if generated_result is not None
                else len(list(_numeric_outputs(outputs)))
            ),
            "expected_outputs": expected,
            "analytical_check": analytical_check,
            "validation_method": (
                str(analytical_check.get("validation_method") or "BASIC_ONLY")
                if analytical_check.get("status") == "PASS"
                else "BASIC_ONLY"
            ),
            "validation_level": (
                "analytical" if analytical_check.get("status") == "PASS" else "basic"
            ),
        }


def _numeric_outputs(value: Mapping[str, Any], prefix: str = ""):
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            yield path, float(item)
        elif isinstance(item, Mapping):
            yield from _numeric_outputs(item, path)


def _issue(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


__all__ = ["GeneratedSimulationResultCritic"]
