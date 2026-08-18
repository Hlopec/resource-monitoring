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
    get_list_resources_handler,
)
from app.api.mappers import resource_details_response
from app.api.schemas import (
    ResourceAliasResponse,
    ResourceClassificationResponse,
    ResourceDetailsResponse,
    ResourceIdentifierResponse,
    ResourceLabelResponse,
    ResourceMergeResponse,
    ResourceOwnershipResponse,
    ResourceStateResponse,
)
from app.application.errors import (
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
)
from app.application.queries import (
    DEFAULT_RESOURCE_PAGE_SIZE,
    GetResourceDetailsQuery,
    ListResourcesQuery,
)
from app.application.results import (
    ResourceAliasResult,
    ResourceClassificationResult,
    ResourceDetailsResult,
    ResourceIdentifierResult,
    ResourceLabelResult,
    ResourceMergeResult,
    ResourceOwnershipResult,
    ResourcePageResult,
    ResourceStateResult,
)
from app.main import app


class RecordingDetailsHandler:
    def __init__(self, result: ResourceDetailsResult) -> None:
        self.result = result
        self.queries: list[GetResourceDetailsQuery] = []

    def handle(self, query: GetResourceDetailsQuery) -> ResourceDetailsResult:
        self.queries.append(query)
        return self.result


class RaisingDetailsHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.queries: list[GetResourceDetailsQuery] = []

    def handle(self, query: GetResourceDetailsQuery) -> ResourceDetailsResult:
        self.queries.append(query)
        raise self.exc


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
    return datetime(2026, 8, 19, 10, 0, tzinfo=UTC) + timedelta(minutes=minutes)


def _details_result(
    *,
    tenant_id: UUID,
    resource_id: UUID,
    include_optional: bool = True,
) -> ResourceDetailsResult:
    organization_id = uuid4() if include_optional else None
    target_resource_id = uuid4()
    return ResourceDetailsResult(
        id=resource_id,
        tenant_id=tenant_id,
        organization_id=organization_id,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        canonical_name="app01.example.com",
        display_name="Application 01",
        record_version=7,
        created_at=_dt(),
        updated_at=_dt(1),
        state=(
            ResourceStateResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000101"),
                lifecycle_status_id=UUID("0198a4a2-0000-7000-8000-000000000102"),
                criticality_id=UUID("0198a4a2-0000-7000-8000-000000000103"),
                exposure_level_id=UUID("0198a4a2-0000-7000-8000-000000000104"),
                source_priority=3,
                confidence_score=Decimal("0.95"),
                valid_from=_dt(2),
                source="cmdb",
            )
            if include_optional
            else None
        ),
        identifiers=(
            ResourceIdentifierResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000201"),
                identifier_type_id=UUID("0198a4a2-0000-7000-8000-000000000202"),
                namespace="dns",
                normalized_value="app01.example.com",
                original_value="APP01.EXAMPLE.COM",
                is_primary=True,
                confidence_score=Decimal("1.00"),
                valid_from=_dt(3),
            ),
            ResourceIdentifierResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000203"),
                identifier_type_id=UUID("0198a4a2-0000-7000-8000-000000000204"),
                namespace=None,
                normalized_value="10.0.0.5",
                original_value="10.0.0.5",
                is_primary=False,
                confidence_score=Decimal("0.875"),
                valid_from=_dt(4),
            ),
        ),
        ownership=(
            ResourceOwnershipResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000301"),
                organization_id=organization_id or uuid4(),
                ownership_role_id=UUID("0198a4a2-0000-7000-8000-000000000302"),
                is_primary=True,
                confidence_score=Decimal("0.90"),
                valid_from=_dt(5),
                source="inventory",
            ),
            ResourceOwnershipResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000303"),
                organization_id=uuid4(),
                ownership_role_id=UUID("0198a4a2-0000-7000-8000-000000000304"),
                is_primary=False,
                confidence_score=Decimal("0.80"),
                valid_from=_dt(6),
                source=None,
            ),
        ),
        classifications=(
            ResourceClassificationResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000401"),
                classification_type_id=UUID("0198a4a2-0000-7000-8000-000000000402"),
                classification_value_id=UUID("0198a4a2-0000-7000-8000-000000000403"),
                is_primary=True,
                confidence_score=Decimal("0.70"),
                valid_from=_dt(7),
                source="policy",
            ),
            ResourceClassificationResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000404"),
                classification_type_id=UUID("0198a4a2-0000-7000-8000-000000000405"),
                classification_value_id=UUID("0198a4a2-0000-7000-8000-000000000406"),
                is_primary=False,
                confidence_score=Decimal("0.60"),
                valid_from=_dt(8),
                source=None,
            ),
        ),
        labels=(
            ResourceLabelResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000501"),
                label_id=UUID("0198a4a2-0000-7000-8000-000000000502"),
                valid_from=_dt(9),
                source="manual",
            ),
            ResourceLabelResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000503"),
                label_id=UUID("0198a4a2-0000-7000-8000-000000000504"),
                valid_from=_dt(10),
                source=None,
            ),
        ),
        aliases=(
            ResourceAliasResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000601"),
                alias_type="hostname",
                alias_value="APP01",
                normalized_value="app01",
                source="dns",
                first_seen_at=_dt(11),
                last_seen_at=_dt(12),
            ),
            ResourceAliasResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000602"),
                alias_type="fqdn",
                alias_value="APP01.EXAMPLE.COM",
                normalized_value="app01.example.com",
                source=None,
                first_seen_at=_dt(13),
                last_seen_at=_dt(14),
            ),
        ),
        outgoing_merge=(
            ResourceMergeResult(
                id=UUID("0198a4a2-0000-7000-8000-000000000701"),
                source_resource_id=resource_id,
                target_resource_id=target_resource_id,
                reason="duplicate",
                source="manual",
                merged_at=_dt(15),
            )
            if include_optional
            else None
        ),
    )


