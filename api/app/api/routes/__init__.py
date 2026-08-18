"""Route modules owned by the FastAPI transport layer."""

from app.api.routes.system import router as system_router

__all__ = ["system_router"]
