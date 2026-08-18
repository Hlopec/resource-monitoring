from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.composition import get_list_resources_handler
from app.application.errors import PersistenceError
from app.application.handlers import ListResourcesHandler
from app.application.queries import DEFAULT_RESOURCE_PAGE_SIZE, ListResourcesQuery
from app.application.results import ResourcePageResult, ResourceSummaryResult
from app.main import app


class RecordingListResourcesHandler:
    def __init__(self, result: ResourcePageResult) -> None:
        self.result = result
        self.queries: list[ListResourcesQuery] = []

    def handle(self, query: ListResourcesQuery) -> ResourcePageResult:
        self.queries.append(query)
        return self.result


class RaisingListResourcesHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def handle(self, query: ListResourcesQuery) -> ResourcePageResult:
        raise self.exc


class UnitOfWorkShouldNotBeCreated:
    def __call__(self) -> object:
        raise AssertionError("Invalid list query should fail before UoW creation")


def _client_with_handler(handler: object) -> TestClient:
    app.dependency_overrides[get_list_resources_handler] = lambda: handler
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _empty_page() -> ResourcePageResult:
    return ResourcePageResult(items=(), next_cursor=None, page_size=DEFAULT_RESOURCE_PAGE_SIZE)


def _summary(
    *,
    resource_id: UUID,
    tenant_id: UUID,
    created_at: datetime,
    canonical_name: str,
) -> ResourceSummaryResult:
    return ResourceSummaryResult(
        resource_id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        lifecycle_status_id=UUID("0198a4a2-0000-7000-8000-000000000004"),
        canonical_name=canonical_name,
        display_name="Example",
        primary_organization_id=None,
        primary_ownership_role_id=None,
        record_version=1,
        first_seen_at=created_at,
        last_seen_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )


def test_exact_resource_list_route_exists_without_alternative_resource_route() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    tenant_id = uuid4()
    try:
        response = client.get(f"/api/v1/tenants/{tenant_id}/resources")
        alternative = client.get("/api/v1/resources")
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert alternative.status_code == 404


def test_default_query_mapping_uses_path_tenant_and_application_defaults() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    tenant_id = uuid4()
    try:
        response = client.get(f"/api/v1/tenants/{tenant_id}/resources")
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert handler.queries == [
        ListResourcesQuery(
            tenant_id=tenant_id,
            page_size=DEFAULT_RESOURCE_PAGE_SIZE,
        )
    ]


