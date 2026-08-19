"""Top-level FastAPI router composition."""

from fastapi import APIRouter, FastAPI

from app.api.routes.resource_lookups import router as resource_lookups_router
from app.api.routes.resources import router as resources_router
from app.api.routes.system import router as system_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(resource_lookups_router)
api_v1_router.include_router(resources_router)


def include_api_routes(app: FastAPI) -> None:
    """Attach stable system routes and the production API version boundary."""
    app.include_router(system_router)
    app.include_router(api_v1_router)
