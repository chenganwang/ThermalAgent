from __future__ import annotations

import importlib
import os
from typing import Any

from .base import SimulationAdapter
from ..contracts import (
    SIMULATION_STATUS_UNAVAILABLE,
    SimulationAdapterResult,
    SimulationRunRequest,
    SimulationToolSpec,
)
from ..schema import AdapterStatus


class MatlabAdapter(SimulationAdapter):
    name = "matlab"
    software = "matlab"
    backend_type = "matlab"

    def __init__(
        self,
        engine: object | None = None,
        *,
        enabled: bool | None = None,
        engine_factory: object | None = None,
        start_timeout_seconds: int | None = None,
        fake_engine: bool | None = None,
    ) -> None:
        self._engine = engine
        self._enabled_override = enabled
        self._engine_factory = engine_factory
        self._engine_is_fake = bool(fake_engine) or _env_bool("MATLAB_ENGINE_FAKE_FOR_TEST", False)
        self.start_timeout_seconds = start_timeout_seconds if start_timeout_seconds is not None else _env_int("MATLAB_ENGINE_START_TIMEOUT_SEC", 30)

    @property
    def engine(self) -> object | None:
        return self._engine

    def capabilities(self) -> dict[str, object]:
        return {
            "tools": ["matlab_function_eval"],
            "mock": False,
            "real_backend": self._engine is not None,
            "requires_external_software": True,
            "external_software_name": "MATLAB Engine for Python",
            "hooks": ["start_engine", "stop_engine", "restart_engine", "engine_status", "call_function", "call_simulink_model"],
            "start_timeout_seconds": self.start_timeout_seconds,
            "real_execution_enabled": self._real_execution_enabled(),
            "fake_engine": self._engine_is_fake,
            "allowed_functions": self.allowed_functions(),
        }

    def health_check(self) -> AdapterStatus:
        return self.engine_status()

    def engine_status(self) -> AdapterStatus:
        capabilities = self.capabilities()
        enabled = self._is_enabled()
        if not enabled:
            return AdapterStatus(
                adapter_name=self.adapter_name,
                available=False,
                backend_type=self.backend_type,
                reason="matlab_disabled_by_config",
                capabilities=capabilities,
                supported_tools=list(capabilities.get("tools") or []),
                supports_real_backend=False,
                supports_mock=False,
                requires_external_software=True,
                external_software_name="MATLAB Engine for Python",
                external_software_available=False,
            )
        if self._engine is not None:
            return AdapterStatus(
                adapter_name=self.adapter_name,
                available=True,
                backend_type=self.backend_type,
                reason="available",
                capabilities=capabilities,
                supported_tools=list(capabilities.get("tools") or []),
                supports_real_backend=True,
                supports_mock=False,
                requires_external_software=True,
                external_software_name="MATLAB Engine for Python",
                external_software_available=not self._engine_is_fake,
            )
        if not self._real_execution_enabled() and self._engine_factory is None:
            return AdapterStatus(
                adapter_name=self.adapter_name,
                available=False,
                backend_type=self.backend_type,
                reason="matlab_real_execution_disabled",
                capabilities=capabilities,
                supported_tools=list(capabilities.get("tools") or []),
                supports_real_backend=False,
                supports_mock=False,
                requires_external_software=True,
                external_software_name="MATLAB Engine for Python",
                external_software_available=False,
            )
        if self._engine_factory is not None or self._engine_importable():
            reason = "matlab_engine_not_connected"
        else:
            reason = "matlab_engine_not_available"
        return AdapterStatus(
            adapter_name=self.adapter_name,
            available=False,
            backend_type=self.backend_type,
            reason=reason,
            capabilities=capabilities,
            supported_tools=list(capabilities.get("tools") or []),
            supports_real_backend=False,
            supports_mock=False,
            requires_external_software=True,
            external_software_name="MATLAB Engine for Python",
            external_software_available=self._engine_factory is not None,
        )

    def run(self, request: SimulationRunRequest, spec: SimulationToolSpec) -> SimulationAdapterResult:
        status = self.health_check()
        if not status.available:
            error_code = self._compat_error_code(status.reason)
            return SimulationAdapterResult(
                tool_name=spec.tool_name,
                adapter_name=self.name,
                status=SIMULATION_STATUS_UNAVAILABLE,
                mocked=False,
                raw_result={},
                warnings=[status.reason],
                errors=[
                    {
                        "code": error_code,
                        "message": "MATLAB Engine is unavailable; use Mock Adapter for baseline execution.",
                    }
                ],
                backend_type=self.backend_type,
                software=self.software,
                metadata={
                    "engine_connected": False,
                    "real_engine_used": False,
                    "cfd_executed": False,
                    "solver_executed": False,
                    "reason": status.reason,
                    "compat_error_code": error_code,
                },
            )
        return SimulationAdapterResult(
            tool_name=spec.tool_name,
            adapter_name=self.name,
            status=SIMULATION_STATUS_UNAVAILABLE,
            mocked=False,
            raw_result={},
            warnings=["matlab_engine_interface_only"],
            errors=[
                {
                    "code": "matlab_engine_interface_only",
                    "message": "Real MATLAB Engine execution is intentionally deferred after Phase 1.",
                }
            ],
            backend_type=self.backend_type,
            software="matlab-unavailable",
            metadata={
                "engine_connected": True,
                "real_engine_used": False,
                "cfd_executed": False,
                "solver_executed": False,
            },
        )

    def start_engine(self) -> AdapterStatus:
        if not self._is_enabled():
            return self.engine_status()
        if self._engine is not None:
            return self.engine_status()
        if self._engine_factory is None and not self._real_execution_enabled():
            return self.engine_status()
        try:
            self._engine = self._create_engine()
        except ImportError:
            return AdapterStatus(
                adapter_name=self.adapter_name,
                available=False,
                backend_type=self.backend_type,
                reason="matlab_engine_not_available",
                capabilities=self.capabilities(),
                supported_tools=["matlab_function_eval"],
                requires_external_software=True,
                external_software_name="MATLAB Engine for Python",
                external_software_available=False,
            )
        except Exception as exc:
            return AdapterStatus(
                adapter_name=self.adapter_name,
                available=False,
                backend_type=self.backend_type,
                reason=f"matlab_engine_start_failed:{type(exc).__name__}",
                capabilities=self.capabilities(),
                supported_tools=["matlab_function_eval"],
                requires_external_software=True,
                external_software_name="MATLAB Engine for Python",
                external_software_available=False,
            )
        return self.engine_status()

    def stop_engine(self) -> AdapterStatus:
        if self._engine is not None:
            self._close_engine(self._engine)
            self._engine = None
        return self.engine_status()

    def restart_engine(self) -> AdapterStatus:
        self.stop_engine()
        return self.start_engine()

    def call_function(
        self,
        function_name: str,
        parameters: dict | None = None,
        *,
        args: list | tuple | None = None,
        kwargs: dict | None = None,
    ) -> object:
        if not self._is_enabled():
            return {
                "status": "unavailable",
                "mocked": False,
                "is_real": False,
                "is_fake": False,
                "backend_type": self.backend_type,
                "function_name": function_name,
                "error": {
                    "code": "matlab_disabled_by_config",
                    "message": "MATLAB simulation is disabled by configuration.",
                },
            }
        if not self._is_function_allowed(function_name):
            return {
                "status": "failed",
                "mocked": False,
                "is_real": False,
                "is_fake": bool(self._engine_is_fake),
                "backend_type": self.backend_type,
                "function_name": function_name,
                "error": {
                    "code": "matlab_function_not_allowed",
                    "message": f"MATLAB function is not allowed by MATLAB_ALLOWED_FUNCTIONS: {function_name}",
                },
            }
        if self._engine is None:
            status = self.engine_status()
            return {
                "status": "unavailable",
                "mocked": False,
                "is_real": False,
                "is_fake": False,
                "backend_type": self.backend_type,
                "function_name": function_name,
                "error": {
                    "code": status.reason,
                    "message": "MATLAB Engine is not connected.",
                },
            }
        func = getattr(self._engine, function_name)
        call_args = list(args or [])
        call_kwargs = dict(kwargs if kwargs is not None else (parameters or {}))
        try:
            result = func(*call_args, **call_kwargs)
        except TypeError:
            try:
                result = func(parameters or call_kwargs)
            except Exception as exc:
                return {
                    "status": "failed",
                    "mocked": False,
                    "is_real": False,
                    "is_fake": bool(self._engine_is_fake),
                    "backend_type": self.backend_type,
                    "function_name": function_name,
                    "error": {"code": "matlab_function_call_failed", "message": f"{type(exc).__name__}: {exc}"},
                }
        except Exception as exc:
            return {
                "status": "failed",
                "mocked": False,
                "is_real": False,
                "is_fake": bool(self._engine_is_fake),
                "backend_type": self.backend_type,
                "function_name": function_name,
                "error": {"code": "matlab_function_call_failed", "message": f"{type(exc).__name__}: {exc}"},
            }
        return {
            "status": "success",
            "mocked": False,
            "is_real": not self._engine_is_fake,
            "is_fake": bool(self._engine_is_fake),
            "backend_type": self.backend_type,
            "software": "MATLAB" if not self._engine_is_fake else "matlab-fake-engine",
            "function_name": function_name,
            "result": result,
        }

    def call_simulink_model(self, model_name: str, parameters: dict | None = None) -> dict[str, object]:
        return {
            "status": "not_implemented",
            "mocked": False,
            "code": "simulink_not_implemented",
            "model_name": model_name,
            "parameters": parameters or {},
            "message": "Simulink execution is a structured placeholder and is not connected in Phase 3.",
        }

    def _is_enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        raw = os.getenv("MATLAB_SIMULATION_ENABLED")
        if raw is None:
            return True
        return raw.strip().lower() not in {"0", "false", "no", "off"}

    def _real_execution_enabled(self) -> bool:
        return _env_bool("MATLAB_ENGINE_REAL_EXECUTION_ENABLED", False)

    def allowed_functions(self) -> list[str]:
        raw = os.getenv("MATLAB_ALLOWED_FUNCTIONS") or "plus,minus,times,mtimes"
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _is_function_allowed(self, function_name: str) -> bool:
        normalized = str(function_name or "").strip()
        return bool(normalized) and normalized in set(self.allowed_functions())

    def _engine_importable(self) -> bool:
        try:
            self._import_matlab_engine()
            return True
        except Exception:
            return False

    def _import_matlab_engine(self):
        return importlib.import_module("matlab.engine")

    def _create_engine(self) -> object:
        if self._engine_factory is not None:
            try:
                return self._engine_factory(timeout_seconds=self.start_timeout_seconds)  # type: ignore[misc]
            except TypeError:
                return self._engine_factory()  # type: ignore[misc]
        if not self._real_execution_enabled():
            raise RuntimeError("matlab_real_execution_disabled")
        matlab_engine = self._import_matlab_engine()
        starter = getattr(matlab_engine, "start_matlab")
        return starter()

    def _close_engine(self, engine: object) -> None:
        for name in ("quit", "exit", "close"):
            method = getattr(engine, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                return

    def _compat_error_code(self, reason: str) -> str:
        if (
            self._enabled_override is None
            and os.getenv("MATLAB_SIMULATION_ENABLED") is None
            and os.getenv("MATLAB_ENGINE_REAL_EXECUTION_ENABLED") is None
            and reason in {"matlab_engine_not_available", "matlab_real_execution_disabled"}
        ):
            return "matlab_engine_unavailable"
        return reason


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


__all__ = ["MatlabAdapter"]