def test_all_supported_filters_are_mapped_to_list_resources_query() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    tenant_id = uuid4()
    values = {
        "resource_type_id": uuid4(),
        "lifecycle_status_id": uuid4(),
        "organization_id": uuid4(),
        "label_id": uuid4(),
        "classification_type_id": uuid4(),
        "classification_value_id": uuid4(),
    }
    cursor = "opaque.cursor+/=_unchanged"
    try:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources",
            params={
                **{name: str(value) for name, value in values.items()},
                "page_size": "17",
                "cursor": cursor,
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert handler.queries == [
        ListResourcesQuery(
            tenant_id=tenant_id,
            resource_type_id=values["resource_type_id"],
            lifecycle_status_id=values["lifecycle_status_id"],
            organization_id=values["organization_id"],
            label_id=values["label_id"],
            classification_type_id=values["classification_type_id"],
            classification_value_id=values["classification_value_id"],
            page_size=17,
            cursor=cursor,
        )
    ]


def test_path_tenant_scope_has_no_default_or_query_override() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    path_tenant_id = uuid4()
    query_tenant_id = uuid4()
    try:
        response = client.get(
            f"/api/v1/tenants/{path_tenant_id}/resources",
            params={"tenant_id": str(query_tenant_id)},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert handler.queries[0].tenant_id == path_tenant_id
    assert handler.queries[0].tenant_id != query_tenant_id


def test_malformed_path_uuid_is_transport_validation_error() -> None:
    response = TestClient(app).get("/api/v1/tenants/not-a-uuid/resources")

    assert response.status_code == 422
    assert "validation_error" not in response.text


def test_malformed_uuid_filter_is_transport_validation_error() -> None:
    response = TestClient(app).get(
        f"/api/v1/tenants/{uuid4()}/resources",
        params={"resource_type_id": "not-a-uuid"},
    )

    assert response.status_code == 422
    assert "validation_error" not in response.text


def test_legal_page_size_is_forwarded_exactly() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    try:
        response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources",
            params={"page_size": "200"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert handler.queries[0].page_size == 200


def test_invalid_page_size_uses_centralized_application_validation_response() -> None:
    handler = ListResourcesHandler(UnitOfWorkShouldNotBeCreated())
    client = _client_with_handler(handler)
    try:
        response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources",
            params={"page_size": "0"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"][0]["field"] == "page_size"


def test_cursor_is_passed_through_unchanged() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    cursor = "opaque.cursor+/=_unchanged"
    try:
        response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources",
            params={"cursor": cursor},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert handler.queries[0].cursor == cursor


def test_non_empty_result_maps_to_ordered_resource_page_response() -> None:
    tenant_id = uuid4()
    first_id = UUID("0198a4a2-0000-7000-8000-000000000011")
    second_id = UUID("0198a4a2-0000-7000-8000-000000000012")
    now = datetime(2026, 8, 18, 20, 0, tzinfo=UTC)
    handler = RecordingListResourcesHandler(
        ResourcePageResult(
            items=(
                _summary(
                    resource_id=first_id,
                    tenant_id=tenant_id,
                    created_at=now,
                    canonical_name="first.example.com",
                ),
                _summary(
                    resource_id=second_id,
                    tenant_id=tenant_id,
                    created_at=now + timedelta(minutes=1),
                    canonical_name="second.example.com",
                ),
            ),
            next_cursor="opaque-next-cursor",
            page_size=2,
        )
    )
    client = _client_with_handler(handler)
    try:
        response = client.get(f"/api/v1/tenants/{tenant_id}/resources")
    finally:
        _clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert [item["resource_id"] for item in payload["items"]] == [
        str(first_id),
        str(second_id),
    ]
    assert [item["canonical_name"] for item in payload["items"]] == [
        "first.example.com",
        "second.example.com",
    ]
    assert payload["next_cursor"] == "opaque-next-cursor"
    assert payload["items"][0]["tenant_id"] == str(tenant_id)
    assert payload["items"][0]["primary_organization_id"] is None


def test_empty_result_returns_200_with_exact_empty_page_shape() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    try:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources")
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_resource_list_response_has_no_pagination_extras() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    try:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources")
    finally:
        _clear_overrides()

    assert {"total_count", "offset", "page", "limit", "total_pages"}.isdisjoint(
        response.json()
    )


def test_classification_value_without_type_uses_application_validation_envelope() -> None:
    handler = ListResourcesHandler(UnitOfWorkShouldNotBeCreated())
    client = _client_with_handler(handler)
    try:
        response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources",
            params={"classification_value_id": str(uuid4())},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "validation_error",
        "message": "Input validation failed",
        "details": [
            {
                "field": "classification_value_id",
                "message": "requires classification_type_id",
            }
        ],
    }


def test_persistence_error_propagates_to_centralized_error_handler() -> None:
    handler = RaisingListResourcesHandler(PersistenceError("postgres SELECT secret"))
    client = _client_with_handler(handler)
    try:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources")
    finally:
        _clear_overrides()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "postgres" not in response.text
    assert "SELECT" not in response.text


def test_dependency_override_uses_fake_handler_without_database_access() -> None:
    handler = RecordingListResourcesHandler(_empty_page())
    client = _client_with_handler(handler)
    try:
        response = client.get(f"/api/v1/tenants/{uuid4()}/resources")
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert len(handler.queries) == 1


def test_system_routes_remain_unchanged() -> None:
    client = TestClient(app)

    assert client.get("/").json() == {
        "service": "resource-monitoring-api",
        "status": "running",
    }
    assert client.get("/health").json() == {"status": "healthy"}
