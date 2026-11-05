from __future__ import annotations


class MatlabIntegrationError(Exception):
    code = "matlab_integration_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class MatlabConfigurationError(MatlabIntegrationError):
    code = "matlab_configuration_error"


class MatlabEngineUnavailableError(MatlabIntegrationError):
    code = "matlab_engine_unavailable"


class MatlabUnsafeCallError(MatlabIntegrationError):
    code = "matlab_unsafe_call_rejected"


class MatlabDemoValidationError(MatlabIntegrationError):
    code = "invalid_demo_parameters"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: str = "invalid_parameters",
        missing_parameters: list[str] | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.status = status
        self.missing_parameters = list(missing_parameters or [])


__all__ = [
    "MatlabConfigurationError",
    "MatlabDemoValidationError",
    "MatlabEngineUnavailableError",
    "MatlabIntegrationError",
    "MatlabUnsafeCallError",
]
