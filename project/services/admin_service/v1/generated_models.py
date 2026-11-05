from __future__ import annotations

from collections.abc import Callable
from typing import Any

from services.simulation_service.matlab.runtime import get_matlab_runtime_manager
from services.simulation_service.modeling.compiler import (
    CompilationError,
    CompilationPlanner,
    GeneratedModelArtifactStore,
    ModelCompiler,
)
from services.simulation_service.modeling.lifecycle import (
    GeneratedModelLifecycleError,
    GeneratedModelService,
)
from services.simulation_service.modeling.registry import ComponentRegistry
from services.simulation_service.modeling.simulink_compiler import SimulinkCompilerBackend

from ..contracts import AdminAPIError


class GeneratedModelAdminService:
    """Admin control-plane facade for autonomously generated model revisions."""

    def __init__(
        self,
        lifecycle: GeneratedModelService | None = None,
        *,
        compiler_factory: Callable[[], ModelCompiler] | None = None,
    ) -> None:
        self.lifecycle = lifecycle or GeneratedModelService()
        self._compiler_factory = compiler_factory or self._real_compiler

    def capabilities(self) -> dict[str, Any]:
        return {
            "generated_models": True,
            "immutable_revisions": True,
            "admin_approval_required": True,
            "admin_enable_required": True,
            "user_confirmation_required": True,
            "compiler_backend": "matlab_simulink_simscape",
            "artifact_paths_public": False,
            "persistence": "host_local_file_backed",
            "retention_policies": ["ephemeral", "resident"],
            "engineering_edit_surface": "model_ir_only",
            "safe_delete": "tombstone_plus_controlled_artifact_cleanup",
        }

    def list_models(
        self,
        *,
        status: str | None = None,
        query: str | None = None,
        origin: str | None = None,
        retention: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = self.lifecycle.repository.list(
                status=status, query=query, origin=origin, retention=retention,
            )
        except GeneratedModelLifecycleError as exc:
            raise _admin_error(exc) from exc
        return {**result, "capabilities": self.capabilities()}

    def get_model(self, generation_id: str) -> dict[str, Any]:
        try:
            current = self.lifecycle.repository.get(generation_id)
            return {**current, "revision_history": self.lifecycle.repository.history(generation_id), "capabilities": self.capabilities()}
        except GeneratedModelLifecycleError as exc:
            raise _admin_error(exc) from exc

    def compile(self, generation_id: str, *, actor_id: str) -> dict[str, Any]:
        try:
            result = self.lifecycle.compile_candidate(generation_id, self._compiler_factory())
        except GeneratedModelLifecycleError as exc:
            raise _admin_error(exc) from exc
        except CompilationError as exc:
            raise AdminAPIError(exc.code, str(exc), status_code=409) from exc
        if result.get("status") != "pending_approval":
            errors = ((result.get("compilation") or {}).get("errors") or [])
            code = str((errors[0] if errors else {}).get("code") or "GENERATED_MODEL_COMPILE_FAILED")
            raise AdminAPIError(code, "Generated-model compilation did not complete.", status_code=409)
        return result

    def approve(self, generation_id: str, *, actor_id: str, reason: str) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.approve(generation_id, actor_id=actor_id, reason=reason))

    def reject(self, generation_id: str, *, actor_id: str, reason: str) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.reject(generation_id, actor_id=actor_id, reason=reason))

    def enable(self, generation_id: str, *, actor_id: str) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.enable(generation_id, actor_id=actor_id))

    def disable(self, generation_id: str, *, actor_id: str) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.disable(generation_id, actor_id=actor_id))

    def update_metadata(
        self,
        generation_id: str,
        *,
        actor_id: str,
        display_name: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.update_metadata(
            generation_id, actor_id=actor_id, display_name=display_name, description=description,
        ))

    def create_engineering_revision(
        self,
        generation_id: str,
        *,
        actor_id: str,
        model_ir: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.create_engineering_revision(
            generation_id, model_ir, actor_id=actor_id, reason=reason,
        ))

    def promote(self, generation_id: str, *, actor_id: str) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.promote(generation_id, actor_id=actor_id))

    def delete(
        self,
        generation_id: str,
        *,
        actor_id: str,
        reason: str,
        active_jobs: bool,
    ) -> dict[str, Any]:
        return self._transition(lambda: self.lifecycle.delete(
            generation_id, actor_id=actor_id, reason=reason, active_jobs=active_jobs,
        ))

    @staticmethod
    def _transition(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except GeneratedModelLifecycleError as exc:
            raise _admin_error(exc) from exc

    def _real_compiler(self) -> ModelCompiler:
        runtime = get_matlab_runtime_manager()
        capabilities = runtime.simulation_build_capabilities()
        registry = self.lifecycle.registry
        return ModelCompiler(
            CompilationPlanner(registry, capabilities),
            SimulinkCompilerBackend(runtime),
            GeneratedModelArtifactStore(),
        )


def _admin_error(exc: GeneratedModelLifecycleError) -> AdminAPIError:
    status = 404 if exc.code == "GENERATED_MODEL_NOT_FOUND" else 410 if exc.code == "GENERATED_MODEL_DELETED" else 422 if exc.code.endswith("_INVALID") and "TRANSITION" not in exc.code else 409
    return AdminAPIError(exc.code, str(exc), status_code=status)


__all__ = ["GeneratedModelAdminService"]
