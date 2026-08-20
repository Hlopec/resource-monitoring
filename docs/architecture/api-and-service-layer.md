# API Architecture and Transport Boundaries

## Purpose

Stage `04.1.1` defines the first API and service-layer architecture baseline. Stage `04.1.2` adds explicit FastAPI dependency wiring for the existing Block 03 Resource handlers without adding production Resource endpoints. Stage `04.2` adds production Resource read, relationship, identity lookup, and explicit canonical-resolution endpoints. Stage `04.3` starts the production Resource command API. The baseline establishes where FastAPI code lives, how HTTP transport code will call application handlers, how application errors will be translated to HTTP responses, and which dependencies are forbidden across boundaries.

The accepted dependency direction is:

```text
HTTP/FastAPI
-> API transport layer
-> application commands, queries, handlers, results, errors
-> application ports
-> persistence adapters / SQLAlchemy
-> PostgreSQL
```

Dependencies must not point back up this chain.

## Package Structure

The API transport boundary starts in `api/app/api/`:

```text
api/app/api/
  __init__.py
  composition.py
  errors.py
  router.py
  routes/
    __init__.py
    resource_lookups.py
    resources.py
    system.py
  schemas.py
```

`router.py` composes FastAPI routers. `routes/system.py` owns the existing `/` and `/health` endpoints. `routes/resources.py` owns Resource collection read/create, detail, history, relationship, and explicit canonical-resolution routes. `routes/resource_lookups.py` owns static Resource identity lookup routes so they cannot be shadowed by dynamic `{resource_id}` paths. `schemas.py` owns Pydantic transport contracts, reusable scalar serialization policy, Resource read/write response shapes, lookup responses, canonical-resolution responses, and the public API error envelope. `mappers/resources.py` owns explicit Resource application-result to API-schema mapping. `errors.py` owns centralized `ApplicationError` to HTTP response mapping. `composition.py` is the explicit composition root where FastAPI dependencies wire application handlers to the application-facing `UnitOfWorkFactory`.

`api/app/main.py` remains bootstrap-oriented: it creates the FastAPI application and includes routers. It should not hold production endpoint logic, SQLAlchemy session access, repositories, or application use-case decisions.

## Router Versioning

Production API routes will live below:

```text
/api/v1
```

Future tenant-owned Resource routes should use this convention:

```text
/api/v1/tenants/{tenant_id}/...
```

The `tenant_id` path value is a scope selector for application commands and queries. It is not an authentication or authorization decision. Until the auth/RBAC layer exists, API code must continue to pass explicit tenant ids into application contracts and must preserve the existing policy that wrong-tenant and missing resources are indistinguishable to callers.

The existing system routes remain outside the versioned production API:

```text
GET /
GET /health
```

## Transport and Application Boundary

FastAPI route handlers may:

- parse HTTP path, query, header, and body data;
- use Pydantic request and response schemas;
- map transport schemas into explicit application commands or queries;
- instantiate or receive explicit application handlers;
- call a handler's `handle(...)` method;
- map application results into response schemas;
- map application errors into HTTP responses;
- define OpenAPI metadata, tags, status codes, and examples.

FastAPI route handlers must not:

- import SQLAlchemy `Session`, `sessionmaker`, `engine`, `Select`, `Query`, `Result`, or `Row`;
- import ORM models as request or response contracts;
- import concrete SQLAlchemy repositories;
- call repository mutation APIs directly;
- execute raw SQL;
- call `commit()`, `rollback()`, or `flush()`;
- translate PostgreSQL or SQLAlchemy exceptions directly;
- bypass application handlers for production use cases.

Application commands, queries, handlers, results, ports, and errors remain transport-neutral. `api/app/application/` must not import FastAPI, Pydantic, Starlette, `HTTPException`, `Request`, `Response`, API routers, API schemas, `app.api`, or concrete persistence implementations.

## Schema Boundary

Pydantic models are transport contracts only. They live in `app.api.schemas` or future route-specific API schema modules. Application dataclasses remain plain frozen dataclasses and must not become Pydantic models.

The mapping rule is explicit:

```text
Pydantic request schema -> application Command or Query
application Result -> Pydantic response schema
```

ORM entities must not be returned as API schemas and should not be exposed through Pydantic `from_attributes` response models. The current API schemas set `from_attributes=False` to keep that boundary visible.

Resource request and response schemas are added only as their production endpoints are introduced.

Stage `04.1.3` keeps the schema surface in `api/app/api/schemas.py` because the current API-owned contract set is still small. A separate schema package should be introduced only when multiple meaningful schema modules exist.

`ApiSchema` is the API-owned Pydantic base. It does not inherit from ORM models or application dataclasses and keeps `from_attributes=False`. Broad ORM auto-loading is prohibited because it hides the transport/application boundary, can accidentally expose mapped fields, and encourages route code to return persistence objects.

Transport validation is limited to HTTP/API shape concerns: UUID parsing, required and optional fields, scalar types, timezone-aware timestamp fields, and response shape. Application handlers remain authoritative for lifecycle rules, temporal invariants, merge rules, ownership and classification semantics, tenant business rules, conflict semantics, and persistence error translation.

## Common Serialization Policy

API serializers own JSON representation decisions:

| Application value | JSON representation |
| --- | --- |
| `UUID` | canonical UUID string |
| aware `datetime` | ISO-8601 string preserving the accepted timezone offset |
| `Decimal` | string, to preserve precision and avoid binary floating point drift |
| opaque cursor | unchanged string |
| tuple | ordered JSON array |

Timestamp fields representing application timestamps use the reusable API-owned `AwareDatetime` annotation. Naive datetimes are rejected; accepted values are not silently assigned a timezone, converted to the local server timezone, or normalized to UTC by the API schema layer.

The Decimal policy is defined by the API-owned `ApiDecimal` scalar alias; future API schemas should use it for Decimal transport fields so JSON emits strings without converting through `float`.

Application cursors remain opaque strings. API schemas expose only `next_cursor: str | None`; they do not decode, inspect, rebuild, or expose cursor internals.

Application results may use immutable tuples. Explicit API mappers convert those tuples into response lists so JSON emits ordered arrays without mutating the application result objects.

## Resource Transport Primitives

The current reusable Resource list transport shape is `ResourceSummaryResponse`, matching `ResourceSummaryResult` exactly:

| Field | Type |
| --- | --- |
| `resource_id` | `UUID` |
| `tenant_id` | `UUID` |
| `resource_type_id` | `UUID` |
| `lifecycle_status_id` | `UUID` |
| `canonical_name` | `str` |
| `display_name` | `str | None` |
| `primary_organization_id` | `UUID | None` |
| `primary_ownership_role_id` | `UUID | None` |
| `record_version` | `int` |
| `first_seen_at` | `AwareDatetime` |
| `last_seen_at` | `AwareDatetime` |
| `created_at` | `AwareDatetime` |
| `updated_at` | `AwareDatetime` |

The cursor page envelope is intentionally small:

```json
{
  "items": [],
  "next_cursor": null
}
```

It does not expose `total_count`, `offset`, `page`, `page_number`, `limit`, or `total_pages` because those values are not part of the application result contract and would imply a different pagination model.

Explicit mapping functions live in `app.api.mappers.resources`:

