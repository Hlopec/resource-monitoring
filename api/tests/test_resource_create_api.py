from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from typing import Iterator
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.composition import get_create_resource_handler
from app.api.mappers import resource_created_response
from app.api.schemas import CreateResourceRequest, ResourceCreatedResponse
from app.application.commands import CreateResourceCommand
from app.application.errors import (
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    ValidationError,
    ValidationFailure,
)
from app.application.results import ResourceCreatedResult
from app.main import app


class RecordingCreateResourceHandler:
    def __init__(self, result: ResourceCreatedResult) -> None:
        self.result = result
        self.commands: list[CreateResourceCommand] = []

    def handle(self, command: CreateResourceCommand) -> ResourceCreatedResult:
        self.commands.append(command)
        return self.result


class RaisingCreateResourceHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.commands: list[CreateResourceCommand] = []

    def handle(self, command: CreateResourceCommand) -> ResourceCreatedResult:
        self.commands.append(command)
        raise self.exc


@contextmanager
def _client_with_override(handler: object) -> Iterator[TestClient]:
    sentinel = object()
    previous = app.dependency_overrides.get(get_create_resource_handler, sentinel)
    app.dependency_overrides[get_create_resource_handler] = lambda: handler
    try:
        yield TestClient(app)
    finally:
        if previous is sentinel:
            app.dependency_overrides.pop(get_create_resource_handler, None)
        else:
            app.dependency_overrides[get_create_resource_handler] = previous


def _created_result(
    *,
    resource_id: UUID,
    tenant_id: UUID,
    canonical_name: str = "app01.example.com",
    record_version: int = 1,
) -> ResourceCreatedResult:
    return ResourceCreatedResult(
        resource_id=resource_id,
        tenant_id=tenant_id,
        canonical_name=canonical_name,
        record_version=record_version,
    )


def _request_payload() -> dict[str, object]:
    return {
        "resource_type_id": "0198a4a2-0000-7000-8000-000000000101",
        "canonical_name": "app01.example.com",
        "display_name": "Application 01",
        "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000102",
        "criticality_id": "0198a4a2-0000-7000-8000-000000000103",
        "exposure_level_id": "0198a4a2-0000-7000-8000-000000000104",
        "source_priority": 7,
        "confidence_score": "0.8750",
        "first_seen_at": "2026-08-19T12:00:00+00:00",
        "last_seen_at": "2026-08-19T15:30:00+03:00",
    }


def _post_resource(
    client: TestClient,
    tenant_id: UUID | str,
    payload: dict[str, object] | None = None,
) -> object:
    return client.post(
        f"/api/v1/tenants/{tenant_id}/resources",
        json=_request_payload() if payload is None else payload,
    )


def test_exact_collection_path_exposes_get_and_post_methods_only() -> None:
    operations = {
        (method, route.path)
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/tenants/")
        for method in route.methods
    }

    assert ("GET", "/api/v1/tenants/{tenant_id}/resources") in operations
    assert ("POST", "/api/v1/tenants/{tenant_id}/resources") in operations
    assert ("PATCH", "/api/v1/tenants/{tenant_id}/resources") not in operations
    assert ("PUT", "/api/v1/tenants/{tenant_id}/resources") not in operations
    assert ("DELETE", "/api/v1/tenants/{tenant_id}/resources") not in operations


def test_successful_create_maps_exact_command_and_returns_201() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=resource_id, tenant_id=tenant_id)
    )
    payload = _request_payload()

    with _client_with_override(handler) as client:
        response = _post_resource(client, tenant_id, payload)

    assert response.status_code == 201
    assert response.json() == {
        "resource_id": str(resource_id),
        "tenant_id": str(tenant_id),
        "canonical_name": "app01.example.com",
        "record_version": 1,
    }
    assert handler.commands == [
        CreateResourceCommand(
            tenant_id=tenant_id,
            resource_type_id=UUID(str(payload["resource_type_id"])),
            canonical_name="app01.example.com",
            display_name="Application 01",
            lifecycle_status_id=UUID(str(payload["lifecycle_status_id"])),
            criticality_id=UUID(str(payload["criticality_id"])),
            exposure_level_id=UUID(str(payload["exposure_level_id"])),
            source_priority=7,
            confidence_score=Decimal("0.8750"),
            first_seen_at=datetime.fromisoformat("2026-08-19T12:00:00+00:00"),
            last_seen_at=datetime.fromisoformat("2026-08-19T15:30:00+03:00"),
        )
    ]


def test_create_request_schema_has_no_body_tenant() -> None:
    assert "tenant_id" not in CreateResourceRequest.model_fields


def test_body_tenant_is_not_authoritative_when_extras_are_ignored() -> None:
    path_tenant_id = uuid4()
    body_tenant_id = uuid4()
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=path_tenant_id)
    )
    payload = {**_request_payload(), "tenant_id": str(body_tenant_id)}

    with _client_with_override(handler) as client:
        response = _post_resource(client, path_tenant_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].tenant_id == path_tenant_id
    assert handler.commands[0].tenant_id != body_tenant_id


