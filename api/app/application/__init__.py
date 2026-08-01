"""Application core boundary.

This package contains application-facing errors and ports. It must not depend on
SQLAlchemy or concrete persistence implementations.
"""

from app.application.errors import (
    ApplicationError,
    ConcurrentModificationError,
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
)

__all__ = [
    "ApplicationError",
    "ConcurrentModificationError",
    "ConflictError",
    "EntityNotFoundError",
    "PersistenceError",
    "TenantBoundaryError",
]
