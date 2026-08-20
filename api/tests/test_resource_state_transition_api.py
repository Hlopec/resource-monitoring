from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from typing import Iterator
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.composition import (
    get_create_resource_handler,
    get_transition_resource_state_handler,
)
from app.api.mappers import resource_state_transitioned_response
from app.api.schemas import (
    ResourceStateTransitionedResponse,
    TransitionResourceStateRequest,
)
from app.application.commands import (
    CreateResourceCommand,
    TransitionResourceStateCommand,
)
from app.application.errors import (
    ConcurrentModificationError,
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
    ValidationError,
    ValidationFailure,
)
from app.application.results import (
    ResourceCreatedResult,
    ResourceStateTransitionedResult,
)
from app.main import app


class RecordingTransitionResourceStateHandler:
    def __init__(self, result: ResourceStateTransitionedResult) -> None:
        self.result = result
        self.commands: list[TransitionResourceStateCommand] = []

    def handle(
        self,
        command: TransitionResourceStateCommand,
    ) -> ResourceStateTransitionedResult:
        self.commands.append(command)
        return self.result


class RaisingTransitionResourceStateHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.commands: list[TransitionResourceStateCommand] = []

    def handle(
        self,
        command: TransitionResourceStateCommand,
    ) -> ResourceStateTransitionedResult:
        self.commands.append(command)
        raise self.exc


class RecordingCreateResourceHandler:
    def __init__(self, result: ResourceCreatedResult) -> None:
        self.result = result
        self.commands: list[CreateResourceCommand] = []

    def handle(self, command: CreateResourceCommand) -> ResourceCreatedResult:
        self.commands.append(command)
        return self.result


@contextmanager
def _client_with_transition_override(handler: object) -> Iterator[TestClient]:
    sentinel = object()
    previous = app.dependency_overrides.get(
        get_transition_resource_state_handler,
        sentinel,
    )
    app.dependency_overrides[get_transition_resource_state_handler] = lambda: handler
    try:
        yield TestClient(app)
    finally:
        if previous is sentinel:
            app.dependency_overrides.pop(get_transition_resource_state_handler, None)
        else:
            app.dependency_overrides[get_transition_resource_state_handler] = previous


@contextmanager
def _client_with_create_override(handler: object) -> Iterator[TestClient]:
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


def _transitioned_result(
    *,
    resource_id: UUID,
    previous_state_id: UUID | None = UUID(
        "0198a4a2-0000-7000-8000-000000000201"
    ),
    new_state_id: UUID = UUID("0198a4a2-0000-7000-8000-000000000202"),
    transitioned_at: datetime = datetime.fromisoformat(
        "2026-08-20T10:30:00+00:00"
    ),
) -> ResourceStateTransitionedResult:
    return ResourceStateTransitionedResult(
        resource_id=resource_id,
        previous_state_id=previous_state_id,
        new_state_id=new_state_id,
        transitioned_at=transitioned_at,
    )


def _request_payload() -> dict[str, object]:
    return {
        "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000101",
        "criticality_id": "0198a4a2-0000-7000-8000-000000000102",
        "exposure_level_id": "0198a4a2-0000-7000-8000-000000000103",
        "source_priority": 11,
        "confidence_score": "0.8750",
        "transitioned_at": "2026-08-20T10:30:00+00:00",
        "source": "cmdb",
    }


def _post_transition(
    client: TestClient,
    tenant_id: UUID | str,
    resource_id: UUID | str,
    payload: dict[str, object] | None = None,
) -> object:
    return client.post(
        f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
        json=_request_payload() if payload is None else payload,
    )


def test_exact_state_transition_endpoint_exists() -> None:
    operations = {
        (method, route.path)
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/tenants/")
        for method in route.methods
    }

    assert (
        "POST",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
    ) in operations
    assert (
        "PATCH",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}",
    ) not in operations
    assert (
        "PUT",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}",
    ) not in operations


