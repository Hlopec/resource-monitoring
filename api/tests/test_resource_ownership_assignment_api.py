from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from typing import Iterator
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.composition import (
    get_assign_resource_identifier_handler,
    get_assign_resource_ownership_handler,
    get_create_resource_handler,
    get_transition_resource_state_handler,
)
from app.api.mappers import resource_ownership_assigned_response
from app.api.schemas import (
    AssignResourceOwnershipRequest,
    ResourceOwnershipAssignedResponse,
)
from app.application.commands import (
    AssignResourceIdentifierCommand,
    AssignResourceOwnershipCommand,
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
    ResourceIdentifierAssignedResult,
    ResourceOwnershipAssignedResult,
    ResourceStateTransitionedResult,
)
from app.main import app


class RecordingAssignResourceOwnershipHandler:
    def __init__(
        self,
        result: ResourceOwnershipAssignedResult,
    ) -> None:
        self.result = result
        self.commands: list[AssignResourceOwnershipCommand] = []

    def handle(
        self,
        command: AssignResourceOwnershipCommand,
    ) -> ResourceOwnershipAssignedResult:
        self.commands.append(command)
        return self.result


class RaisingAssignResourceOwnershipHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.commands: list[AssignResourceOwnershipCommand] = []

    def handle(
        self,
        command: AssignResourceOwnershipCommand,
    ) -> ResourceOwnershipAssignedResult:
        self.commands.append(command)
        raise self.exc


class RecordingCreateResourceHandler:
    def __init__(self, result: ResourceCreatedResult) -> None:
        self.result = result
        self.commands: list[CreateResourceCommand] = []

    def handle(self, command: CreateResourceCommand) -> ResourceCreatedResult:
        self.commands.append(command)
        return self.result


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


class RecordingAssignResourceIdentifierHandler:
    def __init__(self, result: ResourceIdentifierAssignedResult) -> None:
        self.result = result
        self.commands: list[AssignResourceIdentifierCommand] = []

    def handle(
        self,
        command: AssignResourceIdentifierCommand,
    ) -> ResourceIdentifierAssignedResult:
        self.commands.append(command)
        return self.result


@contextmanager
def _client_with_ownership_override(handler: object) -> Iterator[TestClient]:
    sentinel = object()
    previous = app.dependency_overrides.get(
        get_assign_resource_ownership_handler,
        sentinel,
    )
    app.dependency_overrides[get_assign_resource_ownership_handler] = lambda: handler
    try:
        yield TestClient(app)
    finally:
        if previous is sentinel:
            app.dependency_overrides.pop(get_assign_resource_ownership_handler, None)
        else:
            app.dependency_overrides[get_assign_resource_ownership_handler] = previous


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
def _client_with_identifier_override(handler: object) -> Iterator[TestClient]:
    sentinel = object()
    previous = app.dependency_overrides.get(
        get_assign_resource_identifier_handler,
        sentinel,
    )
    app.dependency_overrides[get_assign_resource_identifier_handler] = lambda: handler
    try:
        yield TestClient(app)
    finally:
        if previous is sentinel:
            app.dependency_overrides.pop(get_assign_resource_identifier_handler, None)
        else:
            app.dependency_overrides[get_assign_resource_identifier_handler] = previous


def _assigned_result(
    *,
    resource_id: UUID,
    ownership_id: UUID = UUID("0198a4a2-0000-7000-8000-000000000401"),
    organization_id: UUID = UUID("0198a4a2-0000-7000-8000-000000000402"),
    ownership_role_id: UUID = UUID("0198a4a2-0000-7000-8000-000000000403"),
    is_primary: bool = True,
    valid_from: datetime = datetime.fromisoformat("2026-08-20T10:30:00+00:00"),
    source: str | None = "cmdb",
) -> ResourceOwnershipAssignedResult:
    return ResourceOwnershipAssignedResult(
        resource_id=resource_id,
        ownership_id=ownership_id,
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        is_primary=is_primary,
        valid_from=valid_from,
        source=source,
    )


def _request_payload() -> dict[str, object]:
    return {
        "organization_id": "0198a4a2-0000-7000-8000-000000000402",
        "ownership_role_id": "0198a4a2-0000-7000-8000-000000000403",
        "is_primary": True,
        "confidence_score": "0.8750",
        "valid_from": "2026-08-20T10:30:00+00:00",
        "source": "cmdb",
    }


