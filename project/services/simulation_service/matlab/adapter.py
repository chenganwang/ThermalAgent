from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from .availability import assess_matlab_availability
from .config import MatlabIntegrationConfig, load_matlab_integration_config
from .engine_client import MatlabEngineClient
from .errors import MatlabDemoValidationError, MatlabEngineUnavailableError, MatlabIntegrationError
from .evidence import write_matlab_demo_evidence
from .schemas import MatlabSimulationResult, MatlabStatus


class MatlabSimulationAdapter:
    def __init__(
        self,
        *,
        config: MatlabIntegrationConfig | None = None,
        engine_factory: Callable[..., object] | None = None,
        import_engine: Callable[[], object] | None = None,
        fake_engine: bool = False,
    ) -> None:
        self.config = config or load_matlab_integration_config()
        self.client = MatlabEngineClient(
            self.config,
            engine_factory=engine_factory,
            import_engine=import_engine,
            fake_engine=fake_engine,
        )
        self.fake_engine = bool(fake_engine)

    def status(self) -> MatlabStatus:
        config = self.config
        assessment = assess_matlab_availability(
            config,
            import_engine=(lambda: object()) if self.fake_engine else self.client._import_engine,
            check_engine_import=config.enabled,
        )
        discovery = assessment["discovery"]
        status = str(assessment["status"])
        errors: list[dict[str, Any]] = []
        if status == "engine_not_installed":
            errors.append(
                {
                    "code": "engine_not_installed",
                    "message": "Install MATLAB Engine for Python from the discovered MATLAB engine directory.",
                }
            )
        if status == "matlab_not_found":
            errors.append({"code": "matlab_not_found", "message": "MATLAB executable was not found under SIMULATION_MATLAB_ROOT."})
        return MatlabStatus(
            enabled=config.enabled,
            available=bool(assessment["available"]),
            status=status,
            engine_importable=bool(assessment["engine_importable"]),
            engine_start_allowed=bool(assessment["engine_start_allowed"]),
            license_confirmed_by_operator=bool(assessment["license_confirmed_by_operator"]),
            api_enabled=bool(assessment["api_enabled"]),
            demo_run_allowed=bool(assessment["demo_run_allowed"]),
            safe_to_run_demo=bool(assessment["safe_to_run_demo"]),
            message=str(assessment["message"]),
            matlab_root=discovery.matlab_root,
            root_exists=discovery.root_exists,
            version_dirs=list(discovery.version_dirs),
            selected_version_dir=discovery.selected_version_dir,
            matlab_exe=discovery.matlab_exe,
            matlab_exe_found=discovery.matlab_exe_found,
            matlab_exe_candidates=list(discovery.matlab_exe_candidates),
            engine_python_dir=discovery.engine_python_dir,
            engine_python_dir_found=discovery.engine_python_dir_found,
            engine_python_candidates=list(discovery.engine_python_candidates),
            multiple_versions_found=discovery.multiple_versions_found,
            engine_install_command=assessment["engine_install_command"],
            python_version=assessment["python_version"],
            python_executable=None,
            allowed_demos=list(config.allowed_demos),
            engine_type="fake" if self.fake_engine else "matlab",
            errors=errors,
        )

    def run_demo(
        self,
        demo_name: str,
        params: dict[str, Any] | None,
        *,
        require_api_enabled: bool = False,
    ) -> MatlabSimulationResult:
        params = dict(params or {})
        try:
            normalized = self._validate_params(demo_name, params)
        except MatlabDemoValidationError as exc:
            return self._error_result(
                demo_name,
                params,
                exc.status,
                exc.code,
                str(exc),
                missing_parameters=exc.missing_parameters,
            )
        blocked = self._preflight(
            demo_name,
            normalized,
            require_api_enabled=require_api_enabled,
        )
        if blocked is not None:
            return blocked

        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        try:
            self.client.start_engine()
            outputs, formula, assumptions, units = self._execute_demo(demo_name, normalized)
            matlab_version = self.client.version()
        except MatlabIntegrationError as exc:
            return self._error_result(demo_name, normalized, getattr(exc, "code", "failed"), exc.code, str(exc))
        except Exception as exc:
            return self._error_result(
                demo_name,
                normalized,
                "failed",
                "matlab_demo_execution_failed",
                f"{type(exc).__name__}",
            )
        finally:
            self.client.close()
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((perf_counter() - started) * 1000)
        engine_type = "fake" if self.fake_engine else "matlab"
        is_real = engine_type == "matlab"
        evidence = write_matlab_demo_evidence(
            config=self.config,
            demo_name=demo_name,
            engine_type=engine_type,
            is_real_matlab=is_real,
            matlab_version=matlab_version,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            inputs=normalized,
            outputs=outputs,
            formula=formula,
            assumptions=assumptions,
            status="success",
        )
        return MatlabSimulationResult(
            success=True,
            status="success",
            demo_name=demo_name,
            inputs=normalized,
            outputs=outputs,
            engine_type=engine_type,
            is_real_matlab=is_real,
            is_fake=self.fake_engine,
            matlab_version=matlab_version,
            evidence_id=str(evidence["evidence_id"]),
            evidence_path=str(evidence["json_path"]),
            human_validated=False,
            license_confirmed_by_operator=self.config.operator_confirmed_license,
            duration_ms=duration_ms,
            formula=formula,
            assumptions=assumptions,
            units=units,
            warnings=[] if is_real else ["fake_engine_for_tests_only"],
            metadata={"phase": "6A", "controlled_adapter": True},
        )

    def close(self) -> None:
        self.client.close()

    def _preflight(
        self,
        demo_name: str,
        inputs: dict[str, Any],
        *,
        require_api_enabled: bool,
    ) -> MatlabSimulationResult | None:
        config = self.config
        if not config.enabled:
            return self._error_result(demo_name, inputs, "disabled", "matlab_integration_disabled", "MATLAB integration is disabled.")
        if require_api_enabled and not config.allow_api:
            return self._error_result(demo_name, inputs, "disabled", "matlab_api_disabled", "MATLAB demo API is disabled.")
        if not config.allow_demo_run:
            return self._error_result(demo_name, inputs, "not_configured", "matlab_demo_run_disabled", "MATLAB demo execution is disabled.")
        if config.require_license_confirmation and not config.operator_confirmed_license:
            return self._error_result(demo_name, inputs, "license_not_confirmed", "matlab_license_not_confirmed", "Operator license confirmation is required.")
        if not config.allow_engine_start:
            return self._error_result(demo_name, inputs, "not_configured", "matlab_engine_start_disabled", "MATLAB engine startup is disabled.")
        if demo_name not in set(config.allowed_demos):
            return self._error_result(demo_name, inputs, "failed", "matlab_demo_not_allowed", f"Demo is not whitelisted: {demo_name}")
        return None

    def _validate_params(self, demo_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if demo_name == "basic_numeric":
            self._require_params(params, ("a", "b"))
            return {"a": _number(params.get("a"), "a"), "b": _number(params.get("b"), "b")}
        if demo_name == "heat_conduction_1d":
            self._require_params(
                params,
                (
                    "length_m",
                    "area_m2",
                    "thermal_conductivity_w_mk",
                    "t_hot_c",
                    "t_cold_c",
                ),
            )
            values = {
                "length_m": _positive(params.get("length_m"), "length_m"),
                "area_m2": _positive(params.get("area_m2"), "area_m2"),
                "thermal_conductivity_w_mk": _positive(
                    params.get("thermal_conductivity_w_mk"),
                    "thermal_conductivity_w_mk",
                ),
                "t_hot_c": _number(params.get("t_hot_c"), "t_hot_c"),
                "t_cold_c": _number(params.get("t_cold_c"), "t_cold_c"),
            }
            if abs(values["t_hot_c"] - values["t_cold_c"]) > 1000:
                raise MatlabDemoValidationError("temperature difference is outside the Phase 6A demo range")
            return values
        raise MatlabDemoValidationError(
            f"Unknown demo: {demo_name}",
            code="matlab_demo_not_allowed",
            status="failed",
        )

    @staticmethod
    def _require_params(params: dict[str, Any], names: tuple[str, ...]) -> None:
        missing = [
            name
            for name in names
            if name not in params
            or params.get(name) is None
            or (isinstance(params.get(name), str) and not str(params.get(name)).strip())
        ]
        if missing:
            raise MatlabDemoValidationError(
                "Missing required demo parameters: " + ", ".join(missing),
                code="missing_demo_parameters",
                status="missing_parameters",
                missing_parameters=missing,
            )

    def _execute_demo(self, demo_name: str, params: dict[str, Any]) -> tuple[dict[str, Any], str, list[str], dict[str, str]]:
        if demo_name == "basic_numeric":
            result = self.client.call_function("plus", [params["a"], params["b"]])
            return (
                {"sum": float(result)},
                "sum = plus(a, b)",
                ["Only scalar numeric inputs are accepted.", "No arbitrary MATLAB code is executed."],
                {"sum": "1"},
            )
        if demo_name == "heat_conduction_1d":
            delta_t = self.client.call_function("minus", [params["t_hot_c"], params["t_cold_c"]])
            k_area = self.client.call_function("times", [params["thermal_conductivity_w_mk"], params["area_m2"]])
            numerator = self.client.call_function("times", [k_area, delta_t])
            heat_rate = float(numerator) / float(params["length_m"])
            return (
                {"heat_rate_w": heat_rate},
                "q = k * A * (T_hot - T_cold) / L",
                [
                    "One-dimensional steady conduction.",
                    "No contact resistance, radiation, convection, or transient storage is included.",
                    "This is a controlled demo path, not a production validated model.",
                ],
                {"heat_rate_w": "W"},
            )
        raise MatlabDemoValidationError(f"Unknown demo: {demo_name}", code="matlab_demo_not_allowed")

    def _error_result(
        self,
        demo_name: str,
        inputs: dict[str, Any],
        status: str,
        code: str,
        message: str,
        *,
        missing_parameters: list[str] | None = None,
    ) -> MatlabSimulationResult:
        return MatlabSimulationResult(
            success=False,
            status=status,
            demo_name=demo_name,
            inputs=dict(inputs),
            engine_type="fake" if self.fake_engine else "none",
            is_real_matlab=False,
            is_fake=self.fake_engine,
            human_validated=False,
            license_confirmed_by_operator=self.config.operator_confirmed_license,
            missing_parameters=list(missing_parameters or []),
            error={"code": code, "message": message},
            warnings=["matlab_demo_not_executed"],
            metadata={"phase": "6A", "controlled_adapter": True},
        )


def _number(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MatlabDemoValidationError(f"{name} must be numeric") from exc


def _positive(value: Any, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise MatlabDemoValidationError(f"{name} must be > 0")
    return number


__all__ = ["MatlabSimulationAdapter"]