- `resource_summary_response(result: ResourceSummaryResult) -> ResourceSummaryResponse`
- `resource_page_response(result: ResourcePageResult) -> ResourcePageResponse`
- `resource_created_response(result: ResourceCreatedResult) -> ResourceCreatedResponse`
- `resource_state_transitioned_response(result: ResourceStateTransitionedResult) -> ResourceStateTransitionedResponse`
- `resource_read_response(result: ResourceReadResult) -> ResourceReadResponse`
- `resource_state_response(result: ResourceStateResult) -> ResourceStateResponse`
- `resource_identifier_response(result: ResourceIdentifierResult) -> ResourceIdentifierResponse`
- `resource_ownership_response(result: ResourceOwnershipResult) -> ResourceOwnershipResponse`
- `resource_classification_response(result: ResourceClassificationResult) -> ResourceClassificationResponse`
- `resource_label_response(result: ResourceLabelResult) -> ResourceLabelResponse`
- `resource_alias_response(result: ResourceAliasResult) -> ResourceAliasResponse`
- `resource_merge_response(result: ResourceMergeResult) -> ResourceMergeResponse`
- `resource_details_response(result: ResourceDetailsResult) -> ResourceDetailsResponse`
- `resource_state_history_response(result: ResourceStateHistoryResult) -> ResourceStateHistoryResponse`
- `resource_ownership_history_response(result: ResourceOwnershipHistoryResult) -> ResourceOwnershipHistoryResponse`
- `resource_label_history_response(result: ResourceLabelHistoryResult) -> ResourceLabelHistoryResponse`
- `resource_classification_history_response(result: ResourceClassificationHistoryResult) -> ResourceClassificationHistoryResponse`
- `resource_identifier_history_response(result: ResourceIdentifierHistoryResult) -> ResourceIdentifierHistoryResponse`
- `resource_history_response(result: ResourceHistoryResult) -> ResourceHistoryResponse`
- `resource_relationship_response(result: ResourceRelationshipResult) -> ResourceRelationshipResponse`
- `resource_relationships_response(result: ResourceRelationshipsResult) -> ResourceRelationshipsResponse`
- `resource_identifier_lookup_response(result: ResourceIdentifierLookupResult) -> ResourceIdentifierLookupResponse`
- `resource_alias_lookup_response(result: ResourceAliasLookupResult) -> ResourceAliasLookupResponse`
- `canonical_resource_resolved_response(result: CanonicalResourceResolvedResult) -> CanonicalResourceResolvedResponse`

These functions construct response schemas field by field. There is no generic serializer, serializer registry, reflection mapper, DTO framework, or `model_validate(..., from_attributes=True)` shortcut over arbitrary objects.

## Composition Boundary

Runtime composition is explicit. Future routes should receive a handler directly or through a small FastAPI dependency that builds the handler from:

```text
SQLAlchemyUnitOfWork / UnitOfWorkFactory
-> explicit application Handler
-> route handler
```

`app.api.composition` is the allowed API-side location for wiring concrete persistence adapters into application handlers. Route modules should depend on application commands, queries, results, handlers, and API schemas rather than concrete SQLAlchemy repositories.

No command bus, mediator, handler registry, service locator, automatic handler discovery, generic IoC framework, or auto-scanning mechanism is part of this baseline.

Stage `04.1.2` keeps composition in the single `api/app/api/composition.py` module because the current wiring is still small and easier to audit in one place. This module is the only API package module that imports `SQLAlchemyUnitOfWork`.

## Dependency Wiring

The Unit of Work dependency is:

```python
def get_unit_of_work_factory() -> UnitOfWorkFactory:
    return SQLAlchemyUnitOfWork
```

The public return type is the application-facing `UnitOfWorkFactory`. Returning the `SQLAlchemyUnitOfWork` class is intentional: it is a factory reference, not an open Unit of Work. Resolving this dependency must not create a SQLAlchemy session, begin a transaction, enter a Unit of Work, execute SQL, commit, roll back, or flush.

Every Resource handler provider is explicit and typed:

```python
def get_list_resources_handler(
    uow_factory: UnitOfWorkFactory = Depends(get_unit_of_work_factory),
) -> ListResourcesHandler:
    return ListResourcesHandler(uow_factory)
```

There is no generic handler factory, registry, container, mediator, command bus, service locator, reflection-based registration, or shared base provider. The visible provider inventory is the audit mechanism.

The current Resource handler providers are:

| Provider | Handler |
| --- | --- |
| `get_list_resources_handler` | `ListResourcesHandler` |
| `get_get_resource_by_id_handler` | `GetResourceByIdHandler` |
| `get_get_resource_details_handler` | `GetResourceDetailsHandler` |
| `get_get_resource_history_handler` | `GetResourceHistoryHandler` |
| `get_get_resource_relationships_handler` | `GetResourceRelationshipsHandler` |
| `get_get_resource_by_canonical_name_handler` | `GetResourceByCanonicalNameHandler` |
| `get_find_resource_by_identifier_handler` | `FindResourceByIdentifierHandler` |
| `get_find_resource_by_alias_handler` | `FindResourceByAliasHandler` |
| `get_resolve_canonical_resource_handler` | `ResolveCanonicalResourceHandler` |
| `get_create_resource_handler` | `CreateResourceHandler` |
| `get_transition_resource_state_handler` | `TransitionResourceStateHandler` |
| `get_assign_resource_identifier_handler` | `AssignResourceIdentifierHandler` |
| `get_assign_resource_ownership_handler` | `AssignResourceOwnershipHandler` |
| `get_assign_resource_classification_handler` | `AssignResourceClassificationHandler` |
| `get_assign_resource_label_handler` | `AssignResourceLabelHandler` |
| `get_assign_resource_relationship_handler` | `AssignResourceRelationshipHandler` |
| `get_assign_resource_alias_handler` | `AssignResourceAliasHandler` |
| `get_merge_resource_handler` | `MergeResourceHandler` |

`EnsureResourceExistsHandler` remains an internal application architecture/reference handler and is not wired as a Block 04 Resource API dependency.

## Dependency Overrides

The wiring uses standard FastAPI dependency semantics. Tests and future route tests can replace the Unit of Work factory with:

```python
app.dependency_overrides[get_unit_of_work_factory] = fake_factory_provider
```

They can also replace one explicit handler provider:

```python
app.dependency_overrides[get_list_resources_handler] = fake_handler_provider
```

No monkeypatching of `app.persistence.sqlalchemy`, SQLAlchemy sessions, engines, or repository internals should be required for API dependency tests.

## Handler Lifetime and Transactions

Handler providers return fresh handler instances. They do not cache handlers, Unit of Work instances, SQLAlchemy sessions, repositories, or transaction contexts in module-level globals.

FastAPI dependencies do not own transaction lifecycle. Application handlers keep the Block 03 transaction semantics:

- read handlers create one fresh Unit of Work per `handle(...)` call, perform read-only work, avoid write locks, and do not commit;
- write handlers create one fresh Unit of Work per `handle(...)` call and commit exactly once as the final successful persistence operation;
- rollback and cleanup remain owned by the Unit of Work context manager.

The API layer must not wrap handler execution in an extra Unit of Work, retry framework, transaction context, background task abstraction, or async SQLAlchemy layer.

The current architecture remains synchronous. Do not introduce `AsyncSession`, `create_async_engine`, async repositories, async Unit of Work implementations, or thread-pool wrappers as part of this boundary.

## Error Policy

Stage `04.1.4` completes the API foundation error boundary:

```text
ApplicationError
-> central FastAPI exception handler
-> public API error envelope
-> sanitized HTTP response
```

