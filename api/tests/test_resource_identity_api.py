from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
from datetime import UTC, datetime
from typing import Iterator
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.composition import (
    get_find_resource_by_alias_handler,
    get_find_resource_by_identifier_handler,
    get_get_resource_by_canonical_name_handler,
    get_get_resource_details_handler,
    get_get_resource_history_handler,
    get_get_resource_relationships_handler,
    get_resolve_canonical_resource_handler,
)
from app.api.mappers import (
    canonical_resource_resolved_response,
    resource_alias_lookup_response,
    resource_identifier_lookup_response,
    resource_read_response,
)
from app.api.schemas import (
    CanonicalResourceResolvedResponse,
    ResourceAliasLookupResponse,
    ResourceIdentifierLookupResponse,
    ResourceReadResponse,
)
from app.application.errors import (
    ConflictError,
    EntityNotFoundError,
    PersistenceError,
    TenantBoundaryError,
    ValidationError,
    ValidationFailure,
)
from app.application.queries import (
    FindResourceByAliasQuery,
    FindResourceByIdentifierQuery,
    GetResourceByCanonicalNameQuery,
    GetResourceDetailsQuery,
    GetResourceHistoryQuery,
    GetResourceRelationshipsQuery,
    ResolveCanonicalResourceQuery,
)
from app.application.results import (
    CanonicalResourceResolvedResult,
    ResourceAliasLookupResult,
    ResourceDetailsResult,
    ResourceHistoryResult,
    ResourceIdentifierLookupResult,
    ResourceReadResult,
    ResourceRelationshipsResult,
)
from app.main import app


class RecordingCanonicalNameHandler:
    def __init__(self, result: ResourceDetailsResult) -> None:
        self.result = result
        self.queries: list[GetResourceByCanonicalNameQuery] = []

    def handle(self, query: GetResourceByCanonicalNameQuery) -> ResourceDetailsResult:
        self.queries.append(query)
        return self.result


class RecordingIdentifierLookupHandler:
    def __init__(self, result: ResourceIdentifierLookupResult) -> None:
        self.result = result
        self.queries: list[FindResourceByIdentifierQuery] = []

    def handle(
        self,
        query: FindResourceByIdentifierQuery,
    ) -> ResourceIdentifierLookupResult:
        self.queries.append(query)
        return self.result


class RecordingAliasLookupHandler:
    def __init__(self, result: ResourceAliasLookupResult) -> None:
        self.result = result
        self.queries: list[FindResourceByAliasQuery] = []

    def handle(self, query: FindResourceByAliasQuery) -> ResourceAliasLookupResult:
        self.queries.append(query)
        return self.result


class RecordingCanonicalResolutionHandler:
    def __init__(self, result: CanonicalResourceResolvedResult) -> None:
        self.result = result
        self.queries: list[ResolveCanonicalResourceQuery] = []

    def handle(
        self,
        query: ResolveCanonicalResourceQuery,
    ) -> CanonicalResourceResolvedResult:
        self.queries.append(query)
        return self.result


class RecordingDetailsHandler:
    def __init__(self, result: ResourceDetailsResult) -> None:
        self.result = result
        self.queries: list[GetResourceDetailsQuery] = []

    def handle(self, query: GetResourceDetailsQuery) -> ResourceDetailsResult:
        self.queries.append(query)
        return self.result


class RecordingHistoryHandler:
    def __init__(self, result: ResourceHistoryResult) -> None:
        self.result = result
        self.queries: list[GetResourceHistoryQuery] = []

    def handle(self, query: GetResourceHistoryQuery) -> ResourceHistoryResult:
        self.queries.append(query)
        return self.result


class RecordingRelationshipsHandler:
    def __init__(self, result: ResourceRelationshipsResult) -> None:
        self.result = result
        self.queries: list[GetResourceRelationshipsQuery] = []

    def handle(
        self,
        query: GetResourceRelationshipsQuery,
    ) -> ResourceRelationshipsResult:
        self.queries.append(query)
        return self.result


class RaisingHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def handle(self, query: object) -> object:
        raise self.exc


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


def _dt() -> datetime:
    return datetime(2026, 8, 19, 16, 0, tzinfo=UTC)


def _read_result(
    *,
    resource_id: UUID,
    tenant_id: UUID,
    display_name: str | None = "Application 01",
) -> ResourceReadResult:
    return ResourceReadResult(
        id=resource_id,
        tenant_id=tenant_id,
        canonical_name="app01.example.com",
        display_name=display_name,
    )