def _field_names(dataclass_type: type[object]) -> list[str]:
    return [field.name for field in fields(dataclass_type)]


def test_exact_resource_details_route_exists_without_accidental_alternatives() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingDetailsHandler(
        _details_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{tenant_id}/resources/{resource_id}")
        missing_tenant_scope = client.get(f"/api/v1/resources/{resource_id}")
        missing_resource_scope = client.get(f"/api/v1/tenants/{tenant_id}/resource")

    assert response.status_code == 200
    assert missing_tenant_scope.status_code == 404
    assert missing_resource_scope.status_code == 404


def test_details_query_mapping_uses_exact_path_tenant_and_resource_ids() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    query_tenant_id = uuid4()
    handler = RecordingDetailsHandler(
        _details_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}",
            params={"tenant_id": str(query_tenant_id), "resource_id": str(uuid4())},
        )

    assert response.status_code == 200
    assert handler.queries == [
        GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource_id)
    ]


def test_malformed_details_tenant_uuid_is_transport_validation_error() -> None:
    response = TestClient(app).get(f"/api/v1/tenants/not-a-uuid/resources/{uuid4()}")

    assert response.status_code == 422
    assert "validation_error" not in response.text


def test_malformed_details_resource_uuid_is_transport_validation_error() -> None:
    response = TestClient(app).get(f"/api/v1/tenants/{uuid4()}/resources/not-a-uuid")

    assert response.status_code == 422
    assert "validation_error" not in response.text


