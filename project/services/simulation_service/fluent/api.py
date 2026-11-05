from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .contracts import FluentError, PrepareJob, RunJob
from .service import FluentService

class _FluentRoute(APIRoute):
    """Reject malformed values without echoing NaN/Infinity or user inputs."""

    def get_route_handler(self):
        handle = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handle(request)
            except RequestValidationError as exc:
                return JSONResponse(status_code=422, content={"detail": [
                    {"type": item["type"], "loc": list(item["loc"]), "msg": item["msg"]}
                    for item in exc.errors()
                ]})

        return validated


router = APIRouter(prefix="/simulation/fluent", tags=["Fluent engineering jobs"], route_class=_FluentRoute)
cfd_router = APIRouter(prefix="/simulation/cfd", tags=["Pluggable CFD jobs"], route_class=_FluentRoute)


@lru_cache(maxsize=1)
def get_fluent_service() -> FluentService:
    return _call(FluentService)


def _call(function, *args):
    try:
        return function(*args)
    except FluentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public()) from None
    except OSError:
        raise HTTPException(status_code=503, detail={"code": "FLUENT_STORAGE_UNAVAILABLE", "message": "Fluent job storage is unavailable."}) from None


@router.get("/status")
@cfd_router.get("/status")
def status(service: FluentService = Depends(get_fluent_service)):
    return _call(service.status)


@router.get("/environment")
@cfd_router.get("/environment")
def environment(service: FluentService = Depends(get_fluent_service)):
    return _call(service.status)["environment"]


@router.get("/jobs")
@cfd_router.get("/jobs")
def jobs(limit: int = Query(default=50, ge=1, le=100), service: FluentService = Depends(get_fluent_service)):
    return _call(service.list, limit)


@router.post("/jobs", status_code=201)
@cfd_router.post("/jobs", status_code=201)
def prepare(payload: PrepareJob, service: FluentService = Depends(get_fluent_service)):
    return _call(service.prepare, payload)


@router.get("/jobs/{job_id}")
@cfd_router.get("/jobs/{job_id}")
def get(job_id: str, service: FluentService = Depends(get_fluent_service)):
    return _call(service.get, job_id)


@router.post("/jobs/{job_id}/run", status_code=202)
@cfd_router.post("/jobs/{job_id}/run", status_code=202)
def run(job_id: str, payload: RunJob, service: FluentService = Depends(get_fluent_service)):
    return _call(service.run, job_id, payload)


@router.get("/jobs/{job_id}/report")
@cfd_router.get("/jobs/{job_id}/report")
def report(job_id: str, service: FluentService = Depends(get_fluent_service)):
    return _call(service.report, job_id)
