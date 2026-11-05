from __future__ import annotations

from typing import Any

from .errors import MatlabUnsafeCallError


BLOCKED_FUNCTIONS = {
    "eval",
    "evalin",
    "feval",
    "run",
    "system",
    "dos",
    "unix",
    "perl",
    "python",
    "delete",
    "rmdir",
    "copyfile",
    "movefile",
}


def call_whitelisted_function(engine: object, function_name: str, args: list[Any], allowed_functions: set[str]) -> Any:
    name = str(function_name or "").strip()
    if not name or name in BLOCKED_FUNCTIONS or name not in allowed_functions or name.startswith("!"):
        raise MatlabUnsafeCallError(
            f"MATLAB function is not allowed: {name}",
            code="matlab_function_not_allowed",
        )
    func = getattr(engine, name, None)
    if not callable(func):
        raise MatlabUnsafeCallError(
            f"MATLAB function is not available on the engine: {name}",
            code="matlab_function_unavailable",
        )
    return func(*args)


__all__ = ["BLOCKED_FUNCTIONS", "call_whitelisted_function"]
