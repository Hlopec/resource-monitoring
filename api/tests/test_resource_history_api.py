from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterator
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.composition import (
    get_get_resource_details_handler,
    get_get_resource_history_handler,
    get_list_resources_handler,
)
from app.api.mappers import resource_history_response
from app.api.schemas import (
    ResourceClassificationHistoryResponse,
    ResourceHistoryResponse,
    ResourceIdentifierHistoryResponse,
    ResourceLabelHistoryResponse,
    ResourceOwnershipHistoryResponse,
    ResourceStateHistoryResponse,
)
from app.application.errors import (
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
)
from app.application.queries import (
    DEFAULT_RESOURCE_PAGE_SIZE,
    GetResourceDetailsQuery,
    GetResourceHistoryQuery,
    ListResourcesQuery,
)
from app.application.results import (
    ResourceClassificationHistoryResult,
    ResourceDetailsResult,
    ResourceHistoryResult,
    ResourceIdentifierHistoryResult,
    ResourceLabelHistoryResult,
    ResourceOwnershipHistoryResult,
    ResourcePageResult,
    ResourceStateHistoryResult,
)
from app.main import app


class RecordingHistoryHandler:
    def __init__(self, result: ResourceHistoryResult) -> None:
        self.result = result
        self.queries: list[GetResourceHistoryQuery] = []

    def handle(self, query: GetResourceHistoryQuery) -> ResourceHistoryResult:
        self.queries.append(query)
        return self.result


class RaisingHistoryHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.queries: list[GetResourceHistoryQuery] = []

    def handle(self, query: GetResourceHistoryQuery) -> ResourceHistoryResult:
        self.queries.append(query)
        raise self.exc


class RecordingDetailsHandler:
    def __init__(self, result: ResourceDetailsResult) -> None:
        self.result = result
        self.queries: list[GetResourceDetailsQuery] = []

    def handle(self, query: GetResourceDetailsQuery) -> ResourceDetailsResult:
        self.queries.append(query)
        return self.result


class RecordingListHandler:
    def __init__(self, result: ResourcePageResult) -> None:
        self.result = result
        self.queries: list[ListResourcesQuery] = []

    def handle(self, query: ListResourcesQuery) -> ResourcePageResult:
        self.queries.append(query)
        return self.result


@contextmanager
def _client_with_override(provider: object, handler: object) -> Iterator[TestClient]:
    sentinel = object()
    previous = app.dependency_overrides.get(provider, sentinel)
    app.dependency_overrides[provider] = lambda: handler
    try:
        yield TestClient(app)
    finally:
        if previous is sentinel:
            app.dependency_overrides.pop(provider, None)
        else:
            app.dependency_overrides[provider] = previous


def _dt(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 19, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes)


def _history_result(
    *,
    tenant_id: UUID,
    resource_id: UUID,
) -> ResourceHistoryResult:
    return ResourceHistoryResult(
        id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        canonical_name="app01.example.com",
        display_name="Application 01",
        states=(
            ResourceStateHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000902"),
                lifecycle_status_id=UUID("0198a4a2-0000-7000-8000-000000000102"),
                criticality_id=UUID("0198a4a2-0000-7000-8000-000000000103"),
                exposure_level_id=UUID("0198a4a2-0000-7000-8000-000000000104"),
                source_priority=2,
                confidence_score=Decimal("0.9500"),
                valid_from=_dt(20),
                valid_to=None,
                source="cmdb",
            ),
            ResourceStateHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000101"),
                lifecycle_status_id=UUID("0198a4a2-0000-7000-8000-000000000105"),
                criticality_id=UUID("0198a4a2-0000-7000-8000-000000000106"),
                exposure_level_id=UUID("0198a4a2-0000-7000-8000-000000000107"),
                source_priority=4,
                confidence_score=Decimal("0.875"),
                valid_from=_dt(5),
                valid_to=_dt(10),
                source=None,
            ),
        ),
        ownership=(
            ResourceOwnershipHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000903"),
                organization_id=UUID("0198a4a2-0000-7000-8000-000000000301"),
                ownership_role_id=UUID("0198a4a2-0000-7000-8000-000000000302"),
                is_primary=True,
                confidence_score=Decimal("0.90"),
                valid_from=_dt(19),
                valid_to=None,
                source="inventory",
            ),
            ResourceOwnershipHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000201"),
                organization_id=UUID("0198a4a2-0000-7000-8000-000000000303"),
                ownership_role_id=UUID("0198a4a2-0000-7000-8000-000000000304"),
                is_primary=False,
                confidence_score=Decimal("0.80"),
                valid_from=_dt(4),
                valid_to=_dt(8),
                source=None,
            ),
        ),
        labels=(
            ResourceLabelHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000904"),
                label_id=UUID("0198a4a2-0000-7000-8000-000000000401"),
                valid_from=_dt(18),
                valid_to=None,
                source="manual",
            ),
            ResourceLabelHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000301"),
                label_id=UUID("0198a4a2-0000-7000-8000-000000000402"),
                valid_from=_dt(3),
                valid_to=_dt(7),
                source=None,
            ),
        ),
        classifications=(
            ResourceClassificationHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000905"),
                classification_type_id=UUID("0198a4a2-0000-7000-8000-000000000501"),
                classification_value_id=UUID("0198a4a2-0000-7000-8000-000000000502"),
                is_primary=True,
                confidence_score=Decimal("0.70"),
                valid_from=_dt(17),
                valid_to=None,
                source="policy",
            ),
            ResourceClassificationHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000401"),
                classification_type_id=UUID("0198a4a2-0000-7000-8000-000000000503"),
                classification_value_id=UUID("0198a4a2-0000-7000-8000-000000000504"),
                is_primary=False,
                confidence_score=Decimal("0.60"),
                valid_from=_dt(2),
                valid_to=_dt(6),
                source=None,
            ),
        ),
        identifiers=(
            ResourceIdentifierHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000906"),
                identifier_type_id=UUID("0198a4a2-0000-7000-8000-000000000601"),
                namespace="dns",
                normalized_value="app01.example.com",
                original_value="APP01.EXAMPLE.COM",
                is_primary=True,
                confidence_score=Decimal("1.000"),
                valid_from=_dt(16),
                valid_to=None,
            ),
            ResourceIdentifierHistoryResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000501"),
                identifier_type_id=UUID("0198a4a2-0000-7000-8000-000000000602"),
                namespace=None,
                normalized_value="10.0.0.5",
                original_value="10.0.0.5",
                is_primary=False,
                confidence_score=Decimal("0.5555"),
                valid_from=_dt(1),
                valid_to=_dt(9),
            ),
        ),
    )