def _details_result(*, tenant_id: UUID, resource_id: UUID) -> ResourceDetailsResult:
    return ResourceDetailsResult(
        id=resource_id,
        tenant_id=tenant_id,
        organization_id=None,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        canonical_name="app01.example.com",
        display_name="Application 01",
        record_version=7,
        created_at=_dt(),
        updated_at=_dt(),
        state=None,
        identifiers=(),
        ownership=(),
        classifications=(),
        labels=(),
        aliases=(),
        outgoing_merge=None,
    )


def _identifier_lookup_result(
    *,
    tenant_id: UUID,
    resource_id: UUID,
    namespace: str | None = "dns",
    display_name: str | None = "Application 01",
) -> ResourceIdentifierLookupResult:
    return ResourceIdentifierLookupResult(
        resource=_read_result(
            resource_id=resource_id,
            tenant_id=tenant_id,
            display_name=display_name,
        ),
        identifier_id=UUID("0198a4a2-0000-7000-8000-000000000101"),
        identifier_type_id=UUID("0198a4a2-0000-7000-8000-000000000102"),
        namespace=namespace,
        normalized_value="app01.example.com",
        original_value="APP01.EXAMPLE.COM",
        is_primary=True,
    )


def _alias_lookup_result(
    *,
    tenant_id: UUID,
    resource_id: UUID,
    display_name: str | None = "Application 01",
) -> ResourceAliasLookupResult:
    return ResourceAliasLookupResult(
        resource=_read_result(
            resource_id=resource_id,
            tenant_id=tenant_id,
            display_name=display_name,
        ),
        alias_id=UUID("0198a4a2-0000-7000-8000-000000000201"),
        alias_type="hostname",
        normalized_value="app01",
        alias_value="APP01",
    )


def _canonical_result(
    *,
    tenant_id: UUID,
    requested_resource_id: UUID,
    canonical_resource_id: UUID,
    immediate_target_resource_id: UUID | None,
    merge_depth: int,
    is_canonical: bool,
) -> CanonicalResourceResolvedResult:
    return CanonicalResourceResolvedResult(
        requested_resource_id=requested_resource_id,
        canonical_resource_id=canonical_resource_id,
        immediate_target_resource_id=immediate_target_resource_id,
        merge_depth=merge_depth,
        is_canonical=is_canonical,
        canonical_resource=_read_result(
            resource_id=canonical_resource_id,
            tenant_id=tenant_id,
            display_name="Canonical Application",
        ),
    )


def _history_result(*, tenant_id: UUID, resource_id: UUID) -> ResourceHistoryResult:
    return ResourceHistoryResult(
        id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=UUID("0198a4a2-0000-7000-8000-000000000003"),
        canonical_name="app01.example.com",
        display_name="Application 01",
        states=(),
        ownership=(),
        labels=(),
        classifications=(),
        identifiers=(),
    )


def _relationships_result(
    *,
    tenant_id: UUID,
    resource_id: UUID,
) -> ResourceRelationshipsResult:
    return ResourceRelationshipsResult(
        resource_id=resource_id,
        tenant_id=tenant_id,
        relationships=(),
    )


def _field_names(dataclass_type: type[object]) -> list[str]:
    return [field.name for field in fields(dataclass_type)]


def test_identity_response_schemas_match_application_results() -> None:
    assert list(ResourceReadResponse.model_fields) == _field_names(ResourceReadResult)
    assert list(ResourceIdentifierLookupResponse.model_fields) == _field_names(
        ResourceIdentifierLookupResult
    )
    assert list(ResourceAliasLookupResponse.model_fields) == _field_names(
        ResourceAliasLookupResult
    )
    assert list(CanonicalResourceResolvedResponse.model_fields) == _field_names(
        CanonicalResourceResolvedResult
    )


def test_identity_mappers_return_api_schemas() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    read_result = _read_result(resource_id=resource_id, tenant_id=tenant_id)
    identifier_result = _identifier_lookup_result(
        tenant_id=tenant_id,
        resource_id=resource_id,
    )
    alias_result = _alias_lookup_result(tenant_id=tenant_id, resource_id=resource_id)
    canonical_result = _canonical_result(
        tenant_id=tenant_id,
        requested_resource_id=resource_id,
        canonical_resource_id=resource_id,
        immediate_target_resource_id=None,
        merge_depth=0,
        is_canonical=True,
    )

    assert isinstance(resource_read_response(read_result), ResourceReadResponse)
    assert isinstance(
        resource_identifier_lookup_response(identifier_result),
        ResourceIdentifierLookupResponse,
    )
    assert isinstance(
        resource_alias_lookup_response(alias_result),
        ResourceAliasLookupResponse,
    )
    assert isinstance(
        canonical_resource_resolved_response(canonical_result),
        CanonicalResourceResolvedResponse,
    )


