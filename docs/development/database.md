# Database development

## Scope

The database foundation introduces SQLAlchemy 2.x typed declarative models and Alembic schema management for the first Resource Inventory entities:

- `tenant`
- `organization`
- `resource_type`
- `identifier_type`
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

## UUIDv7 and timestamps

Major entity primary keys use a centralized UUIDv7 generator in `app.db.uuid`. Application-side ID defaults make IDs available before flush when the object is constructed through SQLAlchemy defaults.
The generator is protected by a process-local lock. If the 12-bit monotonic sequence is exhausted within one millisecond, generation waits for the next clock millisecond rather than wrapping the sequence.

Timestamp columns use PostgreSQL `TIMESTAMPTZ` via SQLAlchemy timezone-aware `DateTime`. Application defaults use UTC-aware datetimes for `created_at` and `updated_at`.
All managed catalog models use the same timestamp policy.

## Organization hierarchy

The database rejects direct self-parenting through `parent_organization_id IS NULL OR parent_organization_id <> id`. More complex hierarchy cycles, such as `A -> B -> A`, are intentionally deferred to the application or service layer in a later stage.

## Catalog seed

Run:

- `make db-seed`

The seed inserts only a minimal baseline for managed reference catalogs. It is idempotent, deterministic by catalog `code`, and does not overwrite existing catalog rows.
If a seeded system catalog `code` already exists with a different deterministic UUID, the seed exits with a clear conflict error instead of creating a duplicate or silently accepting the mismatch. Inserts use PostgreSQL conflict handling so concurrent seed runs do not create duplicate rows.

## Tests

Run:

- `make db-test`

Database tests create and destroy an isolated `resource_monitoring_test` database. They do not use the normal development database for destructive migration checks.
