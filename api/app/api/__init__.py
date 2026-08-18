"""FastAPI transport boundary for the resource monitoring service."""

from app.api.router import api_v1_router, include_api_routes

__all__ = ["api_v1_router", "include_api_routes"]