def test_confidence_score_preserves_decimal_precision_from_json_string() -> None:
    tenant_id = uuid4()
    precision_sensitive = "0.123456789123456789123456789"
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=tenant_id)
    )
    payload = {**_request_payload(), "confidence_score": precision_sensitive}

    with _client_with_override(handler) as client:
        response = _post_resource(client, tenant_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].confidence_score == Decimal(precision_sensitive)
    assert not isinstance(handler.commands[0].confidence_score, float)


def test_aware_datetime_values_reach_command_without_offset_normalization() -> None:
    tenant_id = uuid4()
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=tenant_id)
    )
    payload = {
        **_request_payload(),
        "first_seen_at": "2026-08-19T05:10:11+00:00",
        "last_seen_at": "2026-08-19T08:10:11+03:00",
    }

    with _client_with_override(handler) as client:
        response = _post_resource(client, tenant_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].first_seen_at == datetime.fromisoformat(
        "2026-08-19T05:10:11+00:00"
    )
    assert handler.commands[0].last_seen_at == datetime.fromisoformat(
        "2026-08-19T08:10:11+03:00"
    )


def test_naive_datetime_is_transport_validation_error_and_handler_is_not_called() -> None:
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=uuid4())
    )
    payload = {**_request_payload(), "first_seen_at": "2026-08-19T05:10:11"}

    with _client_with_override(handler) as client:
        response = _post_resource(client, uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_path_uuid_is_transport_validation_error() -> None:
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=uuid4())
    )

    with _client_with_override(handler) as client:
        response = _post_resource(client, "not-a-uuid")

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_body_uuid_is_transport_validation_error() -> None:
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=uuid4())
    )
    payload = {**_request_payload(), "resource_type_id": "not-a-uuid"}

    with _client_with_override(handler) as client:
        response = _post_resource(client, uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_missing_required_body_field_is_transport_validation_error() -> None:
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=uuid4())
    )
    payload = _request_payload()
    payload.pop("canonical_name")

    with _client_with_override(handler) as client:
        response = _post_resource(client, uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_resource_created_schema_and_mapper_match_application_result() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    result = _created_result(
        resource_id=resource_id,
        tenant_id=tenant_id,
        canonical_name="created.example.com",
        record_version=3,
    )

    response = resource_created_response(result)

    assert list(ResourceCreatedResponse.model_fields) == [
        field.name for field in fields(ResourceCreatedResult)
    ]
    assert response == ResourceCreatedResponse(
        resource_id=resource_id,
        tenant_id=tenant_id,
        canonical_name="created.example.com",
        record_version=3,
    )


def test_application_validation_error_uses_centralized_response() -> None:
    handler = RaisingCreateResourceHandler(
        ValidationError(
            "invalid resource",
            failures=(ValidationFailure("canonical_name", "must be unique"),),
        )
    )

    with _client_with_override(handler) as client:
        response = _post_resource(client, uuid4())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"] == [
        {"field": "canonical_name", "message": "must be unique"}
    ]


def test_entity_not_found_error_uses_centralized_non_disclosing_response() -> None:
    handler = RaisingCreateResourceHandler(EntityNotFoundError("type missing"))

    with _client_with_override(handler) as client:
        response = _post_resource(client, uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "type missing" not in response.text


def test_conflict_error_uses_centralized_response() -> None:
    handler = RaisingCreateResourceHandler(
        ConflictError("duplicate canonical name", constraint="resource_name_key")
    )

    with _client_with_override(handler) as client:
        response = _post_resource(client, uuid4())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "resource_name_key" not in response.text


def test_persistence_error_uses_centralized_sanitized_response() -> None:
    handler = RaisingCreateResourceHandler(
        PersistenceError("postgres INSERT secret SQLSTATE 23505")
    )

    with _client_with_override(handler) as client:
        response = _post_resource(client, uuid4())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "postgres" not in response.text
    assert "INSERT" not in response.text
    assert "SQLSTATE" not in response.text


def test_post_succeeds_with_only_create_handler_override() -> None:
    tenant_id = uuid4()
    handler = RecordingCreateResourceHandler(
        _created_result(resource_id=uuid4(), tenant_id=tenant_id)
    )

    with _client_with_override(handler) as client:
        response = _post_resource(client, tenant_id)

    assert response.status_code == 201
    assert len(handler.commands) == 1


def test_existing_read_and_system_route_inventory_remains_available() -> None:
    operations = {
        (method, route.path)
        for route in app.routes
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }

    assert ("GET", "/") in operations
    assert ("GET", "/health") in operations
    assert ("GET", "/api/v1/tenants/{tenant_id}/resources") in operations
    assert ("GET", "/api/v1/tenants/{tenant_id}/resources/{resource_id}") in operations
    assert (
        "GET",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/history",
    ) in operations
    assert (
        "GET",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships",
    ) in operations
    assert (
        "GET",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical",
    ) in operations
    assert (
        "GET",
        "/api/v1/tenants/{tenant_id}/resource-lookups/canonical-name",
    ) in operations
    assert (
        "GET",
        "/api/v1/tenants/{tenant_id}/resource-lookups/identifier",
    ) in operations
    assert (
        "GET",
        "/api/v1/tenants/{tenant_id}/resource-lookups/alias",
    ) in operations
