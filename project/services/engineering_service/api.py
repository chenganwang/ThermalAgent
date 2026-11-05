"""Authenticated by the hosting API; no arbitrary file paths or external replay."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from services.physics_service.api import _PhysicsRoute

from services.simulation_service.reference import LayeredWallRequest
from .execution import RunRecorder, configured_store, execute_reference, finish_local_report, reference_plan, resume_run
from .store import RunConflict
from .result_identity import ResultIdentityError


Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,96}$")]
router = APIRouter(prefix="/engineering", tags=["engineering"], route_class=_PhysicsRoute)


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_ids: list[Identifier] = Field(min_length=2, max_length=4)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1)
    confirmed: StrictBool

    @field_validator("confirmed")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation is required")
        return value


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: LayeredWallRequest
    project_id: Identifier = "local"


def get_store(request: Request):
    agent = getattr(request.app.state, "agent", None)
    store = getattr(agent, "engineering_store", None)
    if store is None:
        cfg = getattr(request.app.state, "cfg", None)
        if cfg is not None:
            store = configured_store(cfg.paths.project_root)
    if store is None:
        raise HTTPException(503, detail={"code": "ENGINEERING_STORE_UNAVAILABLE"})
    return store


def call(action):
    try:
        return action()
    except ResultIdentityError:
        raise HTTPException(409, detail={"code": "ENGINEERING_RESULT_IDENTITY_MISMATCH", "message": "记录的结果与本次执行输入不一致，已拒绝返回。"}) from None
    except KeyError:
        raise HTTPException(404, detail={"code": "ENGINEERING_RECORD_NOT_FOUND"}) from None
    except RunConflict as exc:
        raise HTTPException(409, detail={"code": "ENGINEERING_RUN_CONFLICT", "message": str(exc)}) from None
    except Exception as exc:
        raise HTTPException(503, detail={"code": "ENGINEERING_STORAGE_ERROR", "error_type": type(exc).__name__}) from None


@router.get("/projects")
def projects(store=Depends(get_store)):
    return {"projects": call(store.projects)}


@router.post("/projects", status_code=201)
def create_project(payload: ProjectRequest, store=Depends(get_store)):
    return call(lambda: store.create_project(payload.title, payload.description))


@router.get("/runs")
def runs(project_id: Identifier | None = None, limit: int = Query(30, ge=1, le=100),
         offset: int = Query(0, ge=0), store=Depends(get_store)):
    return call(lambda: store.list_runs(project_id, limit, offset))


@router.post("/runs/compare")
def compare(payload: CompareRequest, store=Depends(get_store)):
    if len(set(payload.run_ids)) != len(payload.run_ids):
        raise HTTPException(422, detail={"code": "DISTINCT_RUNS_REQUIRED"})
    return call(lambda: store.compare(payload.run_ids))


@router.get("/runs/{run_id}")
def run_detail(run_id: Identifier, store=Depends(get_store)):
    return call(lambda: store.get(run_id))


@router.post("/runs/{run_id}/resume")
def resume(run_id: Identifier, payload: ResumeRequest, store=Depends(get_store)):
    return call(lambda: resume_run(store, run_id, payload.expected_revision))


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
def artifact(run_id: Identifier, artifact_id: Identifier, store=Depends(get_store)):
    item = call(lambda: store.artifact(run_id, artifact_id))
    suffix = "md" if item["kind"] == "report" else "json"
    return Response(item["content"], media_type=item["media_type"], headers={
        "Content-Disposition": f'attachment; filename="{artifact_id}.{suffix}"',
        "ETag": '"' + item["sha256"] + '"', "X-Content-Type-Options": "nosniff"})


@router.post("/reference/solve")
def reference(payload: ReferenceRequest, store=Depends(get_store)):
    if not call(lambda: store.project_exists(payload.project_id)):
        raise HTTPException(404, detail={"code": "ENGINEERING_PROJECT_NOT_FOUND"})
    plan = reference_plan(payload.inputs.model_dump())
    recorder = RunRecorder(store, {"origin": "reference_solver_api"}, payload.project_id)
    try:
        result = execute_reference(plan, recorder)
        run = result.pop("engineering_run")
        run, report = finish_local_report(run, result)
        recorder(run, result, report)
        run["persistence"] = recorder.state
        return {"result": result["reference_solver"], "engineering_run": run, "report": report}
    finally:
        recorder.close()


from .task_api import router as task_router
router.include_router(task_router)
