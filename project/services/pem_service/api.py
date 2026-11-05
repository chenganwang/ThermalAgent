"""PEM endpoints inherit the host's API authentication and finite-input errors."""
from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError

from services.engineering_service.api import get_store
from services.physics_service.api import _PhysicsRoute
from .contracts import CompareRequest, DOERequest, Identifier, ImportRequest, StudyRequest
from .extensions import domain_catalog, extension_catalog
from .parameters import ParameterError, REQUIRED_NAMES, TOPOLOGIES, example_study
from .service import PEMService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pem", tags=["pem-flowfield"], route_class=_PhysicsRoute)


def service(store=Depends(get_store)):
    return PEMService(store)


def call(action):
    try:
        return action()
    except KeyError:
        raise HTTPException(404, detail={"code": "PEM_RECORD_NOT_FOUND"}) from None
    except ParameterError as exc:
        raise HTTPException(422, detail={"code": "PEM_PARAMETER_REJECTED", "reasons": exc.reasons}) from None
    except ValidationError as exc:
        raise HTTPException(422, detail={"code": "PEM_INPUT_INVALID", "errors": [
            {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}) from None
    except ValueError:
        raise HTTPException(422, detail={"code": "PEM_INPUT_OR_RECORD_INVALID",
                                        "message": "输入不符合数据合同或记录完整性检查；请核对字段、单位和所属研究。"}) from None
    except Exception as exc:
        logger.error("PEM operation failed: error_type=%s", type(exc).__name__)
        raise HTTPException(503, detail={"code": "PEM_OPERATION_UNAVAILABLE", "error_type": type(exc).__name__}) from None


@router.get("/catalog")
def catalog():
    return {**domain_catalog(), "schema_version": "1.0", "required_parameters": list(REQUIRED_NAMES),
            "topologies": list(TOPOLOGIES), "example_study": example_study(),
            "provenance_values": ["fluent_export", "manual_import", "synthetic_demo"],
            "units": {"length": ["m", "mm", "cm", "um"], "mass_flow_rate": ["kg/s", "g/s", "kg/h"],
                      "temperature": ["K", "degC"], "outlet_pressure": ["Pa", "kPa", "MPa"]}}


@router.get("/extensions")
def extensions():
    return extension_catalog()


@router.get("/studies")
def studies(project_id: Identifier | None = None, svc=Depends(service)):
    return {"studies": call(lambda: svc.store.studies(project_id))}


@router.post("/studies", status_code=201)
def create_study(payload: StudyRequest, svc=Depends(service)):
    return call(lambda: svc.create_study(payload.model_dump()))


@router.get("/studies/{study_id}")
def get_study(study_id: Identifier, svc=Depends(service)):
    return call(lambda: svc.get_study(study_id))


@router.post("/studies/{study_id}/doe")
def doe(study_id: Identifier, payload: DOERequest, svc=Depends(service)):
    return call(lambda: svc.doe(study_id, payload.model_dump()))


@router.get("/studies/{study_id}/candidates")
def candidates(study_id: Identifier, format: Literal["json", "csv"] = "json", svc=Depends(service)):
    if format == "csv":
        content = call(lambda: svc.candidate_csv(study_id))
        return Response(content.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{study_id}_candidates.csv"'})
    return {"study": call(lambda: svc.store.get_study(study_id)),
            "batches": call(lambda: svc.store.batches(study_id)),
            "candidates": call(lambda: svc.store.candidates(study_id))}


@router.post("/studies/{study_id}/imports", status_code=201)
def import_results(study_id: Identifier, payload: ImportRequest, svc=Depends(service)):
    return call(lambda: svc.import_results(study_id, payload.model_dump()))


@router.get("/studies/{study_id}/imports/{import_id}/source")
def import_source(study_id: Identifier, import_id: Identifier, svc=Depends(service)):
    source = call(lambda: svc.store.source(study_id, import_id))
    filename = quote(source["source"].get("filename", "simulation-results.json"), safe="")
    return Response(source["content"], media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                             "X-Content-SHA256": source["sha256"]})


@router.get("/studies/{study_id}/results")
def results(study_id: Identifier, svc=Depends(service)):
    return {"results": call(lambda: svc.store.results(study_id)), "imports": call(lambda: svc.store.imports(study_id))}


@router.post("/studies/{study_id}/compare")
def compare(study_id: Identifier, payload: CompareRequest, svc=Depends(service)):
    return call(lambda: svc.compare(study_id, payload.result_ids))


@router.get("/studies/{study_id}/report")
def report(study_id: Identifier, format: Literal["json", "markdown"] = "json", svc=Depends(service)):
    generated = call(lambda: svc.report(study_id))
    if format == "markdown":
        return Response(generated["content"], media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{study_id}_report.md"'})
    return generated