def test_successful_transition_maps_exact_command_and_returns_200() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    previous_state_id = uuid4()
    new_state_id = uuid4()
    transitioned_at = datetime.fromisoformat("2026-08-20T11:30:00+03:00")
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(
            resource_id=resource_id,
            previous_state_id=previous_state_id,
            new_state_id=new_state_id,
            transitioned_at=transitioned_at,
        )
    )
    payload = {
        "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000111",
        "criticality_id": "0198a4a2-0000-7000-8000-000000000112",
        "exposure_level_id": "0198a4a2-0000-7000-8000-000000000113",
        "source_priority": 19,
        "confidence_score": "0.9750",
        "transitioned_at": "2026-08-20T11:30:00+03:00",
        "source": "scanner",
    }

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id, payload)

    assert response.status_code == 200
    assert response.json() == {
        "resource_id": str(resource_id),
        "previous_state_id": str(previous_state_id),
        "new_state_id": str(new_state_id),
        "transitioned_at": "2026-08-20T11:30:00+03:00",
    }
    assert handler.commands == [
        TransitionResourceStateCommand(
            tenant_id=tenant_id,
            resource_id=resource_id,
            lifecycle_status_id=UUID(str(payload["lifecycle_status_id"])),
            criticality_id=UUID(str(payload["criticality_id"])),
            exposure_level_id=UUID(str(payload["exposure_level_id"])),
            source_priority=19,
            confidence_score=Decimal("0.9750"),
            transitioned_at=transitioned_at,
            source="scanner",
        )
    ]


def test_request_schema_has_no_body_tenant_or_resource_ids() -> None:
    assert "tenant_id" not in TransitionResourceStateRequest.model_fields
    assert "resource_id" not in TransitionResourceStateRequest.model_fields


def test_body_tenant_and_resource_ids_cannot_override_path_ids() -> None:
    path_tenant_id = uuid4()
    path_resource_id = uuid4()
    body_tenant_id = uuid4()
    body_resource_id = uuid4()
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=path_resource_id)
    )
    payload = {
        **_request_payload(),
        "tenant_id": str(body_tenant_id),
        "resource_id": str(body_resource_id),
    }

    with _client_with_transition_override(handler) as client:
        response = _post_transition(
            client,
            path_tenant_id,
            path_resource_id,
            payload,
        )

    assert response.status_code == 200
    assert handler.commands[0].tenant_id == path_tenant_id
    assert handler.commands[0].tenant_id != body_tenant_id
    assert handler.commands[0].resource_id == path_resource_id
    assert handler.commands[0].resource_id != body_resource_id


def test_confidence_score_preserves_decimal_precision_from_json_string() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    precision_sensitive = "0.123456789123456789123456789"
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=resource_id)
    )
    payload = {**_request_payload(), "confidence_score": precision_sensitive}

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id, payload)

    assert response.status_code == 200
    assert handler.commands[0].confidence_score == Decimal(precision_sensitive)
    assert not isinstance(handler.commands[0].confidence_score, float)


def test_aware_utc_datetime_reaches_command_unchanged() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=resource_id)
    )
    payload = {**_request_payload(), "transitioned_at": "2026-08-20T05:10:11+00:00"}

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id, payload)

    assert response.status_code == 200
    assert handler.commands[0].transitioned_at == datetime.fromisoformat(
        "2026-08-20T05:10:11+00:00"
    )


def test_aware_non_utc_datetime_reaches_command_without_offset_normalization() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=resource_id)
    )
    payload = {**_request_payload(), "transitioned_at": "2026-08-20T08:10:11+03:00"}

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id, payload)

    assert response.status_code == 200
    assert handler.commands[0].transitioned_at == datetime.fromisoformat(
        "2026-08-20T08:10:11+03:00"
    )


def test_naive_datetime_is_transport_validation_error_and_handler_is_not_called() -> None:
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=uuid4())
    )
    payload = {**_request_payload(), "transitioned_at": "2026-08-20T05:10:11"}

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_tenant_uuid_is_transport_validation_error() -> None:
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=uuid4())
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, "not-a-uuid", uuid4())

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_resource_uuid_is_transport_validation_error() -> None:
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=uuid4())
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), "not-a-uuid")

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_body_uuid_is_transport_validation_error() -> None:
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=uuid4())
    )
    payload = {**_request_payload(), "lifecycle_status_id": "not-a-uuid"}

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_missing_required_body_field_is_transport_validation_error() -> None:
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=uuid4())
    )
    payload = _request_payload()
    payload.pop("criticality_id")

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_omitted_source_maps_to_none() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=resource_id)
    )
    payload = _request_payload()
    payload.pop("source")

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id, payload)

    assert response.status_code == 200
    assert handler.commands[0].source is None


def test_explicit_empty_source_is_preserved() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=resource_id)
    )
    payload = {**_request_payload(), "source": ""}

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id, payload)

    assert response.status_code == 200
    assert handler.commands[0].source == ""


def test_response_mapping_preserves_null_previous_state() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    new_state_id = uuid4()
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(
            resource_id=resource_id,
            previous_state_id=None,
            new_state_id=new_state_id,
        )
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id)

    assert response.status_code == 200
    assert response.json()["resource_id"] == str(resource_id)
    assert response.json()["previous_state_id"] is None
    assert response.json()["new_state_id"] == str(new_state_id)


