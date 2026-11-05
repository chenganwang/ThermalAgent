from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable

from .availability import check_matlab_engine_importable
from .config import MatlabIntegrationConfig
from .errors import MatlabEngineUnavailableError
from .safe_calls import call_whitelisted_function


class MatlabEngineClient:
    def __init__(
        self,
        config: MatlabIntegrationConfig,
        *,
        engine_factory: Callable[..., object] | None = None,
        import_engine: Callable[[], object] | None = None,
        fake_engine: bool = False,
    ) -> None:
        self.config = config
        self._engine_factory = engine_factory
        self._import_engine = import_engine
        self.fake_engine = bool(fake_engine)
        self.engine: object | None = None

    def import_status(self) -> dict[str, Any]:
        if self.fake_engine and self._engine_factory is not None:
            return {"engine_importable": True, "reason": "fake_engine_for_test", "module": None}
        return check_matlab_engine_importable(self._import_engine)

    def start_engine(self) -> object:
        if self.engine is not None:
            return self.engine
        if self.fake_engine and self._engine_factory is not None:
            self.engine = self._call_factory()
            return self.engine
        if not self.config.allow_engine_start:
            raise MatlabEngineUnavailableError("MATLAB engine start is disabled.", code="not_configured")
        import_status = self.import_status()
        module = import_status.get("module")
        if not import_status.get("engine_importable") or module is None:
            raise MatlabEngineUnavailableError("MATLAB Engine for Python is not installed.", code="engine_not_installed")
        try:
            starter = getattr(module, "start_matlab")
            self.engine = self._start_with_timeout(starter)
        except MatlabEngineUnavailableError:
            raise
        except Exception as exc:
            raise MatlabEngineUnavailableError(
                f"MATLAB engine start failed: {type(exc).__name__}",
                code="engine_start_failed",
            ) from exc
        return self.engine

    def call_function(self, function_name: str, args: list[Any]) -> Any:
        if self.engine is None:
            raise MatlabEngineUnavailableError("MATLAB engine is not connected.", code="engine_not_connected")
        return call_whitelisted_function(
            self.engine,
            function_name,
            list(args),
            set(self.config.allowed_functions),
        )

    def version(self) -> str | None:
        engine = self.engine
        if engine is None:
            return None
        for name in ("version", "ver"):
            method = getattr(engine, name, None)
            if callable(method):
                try:
                    value = method()
                except Exception:
                    continue
                if value is not None:
                    return str(value)
        return "FAKE-MATLAB" if self.fake_engine else None

    def close(self) -> None:
        engine = self.engine
        self.engine = None
        if engine is None:
            return
        for name in ("quit", "exit", "close"):
            method = getattr(engine, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                return

    def _call_factory(self) -> object:
        factory = self._engine_factory
        if factory is None:
            raise MatlabEngineUnavailableError("No fake engine factory was provided.", code="engine_not_installed")
        try:
            return factory(timeout_seconds=self.config.engine_timeout_seconds)
        except TypeError:
            return factory()

    def _start_with_timeout(self, starter: Callable[[], object]) -> object:
        timeout = max(int(self.config.engine_timeout_seconds or 0), 1)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(starter)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise MatlabEngineUnavailableError(
                f"MATLAB engine start timed out after {timeout} seconds.",
                code="engine_start_failed",
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["MatlabEngineClient"]
