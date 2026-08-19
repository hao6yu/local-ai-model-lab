from typing import Literal

from pydantic import BaseModel

PortalState = Literal["ok"]
ModelState = Literal["reachable", "unavailable"]


class UpstreamHealth(BaseModel):
    state: ModelState
    detail: str | None = None


class HealthResponse(BaseModel):
    portal: PortalState
    model: UpstreamHealth