def _post_ownership(
    client: TestClient,
    tenant_id: UUID | str,
    resource_id: UUID | str,
    payload: dict[str, object] | None = None,
) -> object:
    return client.post(
        f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/ownership",
        json=_request_payload() if payload is None else payload,
    )


def test_exact_ownership_assignment_endpoint_exists() -> None:
    operations = {
        (method, route.path)
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/tenants/")
        for method in route.methods
    }

    assert (
        "POST",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/ownership",
    ) in operations
    assert (
        "PATCH",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/ownership",
    ) not in operations


def test_successful_assignment_maps_exact_command_and_returns_201() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    ownership_id = uuid4()
    organization_id = uuid4()
    ownership_role_id = uuid4()
    valid_from = datetime.fromisoformat("2026-08-20T11:30:00+03:00")
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(
            resource_id=resource_id,
            ownership_id=ownership_id,
            organization_id=organization_id,
            ownership_role_id=ownership_role_id,
            is_primary=False,
            valid_from=valid_from,
            source=" scanner ",
        )
    )
    payload = {
        "organization_id": str(organization_id),
        "ownership_role_id": str(ownership_role_id),
        "is_primary": False,
        "confidence_score": "0.9750",
        "valid_from": "2026-08-20T11:30:00+03:00",
        "source": " scanner ",
    }

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id, payload)

    assert response.status_code == 201
    assert response.json() == {
        "resource_id": str(resource_id),
        "ownership_id": str(ownership_id),
        "organization_id": str(organization_id),
        "ownership_role_id": str(ownership_role_id),
        "is_primary": False,
        "valid_from": "2026-08-20T11:30:00+03:00",
        "source": " scanner ",
    }
    assert handler.commands == [
        AssignResourceOwnershipCommand(
            tenant_id=tenant_id,
            resource_id=resource_id,
            organization_id=organization_id,
            ownership_role_id=ownership_role_id,
            is_primary=False,
            confidence_score=Decimal("0.9750"),
            valid_from=valid_from,
            source=" scanner ",
        )
    ]


def test_request_schema_has_no_body_tenant_or_resource_ids() -> None:
    assert "tenant_id" not in AssignResourceOwnershipRequest.model_fields
    assert "resource_id" not in AssignResourceOwnershipRequest.model_fields


def test_body_tenant_and_resource_ids_cannot_override_path_ids() -> None:
    path_tenant_id = uuid4()
    path_resource_id = uuid4()
    body_tenant_id = uuid4()
    body_resource_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=path_resource_id)
    )
    payload = {
        **_request_payload(),
        "tenant_id": str(body_tenant_id),
        "resource_id": str(body_resource_id),
    }

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(
            client,
            path_tenant_id,
            path_resource_id,
            payload,
        )

    assert response.status_code == 201
    assert handler.commands[0].tenant_id == path_tenant_id
    assert handler.commands[0].tenant_id != body_tenant_id
    assert handler.commands[0].resource_id == path_resource_id
    assert handler.commands[0].resource_id != body_resource_id


def test_organization_and_role_ids_are_preserved_without_api_resolution() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    organization_id = uuid4()
    ownership_role_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(
            resource_id=resource_id,
            organization_id=organization_id,
            ownership_role_id=ownership_role_id,
        )
    )
    payload = {
        **_request_payload(),
        "organization_id": str(organization_id),
        "ownership_role_id": str(ownership_role_id),
    }

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].organization_id == organization_id
    assert handler.commands[0].ownership_role_id == ownership_role_id


def test_is_primary_maps_false_and_true_exactly() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()

    for is_primary in [False, True]:
        handler = RecordingAssignResourceOwnershipHandler(
            _assigned_result(resource_id=resource_id, is_primary=is_primary)
        )
        payload = {**_request_payload(), "is_primary": is_primary}

        with _client_with_ownership_override(handler) as client:
            response = _post_ownership(client, tenant_id, resource_id, payload)

        assert response.status_code == 201
        assert handler.commands[0].is_primary is is_primary