def _empty_history_result(
    *,
    tenant_id: UUID,
    resource_id: UUID,
) -> ResourceHistoryResult:
    return ResourceHistoryResult(
        id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        canonical_name="empty.example.com",
        display_name="Empty",
        states=(),
        ownership=(),
        labels=(),
        classifications=(),
        identifiers=(),
    )


def _details_result(*, tenant_id: UUID, resource_id: UUID) -> ResourceDetailsResult:
    return ResourceDetailsResult(
        id=resource_id,
        tenant_id=tenant_id,
        organization_id=None,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        canonical_name="app01.example.com",
        display_name="Application 01",
        record_version=1,
        created_at=_dt(),
        updated_at=_dt(1),
        state=None,
        identifiers=(),
        ownership=(),
        classifications=(),
        labels=(),
        aliases=(),
        outgoing_merge=None,
    )


def _field_names(dataclass_type: type[object]) -> list[str]:
    return [field.name for field in fields(dataclass_type)]


def test_exact_resource_history_route_exists_without_accidental_alternates() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingHistoryHandler(
        _empty_history_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/history"
        )
        no_tenant_scope = client.get(f"/api/v1/resources/{resource_id}/history")
        plural_history = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/histories"
        )

    assert response.status_code == 200
    assert no_tenant_scope.status_code == 404
    assert plural_history.status_code == 404


def test_history_query_mapping_uses_exact_path_tenant_and_resource_ids() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    query_tenant_id = uuid4()
    handler = RecordingHistoryHandler(
        _empty_history_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/history",
            params={"tenant_id": str(query_tenant_id), "resource_id": str(uuid4())},
        )

    assert response.status_code == 200
    assert handler.queries == [
        GetResourceHistoryQuery(tenant_id=tenant_id, resource_id=resource_id)
    ]


def test_malformed_history_tenant_uuid_is_transport_validation_error() -> None:
    response = TestClient(app).get(
        f"/api/v1/tenants/not-a-uuid/resources/{uuid4()}/history"
    )

    assert response.status_code == 422
    assert "validation_error" not in response.text


def test_malformed_history_resource_uuid_is_transport_validation_error() -> None:
    response = TestClient(app).get(
        f"/api/v1/tenants/{uuid4()}/resources/not-a-uuid/history"
    )

    assert response.status_code == 422
    assert "validation_error" not in response.text


def test_history_dependency_override_uses_fake_handler_without_database_access() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingHistoryHandler(
        _empty_history_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/history"
        )

    assert response.status_code == 200
    assert len(handler.queries) == 1


