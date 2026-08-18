"""Top-level FastAPI router composition."""

from fastapi import APIRouter, FastAPI

from app.api.routes.system import router as system_router

api_v1_router = APIRouter(prefix="/api/v1")


def include_api_routes(app: FastAPI) -> None:
    """Attach stable system routes and the production API version boundary."""
    app.include_router(system_router)
    app.include_router(api_v1_router)
