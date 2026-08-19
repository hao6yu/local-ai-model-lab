from fastapi import APIRouter, Request

from app.core import runtime as runtime_service
from app.core.config import Settings
from app.core.health import Probe
from app.schemas.health import HealthResponse
from app.schemas.runtime import RuntimeResponse

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    probe: Probe = request.app.state.probe_upstream
    return HealthResponse(portal="ok", model=probe(settings))


@router.get("/runtime", response_model=RuntimeResponse)
def get_runtime(request: Request) -> RuntimeResponse:
    settings: Settings = request.app.state.settings
    return runtime_service.build_runtime(settings)