def test_state_transitioned_schema_and_mapper_match_application_result() -> None:
    resource_id = uuid4()
    previous_state_id = uuid4()
    new_state_id = uuid4()
    transitioned_at = datetime.fromisoformat("2026-08-20T10:30:00+00:00")
    result = _transitioned_result(
        resource_id=resource_id,
        previous_state_id=previous_state_id,
        new_state_id=new_state_id,
        transitioned_at=transitioned_at,
    )

    response = resource_state_transitioned_response(result)

    assert list(ResourceStateTransitionedResponse.model_fields) == [
        field.name for field in fields(ResourceStateTransitionedResult)
    ]
    assert response == ResourceStateTransitionedResponse(
        resource_id=resource_id,
        previous_state_id=previous_state_id,
        new_state_id=new_state_id,
        transitioned_at=transitioned_at,
    )


def test_application_validation_error_uses_centralized_response() -> None:
    handler = RaisingTransitionResourceStateHandler(
        ValidationError(
            "invalid transition",
            failures=(ValidationFailure("transitioned_at", "must be ordered"),),
        )
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"] == [
        {"field": "transitioned_at", "message": "must be ordered"}
    ]


def test_entity_not_found_error_uses_centralized_non_disclosing_response() -> None:
    handler = RaisingTransitionResourceStateHandler(EntityNotFoundError("missing"))

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "missing" not in response.text


def test_tenant_boundary_error_matches_not_found_envelope() -> None:
    missing_handler = RaisingTransitionResourceStateHandler(
        EntityNotFoundError("missing")
    )
    boundary_handler = RaisingTransitionResourceStateHandler(
        TenantBoundaryError("other tenant")
    )

    with _client_with_transition_override(missing_handler) as client:
        missing_response = _post_transition(client, uuid4(), uuid4())
    with _client_with_transition_override(boundary_handler) as client:
        boundary_response = _post_transition(client, uuid4(), uuid4())

    assert missing_response.status_code == 404
    assert boundary_response.status_code == 404
    assert boundary_response.json() == missing_response.json()


def test_conflict_error_uses_centralized_response() -> None:
    handler = RaisingTransitionResourceStateHandler(
        ConflictError("state conflict", constraint="resource_state_current_key")
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "resource_state_current_key" not in response.text


def test_concurrent_modification_error_uses_specific_centralized_response() -> None:
    handler = RaisingTransitionResourceStateHandler(
        ConcurrentModificationError("state changed")
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "concurrent_modification"
    assert "state changed" not in response.text


def test_persistence_error_uses_centralized_sanitized_response() -> None:
    handler = RaisingTransitionResourceStateHandler(
        PersistenceError("postgres UPDATE secret SQLSTATE 40001")
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, uuid4(), uuid4())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "postgres" not in response.text
    assert "UPDATE" not in response.text
    assert "SQLSTATE" not in response.text


def test_post_succeeds_with_only_transition_handler_override() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingTransitionResourceStateHandler(
        _transitioned_result(resource_id=resource_id)
    )

    with _client_with_transition_override(handler) as client:
        response = _post_transition(client, tenant_id, resource_id)

    assert response.status_code == 200
    assert len(handler.commands) == 1


def test_resource_create_route_still_works_with_own_override() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingCreateResourceHandler(
        ResourceCreatedResult(
            resource_id=resource_id,
            tenant_id=tenant_id,
            canonical_name="created.example.com",
            record_version=1,
        )
    )

    with _client_with_create_override(handler) as client:
        response = client.post(
            f"/api/v1/tenants/{tenant_id}/resources",
            json={
                "resource_type_id": "0198a4a2-0000-7000-8000-000000000101",
                "canonical_name": "created.example.com",
                "display_name": "Created",
                "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000102",
                "criticality_id": "0198a4a2-0000-7000-8000-000000000103",
                "exposure_level_id": "0198a4a2-0000-7000-8000-000000000104",
                "source_priority": 7,
                "confidence_score": "0.8750",
                "first_seen_at": "2026-08-20T10:00:00+00:00",
                "last_seen_at": "2026-08-20T10:05:00+00:00",
            },
        )

    assert response.status_code == 201
    assert response.json()["resource_id"] == str(resource_id)
    assert len(handler.commands) == 1


def test_existing_resource_and_system_route_inventory_remains_available() -> None:
    operations = {
        (method, route.path)
        for route in app.routes
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }

    assert ("GET", "/") in operations
    assert ("GET", "/health") in operations
    assert ("GET", "/api/v1/tenants/{tenant_id}/resources") in operations
    assert ("POST", "/api/v1/tenants/{tenant_id}/resources") in operations
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
    assert (
        "POST",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
    ) in operations