def test_canonical_name_lookup_maps_exact_query_and_reuses_details_response() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    canonical_name = " APP01.Example.COM "
    handler = RecordingCanonicalNameHandler(
        _details_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(
        get_get_resource_by_canonical_name_handler,
        handler,
    ) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resource-lookups/canonical-name",
            params={"canonical_name": canonical_name},
        )

    assert response.status_code == 200
    assert handler.queries == [
        GetResourceByCanonicalNameQuery(
            tenant_id=tenant_id,
            canonical_name=canonical_name,
        )
    ]
    assert response.json()["id"] == str(resource_id)
    assert response.json()["record_version"] == 7


def test_canonical_name_lookup_errors_and_transport_validation() -> None:
    missing = RaisingHandler(EntityNotFoundError("missing"))
    persistence = RaisingHandler(PersistenceError("postgres SELECT canonical secret"))

    with _client_with_override(
        get_get_resource_by_canonical_name_handler,
        missing,
    ) as client:
        not_found_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/canonical-name",
            params={"canonical_name": "missing.example.com"},
        )
    with _client_with_override(
        get_get_resource_by_canonical_name_handler,
        persistence,
    ) as client:
        persistence_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/canonical-name",
            params={"canonical_name": "app01.example.com"},
        )
    malformed_response = TestClient(app).get(
        "/api/v1/tenants/not-a-uuid/resource-lookups/canonical-name",
        params={"canonical_name": "app01.example.com"},
    )

    assert not_found_response.status_code == 404
    assert not_found_response.json()["error"]["code"] == "not_found"
    assert persistence_response.status_code == 503
    assert persistence_response.json()["error"]["code"] == "service_unavailable"
    assert "postgres" not in persistence_response.text
    assert "SELECT" not in persistence_response.text
    assert malformed_response.status_code == 422
    assert "validation_error" not in malformed_response.text


def test_identifier_lookup_maps_exact_query_and_namespace_variants() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    identifier_type_id = uuid4()
    handler = RecordingIdentifierLookupHandler(
        _identifier_lookup_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(
        get_find_resource_by_identifier_handler,
        handler,
    ) as client:
        omitted_response = client.get(
            f"/api/v1/tenants/{tenant_id}/resource-lookups/identifier",
            params={
                "identifier_type_id": str(identifier_type_id),
                "normalized_value": " Example.COM ",
            },
        )
        empty_response = client.get(
            f"/api/v1/tenants/{tenant_id}/resource-lookups/identifier",
            params={
                "identifier_type_id": str(identifier_type_id),
                "normalized_value": "Example.COM",
                "namespace": "",
            },
        )

    assert omitted_response.status_code == 200
    assert empty_response.status_code == 200
    assert handler.queries == [
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value=" Example.COM ",
        ),
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier_type_id,
            namespace="",
            normalized_value="Example.COM",
        ),
    ]


def test_identifier_lookup_response_mapping_and_null_display_name() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingIdentifierLookupHandler(
        _identifier_lookup_result(
            tenant_id=tenant_id,
            resource_id=resource_id,
            namespace=None,
            display_name=None,
        )
    )

    with _client_with_override(
        get_find_resource_by_identifier_handler,
        handler,
    ) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resource-lookups/identifier",
            params={
                "identifier_type_id": str(handler.result.identifier_type_id),
                "normalized_value": "app01.example.com",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "resource": {
            "id": str(resource_id),
            "tenant_id": str(tenant_id),
            "canonical_name": "app01.example.com",
            "display_name": None,
        },
        "identifier_id": str(handler.result.identifier_id),
        "identifier_type_id": str(handler.result.identifier_type_id),
        "namespace": None,
        "normalized_value": "app01.example.com",
        "original_value": "APP01.EXAMPLE.COM",
        "is_primary": True,
    }


