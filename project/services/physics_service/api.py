"""Stateless physics-validation HTTP adapter; no execution or persistence."""
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .contracts import PhysicsValidationRequest, PhysicsValidationResult
from .validator import validate_physics

class _PhysicsRoute(APIRoute):
    """Malformed numeric payloads must not be echoed as non-JSON NaN/Infinity."""

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


router = APIRouter(prefix="/simulation/physics", tags=["physics"], route_class=_PhysicsRoute)


@router.post("/validate", response_model=PhysicsValidationResult)
def validate_constraints(request: PhysicsValidationRequest) -> PhysicsValidationResult:
    return validate_physics(request)
