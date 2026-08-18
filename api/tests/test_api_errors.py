from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_application_error_handlers
from app.api.schemas import ApiErrorResponse
from app.application.errors import (
    ConcurrentModificationError,
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
    ValidationError,
    ValidationFailure,
)
from app.main import app as real_app

SENSITIVE_STRINGS = (
    "sqlalchemy",
    "postgres",
    "SQLSTATE",
    "constraint",
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "Traceback",
    "uq_",
    "other tenant",
)


def _app_with_error(error: Exception) -> FastAPI:
    app = FastAPI()
    register_application_error_handlers(app)

    @app.get("/raise")
    def raise_error() -> None:
        raise error

    return app


def _error_body(error: Exception, status_code: int) -> dict[str, object]:
    response = TestClient(_app_with_error(error)).get("/raise")

    assert response.status_code == status_code
    return response.json()


def _body_text(body: dict[str, object]) -> str:
    return str(body)


def test_validation_error_maps_to_422_with_ordered_safe_details() -> None:
    error = ValidationError(
        "Internal validation text",
        failures=(
            ValidationFailure("classification_value_id", "requires classification_type_id"),
            ValidationFailure("page_size", "must be <= 200"),
        ),
    )

    body = _error_body(error, 422)

    assert body == {
        "error": {
            "code": "validation_error",
            "message": "Input validation failed",
            "details": [
                {
                    "field": "classification_value_id",
                    "message": "requires classification_type_id",
                },
                {"field": "page_size", "message": "must be <= 200"},
            ],
        }
    }
    assert "Internal validation text" not in _body_text(body)


def test_entity_not_found_maps_to_sanitized_404_without_lookup_metadata() -> None:
    secret_value = f"other tenant {uuid4()} SELECT secret FROM resource"
    error = EntityNotFoundError(
        "Resource missing",
        entity_type="Resource",
        lookup_field="resource_id",
        lookup_value=secret_value,
    )

    body = _error_body(error, 404)

    assert body == {
        "error": {
            "code": "not_found",
            "message": "Requested resource was not found",
            "details": [],
        }
    }
    assert secret_value not in _body_text(body)


def test_conflict_error_maps_to_sanitized_409_without_constraint() -> None:
    error = ConflictError(
        "Identifier conflict",
        entity_type="ResourceIdentifier",
        conflict_field="current_value",
        constraint="uq_resource_identifier_current",
    )

    body = _error_body(error, 409)

    assert body == {
        "error": {
            "code": "conflict",
            "message": "Request conflicts with the current resource state",
            "details": [],
        }
    }
    assert "uq_resource_identifier_current" not in _body_text(body)
    assert "constraint" not in _body_text(body)


def test_concurrent_modification_mapping_is_not_shadowed_by_conflict() -> None:
    error = ConcurrentModificationError(
        "Resource was modified concurrently",
        entity_type="Resource",
        conflict_field="record_version",
    )

    body = _error_body(error, 409)

    assert body == {
        "error": {
            "code": "concurrent_modification",
            "message": "Resource was modified concurrently",
            "details": [],
        }
    }


def test_tenant_boundary_maps_like_not_found_without_tenant_disclosure() -> None:
    error = TenantBoundaryError(
        f"cross tenant source={uuid4()} target={uuid4()} other tenant"
    )

    body = _error_body(error, 404)

    assert body == {
        "error": {
            "code": "not_found",
            "message": "Requested resource was not found",
            "details": [],
        }
    }
    assert "tenant" not in _body_text(body).lower()
    assert "cross" not in _body_text(body).lower()
    assert "other tenant" not in _body_text(body)


def test_persistence_error_maps_to_sanitized_503_without_cause_leakage() -> None:
    cause = RuntimeError(
        "postgres SQLSTATE 23505 constraint uq_secret SELECT password FROM users"
    )
    error = PersistenceError("storage failure")
    error.__cause__ = cause

    body = _error_body(error, 503)
    body_text = _body_text(body)

    assert body == {
        "error": {
            "code": "service_unavailable",
            "message": "Service is temporarily unavailable",
            "details": [],
        }
    }
    assert all(sensitive not in body_text for sensitive in SENSITIVE_STRINGS)


def test_application_error_handlers_are_registered_on_real_app() -> None:
    assert real_app.exception_handlers
    assert any(
        getattr(error_type, "__name__", "") == "ApplicationError"
        for error_type in real_app.exception_handlers
    )

    client = TestClient(real_app)
    assert client.get("/").json() == {
        "service": "resource-monitoring-api",
        "status": "running",
    }
    assert client.get("/health").json() == {"status": "healthy"}


def test_unknown_errors_keep_standard_fastapi_500_behavior() -> None:
    app = FastAPI()
    register_application_error_handlers(app)

    @app.get("/unknown")
    def unknown() -> None:
        raise RuntimeError("unexpected SELECT secret")

    response = TestClient(app, raise_server_exceptions=False).get("/unknown")

    assert response.status_code == 500
    assert "validation_error" not in response.text
    assert "not_found" not in response.text
    assert "service_unavailable" not in response.text
    assert "unexpected SELECT secret" not in response.text


def test_error_schema_can_generate_openapi_component() -> None:
    app = FastAPI()

    @app.get("/error", response_model=ApiErrorResponse)
    def error_response() -> ApiErrorResponse:
        return ApiErrorResponse.model_validate(
            {
                "error": {
                    "code": "conflict",
                    "message": "Request conflicts with the current resource state",
                    "details": [],
                }
            }
        )

    schema = app.openapi()

    assert "ApiErrorResponse" in schema["components"]["schemas"]
    assert "ApiError" in schema["components"]["schemas"]
    assert "ApiErrorDetail" in schema["components"]["schemas"]