def test_identifier_lookup_errors_and_validation() -> None:
    validation = RaisingHandler(
        ValidationError(
            "invalid identifier",
            failures=(ValidationFailure("normalized_value", "must not be empty"),),
        )
    )
    persistence = RaisingHandler(PersistenceError("postgres SELECT identifier secret"))

    with _client_with_override(
        get_find_resource_by_identifier_handler,
        validation,
    ) as client:
        validation_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/identifier",
            params={"identifier_type_id": str(uuid4()), "normalized_value": ""},
        )
    with _client_with_override(
        get_find_resource_by_identifier_handler,
        persistence,
    ) as client:
        persistence_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/identifier",
            params={"identifier_type_id": str(uuid4()), "normalized_value": "x"},
        )
    miss = RaisingHandler(EntityNotFoundError("missing"))
    with _client_with_override(get_find_resource_by_identifier_handler, miss) as client:
        miss_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/identifier",
            params={"identifier_type_id": str(uuid4()), "normalized_value": "x"},
        )
    malformed_response = TestClient(app).get(
        f"/api/v1/tenants/{uuid4()}/resource-lookups/identifier",
        params={"identifier_type_id": "not-a-uuid", "normalized_value": "x"},
    )

    assert validation_response.status_code == 422
    assert validation_response.json()["error"]["code"] == "validation_error"
    assert persistence_response.status_code == 503
    assert "postgres" not in persistence_response.text
    assert "SELECT" not in persistence_response.text
    assert miss_response.status_code == 404
    assert miss_response.json()["error"]["code"] == "not_found"
    assert malformed_response.status_code == 422
    assert "validation_error" not in malformed_response.text


def test_alias_lookup_maps_exact_query_and_response() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    alias_type = " HostName "
    normalized_value = " APP01 "
    handler = RecordingAliasLookupHandler(
        _alias_lookup_result(
            tenant_id=tenant_id,
            resource_id=resource_id,
            display_name=None,
        )
    )

    with _client_with_override(get_find_resource_by_alias_handler, handler) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resource-lookups/alias",
            params={"alias_type": alias_type, "normalized_value": normalized_value},
        )

    assert response.status_code == 200
    assert handler.queries == [
        FindResourceByAliasQuery(
            tenant_id=tenant_id,
            alias_type=alias_type,
            normalized_value=normalized_value,
        )
    ]
    assert response.json() == {
        "resource": {
            "id": str(resource_id),
            "tenant_id": str(tenant_id),
            "canonical_name": "app01.example.com",
            "display_name": None,
        },
        "alias_id": str(handler.result.alias_id),
        "alias_type": "hostname",
        "normalized_value": "app01",
        "alias_value": "APP01",
    }


def test_alias_lookup_errors_and_validation() -> None:
    validation = RaisingHandler(
        ValidationError(
            "invalid alias",
            failures=(ValidationFailure("alias_type", "must not be empty"),),
        )
    )
    persistence = RaisingHandler(PersistenceError("postgres SELECT alias secret"))
    miss = RaisingHandler(EntityNotFoundError("missing"))

    with _client_with_override(
        get_find_resource_by_alias_handler,
        validation,
    ) as client:
        validation_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/alias",
            params={"alias_type": "", "normalized_value": "app01"},
        )
    with _client_with_override(
        get_find_resource_by_alias_handler,
        persistence,
    ) as client:
        persistence_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/alias",
            params={"alias_type": "hostname", "normalized_value": "app01"},
        )
    with _client_with_override(get_find_resource_by_alias_handler, miss) as client:
        miss_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resource-lookups/alias",
            params={"alias_type": "hostname", "normalized_value": "app01"},
        )

    assert validation_response.status_code == 422
    assert validation_response.json()["error"]["code"] == "validation_error"
    assert persistence_response.status_code == 503
    assert "postgres" not in persistence_response.text
    assert "SELECT" not in persistence_response.text
    assert miss_response.status_code == 404
    assert miss_response.json()["error"]["code"] == "not_found"


def test_canonical_resolution_maps_query_and_already_canonical_result_without_redirect() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    handler = RecordingCanonicalResolutionHandler(
        _canonical_result(
            tenant_id=tenant_id,
            requested_resource_id=resource_id,
            canonical_resource_id=resource_id,
            immediate_target_resource_id=None,
            merge_depth=0,
            is_canonical=True,
        )
    )

    with _client_with_override(
        get_resolve_canonical_resource_handler,
        handler,
    ) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical",
            follow_redirects=False,
        )

    assert response.status_code == 200
    assert response.headers.get("location") is None
    assert handler.queries == [
        ResolveCanonicalResourceQuery(tenant_id=tenant_id, resource_id=resource_id)
    ]
    assert response.json() == {
        "requested_resource_id": str(resource_id),
        "canonical_resource_id": str(resource_id),
        "immediate_target_resource_id": None,
        "merge_depth": 0,
        "is_canonical": True,
        "canonical_resource": {
            "id": str(resource_id),
            "tenant_id": str(tenant_id),
            "canonical_name": "app01.example.com",
            "display_name": "Canonical Application",
        },
    }