def test_history_response_schema_exactly_matches_resource_history_result() -> None:
    assert list(ResourceHistoryResponse.model_fields) == _field_names(
        ResourceHistoryResult
    )
    assert list(ResourceStateHistoryResponse.model_fields) == _field_names(
        ResourceStateHistoryResult
    )
    assert list(ResourceOwnershipHistoryResponse.model_fields) == _field_names(
        ResourceOwnershipHistoryResult
    )
    assert list(ResourceLabelHistoryResponse.model_fields) == _field_names(
        ResourceLabelHistoryResult
    )
    assert list(ResourceClassificationHistoryResponse.model_fields) == _field_names(
        ResourceClassificationHistoryResult
    )
    assert list(ResourceIdentifierHistoryResponse.model_fields) == _field_names(
        ResourceIdentifierHistoryResult
    )


def test_complete_history_response_preserves_order_and_serializes_scalars() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    result = _history_result(tenant_id=tenant_id, resource_id=resource_id)
    handler = RecordingHistoryHandler(result)

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/history"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(resource_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["resource_type_id"] == str(result.resource_type_id)
    assert payload["canonical_name"] == "app01.example.com"
    assert payload["display_name"] == "Application 01"
    assert [item["id"] for item in payload["states"]] == [
        str(item.id) for item in result.states
    ]
    assert [item["id"] for item in payload["ownership"]] == [
        str(item.id) for item in result.ownership
    ]
    assert [item["id"] for item in payload["labels"]] == [
        str(item.id) for item in result.labels
    ]
    assert [item["id"] for item in payload["classifications"]] == [
        str(item.id) for item in result.classifications
    ]
    assert [item["id"] for item in payload["identifiers"]] == [
        str(item.id) for item in result.identifiers
    ]
    assert payload["states"][0]["valid_from"] == "2026-08-19T12:20:00Z"
    assert payload["states"][0]["valid_to"] is None
    assert payload["states"][0]["confidence_score"] == "0.9500"
    assert payload["identifiers"][0]["confidence_score"] == "1.000"
    assert payload["identifiers"][1]["namespace"] is None
    assert payload["ownership"][1]["source"] is None
    assert payload["classifications"][1]["source"] is None
    assert payload["labels"][1]["source"] is None


def test_empty_history_returns_200_with_exact_empty_shape() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingHistoryHandler(
        _empty_history_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/history"
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(resource_id),
        "tenant_id": str(tenant_id),
        "resource_type_id": "0198a4a2-0000-7000-8000-000000000003",
        "canonical_name": "empty.example.com",
        "display_name": "Empty",
        "states": [],
        "ownership": [],
        "labels": [],
        "classifications": [],
        "identifiers": [],
    }


def test_history_mapper_returns_api_schema_without_model_validate_shortcut() -> None:
    result = _history_result(tenant_id=uuid4(), resource_id=uuid4())

    response = resource_history_response(result)

    assert isinstance(response, ResourceHistoryResponse)
    assert response.states[0].id == result.states[0].id
    assert response.identifiers[1].id == result.identifiers[1].id


def test_history_not_found_uses_centralized_non_disclosing_404() -> None:
    handler = RaisingHistoryHandler(
        EntityNotFoundError(
            "Resource not found",
            entity_type="Resource",
            lookup_field="resource_id",
            lookup_value=uuid4(),
        )
    )

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}/history"
        )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Requested resource was not found",
            "details": [],
        }
    }


def test_history_tenant_boundary_uses_same_envelope_as_not_found() -> None:
    handler = RaisingHistoryHandler(TenantBoundaryError("other tenant has it"))

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}/history"
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "other tenant" not in response.text


def test_history_persistence_error_uses_sanitized_503() -> None:
    handler = RaisingHistoryHandler(PersistenceError("postgres SQLSTATE SELECT secret"))

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}/history"
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "postgres" not in response.text
    assert "SQLSTATE" not in response.text
    assert "SELECT" not in response.text


def test_history_endpoint_has_no_details_or_canonical_dependency_coupling() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingHistoryHandler(
        _history_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_history_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/history"
        )

    assert response.status_code == 200
    assert handler.queries == [
        GetResourceHistoryQuery(tenant_id=tenant_id, resource_id=resource_id)
    ]


def test_existing_resource_list_details_and_system_routes_remain_functional() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    list_handler = RecordingListHandler(
        ResourcePageResult(
            items=(),
            next_cursor=None,
            page_size=DEFAULT_RESOURCE_PAGE_SIZE,
        )
    )
    details_handler = RecordingDetailsHandler(
        _details_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_list_resources_handler, list_handler) as client:
        list_response = client.get(f"/api/v1/tenants/{tenant_id}/resources")
    with _client_with_override(get_get_resource_details_handler, details_handler) as client:
        details_response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}"
        )

    system_client = TestClient(app)
    assert list_response.status_code == 200
    assert list_response.json() == {"items": [], "next_cursor": None}
    assert details_response.status_code == 200
    assert details_response.json()["id"] == str(resource_id)
    assert system_client.get("/").json() == {
        "service": "resource-monitoring-api",
        "status": "running",
    }
    assert system_client.get("/health").json() == {"status": "healthy"}
