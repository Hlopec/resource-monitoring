# API Architecture and Transport Boundaries

## Purpose

Stage `04.1.1` defines the first API and service-layer architecture baseline. Stage `04.1.2` adds explicit FastAPI dependency wiring for the existing Block 03 Resource handlers without adding production Resource endpoints. The baseline establishes where FastAPI code lives, how HTTP transport code will call application handlers, how application errors will be translated to HTTP responses, and which dependencies are forbidden across boundaries.

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
    system.py
  schemas.py
```

`router.py` composes FastAPI routers. `routes/system.py` owns the existing `/` and `/health` endpoints. `schemas.py` owns Pydantic transport contracts, reusable scalar serialization policy, the Resource summary response, and the Resource cursor page envelope. `mappers/resources.py` owns explicit Resource application-result to API-schema mapping. `errors.py` records the HTTP status policy for application errors. `composition.py` is the explicit composition root where FastAPI dependencies wire application handlers to the application-facing `UnitOfWorkFactory`.

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

Full Resource request and response schemas are deferred until production Resource endpoints are implemented.

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

The current reusable Resource transport shape is `ResourceSummaryResponse`, matching `ResourceSummaryResult` exactly:

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

Application errors are mapped at the API boundary:

| Application error | HTTP policy |
| --- | --- |
| `ValidationError` | `422 Unprocessable Entity` |
| `EntityNotFoundError` | `404 Not Found` |
| `ConflictError` | `409 Conflict` |
| `ConcurrentModificationError` | `409 Conflict` |
| `TenantBoundaryError` | `404 Not Found` |
| `PersistenceError` | `503 Service Unavailable` |

HTTP responses must not expose SQLAlchemy exception types, PostgreSQL constraint names, raw SQL, stack traces, or cross-tenant existence details. Error messages may describe the application-level failure but must not reveal whether a missing tenant-scoped entity exists in another tenant.

This stage records the policy in `app.api.errors`; full exception handler registration and response body contracts are deferred until production endpoints need them.

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
- persistence wiring inside the API package is confined to `app.api.composition`;
- explicit provider functions exist for the current Resource handler inventory;
- provider return annotations are concrete application handler types;
- provider parameters depend on `UnitOfWorkFactory` through `Depends(get_unit_of_work_factory)`;
- providers do not open sessions, enter Unit of Work contexts, or call `commit()`, `rollback()`, or `flush()`;
- handler providers produce fresh instances and no global handler singletons are introduced;
- `main.py` stays bootstrap-oriented;
- the FastAPI app imports and keeps `/` and `/health` working;
- the `/api/v1` router baseline is composable without Resource endpoints;
- command bus, mediator, handler registry, and service locator patterns are not introduced.

## Deferred Work

Deferred work includes `04.1.4` application error to HTTP mapping, production Resource endpoints, full Resource details/history/relationship schema families, complete error response bodies, OpenAPI operation metadata hardening, authentication, authorization, rate limiting, caching, background jobs, event buses, collectors, findings, DefectDojo integrations, AI features, GraphQL, WebSockets, and async SQLAlchemy.
