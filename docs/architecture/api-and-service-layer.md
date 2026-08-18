# API Architecture and Transport Boundaries

## Purpose

Stage `04.1.1` defines the first API and service-layer architecture baseline. It does not introduce production Resource endpoints. The baseline establishes where FastAPI code lives, how HTTP transport code will call application handlers, how application errors will be translated to HTTP responses, and which dependencies are forbidden across boundaries.

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

`router.py` composes FastAPI routers. `routes/system.py` owns the existing `/` and `/health` endpoints. `schemas.py` owns Pydantic transport response contracts used by those endpoints. `errors.py` records the HTTP status policy for application errors. `composition.py` is the explicit boundary where future FastAPI dependencies may wire application handlers to `SQLAlchemyUnitOfWork`.

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

## Composition Boundary

Runtime composition is explicit. Future routes should receive a handler directly or through a small FastAPI dependency that builds the handler from:

```text
SQLAlchemyUnitOfWork / UnitOfWorkFactory
-> explicit application Handler
-> route handler
```

`app.api.composition` is the allowed API-side location for wiring concrete persistence adapters into application handlers. Route modules should depend on application commands, queries, results, handlers, and API schemas rather than concrete SQLAlchemy repositories.

No command bus, mediator, handler registry, service locator, automatic handler discovery, generic IoC framework, or auto-scanning mechanism is part of this baseline.

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

## Serialization Policy

API serializers own JSON representation decisions:

| Application value | JSON representation |
| --- | --- |
| `UUID` | UUID string |
| aware `datetime` | ISO-8601 string with timezone offset |
| `Decimal` | string, to preserve precision and avoid binary floating point drift |
| opaque cursor | unchanged string |
| tuple | JSON array |

OpenAPI tags, operation ids, status codes, examples, and schema metadata belong to API modules only. Application commands, queries, handlers, and results must remain unaware of OpenAPI.

## Safeguards

Architecture tests enforce:

- application modules do not import FastAPI, Pydantic, Starlette, API modules, or concrete persistence;
- API route modules do not import SQLAlchemy APIs, ORM models, `app.db`, or concrete persistence;
- API schemas are Pydantic transport contracts and not ORM-backed response models;
- persistence wiring inside the API package is confined to `app.api.composition`;
- `main.py` stays bootstrap-oriented;
- the FastAPI app imports and keeps `/` and `/health` working;
- the `/api/v1` router baseline is composable without Resource endpoints;
- command bus, mediator, handler registry, and service locator patterns are not introduced.

## Deferred Work

Deferred work includes production Resource endpoints, full Resource request/response schemas, complete error response bodies, exception handler registration, authentication, authorization, rate limiting, caching, background jobs, event buses, collectors, findings, DefectDojo integrations, AI features, GraphQL, WebSockets, and async SQLAlchemy.