def test_confidence_score_preserves_decimal_precision_from_json_string() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    precision_sensitive = "0.123456789123456789123456789"
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=resource_id)
    )
    payload = {**_request_payload(), "confidence_score": precision_sensitive}

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].confidence_score == Decimal(precision_sensitive)
    assert not isinstance(handler.commands[0].confidence_score, float)


def test_aware_utc_valid_from_reaches_command_unchanged() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=resource_id)
    )
    payload = {**_request_payload(), "valid_from": "2026-08-20T05:10:11+00:00"}

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].valid_from == datetime.fromisoformat(
        "2026-08-20T05:10:11+00:00"
    )


def test_aware_non_utc_valid_from_reaches_command_without_offset_normalization() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=resource_id)
    )
    payload = {**_request_payload(), "valid_from": "2026-08-20T08:10:11+03:00"}

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].valid_from == datetime.fromisoformat(
        "2026-08-20T08:10:11+03:00"
    )


def test_naive_valid_from_is_transport_validation_error_and_handler_is_not_called() -> None:
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=uuid4())
    )
    payload = {**_request_payload(), "valid_from": "2026-08-20T05:10:11"}

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_tenant_uuid_is_transport_validation_error() -> None:
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=uuid4())
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, "not-a-uuid", uuid4())

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_resource_uuid_is_transport_validation_error() -> None:
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=uuid4())
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), "not-a-uuid")

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_organization_uuid_is_transport_validation_error() -> None:
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=uuid4())
    )
    payload = {**_request_payload(), "organization_id": "not-a-uuid"}

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_malformed_ownership_role_uuid_is_transport_validation_error() -> None:
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=uuid4())
    )
    payload = {**_request_payload(), "ownership_role_id": "not-a-uuid"}

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_missing_required_body_field_is_transport_validation_error() -> None:
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=uuid4())
    )
    payload = _request_payload()
    payload.pop("organization_id")

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4(), payload)

    assert response.status_code == 422
    assert handler.commands == []


def test_omitted_source_maps_to_none() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=resource_id, source=None)
    )
    payload = _request_payload()
    payload.pop("source")

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].source is None


def test_explicit_empty_source_is_preserved() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=resource_id, source="")
    )
    payload = {**_request_payload(), "source": ""}

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id, payload)

    assert response.status_code == 201
    assert handler.commands[0].source == ""


def test_response_mapping_preserves_null_source() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=resource_id, source=None)
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id)

    assert response.status_code == 201
    assert response.json()["resource_id"] == str(resource_id)
    assert response.json()["source"] is None


def test_ownership_assigned_schema_and_mapper_match_application_result() -> None:
    resource_id = uuid4()
    ownership_id = uuid4()
    organization_id = uuid4()
    ownership_role_id = uuid4()
    valid_from = datetime.fromisoformat("2026-08-20T10:30:00+00:00")
    result = _assigned_result(
        resource_id=resource_id,
        ownership_id=ownership_id,
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        valid_from=valid_from,
    )

    response = resource_ownership_assigned_response(result)

    assert list(ResourceOwnershipAssignedResponse.model_fields) == [
        field.name for field in fields(ResourceOwnershipAssignedResult)
    ]
    assert response == ResourceOwnershipAssignedResponse(
        resource_id=resource_id,
        ownership_id=ownership_id,
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        is_primary=True,
        valid_from=valid_from,
        source="cmdb",
    )


def test_application_validation_error_uses_centralized_response() -> None:
    handler = RaisingAssignResourceOwnershipHandler(
        ValidationError(
            "invalid ownership",
            failures=(ValidationFailure("organization_id", "is not in tenant"),),
        )
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"] == [
        {"field": "organization_id", "message": "is not in tenant"}
    ]


def test_entity_not_found_error_uses_centralized_non_disclosing_response() -> None:
    handler = RaisingAssignResourceOwnershipHandler(EntityNotFoundError("missing"))

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "missing" not in response.text


