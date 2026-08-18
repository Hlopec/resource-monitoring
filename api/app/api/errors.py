"""HTTP error policy for application-facing errors."""

from fastapi import status

from app.application.errors import (
    ApplicationError,
    ConcurrentModificationError,
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
    ValidationError,
)

APPLICATION_ERROR_STATUS_CODES: dict[type[ApplicationError], int] = {
    ValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    EntityNotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    ConcurrentModificationError: status.HTTP_409_CONFLICT,
    TenantBoundaryError: status.HTTP_404_NOT_FOUND,
    PersistenceError: status.HTTP_503_SERVICE_UNAVAILABLE,
}