def test_canonical_resolution_maps_merged_resource_result_without_redirect() -> None:
    tenant_id = uuid4()
    source_id = uuid4()
    first_target_id = uuid4()
    terminal_id = uuid4()
    handler = RecordingCanonicalResolutionHandler(
        _canonical_result(
            tenant_id=tenant_id,
            requested_resource_id=source_id,
            canonical_resource_id=terminal_id,
            immediate_target_resource_id=first_target_id,
            merge_depth=2,
            is_canonical=False,
        )
    )

    with _client_with_override(
        get_resolve_canonical_resource_handler,
        handler,
    ) as client:
        response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{source_id}/canonical",
            follow_redirects=False,
        )

    payload = response.json()
    assert response.status_code == 200
    assert response.headers.get("location") is None
    assert payload["requested_resource_id"] == str(source_id)
    assert payload["canonical_resource_id"] == str(terminal_id)
    assert payload["immediate_target_resource_id"] == str(first_target_id)
    assert payload["merge_depth"] == 2
    assert payload["is_canonical"] is False
    assert payload["canonical_resource"]["id"] == str(terminal_id)


def test_canonical_resolution_transport_and_application_errors() -> None:
    not_found = RaisingHandler(EntityNotFoundError("missing"))
    boundary = RaisingHandler(TenantBoundaryError("other tenant has it"))
    conflict = RaisingHandler(ConflictError("merge cycle", entity_type="ResourceMerge"))
    persistence = RaisingHandler(PersistenceError("postgres SELECT canonical secret"))

    with _client_with_override(
        get_resolve_canonical_resource_handler,
        not_found,
    ) as client:
        not_found_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}/canonical"
        )
    with _client_with_override(
        get_resolve_canonical_resource_handler,
        boundary,
    ) as client:
        boundary_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}/canonical"
        )
    with _client_with_override(
        get_resolve_canonical_resource_handler,
        conflict,
    ) as client:
        conflict_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}/canonical"
        )
    with _client_with_override(
        get_resolve_canonical_resource_handler,
        persistence,
    ) as client:
        persistence_response = client.get(
            f"/api/v1/tenants/{uuid4()}/resources/{uuid4()}/canonical"
        )
    malformed_tenant = TestClient(app).get(
        f"/api/v1/tenants/not-a-uuid/resources/{uuid4()}/canonical"
    )
    malformed_resource = TestClient(app).get(
        f"/api/v1/tenants/{uuid4()}/resources/not-a-uuid/canonical"
    )

    assert not_found_response.status_code == 404
    assert not_found_response.json()["error"]["code"] == "not_found"
    assert boundary_response.status_code == 404
    assert boundary_response.json() == not_found_response.json()
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "conflict"
    assert persistence_response.status_code == 503
    assert "postgres" not in persistence_response.text
    assert "SELECT" not in persistence_response.text
    assert malformed_tenant.status_code == 422
    assert malformed_resource.status_code == 422


def test_existing_resource_routes_remain_independent_from_canonical_resolution() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    details_handler = RecordingDetailsHandler(
        _details_result(tenant_id=tenant_id, resource_id=resource_id)
    )
    history_handler = RecordingHistoryHandler(
        _history_result(tenant_id=tenant_id, resource_id=resource_id)
    )
    relationships_handler = RecordingRelationshipsHandler(
        _relationships_result(tenant_id=tenant_id, resource_id=resource_id)
    )

    with _client_with_override(
        get_get_resource_details_handler,
        details_handler,
    ) as client:
        details_response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}"
        )
    with _client_with_override(
        get_get_resource_history_handler,
        history_handler,
    ) as client:
        history_response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/history"
        )
    with _client_with_override(
        get_get_resource_relationships_handler,
        relationships_handler,
    ) as client:
        relationships_response = client.get(
            f"/api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships"
        )

    assert details_response.status_code == 200
    assert history_response.status_code == 200
    assert relationships_response.status_code == 200
    assert details_handler.queries == [
        GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource_id)
    ]
    assert history_handler.queries == [
        GetResourceHistoryQuery(tenant_id=tenant_id, resource_id=resource_id)
    ]
    assert relationships_handler.queries == [
        GetResourceRelationshipsQuery(tenant_id=tenant_id, resource_id=resource_id)
    ]
