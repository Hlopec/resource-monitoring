# Database development

## Scope

The database foundation introduces SQLAlchemy 2.x typed declarative models and Alembic schema management for the first Resource Inventory entities:

- `tenant`
- `organization`
- `resource_type`
- `identifier_type`
- `lifecycle_status`
- `criticality`
- `exposure_level`
- `resource`
- `resource_identifier`
- `ownership_role`
- `relationship_type`
- `classification_type`
- `classification_value`

Global managed catalogs do not contain `tenant_id`. Tenant-domain rows remain tenant-scoped. `organization_type_id` is intentionally not implemented yet because the corresponding catalog is outside Issue #10.

## Settings

Database settings are read from environment variables or `.env`:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

The application builds a SQLAlchemy URL from typed settings. Secrets are not committed.
`POSTGRES_PASSWORD` is required at runtime. Local development values live in `.env.example`; application settings fail fast when the password is absent.
Docker Compose passes the `POSTGRES_*` settings into the API container so Alembic, tests, and seed commands use the same typed settings as application code.

## Migrations

Schema changes are managed only through Alembic. The API does not call `create_all()` during startup.

Use:

- `make db-upgrade`
- `make db-downgrade`
- `make db-current`
- `make db-history`

`make db-downgrade` returns the database to the Alembic base state.
The resource identifier migration depends on revision `202607300001`; downgrading one step returns the schema to the Issue #10 foundation revision.

## UUIDv7 and timestamps

Major entity primary keys use a centralized UUIDv7 generator in `app.db.uuid`. Application-side ID defaults make IDs available before flush when the object is constructed through SQLAlchemy defaults.
The generator is protected by a process-local lock. If the 12-bit monotonic sequence is exhausted within one millisecond, generation waits for the next clock millisecond rather than wrapping the sequence.

Timestamp columns use PostgreSQL `TIMESTAMPTZ` via SQLAlchemy timezone-aware `DateTime`. Application defaults use UTC-aware datetimes for `created_at` and `updated_at`.
All managed catalog models use the same timestamp policy.

## Resource records

`resource` stores the current canonical resource state. It has tenant-aware identity through `UNIQUE (tenant_id, id)` and restrictive foreign keys to `tenant`, `resource_type`, `lifecycle_status`, `criticality`, and `exposure_level`.

`source_priority` is constrained to `0..1000`. Lower-level prioritization policy is deferred to ingestion or service code. `confidence_score` is constrained to `0.0000..1.0000`. `record_version` starts at `1` and is reserved for optimistic concurrency, but service-layer update logic is outside this stage.

Resource archive behavior is logical. `archived_at` records archive state without hard deleting the row.

## Resource identifiers

`resource_identifier` rows are tenant-owned temporal immutable facts. They use a tenant-aware composite foreign key so `(tenant_id, resource_id)` must reference a resource in the same tenant. Resource deletes are restrictive and do not cascade into identifier history.

Current identifier uniqueness is enforced by a PostgreSQL partial unique expression index over `tenant_id`, `identifier_type_id`, `COALESCE(namespace, '')`, and `normalized_value` where `valid_to IS NULL`. This defines null namespace semantics explicitly: `NULL` namespace is normalized to the empty namespace for uniqueness checks.

Current primary identifier uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `resource_id`, and `identifier_type_id` where `is_primary = true AND valid_to IS NULL`. Historical primary identifiers with `valid_to` set remain preserved.

`value_hash` is a lookup accelerator only. It is not collision-proof identity. Matching logic must perform a full `normalized_value` comparison after hash lookup, and distinct normalized values with the same hash are allowed.

`resource_identifier` is modeled as a temporal fact, not as a mutable current-state row. Changing identity fields on an existing row is not the recommended operation. The intended application-level policy is to close the old row by setting `valid_to` and insert a new row with the replacement identity evidence. At this stage the database enforces the validity window, current-row uniqueness, and restrictive foreign keys; it does not add a trigger-based immutable framework.

The table intentionally has `created_at` without `updated_at` because identifier rows are append-oriented temporal facts. Subsequent corrections should be represented by new temporal rows instead of in-place identity mutation.

## Organization hierarchy

The database rejects direct self-parenting through `parent_organization_id IS NULL OR parent_organization_id <> id`. More complex hierarchy cycles, such as `A -> B -> A`, are intentionally deferred to the application or service layer in a later stage.

## Catalog seed

Run:

- `make db-seed`

The seed inserts only a minimal baseline for managed reference catalogs. It is idempotent, deterministic by catalog `code`, and does not overwrite existing catalog rows.
If a seeded system catalog `code` already exists with a different deterministic UUID, the seed exits with a clear conflict error instead of creating a duplicate or silently accepting the mismatch. Inserts use PostgreSQL conflict handling so concurrent seed runs do not create duplicate rows.
Baseline seed data now includes lifecycle statuses (`active`, `inactive`, `archived`), criticalities (`low`, `medium`, `high`, `critical`), and exposure levels (`internal`, `restricted`, `public`).

## Tests

Run:

- `make db-test`

Database tests create and destroy an isolated `resource_monitoring_test` database. They do not use the normal development database for destructive migration checks.
