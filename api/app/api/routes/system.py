"""System routes that do not cross into application use cases."""

from fastapi import APIRouter

from app.api.schemas import RootResponse, StatusResponse

router = APIRouter(tags=["system"])


@router.get("/", response_model=RootResponse)
def read_root() -> RootResponse:
    return RootResponse(service="resource-monitoring-api", status="running")


@router.get("/health", response_model=StatusResponse)
def healthcheck() -> StatusResponse:
    return StatusResponse(status="healthy")
