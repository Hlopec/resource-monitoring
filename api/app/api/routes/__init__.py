"""Route modules owned by the FastAPI transport layer."""

from app.api.routes.resource_lookups import router as resource_lookups_router
from app.api.routes.resources import router as resources_router
from app.api.routes.system import router as system_router

__all__ = ["resource_lookups_router", "resources_router", "system_router"]
