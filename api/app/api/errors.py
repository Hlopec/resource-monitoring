"""HTTP error policy for application-facing errors."""

from fastapi import FastAPI, Request, status
from starlette.responses import JSONResponse

from app.api.schemas import ApiError, ApiErrorDetail, ApiErrorResponse
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
    ConcurrentModificationError: status.HTTP_409_CONFLICT,
    ConflictError: status.HTTP_409_CONFLICT,
    TenantBoundaryError: status.HTTP_404_NOT_FOUND,
    PersistenceError: status.HTTP_503_SERVICE_UNAVAILABLE,
}

VALIDATION_ERROR_CODE = "validation_error"
NOT_FOUND_ERROR_CODE = "not_found"
CONFLICT_ERROR_CODE = "conflict"
CONCURRENT_MODIFICATION_ERROR_CODE = "concurrent_modification"
SERVICE_UNAVAILABLE_ERROR_CODE = "service_unavailable"

VALIDATION_ERROR_MESSAGE = "Input validation failed"
NOT_FOUND_ERROR_MESSAGE = "Requested resource was not found"
CONFLICT_ERROR_MESSAGE = "Request conflicts with the current resource state"
CONCURRENT_MODIFICATION_ERROR_MESSAGE = "Resource was modified concurrently"
SERVICE_UNAVAILABLE_ERROR_MESSAGE = "Service is temporarily unavailable"


def register_application_error_handlers(app: FastAPI) -> None:
    """Register centralized API handlers for application-layer errors."""

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        del request
        return application_error_json_response(exc)


def application_error_json_response(exc: ApplicationError) -> JSONResponse:
    """Build a sanitized JSON response for an application error."""
    return JSONResponse(
        status_code=application_error_status_code(exc),
        content=api_error_response_for(exc).model_dump(mode="json"),
    )


def application_error_status_code(exc: ApplicationError) -> int:
    """Return the HTTP status for an application error."""
    if isinstance(exc, ValidationError):
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    if isinstance(exc, (EntityNotFoundError, TenantBoundaryError)):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, ConcurrentModificationError):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, ConflictError):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, PersistenceError):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def api_error_response_for(exc: ApplicationError) -> ApiErrorResponse:
    """Return the public, sanitized API error envelope for an application error."""
    if isinstance(exc, ValidationError):
        return ApiErrorResponse(
            error=ApiError(
                code=VALIDATION_ERROR_CODE,
                message=VALIDATION_ERROR_MESSAGE,
                details=[
                    ApiErrorDetail(field=failure.field, message=failure.message)
                    for failure in exc.failures
                ],
            )
        )
    if isinstance(exc, (EntityNotFoundError, TenantBoundaryError)):
        return _empty_error(NOT_FOUND_ERROR_CODE, NOT_FOUND_ERROR_MESSAGE)
    if isinstance(exc, ConcurrentModificationError):
        return _empty_error(
            CONCURRENT_MODIFICATION_ERROR_CODE,
            CONCURRENT_MODIFICATION_ERROR_MESSAGE,
        )
    if isinstance(exc, ConflictError):
        return _empty_error(CONFLICT_ERROR_CODE, CONFLICT_ERROR_MESSAGE)
    if isinstance(exc, PersistenceError):
        return _empty_error(
            SERVICE_UNAVAILABLE_ERROR_CODE,
            SERVICE_UNAVAILABLE_ERROR_MESSAGE,
        )
    return _empty_error(SERVICE_UNAVAILABLE_ERROR_CODE, SERVICE_UNAVAILABLE_ERROR_MESSAGE)


def _empty_error(code: str, message: str) -> ApiErrorResponse:
    return ApiErrorResponse(
        error=ApiError(
            code=code,
            message=message,
            details=[],
        )
    )