The public error envelope is deterministic:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Input validation failed",
    "details": [
      {
        "field": "page_size",
        "message": "must be <= 200"
      }
    ]
  }
}
```

`ApiErrorDetail` contains exactly `field` and `message`. `ApiError` contains exactly `code`, `message`, and `details`. `ApiErrorResponse` contains exactly `error`.

Application errors are mapped at the API boundary:

| Application error | HTTP policy |
| --- | --- |
| `ValidationError` | `422 Unprocessable Entity`, `validation_error` |
| `EntityNotFoundError` | `404 Not Found`, `not_found` |
| `ConflictError` | `409 Conflict`, `conflict` |
| `ConcurrentModificationError` | `409 Conflict`, `concurrent_modification` |
| `TenantBoundaryError` | `404 Not Found`, `not_found` |
| `PersistenceError` | `503 Service Unavailable`, `service_unavailable` |

HTTP responses must not expose SQLAlchemy exception types, PostgreSQL constraint names, raw SQL, stack traces, or cross-tenant existence details. Error messages may describe the application-level failure but must not reveal whether a missing tenant-scoped entity exists in another tenant.

`ValidationError` preserves safe ordered `ValidationFailure.field` and `ValidationFailure.message` details. It does not expose the application exception message unless that message is separately chosen as public API text.

`EntityNotFoundError` always returns the stable message `Requested resource was not found`. It does not expose `lookup_value`, tenant ids, lookup strategy, or cross-tenant metadata.

`TenantBoundaryError` intentionally returns the same public envelope as `EntityNotFoundError`. This preserves non-disclosure: callers cannot learn whether an entity exists in another tenant.

`ConflictError` returns a generic API conflict message and does not expose `constraint`, unique index names, SQLSTATE, or database messages. `ConcurrentModificationError` is checked before generic `ConflictError` so the subclass has deterministic `concurrent_modification` mapping.

`PersistenceError` returns `Service is temporarily unavailable` with no details. It must never serialize `str(exc)`, `exc.__cause__`, SQLAlchemy errors, DBAPI errors, SQL text, query params, PostgreSQL details, SQLSTATE, stack traces, or constraint names.

Unexpected exceptions are not normalized by this stage. They are left to standard FastAPI/Starlette 500 behavior so development and tests do not hide programming errors behind application-error envelopes.

FastAPI/Pydantic `RequestValidationError` remains transport validation and is not converted into application `ValidationError` in this stage. Narrow request-validation envelope normalization may be added later when production endpoints need it.

`register_application_error_handlers(app)` is called from `api/app/main.py`. Future route code should let application errors propagate and must not add route-local `try/except ApplicationError` translation.

## Resource List API

Stage `04.2` starts the production Resource Read API. The list endpoint is:

```http
GET /api/v1/tenants/{tenant_id}/resources
```

The route is a thin transport adapter:

```text
HTTP path/query params
-> FastAPI parsing
-> ListResourcesQuery
-> ListResourcesHandler
-> ResourcePageResult
-> resource_page_response(...)
-> ResourcePageResponse
```

The path `tenant_id` is parsed as a native UUID and passed directly into `ListResourcesQuery.tenant_id`. It is a tenant scope selector, not an authentication or authorization decision. There is no default tenant, ambient tenant, global tenant, tenant query-parameter override, or route-level tenant existence check.

Supported query parameters match `ListResourcesQuery` exactly:

- `resource_type_id: UUID | None`
- `lifecycle_status_id: UUID | None`
- `organization_id: UUID | None`
- `label_id: UUID | None`
- `classification_type_id: UUID | None`
- `classification_value_id: UUID | None`
- `page_size: int`
- `cursor: str | None`

The route constructs `ListResourcesQuery` field by field. It does not pass dictionaries into a generic query factory, use reflection mapping, perform filtering in Python, sort results, decode cursors, inspect cursor internals, or access persistence directly.

Page-size semantics remain owned by the application layer: default `50`, minimum `1`, maximum `200`. The route lets `ListResourcesHandler` and existing application validation raise `ValidationError`, which the centralized API error handler maps to the public 422 envelope. The classification rule that `classification_value_id` requires `classification_type_id` is likewise enforced by application validation, not route-local conditionals.

The cursor is opaque. The route accepts `cursor: str | None`, passes it unchanged to `ListResourcesQuery`, and returns `next_cursor` unchanged through `resource_page_response(...)`.

The response model is `ResourcePageResponse`:

```json
{
  "items": [],
  "next_cursor": null
}
```

Non-empty pages contain ordered `ResourceSummaryResponse` items. Empty tenant-scoped results return `200 OK` with `{"items": [], "next_cursor": null}`. The response does not expose `total_count`, `page`, `page_size`, `limit`, `offset`, `total_pages`, filters, links, or previous cursors.

The route depends on `get_list_resources_handler`. It does not instantiate `ListResourcesHandler`, resolve `UnitOfWorkFactory`, import `SQLAlchemyUnitOfWork`, import repositories, call `ResourceQueryService`, or catch `ApplicationError`. Malformed path and query UUIDs remain FastAPI transport-validation errors, separate from application `ValidationError`.

Authentication and authorization remain deferred.

## Resource Details API

Stage `04.2.2` adds the Resource Details endpoint:

```http
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}
```

The route is a thin transport adapter:

```text
HTTP path params
-> FastAPI UUID parsing
-> GetResourceDetailsQuery
-> GetResourceDetailsHandler
-> ResourceDetailsResult
-> resource_details_response(...)
-> ResourceDetailsResponse
```

The route constructs the application query explicitly:

```python
GetResourceDetailsQuery(
    tenant_id=tenant_id,
    resource_id=resource_id,
)
```

Both path values are parsed by FastAPI as native `UUID` values and passed directly into the query. There is no ambient tenant, default tenant, query-parameter tenant override, preflight tenant/resource existence check, repository access, direct `ResourceQueryService` call, or route-local transaction.

The route depends on `get_get_resource_details_handler`, which returns `GetResourceDetailsHandler` from the API composition boundary. Route code does not instantiate handlers directly, resolve `UnitOfWorkFactory`, import `SQLAlchemyUnitOfWork`, import repositories, or catch `ApplicationError`.

The response schema is `ResourceDetailsResponse`, matching `ResourceDetailsResult` exactly:

| Field | Type |
| --- | --- |
| `id` | `UUID` |
| `tenant_id` | `UUID` |
| `organization_id` | `UUID | None` |
| `resource_type_id` | `UUID` |
| `canonical_name` | `str` |
| `display_name` | `str` |
| `record_version` | `int` |
| `created_at` | `AwareDatetime` |
| `updated_at` | `AwareDatetime` |
| `state` | `ResourceStateResponse | None` |
| `identifiers` | `list[ResourceIdentifierResponse]` |
| `ownership` | `list[ResourceOwnershipResponse]` |
| `classifications` | `list[ResourceClassificationResponse]` |
| `labels` | `list[ResourceLabelResponse]` |
| `aliases` | `list[ResourceAliasResponse]` |
| `outgoing_merge` | `ResourceMergeResponse | None` |

Nested response shapes are also exact API-owned projections of current application results:

| Schema | Fields |
| --- | --- |
| `ResourceStateResponse` | `id`, `lifecycle_status_id`, `criticality_id`, `exposure_level_id`, `source_priority`, `confidence_score`, `valid_from`, `source` |
| `ResourceIdentifierResponse` | `id`, `identifier_type_id`, `namespace`, `normalized_value`, `original_value`, `is_primary`, `confidence_score`, `valid_from` |
| `ResourceOwnershipResponse` | `id`, `organization_id`, `ownership_role_id`, `is_primary`, `confidence_score`, `valid_from`, `source` |
| `ResourceClassificationResponse` | `id`, `classification_type_id`, `classification_value_id`, `is_primary`, `confidence_score`, `valid_from`, `source` |
| `ResourceLabelResponse` | `id`, `label_id`, `valid_from`, `source` |
| `ResourceAliasResponse` | `id`, `alias_type`, `alias_value`, `normalized_value`, `source`, `first_seen_at`, `last_seen_at` |
| `ResourceMergeResponse` | `id`, `source_resource_id`, `target_resource_id`, `reason`, `source`, `merged_at` |

Tuples from application results are converted to ordered JSON arrays without sorting. `None` remains JSON `null`. `UUID`, `AwareDatetime`, and `ApiDecimal` reuse the common serialization policy.

Example response shape:

```json
{
  "id": "0198a4a2-0000-7000-8000-000000000001",
  "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
  "organization_id": null,
  "resource_type_id": "0198a4a2-0000-7000-8000-000000000003",
  "canonical_name": "app01.example.com",
  "display_name": "Application 01",
  "record_version": 7,
  "created_at": "2026-08-19T10:00:00Z",
  "updated_at": "2026-08-19T10:01:00Z",
  "state": null,
  "identifiers": [],
  "ownership": [],
  "classifications": [],
  "labels": [],
  "aliases": [],
  "outgoing_merge": null
}
```

Malformed `tenant_id` or `resource_id` values are FastAPI transport validation errors. Missing resources and wrong-tenant resources are handled by application errors and centralized API error translation as the same non-disclosing `404 not_found` envelope. Persistence failures propagate to the centralized `503 service_unavailable` envelope without SQL, SQLSTATE, constraint names, or stack traces.

The details endpoint does not automatically resolve canonical resources. It does not call `ResolveCanonicalResourceHandler`, construct `ResolveCanonicalResourceQuery`, redirect, perform a second details lookup against a canonical target, or replace the requested `resource_id`. If `ResourceDetailsResult.outgoing_merge` is present, the route exposes that exact direct merge projection while keeping `id` equal to the requested resource details result.

The Stage `04.2` Resource read route inventory is:

```text
GET /api/v1/tenants/{tenant_id}/resources
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/history
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical
GET /api/v1/tenants/{tenant_id}/resource-lookups/canonical-name
GET /api/v1/tenants/{tenant_id}/resource-lookups/identifier
GET /api/v1/tenants/{tenant_id}/resource-lookups/alias
```

## Resource History API

Stage `04.2.3` adds the Resource History endpoint:

```http
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/history
```

The route is a thin transport adapter:

```text
HTTP path params
-> FastAPI UUID parsing
-> GetResourceHistoryQuery
-> GetResourceHistoryHandler
-> ResourceHistoryResult
-> resource_history_response(...)
-> ResourceHistoryResponse
```

The route constructs the application query explicitly:

```python
GetResourceHistoryQuery(
    tenant_id=tenant_id,
    resource_id=resource_id,
)
```

Both path values are parsed by FastAPI as native `UUID` values and passed directly into the query. The route does not accept history query filters, cursors, offsets, date ranges, sort controls, or tenant query overrides because `GetResourceHistoryQuery` currently has only `tenant_id` and `resource_id`.

The route depends on `get_get_resource_history_handler`, which returns `GetResourceHistoryHandler` from the API composition boundary. Route code does not instantiate handlers directly, resolve `UnitOfWorkFactory`, import `SQLAlchemyUnitOfWork`, import repositories, call `ResourceQueryService`, or catch `ApplicationError`.

The response schema is `ResourceHistoryResponse`, matching `ResourceHistoryResult` exactly:

| Field | Type |
| --- | --- |
| `id` | `UUID` |
| `tenant_id` | `UUID` |
| `resource_type_id` | `UUID` |
| `canonical_name` | `str` |
| `display_name` | `str` |
| `states` | `list[ResourceStateHistoryResponse]` |
| `ownership` | `list[ResourceOwnershipHistoryResponse]` |
| `labels` | `list[ResourceLabelHistoryResponse]` |
| `classifications` | `list[ResourceClassificationHistoryResponse]` |
| `identifiers` | `list[ResourceIdentifierHistoryResponse]` |

Nested history response shapes are exact API-owned projections of current application history results:

| Schema | Fields |
| --- | --- |
| `ResourceStateHistoryResponse` | `id`, `lifecycle_status_id`, `criticality_id`, `exposure_level_id`, `source_priority`, `confidence_score`, `valid_from`, `valid_to`, `source` |
| `ResourceOwnershipHistoryResponse` | `id`, `organization_id`, `ownership_role_id`, `is_primary`, `confidence_score`, `valid_from`, `valid_to`, `source` |
| `ResourceLabelHistoryResponse` | `id`, `label_id`, `valid_from`, `valid_to`, `source` |
| `ResourceClassificationHistoryResponse` | `id`, `classification_type_id`, `classification_value_id`, `is_primary`, `confidence_score`, `valid_from`, `valid_to`, `source` |
| `ResourceIdentifierHistoryResponse` | `id`, `identifier_type_id`, `namespace`, `normalized_value`, `original_value`, `is_primary`, `confidence_score`, `valid_from`, `valid_to` |

The API boundary preserves the exact tuple order returned by the application layer for every history collection. It does not sort by timestamp, id, category, or current/historical status, and it does not regroup records. Tuple collections become ordered JSON arrays only.

An existing resource with an empty history result returns `200 OK` with the exact empty history representation:

```json
{
  "id": "0198a4a2-0000-7000-8000-000000000001",
  "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
  "resource_type_id": "0198a4a2-0000-7000-8000-000000000003",
  "canonical_name": "empty.example.com",
  "display_name": "Empty",
  "states": [],
  "ownership": [],
  "labels": [],
  "classifications": [],
  "identifiers": []
}
```

Example non-empty response shape:

```json
{
  "id": "0198a4a2-0000-7000-8000-000000000001",
  "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
  "resource_type_id": "0198a4a2-0000-7000-8000-000000000003",
  "canonical_name": "app01.example.com",
  "display_name": "Application 01",
  "states": [
    {
      "id": "0198a4a2-0000-7000-8000-000000000902",
      "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000102",
      "criticality_id": "0198a4a2-0000-7000-8000-000000000103",
      "exposure_level_id": "0198a4a2-0000-7000-8000-000000000104",
      "source_priority": 2,
      "confidence_score": "0.9500",
      "valid_from": "2026-08-19T12:20:00Z",
      "valid_to": null,
      "source": "cmdb"
    }
  ],
  "ownership": [],
  "labels": [],
  "classifications": [],
  "identifiers": []
}
```

`UUID`, `AwareDatetime`, `ApiDecimal`, and `None` reuse the common serialization policy. Decimal values are emitted as JSON strings to preserve precision, aware datetimes are emitted as ISO-8601 strings, and nullable fields such as `valid_to`, `source`, and `namespace` remain JSON `null`.

Malformed `tenant_id` or `resource_id` values are FastAPI transport validation errors. Missing resources and wrong-tenant resources are handled by application errors and centralized API error translation as the same non-disclosing `404 not_found` envelope. Persistence failures propagate to the centralized `503 service_unavailable` envelope without SQL, SQLSTATE, constraint names, or stack traces.

The history endpoint is separate from details. It does not call `GetResourceDetailsHandler`, construct `GetResourceDetailsQuery`, use `get_get_resource_details_handler`, aggregate a details payload, compute diffs, or add relationship history. It also does not automatically resolve canonical resources: it does not call `ResolveCanonicalResourceHandler`, construct `ResolveCanonicalResourceQuery`, redirect, perform a second lookup against a canonical target, or replace the requested `resource_id`.

## Resource Relationships API

Stage `04.2.4` adds the Resource Relationships endpoint:

```http
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships
```

The route is a thin transport adapter:

```text
HTTP path params
-> FastAPI UUID parsing
-> GetResourceRelationshipsQuery
-> GetResourceRelationshipsHandler
-> ResourceRelationshipsResult
-> resource_relationships_response(...)
-> ResourceRelationshipsResponse
```

The route constructs the application query explicitly:

```python
GetResourceRelationshipsQuery(
    tenant_id=tenant_id,
    resource_id=resource_id,
)
```

Both path values are parsed by FastAPI as native `UUID` values and passed directly into the query. The route does not accept relationship filters, cursors, offsets, date ranges, sort controls, direction filters, source/target filters, relationship-type filters, or tenant query overrides because `GetResourceRelationshipsQuery` currently has only `tenant_id` and `resource_id`.

The route depends on `get_get_resource_relationships_handler`, which returns `GetResourceRelationshipsHandler` from the API composition boundary. Route code does not instantiate handlers directly, resolve `UnitOfWorkFactory`, import `SQLAlchemyUnitOfWork`, import repositories, call `ResourceQueryService`, or catch `ApplicationError`.

The response schema is `ResourceRelationshipsResponse`, matching `ResourceRelationshipsResult` exactly:

| Field | Type |
| --- | --- |
| `resource_id` | `UUID` |
| `tenant_id` | `UUID` |
| `relationships` | `list[ResourceRelationshipResponse]` |

The nested current relationship schema is an exact API-owned projection of `ResourceRelationshipResult`:

| Field | Type |
| --- | --- |
| `id` | `UUID` |
| `relationship_type_id` | `UUID` |
| `source_resource_id` | `UUID` |
| `target_resource_id` | `UUID` |
| `direction` | `str` |
| `confidence_score` | `ApiDecimal` |
| `valid_from` | `AwareDatetime` |
| `source` | `str | None` |
| `created_at` | `AwareDatetime` |

This endpoint exposes the existing direct/current one-hop application read model. It does not add recursive traversal, multi-hop expansion, transitive closure, shortest-path lookup, ancestor/descendant expansion, cycle detection, relationship history, or related-resource enrichment chains.

The API boundary preserves the exact tuple order returned by the application layer. It does not sort by relationship type, source id, target id, direction, confidence, `valid_from`, or `created_at`. Tuple collections become ordered JSON arrays only.

An existing resource with no current relationships returns `200 OK` with the exact empty relationship envelope:

```json
{
  "resource_id": "0198a4a2-0000-7000-8000-000000000001",
  "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
  "relationships": []
}
```

Example non-empty response shape:

```json
{
  "resource_id": "0198a4a2-0000-7000-8000-000000000001",
  "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
  "relationships": [
    {
      "id": "0198a4a2-0000-7000-8000-000000000902",
      "relationship_type_id": "0198a4a2-0000-7000-8000-000000000101",
      "source_resource_id": "0198a4a2-0000-7000-8000-000000000001",
      "target_resource_id": "0198a4a2-0000-7000-8000-000000000201",
      "direction": "outgoing",
      "confidence_score": "0.9500",
      "valid_from": "2026-08-19T14:20:00Z",
      "source": "cmdb",
      "created_at": "2026-08-19T14:21:00Z"
    }
  ]
}
```

`UUID`, `AwareDatetime`, `ApiDecimal`, and `None` reuse the common serialization policy. Decimal values are emitted as JSON strings to preserve precision, aware datetimes are emitted as ISO-8601 strings, and nullable fields such as `source` remain JSON `null`.

Malformed `tenant_id` or `resource_id` values are FastAPI transport validation errors. Missing resources and wrong-tenant resources are handled by application errors and centralized API error translation as the same non-disclosing `404 not_found` envelope. Persistence failures propagate to the centralized `503 service_unavailable` envelope without SQL, SQLSTATE, constraint names, or stack traces.

The relationships endpoint is separate from details and history. It does not call `GetResourceDetailsHandler`, `GetResourceDetailsQuery`, `GetResourceHistoryHandler`, `GetResourceHistoryQuery`, their providers, or perform N+1 secondary resource reads. It also does not automatically resolve canonical resources and does not call `ResolveCanonicalResourceHandler`, construct `ResolveCanonicalResourceQuery`, redirect, perform a second lookup against a canonical target, or replace requested/source/target ids.

This endpoint is read-only. It does not call `AssignResourceRelationshipHandler`, construct `AssignResourceRelationshipCommand`, or expose relationship create, update, patch, or delete behavior.

## Resource Identity And Canonical Resolution API

Stage `04.2.5` adds explicit Resource identity lookup routes and an explicit canonical-resolution route. These endpoints are read-only transport adapters over existing application query handlers. They do not introduce writes, mutations, generic identity resolver behavior, fuzzy search, partial search, pagination, redirects, caching, persistence access, new database models, migrations, or async SQLAlchemy.

The Stage `04.2.5` Resource read route inventory is:

```text
GET /api/v1/tenants/{tenant_id}/resources
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/history
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical
GET /api/v1/tenants/{tenant_id}/resource-lookups/canonical-name
GET /api/v1/tenants/{tenant_id}/resource-lookups/identifier
GET /api/v1/tenants/{tenant_id}/resource-lookups/alias
```

The canonical-name lookup endpoint is:

```http
GET /api/v1/tenants/{tenant_id}/resource-lookups/canonical-name?canonical_name=...
```

It maps request values exactly as:

```text
tenant_id + canonical_name
-> GetResourceByCanonicalNameQuery
-> get_get_resource_by_canonical_name_handler
-> GetResourceByCanonicalNameHandler
-> ResourceDetailsResult
-> resource_details_response(...)
-> ResourceDetailsResponse
```

The route passes `canonical_name` unchanged to the application query. It reuses `ResourceDetailsResponse` intentionally because the application result is a full resource details projection. It does not call `ResolveCanonicalResourceHandler`, construct `ResolveCanonicalResourceQuery`, redirect, or replace the matching resource with a canonical target.

The identifier lookup endpoint is:

```http
GET /api/v1/tenants/{tenant_id}/resource-lookups/identifier?identifier_type_id=...&normalized_value=...&namespace=...
```

It maps request values exactly as:

```text
tenant_id + identifier_type_id + namespace + normalized_value
-> FindResourceByIdentifierQuery
-> get_find_resource_by_identifier_handler
-> FindResourceByIdentifierHandler
-> ResourceIdentifierLookupResult
-> resource_identifier_lookup_response(...)
-> ResourceIdentifierLookupResponse
```

The route preserves `namespace=None` when the query parameter is omitted and preserves `namespace=""` when the parameter is present with an empty value. It passes `normalized_value` unchanged and does not trim, lower-case, hash, infer namespace, perform secondary lookup, or normalize input in the transport layer.

`ResourceIdentifierLookupResponse` has exactly:

| Field | Type |
| --- | --- |
| `resource` | `ResourceReadResponse` |
| `identifier_id` | `UUID` |
| `identifier_type_id` | `UUID` |
| `namespace` | `str | None` |
| `normalized_value` | `str` |
| `original_value` | `str` |
| `is_primary` | `bool` |

The alias lookup endpoint is:

```http
GET /api/v1/tenants/{tenant_id}/resource-lookups/alias?alias_type=...&normalized_value=...
```

It maps request values exactly as:

```text
tenant_id + alias_type + normalized_value
-> FindResourceByAliasQuery
-> get_find_resource_by_alias_handler
-> FindResourceByAliasHandler
-> ResourceAliasLookupResult
-> resource_alias_lookup_response(...)
-> ResourceAliasLookupResponse
```

The route passes `alias_type` and `normalized_value` unchanged. It does not normalize, trim, resolve aliases recursively, perform fuzzy search, or resolve the matched resource to a canonical target.

`ResourceAliasLookupResponse` has exactly:

| Field | Type |
| --- | --- |
| `resource` | `ResourceReadResponse` |
| `alias_id` | `UUID` |
| `alias_type` | `str` |
| `normalized_value` | `str` |
| `alias_value` | `str` |

The explicit canonical-resolution endpoint is:

```http
GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical
```

It maps request values exactly as:

```text
tenant_id + resource_id
-> ResolveCanonicalResourceQuery
-> get_resolve_canonical_resource_handler
-> ResolveCanonicalResourceHandler
-> CanonicalResourceResolvedResult
-> canonical_resource_resolved_response(...)
-> CanonicalResourceResolvedResponse
```

This endpoint returns `200 OK` JSON for both already-canonical and merged resources. It does not return an HTTP redirect, does not set a `Location` header, and does not mutate merge state. Application-owned canonical traversal, merge-depth behavior, cycle detection, and conflict semantics remain in the application handler. Conflicts propagate as `ConflictError` and are translated centrally to the stable `409 conflict` envelope.

`CanonicalResourceResolvedResponse` has exactly:

| Field | Type |
| --- | --- |
| `requested_resource_id` | `UUID` |
| `canonical_resource_id` | `UUID` |
| `immediate_target_resource_id` | `UUID | None` |
| `merge_depth` | `int` |
| `is_canonical` | `bool` |
| `canonical_resource` | `ResourceReadResponse` |

`ResourceReadResponse` is the compact embedded Resource shape used by lookup and canonical-resolution responses:

| Field | Type |
| --- | --- |
| `id` | `UUID` |
| `tenant_id` | `UUID` |
| `canonical_name` | `str` |
| `display_name` | `str | None` |

Example identifier lookup response:

```json
{
  "resource": {
    "id": "0198a4a2-0000-7000-8000-000000000001",
    "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
    "canonical_name": "app01.example.com",
    "display_name": "Application 01"
  },
  "identifier_id": "0198a4a2-0000-7000-8000-000000000901",
  "identifier_type_id": "0198a4a2-0000-7000-8000-000000000101",
  "namespace": null,
  "normalized_value": "asset-123",
  "original_value": "ASSET-123",
  "is_primary": true
}
```

Example alias lookup response:

```json
{
  "resource": {
    "id": "0198a4a2-0000-7000-8000-000000000001",
    "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
    "canonical_name": "app01.example.com",
    "display_name": null
  },
  "alias_id": "0198a4a2-0000-7000-8000-000000000902",
  "alias_type": "dns",
  "normalized_value": "app01",
  "alias_value": "APP01"
}
```

Example canonical resolution for an already-canonical resource:

```json
{
  "requested_resource_id": "0198a4a2-0000-7000-8000-000000000001",
  "canonical_resource_id": "0198a4a2-0000-7000-8000-000000000001",
  "immediate_target_resource_id": null,
  "merge_depth": 0,
  "is_canonical": true,
  "canonical_resource": {
    "id": "0198a4a2-0000-7000-8000-000000000001",
    "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
    "canonical_name": "app01.example.com",
    "display_name": "Application 01"
  }
}
```

Example canonical resolution for a merged resource:

```json
{
  "requested_resource_id": "0198a4a2-0000-7000-8000-000000000001",
  "canonical_resource_id": "0198a4a2-0000-7000-8000-000000000003",
  "immediate_target_resource_id": "0198a4a2-0000-7000-8000-000000000002",
  "merge_depth": 2,
  "is_canonical": false,
  "canonical_resource": {
    "id": "0198a4a2-0000-7000-8000-000000000003",
    "tenant_id": "0198a4a2-0000-7000-8000-000000000002",
    "canonical_name": "canonical.example.com",
    "display_name": "Canonical Resource"
  }
}
```

Malformed UUID path or query values remain FastAPI transport-validation errors. Missing resources, wrong-tenant resources, missing identifiers, and missing aliases propagate from application handlers through centralized `ApplicationError` mapping. The public API keeps `404 not_found`, `409 conflict`, and `503 service_unavailable` sanitized and does not expose SQL, constraint names, persistence adapter details, merge internals beyond the response contract, or cross-tenant existence details.

Existing list, details, history, relationships, canonical-name lookup, identifier lookup, and alias lookup routes are canonical-resolution-free. Only `GET /api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical` calls the canonical-resolution handler.

## Resource Command API

Stage `04.3` starts the production Resource Command API. Stage `04.3.1` adds exactly one production write endpoint:

```http
POST /api/v1/tenants/{tenant_id}/resources
```

The existing collection read endpoint remains on the same path with a different HTTP method:

```http
GET /api/v1/tenants/{tenant_id}/resources
```

FastAPI exposes both operations independently. No `PATCH`, `PUT`, `DELETE`, state transition, identifier assignment, alias assignment, ownership assignment, classification assignment, label assignment, relationship assignment, merge, bulk create, upsert, or delete endpoint is part of this stage.

The create route is a thin transport adapter:

```text
HTTP path + JSON body
-> FastAPI / Pydantic transport parsing
-> CreateResourceCommand
-> get_create_resource_handler
-> CreateResourceHandler
-> ResourceCreatedResult
-> resource_created_response(...)
-> ResourceCreatedResponse
-> 201 Created
```

`CreateResourceRequest` is API-owned and has exactly these body fields:

| Field | Type |
| --- | --- |
| `resource_type_id` | `UUID` |
| `canonical_name` | `str` |
| `display_name` | `str` |
| `lifecycle_status_id` | `UUID` |
| `criticality_id` | `UUID` |
| `exposure_level_id` | `UUID` |
| `source_priority` | `int` |
| `confidence_score` | `ApiDecimal` |
| `first_seen_at` | `AwareDatetime` |
| `last_seen_at` | `AwareDatetime` |

`tenant_id` is not a request body field. The route takes the authoritative tenant scope only from `/tenants/{tenant_id}` and passes that path value into the command. Body extras are not application authority and must not override the path tenant.

The route constructs the command explicitly field by field:

```python
CreateResourceCommand(
    tenant_id=tenant_id,
    resource_type_id=request.resource_type_id,
    canonical_name=request.canonical_name,
    display_name=request.display_name,
    lifecycle_status_id=request.lifecycle_status_id,
    criticality_id=request.criticality_id,
    exposure_level_id=request.exposure_level_id,
    source_priority=request.source_priority,
    confidence_score=request.confidence_score,
    first_seen_at=request.first_seen_at,
    last_seen_at=request.last_seen_at,
)
```

The route must not use `request.model_dump()`, `**kwargs`, reflection mapping, generic command factories, a command bus, mediator, handler registry, or service locator. The transport/application mapping must remain visible in route code.

`confidence_score` is passed as a `Decimal` without API rounding or float conversion. Precision-sensitive clients should send decimal-compatible JSON string values, for example `"0.123456789123456789123456789"`, because the current FastAPI/Pydantic JSON-number path does not preserve arbitrary precision before `Decimal` construction. The route does not implement a custom Decimal parser.

`first_seen_at` and `last_seen_at` use the shared `AwareDatetime` transport policy. Naive datetimes are rejected as transport validation errors. Accepted aware datetime values keep their offsets and are passed unchanged into `CreateResourceCommand`; the route does not inject UTC, convert to local machine timezone, strip offsets, or normalize timestamps.

Application handlers remain authoritative for business rules and persistence semantics: tenant existence, catalog existence and active-state checks, canonical-name uniqueness, source-priority rules, confidence-score bounds, and first-seen/last-seen temporal rules. The API layer only validates transport shape and scalar parsing.

The route depends on:

```python
handler: CreateResourceHandler = Depends(get_create_resource_handler)
```

It does not instantiate handlers directly, resolve `UnitOfWorkFactory`, import `SQLAlchemyUnitOfWork`, import repositories, open a Unit of Work, enter a transaction, retry, commit, roll back, or flush. `CreateResourceHandler` remains the sole transaction owner and performs the final commit under Block 03 semantics.

The response schema is `ResourceCreatedResponse`, matching `ResourceCreatedResult` exactly:

| Field | Type |
| --- | --- |
| `resource_id` | `UUID` |
| `tenant_id` | `UUID` |
| `canonical_name` | `str` |
| `record_version` | `int` |

Successful creation returns `201 Created` and the compact result only. The API does not return Resource Details, does not add `created_at`, `updated_at`, state, links, identifiers, metadata, or a read-after-write projection, and does not set a `Location` header in this stage.

Example request:

```json
{
  "resource_type_id": "0198a4a2-0000-7000-8000-000000000101",
  "canonical_name": "app01.example.com",
  "display_name": "Application 01",
  "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000102",
  "criticality_id": "0198a4a2-0000-7000-8000-000000000103",
  "exposure_level_id": "0198a4a2-0000-7000-8000-000000000104",
  "source_priority": 7,
  "confidence_score": "0.8750",
  "first_seen_at": "2026-08-19T12:00:00+00:00",
  "last_seen_at": "2026-08-19T15:30:00+03:00"
}
```

Example `201 Created` response:

```json
{
  "resource_id": "0198a4a2-0000-7000-8000-000000000201",
  "tenant_id": "0198a4a2-0000-7000-8000-000000000001",
  "canonical_name": "app01.example.com",
  "record_version": 1
}
```

After `handler.handle(command)`, the route returns directly from `ResourceCreatedResult`. It does not call `GetResourceDetailsHandler`, `GetResourceByIdHandler`, `ResolveCanonicalResourceHandler`, `ResourceQueryService`, repositories, or a second Unit of Work. There is no read-after-write enrichment or canonical resolution.

Application errors propagate to the centralized API error handler:

| Application error | HTTP policy |
| --- | --- |
| `ValidationError` | `422 validation_error` |
| `EntityNotFoundError` | `404 not_found` |
| `ConflictError` | `409 conflict` |
| `PersistenceError` | `503 service_unavailable` |

The canonical-name uniqueness conflict originates in the application handler and surfaces through the centralized `409 conflict` mapping. The route does not perform preflight canonical-name lookup, tenant lookup, catalog checks, duplicate checks, or route-local `try/except ApplicationError` handling.

The production Resource API operation inventory after Stage `04.3.1` is exactly:

```text
GET  /api/v1/tenants/{tenant_id}/resources
POST /api/v1/tenants/{tenant_id}/resources
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}/history
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical
GET  /api/v1/tenants/{tenant_id}/resource-lookups/canonical-name
GET  /api/v1/tenants/{tenant_id}/resource-lookups/identifier
GET  /api/v1/tenants/{tenant_id}/resource-lookups/alias
```

Stage `04.3.2` adds exactly one additional Resource command endpoint:

```http
POST /api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions
```

This endpoint exposes the existing application state-transition use case only:

```text
HTTP path + JSON body
-> FastAPI / Pydantic transport parsing
-> TransitionResourceStateCommand
-> get_transition_resource_state_handler
-> TransitionResourceStateHandler
-> ResourceStateTransitionedResult
-> resource_state_transitioned_response(...)
-> ResourceStateTransitionedResponse
-> 200 OK
```

No identifier assignment, ownership assignment, classification assignment, label assignment, alias assignment, relationship assignment, merge, bulk state transition, `PATCH`, `PUT`, state deletion, history mutation, ETag, `If-Match`, idempotency framework, post-transition details fetch, post-transition history fetch, or post-transition canonical resolution is part of this stage.

`TransitionResourceStateRequest` is API-owned and has exactly these body fields:

| Field | Type |
| --- | --- |
| `lifecycle_status_id` | `UUID` |
| `criticality_id` | `UUID` |
| `exposure_level_id` | `UUID` |
| `source_priority` | `int` |
| `confidence_score` | `ApiDecimal` |
| `transitioned_at` | `AwareDatetime` |
| `source` | `str | None` |

`tenant_id` and `resource_id` are not request body fields. They come only from the path and are the only authoritative identifiers for the command. The route has no ambient tenant, default tenant, global Resource, or query-parameter override.

The route constructs the command explicitly field by field:

```python
TransitionResourceStateCommand(
    tenant_id=tenant_id,
    resource_id=resource_id,
    lifecycle_status_id=request.lifecycle_status_id,
    criticality_id=request.criticality_id,
    exposure_level_id=request.exposure_level_id,
    source_priority=request.source_priority,
    confidence_score=request.confidence_score,
    transitioned_at=request.transitioned_at,
    source=request.source,
)
```

The route must not use `request.model_dump()`, `**kwargs`, reflection mapping, generic command factories, a command bus, mediator, handler registry, or service locator.

`confidence_score` follows the request-side Decimal convention established by Stage `04.3.1`: precision-sensitive clients should send decimal-compatible JSON string values, for example `"0.123456789123456789123456789"`. The route passes the accepted `Decimal` unchanged and does not convert through `float`, round, quantize, or normalize scale.

`transitioned_at` uses the shared `AwareDatetime` transport policy. Aware UTC and aware non-UTC timestamps are accepted and passed unchanged into the command. Naive datetimes are rejected as transport validation errors. The route does not inject a timezone, convert to server local timezone, strip offsets, or normalize the timestamp.

`source` is optional. When omitted, the command receives `None`. When a client explicitly sends `""`, the route preserves the empty string and leaves any rejection to the application layer. The route does not trim, normalize, or replace source values with defaults.

Application handlers remain authoritative for Resource existence, tenant scope, lifecycle status validity, criticality validity, exposure validity, source-priority rules, confidence-score rules, transition timestamp invariants, current-state replacement semantics, temporal closeout behavior, and conflict/concurrency rules. The API layer only validates HTTP shape and scalar parsing.

The route depends on:

```python
handler: TransitionResourceStateHandler = Depends(
    get_transition_resource_state_handler
)
```

It does not instantiate handlers directly, resolve `UnitOfWorkFactory`, import `SQLAlchemyUnitOfWork`, import repositories, open a Unit of Work, start a transaction, lock rows, retry, commit, roll back, flush, read current state directly, or close current state directly. `TransitionResourceStateHandler` remains the sole transaction owner.

The response schema is `ResourceStateTransitionedResponse`, matching `ResourceStateTransitionedResult` exactly:

| Field | Type |
| --- | --- |
| `resource_id` | `UUID` |
| `previous_state_id` | `UUID | None` |
| `new_state_id` | `UUID` |
| `transitioned_at` | `AwareDatetime` |

Successful state transition returns `200 OK` and the compact transition result. The API does not add `tenant_id`, lifecycle status, criticality, exposure, source priority, confidence, a full state object, Resource Details, links, or metadata.

Example request:

```json
{
  "lifecycle_status_id": "0198a4a2-0000-7000-8000-000000000101",
  "criticality_id": "0198a4a2-0000-7000-8000-000000000102",
  "exposure_level_id": "0198a4a2-0000-7000-8000-000000000103",
  "source_priority": 11,
  "confidence_score": "0.8750",
  "transitioned_at": "2026-08-20T10:30:00+00:00",
  "source": "cmdb"
}
```

Example `200 OK` response:

```json
{
  "resource_id": "0198a4a2-0000-7000-8000-000000000201",
  "previous_state_id": null,
  "new_state_id": "0198a4a2-0000-7000-8000-000000000202",
  "transitioned_at": "2026-08-20T10:30:00+00:00"
}
```

After `handler.handle(command)`, the route returns directly from `ResourceStateTransitionedResult`. It does not call `GetResourceDetailsHandler`, `GetResourceHistoryHandler`, `GetResourceByIdHandler`, `ResolveCanonicalResourceHandler`, `ResourceQueryService`, repositories, or a second Unit of Work. There is no read-after-write enrichment, history fetch, details projection, or canonical resolution.

Application errors propagate to the centralized API error handler:

| Application error | HTTP policy |
| --- | --- |
| `ValidationError` | `422 validation_error` |
| `EntityNotFoundError` | `404 not_found` |
| `TenantBoundaryError` | `404 not_found` |
| `ConflictError` | `409 conflict` |
| `ConcurrentModificationError` | `409 concurrent_modification` |
| `PersistenceError` | `503 service_unavailable` |

`ConcurrentModificationError` remains distinct from generic conflict handling at the centralized error boundary. The route does not add ETag, `If-Match`, version headers, or local application-error translation.

The production Resource API operation inventory after Stage `04.3.2` is exactly:

```text
GET  /api/v1/tenants/{tenant_id}/resource-lookups/canonical-name
GET  /api/v1/tenants/{tenant_id}/resource-lookups/identifier
GET  /api/v1/tenants/{tenant_id}/resource-lookups/alias
GET  /api/v1/tenants/{tenant_id}/resources
POST /api/v1/tenants/{tenant_id}/resources
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}
POST /api/v1/tenants/{tenant_id}/resources/{resource_id}/state-transitions
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}/history
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}/relationships
GET  /api/v1/tenants/{tenant_id}/resources/{resource_id}/canonical
```

## OpenAPI Policy

OpenAPI tags, operation ids, status codes, examples, and schema metadata belong to API modules only. Application commands, queries, handlers, and results must remain unaware of OpenAPI. Stage `04.1.3` only verifies that common schemas can be included in generated OpenAPI components; operation metadata hardening remains deferred.

## Safeguards

Architecture tests enforce:

- application modules do not import FastAPI, Pydantic, Starlette, API modules, or concrete persistence;
- API route modules do not import SQLAlchemy APIs, ORM models, `app.db`, or concrete persistence;
- API schemas are Pydantic transport contracts and not ORM-backed response models;
- API schema and mapper modules do not import SQLAlchemy, ORM models, or persistence adapters;
- API mappers are API-owned and explicitly map application result fields into response schemas;
- broad `from_attributes=True` ORM serialization is not introduced;
- generic serializer registries or reflection mappers are not introduced;
- offset, page-number, total-count, and total-pages pagination models are not introduced;
- API error schemas contain no `constraint`, `sql`, `sqlstate`, `traceback`, `exception`, or `cause` fields;
- API error modules do not import SQLAlchemy, `app.persistence`, or `app.db`;
- route modules do not catch `ApplicationError` locally;
- application exception handlers are registered centrally from bootstrap;
- `ConcurrentModificationError` has specific mapping and is not shadowed by `ConflictError`;
- tenant-boundary mapping is not more revealing than ordinary not-found;
- persistence wiring inside the API package is confined to `app.api.composition`;
- explicit provider functions exist for the current Resource handler inventory;
- provider return annotations are concrete application handler types;
- provider parameters depend on `UnitOfWorkFactory` through `Depends(get_unit_of_work_factory)`;
- providers do not open sessions, enter Unit of Work contexts, or call `commit()`, `rollback()`, or `flush()`;
- handler providers produce fresh instances and no global handler singletons are introduced;
- `main.py` stays bootstrap-oriented;
- the FastAPI app imports and keeps `/` and `/health` working;
- the `/api/v1` production Resource operation inventory contains only list, create, state transition, details, history, relationships, explicit canonical resolution, and three static Resource lookup routes;
- the Resource create route calls only `CreateResourceHandler`, constructs only `CreateResourceCommand`, returns `201 Created`, and maps only `ResourceCreatedResult`;
- the Resource create request schema has no `tenant_id` body field and uses the path tenant as the only authoritative tenant source;
- the Resource create route does not open transactions, call `commit()`, `rollback()`, or `flush()`, perform preflight reads, or read after write;
- the Resource state-transition route calls only `TransitionResourceStateHandler`, constructs only `TransitionResourceStateCommand`, returns `200 OK`, and maps only `ResourceStateTransitionedResult`;
- the Resource state-transition request schema has no `tenant_id` or `resource_id` body fields and uses path identifiers as the only authoritative identifiers;
- the Resource state-transition route does not open transactions, call `commit()`, `rollback()`, or `flush()`, read current state directly, perform preflight reads, read after write, or invoke unrelated write handlers;
- Resource details, history, relationships, and lookup routes do not import or call canonical resolution handlers, queries, or providers;
- the Resource history route does not call Resource details handlers, queries, or providers;
- the Resource relationships route does not call Resource details handlers, Resource history handlers, canonical resolution handlers, relationship write handlers, or graph traversal helpers;
- the Resource canonical route calls only `ResolveCanonicalResourceHandler`, constructs only `ResolveCanonicalResourceQuery`, returns JSON, and does not redirect;
- Resource lookup routes are static `/resource-lookups/...` routes and are included before dynamic Resource id routes;
- Resource lookup routes preserve provided query strings and do not normalize, trim, hash, enrich, or canonical-resolve input;
- Resource routes use API-owned response models and do not call transaction methods;
- command bus, mediator, handler registry, and service locator patterns are not introduced.

## Deferred Work

Stage `04.1` is complete, Stage `04.2` has list, details, history, relationships, identity lookup, and explicit canonical-resolution Resource read endpoints, and Stage `04.3` has Resource creation and state-transition command endpoints. The next planned step is `04.3.3 — Implement Resource Identifier Assignment API`. Deferred work includes additional write endpoints, full endpoint OpenAPI response metadata, request-validation envelope normalization if needed, authentication, authorization, rate limiting, caching, background jobs, event buses, collectors, findings, DefectDojo integrations, AI features, GraphQL, WebSockets, and async SQLAlchemy.