def test_tenant_boundary_error_matches_not_found_envelope() -> None:
    missing_handler = RaisingAssignResourceOwnershipHandler(
        EntityNotFoundError("missing")
    )
    boundary_handler = RaisingAssignResourceOwnershipHandler(
        TenantBoundaryError("other tenant")
    )

    with _client_with_ownership_override(missing_handler) as client:
        missing_response = _post_ownership(client, uuid4(), uuid4())
    with _client_with_ownership_override(boundary_handler) as client:
        boundary_response = _post_ownership(client, uuid4(), uuid4())

    assert missing_response.status_code == 404
    assert boundary_response.status_code == 404
    assert boundary_response.json() == missing_response.json()


def test_conflict_error_uses_centralized_response() -> None:
    handler = RaisingAssignResourceOwnershipHandler(
        ConflictError("ownership conflict", constraint="resource_ownership_key")
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "resource_ownership_key" not in response.text


def test_concurrent_modification_error_uses_specific_centralized_response() -> None:
    handler = RaisingAssignResourceOwnershipHandler(
        ConcurrentModificationError("ownership changed")
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "concurrent_modification"
    assert "ownership changed" not in response.text


def test_persistence_error_uses_centralized_sanitized_response() -> None:
    handler = RaisingAssignResourceOwnershipHandler(
        PersistenceError("postgres INSERT secret SQLSTATE 23505")
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, uuid4(), uuid4())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "postgres" not in response.text
    assert "INSERT" not in response.text
    assert "SQLSTATE" not in response.text


def test_post_succeeds_with_only_ownership_assignment_handler_override() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingAssignResourceOwnershipHandler(
        _assigned_result(resource_id=resource_id)
    )

    with _client_with_ownership_override(handler) as client:
        response = _post_ownership(client, tenant_id, resource_id)

    assert response.status_code == 201
    assert len(handler.commands) == 1


def test_existing_write_routes_still_work_with_their_own_overrides() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    create_handler = RecordingCreateResourceHandler(
        ResourceCreatedResult(
            resource_id=resource_id,
            tenant_id=tenant_id,
            canonical_name="created.example.com",
            record_version=1,
        )
    )
    transition_handler = RecordingTransitionResourceStateHandler(
        ResourceStateTransitionedResult(
            resource_id=resource_id,
            previous_state_id=None,
            new_state_id=uuid4(),
            transitioned_at=datetime.fromisoformat("2026-08-20T10:30:00+00:00"),
        )
    )
    identifier_handler = RecordingAssignResourceIdentifierHandler(
        ResourceIdentifierAssignedResult(
            resource_id=resource_id,
            identifier_id=uuid4(),
            identifier_type_id=uuid4(),
            original_value=" Example.COM ",
            normalized_value="example.com",
            value_hash="ABCDEF012345",
            namespace="dns",
            is_primary=True,
            valid_from=datetime.fromisoformat("2026-08-20T10:30:00+00:00"),
        )
    )

    with _client_with_create_override(create_handler) as client:
        create_response = client.post(
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
    with _client_with_transition_override(transition_handler) as client:
        transition_response = client.post(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
            json={
                "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000102",
                "criticality_id": "0198a4a2-0000-7000-8000-000000000103",
                "exposure_level_id": "0198a4a2-0000-7000-8000-000000000104",
                "source_priority": 7,
                "confidence_score": "0.8750",
                "transitioned_at": "2026-08-20T10:05:00+00:00",
                "source": "scanner",
            },
        )
    with _client_with_identifier_override(identifier_handler) as client:
        identifier_response = client.post(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/identifiers",
            json={
                "identifier_type_id": "0198a4a2-0000-7000-8000-000000000302",
                "original_value": " Example.COM ",
                "normalized_value": "example.com",
                "value_hash": "ABCDEF012345",
                "namespace": "dns",
                "is_primary": True,
                "confidence_score": "0.8750",
                "valid_from": "2026-08-20T10:30:00+00:00",
            },
        )

    assert create_response.status_code == 201
    assert transition_response.status_code == 200
    assert identifier_response.status_code == 201
    assert len(create_handler.commands) == 1
    assert len(transition_handler.commands) == 1
    assert len(identifier_handler.commands) == 1


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
        "POST",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions",
    ) in operations
    assert (
        "POST",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/identifiers",
    ) in operations
    assert (
        "POST",
        "/api/v1/tenants/{tenant_id}/resources/{resource_id}/ownership",
    ) in operations
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