def test_details_dependency_override_uses_fake_handler_without_database_access() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingDetailsHandler(
        _details_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{tenant_id}/resources/{resource_id}")

    assert response.status_code == 200
    assert len(handler.queries) == 1


def test_details_response_schema_exactly_matches_resource_details_result() -> None:
    assert list(ResourceDetailsResponse.model_fields) == _field_names(
        ResourceDetailsResult
    )
    assert list(ResourceStateResponse.model_fields) == _field_names(
        ResourceStateResult
    )
    assert list(ResourceIdentifierResponse.model_fields) == _field_names(
        ResourceIdentifierResult
    )
    assert list(ResourceOwnershipResponse.model_fields) == _field_names(
        ResourceOwnershipResult
    )
    assert list(ResourceClassificationResponse.model_fields) == _field_names(
        ResourceClassificationResult
    )
    assert list(ResourceLabelResponse.model_fields) == _field_names(ResourceLabelResult)
    assert list(ResourceAliasResponse.model_fields) == _field_names(ResourceAliasResult)
    assert list(ResourceMergeResponse.model_fields) == _field_names(ResourceMergeResult)


def test_details_mapping_complete_with_nested_ordering_and_serialization() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    result = _details_result(tenant_id=tenant_id, resource_id=resource_id)
    handler = RecordingDetailsHandler(result)

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{tenant_id}/resources/{resource_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(resource_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["resource_type_id"] == str(result.resource_type_id)
    assert payload["canonical_name"] == "app01.example.com"
    assert payload["record_version"] == 7
    assert payload["created_at"] == "2026-08-19T10:00:00Z"
    assert payload["state"]["confidence_score"] == "0.95"
    assert payload["identifiers"][0]["normalized_value"] == "app01.example.com"
    assert payload["identifiers"][1]["normalized_value"] == "10.0.0.5"
    assert payload["identifiers"][1]["namespace"] is None
    assert [item["id"] for item in payload["ownership"]] == [
        str(item.id) for item in result.ownership
    ]
    assert [item["id"] for item in payload["classifications"]] == [
        str(item.id) for item in result.classifications
    ]
    assert [item["id"] for item in payload["labels"]] == [
        str(item.id) for item in result.labels
    ]
    assert [item["id"] for item in payload["aliases"]] == [
        str(item.id) for item in result.aliases
    ]
    assert payload["aliases"][1]["source"] is None
    assert payload["outgoing_merge"]["source_resource_id"] == str(resource_id)
    assert payload["outgoing_merge"]["target_resource_id"] == str(
        result.outgoing_merge.target_resource_id
    )


def test_details_nullability_maps_none_to_json_null() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingDetailsHandler(
        _details_result(
            tenant_id=tenant_id,
            resource_id=resource_id,
            include_optional=False,
        )
    )

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{tenant_id}/resources/{resource_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_id"] is None
    assert payload["state"] is None
    assert payload["outgoing_merge"] is None
    assert payload["ownership"][1]["source"] is None
    assert payload["classifications"][1]["source"] is None
    assert payload["labels"][1]["source"] is None


def test_details_mapper_returns_api_schema_without_model_validate_shortcut() -> None:
    result = _details_result(tenant_id=uuid4(), resource_id=uuid4())

    response = resource_details_response(result)

    assert isinstance(response, ResourceDetailsResponse)
    assert response.identifiers[0].id == result.identifiers[0].id
    assert response.identifiers[1].id == result.identifiers[1].id


def test_details_not_found_uses_centralized_non_disclosing_404() -> None:
    handler = RaisingDetailsHandler(
        EntityNotFoundError(
            "Resource not found",
            entity_type="Resource",
            lookup_field="resource_id",
            lookup_value=uuid4(),
        )
    )

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Requested resource was not found",
            "details": [],
        }
    }


def test_details_tenant_boundary_uses_same_envelope_as_not_found() -> None:
    handler = RaisingDetailsHandler(TenantBoundaryError("other tenant has it"))

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "other tenant" not in response.text


def test_details_persistence_error_uses_sanitized_503() -> None:
    handler = RaisingDetailsHandler(PersistenceError("postgres SELECT secret"))

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "postgres" not in response.text
    assert "SELECT" not in response.text


def test_details_endpoint_does_not_automatically_resolve_canonical_resource() -> None:
    tenant_id = uuid4()
    requested_resource_id = uuid4()
    result = _details_result(
        tenant_id=tenant_id,
        resource_id=requested_resource_id,
    )
    handler = RecordingDetailsHandler(result)

    with _client_with_override(get_get_resource_details_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{requested_resource_id}"
        )

    payload = response.json()
    assert response.status_code == 200
    assert handler.queries == [
        GetResourceDetailsQuery(
            tenant_id=tenant_id,
            resource_id=requested_resource_id,
        )
    ]
    assert payload["id"] == str(requested_resource_id)
    assert payload["outgoing_merge"]["source_resource_id"] == str(requested_resource_id)
    assert payload["outgoing_merge"]["target_resource_id"] != str(requested_resource_id)


def test_resource_list_endpoint_still_works_with_scoped_override() -> None:
    handler = RecordingListHandler(
        ResourcePageResult(
            items=(),
            next_cursor=None,
            page_size=DEFAULT_RESOURCE_PAGE_SIZE,
        )
    )

    with _client_with_override(get_list_resources_handler, handler) as client:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources")

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
    assert len(handler.queries) == 1


def test_system_routes_remain_available_after_details_route_registration() -> None:
    client = TestClient(app)

    assert client.get("/").json() == {
        "service": "resource-monitoring-api",
        "status": "running",
    }
    assert client.get("/health").json() == {"status": "healthy"}
