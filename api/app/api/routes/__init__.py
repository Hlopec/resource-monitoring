"""Route modules owned by the FastAPI transport layer."""

from app.api.routes.resources import router as resources_router
from app.api.routes.system import router as system_router

__all__ = ["resources_router", "system_router"]
