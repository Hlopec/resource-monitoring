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
- `resource_alias`
- `resource_ownership`
- `resource_relationship`
- `resource_classification`
- `label`
- `resource_label`
- `resource_state`
- `resource_merge`
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

## Sessions and Unit of Work

`app.db.session` owns the shared synchronous SQLAlchemy engine and central `SessionLocal` factory. The factory uses `expire_on_commit=False` and is reused by framework helpers, scripts, and the SQLAlchemy Unit of Work. Unit of Work instances create sessions from an injected factory; tests inject their isolated `sessionmaker`, while production wiring uses the shared `SessionLocal`.

Application command workflows should use `app.persistence.sqlalchemy.SQLAlchemyUnitOfWork`. It is a single-use context manager with explicit `commit()` and `rollback()`. Exiting without a successful explicit commit rolls back. Exceptions trigger rollback and propagate unchanged. The Unit of Work closes its session on exit and does not dispose the shared engine.

`get_session()` remains available for lower-level framework integration. `transaction_session()` remains available for current low-level compatibility paths and scripts, but it is not the application-core transaction abstraction for future use cases.

Shared internal repository primitives live under `app.persistence.sqlalchemy.repositories`. Concrete SQLAlchemy repositories should receive the active `SQLAlchemyUnitOfWork.session` by constructor injection or the small internal `bind_repository(...)` helper. Repositories must not create sessions or engines, commit, roll back, close the shared session, dispose the engine, or create independent transaction boundaries.

Concrete Tenant, Organization, Label, Resource, managed catalog, temporal fact, and lineage adapters are available under `app.persistence.sqlalchemy.repositories`. `SQLAlchemyUnitOfWork` exposes `uow.tenants`, `uow.organizations`, `uow.labels`, `uow.resources`, `uow.resource_types`, `uow.identifier_types`, `uow.relationship_types`, `uow.ownership_roles`, `uow.classification_types`, `uow.classification_values`, `uow.lifecycle_statuses`, `uow.criticalities`, `uow.exposure_levels`, `uow.resource_identifiers`, `uow.resource_ownerships`, `uow.resource_relationships`, `uow.resource_classifications`, `uow.resource_labels`, `uow.resource_states`, `uow.resource_aliases`, and `uow.resource_merges` while the Unit of Work is active. These repositories share the Unit of Work session and are unavailable before enter, after exit, and after the Unit of Work leaves the active state.

```python
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

with SQLAlchemyUnitOfWork() as uow:
    tenant = uow.tenants.get_by_slug("example")
    if tenant is not None:
        children = uow.organizations.list_children(
            tenant.id,
            parent_organization_id,
        )
```

```python
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

with SQLAlchemyUnitOfWork() as uow:
    resource = uow.resources.get_for_update(
        tenant_id,
        resource_id,
    )
    if resource is not None:
        resource.display_name = "Updated"
        uow.commit()
```

```python
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

with SQLAlchemyUnitOfWork() as uow:
    resource_type = uow.resource_types.get_by_code("domain")
    lifecycle = uow.lifecycle_statuses.get_by_code("active")
    values = uow.classification_values.list_active_for_type(
        classification_type_id,
    )
```

```python
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

with SQLAlchemyUnitOfWork() as uow:
    current_state = uow.resource_states.get_current(
        tenant_id,
        resource_id,
    )
    history = uow.resource_states.list_history(
        tenant_id,
        resource_id,
    )
```

```python
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

with SQLAlchemyUnitOfWork() as uow:
    resource = uow.resource_aliases.find_resource_by_alias(
        tenant_id,
        "dns_name",
        "example.com",
    )
    incoming_merges = uow.resource_merges.list_incoming_merges(
        tenant_id,
        resource_id,
    )
```

The base repository supports only internal persistence operations: add an entity to the active session, explicitly flush pending work, explicitly refresh an entity, and evaluate prepared scalar, sequence, or existence statements. `add(...)` does not commit. `flush()` is available only for operations that need generated/default values, early constraint validation, or dependent writes; failed flushes remain part of the Unit of Work transaction and are cleaned up by Unit of Work rollback/exit behavior.

Tenant-owned repository infrastructure uses helpers that require explicit `tenant_id` and apply tenant predicates centrally. Tenant-owned id lookup is always built with both `tenant_id` and entity `id`; there is no optional tenant scope, unscoped fallback, administrative bypass flag, or ambient tenant context. `SQLAlchemyOrganizationRepository` applies tenant scope to id lookup, canonical-name lookup, external-key lookup, existence checks, and direct-child listing. `SQLAlchemyLabelRepository` applies tenant scope to id lookup, key/value lookup, key/value existence checks, and active label listing. `SQLAlchemyResourceRepository` applies tenant scope to id lookup, canonical-name lookup, existence checks, and explicit lock-oriented lookup. Direct organization children are returned in stable `canonical_name, id` order. Active labels are returned in stable `key, value, id` order. Resource canonical names are not currently unique, so canonical-name lookup uses stable `canonical_name, id` scalar ordering.

Managed catalog repositories are global and non-tenant-scoped. `SQLAlchemyManagedCatalogRepository` supports read-only id lookup, exact code lookup, and active listing for `ResourceType`, `IdentifierType`, `RelationshipType`, `OwnershipRole`, `ClassificationType`, `LifecycleStatus`, `Criticality`, and `ExposureLevel`. `SQLAlchemyClassificationValueRepository` supports read-only id lookup, type-and-code lookup, and active listing by `classification_type_id`. All current catalog models use `is_active`; active lists filter on that column and order by `code, id` because no catalog table currently has `sort_order`. The adapters do not expose `add`, `flush`, commit, rollback, generic filtering, pagination, or catalog administration behavior.

Temporal fact repositories live in `app.persistence.sqlalchemy.repositories.temporal`. They map `ResourceIdentifierRepository`, `ResourceOwnershipRepository`, `ResourceRelationshipRepository`, `ResourceClassificationRepository`, `ResourceLabelRepository`, and `ResourceStateRepository` to SQLAlchemy adapters. Current reads use the schema predicate `valid_to IS NULL` plus explicit tenant and domain predicates. `ResourceIdentifierRepository.find_current_by_value(...)` performs exact tenant/type/namespace/normalized-value lookup. `ResourceIdentifierRepository.get_current_primary(...)` uses the schema-defined primary scope of `tenant_id`, `resource_id`, and `identifier_type_id`. `ResourceOwnershipRepository.find_current(...)` performs exact tenant/resource/organization/role lookup. `ResourceOwnershipRepository.get_current_primary(...)` uses the schema-defined primary scope of `tenant_id`, `resource_id`, and `ownership_role_id`. `ResourceRelationshipRepository.find_current(...)` performs exact tenant/source/type/target lookup. `ResourceClassificationRepository.find_current(...)` performs exact tenant/resource/type/value lookup. `ResourceClassificationRepository.get_current_primary(...)` uses the schema-defined primary scope of `tenant_id`, `resource_id`, and `classification_type_id`. `ResourceLabelRepository.find_current(...)` performs exact tenant/resource/label lookup. `ResourceStateRepository.list_history(...)` returns current and closed state rows ordered by `valid_from, id`; other temporal contracts do not currently expose history methods.

Temporal repositories are append/read only. `add(...)` attaches a new temporal fact row to the active Unit of Work session without flushing, committing, rolling back, closing previous rows, rewriting history, or deleting history. Current collection ordering is deterministic: identifiers by `identifier_type_id, namespace, normalized_value, id`; ownership by `ownership_role_id, is_primary DESC, organization_id, id`; relationships by relationship type plus opposite endpoint and id; classifications by `classification_type_id, classification_value_id, id`; labels by `label_id, id`. PostgreSQL continues to enforce current-row uniqueness, `valid_to > valid_from`, tenant-consistent resource references, relationship endpoint constraints, classification type/value consistency, label assignment consistency, and state uniqueness. Commit-time persistence error translation maps only explicitly recognized SQLSTATE and constraint-name combinations; explicit lower-level flush failures may still propagate as raw SQLAlchemy/database errors.

Lineage repositories live in `app.persistence.sqlalchemy.repositories.lineage`. `SQLAlchemyResourceAliasRepository` maps `ResourceAliasRepository` to exact tenant-scoped alias lookup and direct resource alias listing. Alias lookup uses the caller-provided string `alias_type` and precomputed `normalized_value`; it does not normalize input, search identifiers, follow merge chains, or resolve canonical resources. Alias listing returns rows for the direct resource ordered by `alias_type, normalized_value, id`.

`SQLAlchemyResourceMergeRepository` maps `ResourceMergeRepository` to direct outgoing and incoming merge-edge persistence. Outgoing lookup is scoped by tenant and source resource; incoming listing is scoped by tenant and target resource and ordered by `merged_at, id`. The repository does not execute merges, transfer aliases, rewrite temporal facts, update resources, traverse merge chains, or materialize canonical resources.

Lineage repositories are append/read only. `add(...)` attaches `ResourceAlias` or `ResourceMerge` rows to the active Unit of Work session without flushing, committing, rolling back, or translating database exceptions. PostgreSQL continues to enforce alias uniqueness, tenant-consistent resource references, alias seen-window checks, merge endpoint references, self-merge rejection, one outgoing merge per source, and merge cycle prevention.

Loading and locking are explicit. Repository helpers may apply concrete loader options selected for a specific operation, but there is no blanket eager loading or include/expand framework. `SELECT ... FOR UPDATE` is opt-in through `SQLAlchemyResourceRepository.get_for_update(...)` and is not applied to normal resource reads. Optimistic concurrency remains model-specific: `resource.record_version` is mapped as SQLAlchemy's `version_id_col`, and repository infrastructure preserves normal `StaleDataError` behavior without translating or manually incrementing version columns.

Repositories remain transaction-neutral and do not translate errors. `SQLAlchemyUnitOfWork.commit()` owns transaction completion and translates known commit failures through `app.persistence.sqlalchemy.errors`. The boundary is:

```text
Application Handler
    ↓
UnitOfWork.commit()
    ↓
SQLAlchemy/PostgreSQL
    ↓
Persistence translator
    ↓
Technology-neutral ApplicationError
```

The translator uses stable exception type, SQLSTATE, and PostgreSQL constraint-name metadata. It does not parse human-readable database messages. Translated errors retain the original SQLAlchemy/database exception as `__cause__`. Unknown or unmapped persistence errors continue to propagate unchanged; for example, duplicate tenant slugs and missing resource foreign keys are not currently mapped to application conflicts.

Mapped current-row and lineage uniqueness violations use PostgreSQL SQLSTATE `23505` plus exact constraint names. `Resource` optimistic concurrency uses SQLAlchemy `StaleDataError`, produced by the mapped `record_version` `version_id_col`, and is translated to `ConcurrentModificationError`. No automatic retry is added for deadlocks, serialization failures, optimistic conflicts, or uniqueness conflicts. Future transport code owns HTTP mapping for application errors.

## Migrations

Schema changes are managed only through Alembic. The API does not call `create_all()` during startup.

The consolidated Stage `02.0` integrity audit is documented in `docs/architecture/database/resource-inventory-audit.md`. It records table-level constraints, tenant isolation, temporal semantics, index decisions, scaling assumptions, accepted trade-offs, and deferred service-layer responsibilities.

Use:

- `make db-upgrade`
- `make db-downgrade`
- `make db-current`
- `make db-history`

`make db-downgrade` returns the database to the Alembic base state.
The resource identifier migration depends on revision `202607300001`; the resource ownership migration depends on revision `202607300002`; the resource relationship migration depends on revision `202607300003`; the resource classification migration depends on revision `202607300004`; the resource labels migration depends on revision `202607300005`; the resource state migration depends on revision `202607300006`; the resource merge and alias migration depends on revision `202607300007`.

## UUIDv7 and timestamps

Major entity primary keys use a centralized UUIDv7 generator in `app.db.uuid`. Application-side ID defaults make IDs available before flush when the object is constructed through SQLAlchemy defaults.
The generator is protected by a process-local lock. If the 12-bit monotonic sequence is exhausted within one millisecond, generation waits for the next clock millisecond rather than wrapping the sequence.

Timestamp columns use PostgreSQL `TIMESTAMPTZ` via SQLAlchemy timezone-aware `DateTime`. Application defaults use UTC-aware datetimes for `created_at` and `updated_at`.
All managed catalog models use the same timestamp policy.

## Resource records

`resource` stores the current canonical resource state snapshot. It has tenant-aware identity through `UNIQUE (tenant_id, id)` and restrictive foreign keys to `tenant`, `resource_type`, `lifecycle_status`, `criticality`, and `exposure_level`.

`source_priority` is constrained to `0..1000`. Lower-level prioritization policy is deferred to ingestion or service code. `confidence_score` is constrained to `0.0000..1.0000`. `record_version` starts at `1` and is reserved for optimistic concurrency, but service-layer update logic is outside this stage.

Resource archive behavior is logical. `archived_at` records archive state without hard deleting the row.

## Resource state history

`resource_state` stores tenant-owned temporal history for the snapshot state fields kept on `resource`: `lifecycle_status_id`, `criticality_id`, `exposure_level_id`, `source_priority`, and `confidence_score`. The resource snapshot remains the fast current read model; `resource_state` is the auditable history model. The intended invariant is that the mutable `resource` state snapshot equals the current `resource_state` row where `valid_to IS NULL`.

The table uses a tenant-aware composite foreign key so `(tenant_id, resource_id)` references `resource(tenant_id, id)`. Reference catalog fields point to the global `lifecycle_status`, `criticality`, and `exposure_level` catalogs. Deletes of referenced resources and catalog rows are restrictive so state history is not removed implicitly.

A current state row has `valid_to IS NULL`; historical rows keep their validity window. The database enforces exactly one current state per resource with a tenant-first partial unique index over `tenant_id` and `resource_id` where `valid_to IS NULL`. State changes follow an append-oriented policy: close the old current row with `valid_to`, insert the new state row, and update the `resource` snapshot in the application layer. The database intentionally does not add triggers for this workflow.

The migration backfills one current `resource_state` row for each existing `resource` using the current resource snapshot values. `first_seen_at` becomes deterministic `valid_from`, `valid_to` is `NULL`, and `source` is `migration_backfill`. Downgrade removes `resource_state` without modifying the resource snapshot fields.

Additional database checks require non-negative `source_priority`, `confidence_score` in `0.0000..1.0000`, `valid_to > valid_from` when `valid_to` is present, and non-empty source text using `btrim(source)` when `source` is not null.

### Resource State Transition Command

`TransitionResourceStateHandler` owns the current resource-state replacement workflow at the application layer. The command fields are `tenant_id`, `resource_id`, `lifecycle_status_id`, `criticality_id`, `exposure_level_id`, `source_priority`, `confidence_score`, `transitioned_at`, and nullable `source`.

The handler validates command-only values before opening a Unit of Work: `source_priority` must be `0..1000` to remain compatible with the `resource` snapshot constraint, `confidence_score` must be `0..1`, `transitioned_at` must be timezone-aware, and non-null `source` must not be blank. It then opens one fresh Unit of Work, locks the tenant-scoped `resource` row with `uow.resources.get_for_update(...)`, validates active global lifecycle, criticality, and exposure catalog references, and only then reads the current state with `uow.resource_states.get_current(...)`.

If no current state exists, the first `resource_state` row is allowed and the result's `previous_state_id` is `None`. If a current row exists, `transitioned_at` must be strictly greater than the current row's `valid_from`; equality is rejected. No-op replacements are rejected by comparing `lifecycle_status_id`, `criticality_id`, `exposure_level_id`, `source_priority`, `confidence_score`, and `source`. Identity fields and validity-window fields are not part of the no-op comparison.

On success, the handler closes only the existing current row with `valid_to = transitioned_at`, constructs exactly one replacement `ResourceState` with `valid_from = transitioned_at` and `valid_to = NULL`, adds it through the append/read repository, and updates the locked `resource` state snapshot fields to match the new current state: lifecycle status, criticality, exposure level, source priority, and confidence score. It does not modify observation timestamps such as `resource.last_seen_at`; observation and discovery timestamps belong to a dedicated future observation workflow. The handler materializes `ResourceStateTransitionedResult(resource_id, previous_state_id, new_state_id, transitioned_at)` before committing. No explicit flush is needed because UUIDv7 ids are generated when mapped objects are constructed.

The command commits once after all validation and mutation work, then performs no repository access. It does not call explicit rollback, retry deadlocks or serialization failures, translate broad PostgreSQL exceptions, introduce a generic temporal mutation framework, alter migrations, or add persistence adapter APIs. PostgreSQL remains the final guard for one-current-row races and integrity violations. The stable automated concurrency coverage verifies that the resource lock is requested before state reads; a deterministic multi-session lock timing test is deferred because it would be timing-sensitive in the current test harness.

Indexes are scoped to observed query patterns without duplicating leftmost-prefix coverage:

- `ix_resource_state_tenant_resource_valid_from` supports tenant/resource history and current lookup ordered by effective time.
- `ix_resource_state_tenant_lifecycle_status` supports tenant-local lifecycle status filtering.
- `ix_resource_state_tenant_criticality` supports tenant-local criticality filtering.
- `ix_resource_state_tenant_exposure_level` supports tenant-local exposure filtering.
- `ix_resource_state_tenant_valid_to` supports current and historical validity-window scans.

## Resource identifiers

`resource_identifier` rows are tenant-owned temporal immutable facts. They use a tenant-aware composite foreign key so `(tenant_id, resource_id)` must reference a resource in the same tenant. Resource deletes are restrictive and do not cascade into identifier history.

Current identifier uniqueness is enforced by a PostgreSQL partial unique expression index over `tenant_id`, `identifier_type_id`, `COALESCE(namespace, '')`, and `normalized_value` where `valid_to IS NULL`. This defines null namespace semantics explicitly: `NULL` namespace is normalized to the empty namespace for uniqueness checks.

Current primary identifier uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `resource_id`, and `identifier_type_id` where `is_primary = true AND valid_to IS NULL`. Historical primary identifiers with `valid_to` set remain preserved.

`value_hash` is a lookup accelerator only. It is not collision-proof identity. Matching logic must perform a full `normalized_value` comparison after hash lookup, and distinct normalized values with the same hash are allowed.

`AssignResourceIdentifierCommand` is the current application-layer assignment workflow for this table. The command carries `tenant_id`, `resource_id`, `identifier_type_id`, `original_value`, `normalized_value`, `value_hash`, `namespace`, `is_primary`, `confidence_score`, and `valid_from`. Because the project has not defined an identifier normalization or hash algorithm, callers provide both values explicitly and the handler preserves them exactly.

The handler validates blank string fields, optional non-blank namespace, confidence range, and timezone-aware `valid_from` before creating a Unit of Work. It then locks the tenant-scoped resource with `ResourceRepository.get_for_update(...)`, validates active `IdentifierType`, checks same-resource duplicate current assignment with `find_current_by_value(...)`, and checks current primary conflicts with `get_current_primary(...)` when `is_primary=True`. Same-resource duplicates and existing current primary identifiers are rejected before mutation. Cross-resource current-value collisions are not reassigned or closed; PostgreSQL enforces `uq_resource_identifier_current_value` at commit and `SQLAlchemyUnitOfWork.commit()` translates the known conflict.

Successful assignment appends exactly one `ResourceIdentifier` with `valid_to=NULL`, preserves historical rows unchanged, materializes the result before commit, does not call explicit flush, and commits exactly once as the final meaningful operation. Identifier replacement, expiration, deletion, reassignment, primary demotion, source/provenance handling, and hash generation remain separate future workflows.

`resource_identifier` is modeled as a temporal fact, not as a mutable current-state row. Changing identity fields on an existing row is not the recommended operation. The intended application-level policy is to close the old row by setting `valid_to` and insert a new row with the replacement identity evidence. At this stage the database enforces the validity window, current-row uniqueness, and restrictive foreign keys; it does not add a trigger-based immutable framework.

The table intentionally has `created_at` without `updated_at` because identifier rows are append-oriented temporal facts. Subsequent corrections should be represented by new temporal rows instead of in-place identity mutation.

## Resource ownership

`resource_ownership` rows are tenant-owned temporal facts linking a resource to an organization through an `OwnershipRole`. The table uses tenant-aware composite foreign keys for both `(tenant_id, resource_id)` and `(tenant_id, organization_id)`, so PostgreSQL rejects cross-tenant ownership rows. `ownership_role_id` references the global managed `ownership_role` catalog.

Current duplicate ownership is enforced by `uq_resource_ownership_current` over `tenant_id`, `resource_id`, `organization_id`, and `ownership_role_id` where `valid_to IS NULL`. Current primary ownership is enforced by `uq_resource_ownership_current_primary` over `tenant_id`, `resource_id`, and `ownership_role_id` where `is_primary = true AND valid_to IS NULL`. Historical rows with `valid_to` set remain preserved.

`AssignResourceOwnershipCommand` is the current application-layer assignment workflow for this table. The command fields are `tenant_id`, `resource_id`, `organization_id`, `ownership_role_id`, `is_primary`, `confidence_score`, `valid_from`, and nullable `source`.

The handler validates confidence range, timezone-aware `valid_from`, and non-blank `source` when provided before creating a Unit of Work. It then locks the tenant-scoped resource with `ResourceRepository.get_for_update(...)`, validates the tenant-scoped organization with `OrganizationRepository.get_by_id(...)`, validates active `OwnershipRole`, checks duplicate current ownership with `find_current(...)`, and checks current primary conflicts with `get_current_primary(...)` when `is_primary=True`. The current organization model stores `status` and `archived_at`, but no ownership-assignment write-eligibility policy exists yet, so the handler does not enforce one.

Successful assignment appends exactly one `ResourceOwnership` with `valid_to=NULL`, preserves historical rows unchanged, materializes the result before commit, does not call explicit flush, and commits exactly once as the final meaningful operation. Ownership replacement, expiration, removal, transfer, primary demotion, and organization lifecycle write policies remain separate future workflows. Commit-time persistence error translation maps recognized ownership uniqueness races through the existing `SQLAlchemyUnitOfWork.commit()` boundary.

## Resource aliases

`resource_alias` rows are tenant-owned lookup history for alternate resource names. They are not identifier evidence and do not participate in deterministic matching policy. Future callers must provide both the original `alias_value` and a precomputed `normalized_value`; the database does not normalize aliases through validators, triggers, or migration code.

Tenant isolation is enforced through the composite foreign key `(tenant_id, resource_id)` to `resource(tenant_id, id)`. Deletes of referenced resources are restrictive. Within a tenant, `UNIQUE (tenant_id, alias_type, normalized_value)` guarantees one alias lookup key resolves to exactly one resource. The same alias key may exist in a different tenant, and the same normalized value may be reused under a different alias type.

The database enforces non-empty `alias_type`, `alias_value`, and `normalized_value`, optional non-empty `source`, and `last_seen_at >= first_seen_at`.

`AssignResourceAliasCommand` is the current application-layer assignment workflow for this table. The command carries `tenant_id`, `resource_id`, `alias_type`, `alias_value`, `normalized_value`, nullable `source`, `first_seen_at`, and `last_seen_at`.

The handler validates command-only values before opening a Unit of Work: alias strings must not be blank, non-null `source` must not be blank, timestamps must be timezone-aware, and `last_seen_at` must be greater than or equal to `first_seen_at`. It then locks the tenant-scoped resource with `ResourceRepository.get_for_update(...)` before alias lookup. Wrong-tenant resources behave as not found.

Alias identity is `tenant_id + alias_type + normalized_value`. `alias_value` is the original/evidence value supplied by the caller, while `normalized_value` is the upstream lookup identity. The handler does not normalize alias values, derive normalized values, trim accepted values, lowercase, parse DNS/URL/IP data, or hash aliases. Both fields are persisted exactly as supplied.

Before insert, the handler uses `ResourceAliasRepository.find_resource_by_alias(...)` to reject existing alias keys. If the alias already resolves to the same resource, the command raises a duplicate conflict and does not update `last_seen_at`, `source`, or `alias_value`. If the alias resolves to another resource, the command raises a collision conflict and does not transfer the alias, create a `resource_merge`, or resolve canonical lineage. On success, the handler appends exactly one `ResourceAlias`, materializes the result before commit, does not call explicit flush, and commits once as the final meaningful operation. Concurrent uniqueness races are still enforced by `uq_resource_alias_tenant_alias_type_normalized_value` and translated by `SQLAlchemyUnitOfWork.commit()`.

Alias normalization, alias re-observation/update, alias deletion, alias transfer, canonical resolution, and Resource Merge execution remain separate future workflows.

Indexes are scoped to lookup and audit patterns:

- `UNIQUE (tenant_id, alias_type, normalized_value)` supports exact tenant-local alias resolution.
- `ix_resource_alias_tenant_resource_id` supports listing aliases for a resource.
- `ix_resource_alias_tenant_alias_type` supports tenant/type filtering.
- `ix_resource_alias_tenant_last_seen_at` supports recency scans.

## Resource merges

`resource_merge` stores immutable tenant-owned merge lineage from `source_resource_id` to `target_resource_id`. The source resource remains stored in `resource`; no resource rows or existing resource-related rows are deleted, rewritten, or consolidated by this migration. Merge lineage is not represented as `resource_relationship`, because relationships are general graph facts while merges define canonical-resource resolution.

Tenant isolation is enforced with composite foreign keys from `(tenant_id, source_resource_id)` and `(tenant_id, target_resource_id)` to `resource(tenant_id, id)`. A source resource can have one outgoing merge edge through `UNIQUE (tenant_id, source_resource_id)`. A target may have multiple incoming edges, allowing separate resources to merge into the same canonical target.

The database rejects self-merges with `source_resource_id <> target_resource_id` and rejects empty `reason` or `source` when those fields are present. The `prevent_resource_merge_cycle()` trigger function and `trg_resource_merge_prevent_cycle` trigger prevent direct and indirect cycles before insert and before endpoint updates. The trigger traversal is scoped to `tenant_id`, follows outgoing merge edges from the proposed target, uses a visited path plus depth limit, and raises a clear PostgreSQL exception when the proposed source is encountered.

Canonical resolution remains derived rather than materialized on `resource`. A tenant-scoped recursive CTE can resolve a chain such as `A -> B -> C` to `C` while returning the input resource when it has no outgoing merge:

```sql
WITH RECURSIVE lineage(resource_id, path, depth) AS (
    SELECT
        :resource_id::uuid,
        ARRAY[:resource_id::uuid],
        0
    UNION ALL
    SELECT
        resource_merge.target_resource_id,
        lineage.path || resource_merge.target_resource_id,
        lineage.depth + 1
    FROM resource_merge
    JOIN lineage
      ON resource_merge.tenant_id = :tenant_id::uuid
     AND resource_merge.source_resource_id = lineage.resource_id
    WHERE resource_merge.target_resource_id <> ALL(lineage.path)
      AND lineage.depth < 100
)
SELECT resource_id
FROM lineage
ORDER BY depth DESC
LIMIT 1;
```

Future service-layer work owns canonicalization workflow, merge authorization, conflict resolution, alias transfer policy, and concurrency serialization. Opposing concurrent inserts may require advisory locking or another serialization strategy later; advisory locks are intentionally not part of this database-only issue.

Indexes are scoped to documented query patterns:

- `UNIQUE (tenant_id, source_resource_id)` supports deterministic outgoing-edge lookup.
- `ix_resource_merge_tenant_target_merged_at` supports incoming merge lookup and incoming merge history by target. A shorter `(tenant_id, target_resource_id)` index is intentionally omitted because this longer index covers that leftmost-prefix access pattern.
- `ix_resource_merge_tenant_merged_at` supports tenant-local merge timeline scans.

## Resource ownership

`resource_ownership` rows are tenant-owned temporal ownership facts linking a resource, an organization, and a global `ownership_role`. They use tenant-aware composite foreign keys so `(tenant_id, resource_id)` must reference a resource in the same tenant and `(tenant_id, organization_id)` must reference an organization in the same tenant. Deletes of referenced resources, organizations, and ownership roles are restrictive.

A current ownership row has `valid_to IS NULL`; historical rows keep their validity window. Ownership changes follow an append-oriented policy: close the old row by setting `valid_to`, then insert a new ownership row. The database enforces `valid_to > valid_from`, confidence score bounds, current-row uniqueness, primary-owner uniqueness, source text validity, and restrictive foreign keys. Full workflow policy remains application-level.

Current ownership uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `resource_id`, `organization_id`, and `ownership_role_id` where `valid_to IS NULL`. Historical rows with `valid_to` set may reuse the same ownership tuple.

Current primary ownership uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `resource_id`, and `ownership_role_id` where `is_primary = true AND valid_to IS NULL`. This allows one current primary owner per resource and ownership role while allowing different roles to have different primary owners.

Tenant-first indexes support common ownership lookups by resource, organization, ownership role, and current or historical validity state.

## Resource relationships

`resource_relationship` rows are tenant-owned temporal directed edges from `source_resource_id` to `target_resource_id`. Direction is part of identity: `A -> B` and `B -> A` are distinct facts, and endpoints are never sorted or normalized.

The table uses tenant-aware composite foreign keys so `(tenant_id, source_resource_id)` and `(tenant_id, target_resource_id)` must each reference a resource in the same tenant. `relationship_type_id` references the global `relationship_type` catalog. Deletes of referenced resources and relationship types are restrictive.

Direct self-reference is rejected with `source_resource_id <> target_resource_id`. Broader graph cycle detection is intentionally outside this database stage.

A current relationship row has `valid_to IS NULL`; historical rows keep their validity window. Relationship changes follow an append-oriented policy: close the old row by setting `valid_to`, then insert a new row. The database enforces `valid_to > valid_from`, confidence score bounds, current-row uniqueness, source text validity, self-reference rejection, and restrictive foreign keys. Full mutation workflow policy remains application-level and no trigger-based immutable framework is added.

Current relationship uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `source_resource_id`, `target_resource_id`, and `relationship_type_id` where `valid_to IS NULL`. Historical rows with `valid_to` set may reuse the same directed relationship tuple. Reverse direction and the same endpoints with a different relationship type remain valid separate facts.

### Resource Relationship Assignment Command

`AssignResourceRelationshipHandler` owns the current application-layer assignment workflow for one directed relationship. The command fields are `tenant_id`, `source_resource_id`, `relationship_type_id`, `target_resource_id`, `confidence_score`, `valid_from`, and nullable `source`.

The handler validates command-only values before opening a Unit of Work: endpoints must not be the same resource, `confidence_score` must be `0..1`, `valid_from` must be timezone-aware, and non-null `source` must not be blank. It then locks both tenant-scoped endpoint resources in stable UUID string order to reduce opposite-direction deadlock patterns while preserving the command's original source-to-target direction in the inserted row. Missing endpoints are reported by semantic role as `source_resource_id` or `target_resource_id`, independent of lock order.

The handler validates that the global `RelationshipType` exists and is active. The optional `source_type_constraint` and `target_type_constraint` strings on `relationship_type` are not interpreted by this command because no deterministic mapping from those strings to resource types is currently defined. Existing current directed edges are rejected before mutation through `ResourceRelationshipRepository.find_current(...)`; reverse edges and different relationship types are separate facts. On success, the handler appends exactly one current row with `valid_to = NULL`, materializes a scalar result, and commits once without an explicit flush.

Tenant-first indexes support traversal and history queries by source resource, target resource, relationship type, source plus type, target plus type, and current or historical validity state.

## Resource classifications

`resource_classification` rows are tenant-owned temporal classification facts linking a resource to a global `classification_value`. Classification catalogs remain global managed reference data and do not contain `tenant_id`.

The table stores both `classification_type_id` and `classification_value_id`. This is a deliberate materialization: PostgreSQL partial unique indexes cannot use a join from `resource_classification` to `classification_value`, so storing the type id is the smallest declarative design that enforces one current primary value per resource and classification type without race-prone application validation or trigger code. The database proves the materialized type is correct through a composite foreign key from `(classification_type_id, classification_value_id)` to `classification_value(classification_type_id, id)`.

Tenant isolation is enforced with the composite foreign key `(tenant_id, resource_id)` to `resource(tenant_id, id)`. `classification_type_id` references the global `classification_type` catalog, and the composite catalog foreign key references `classification_value`. Deletes of referenced resources, classification values, and classification types are restrictive so classification history is not removed implicitly.

A current classification row has `valid_to IS NULL`; historical rows keep their validity window. Classification changes follow an append-oriented policy: close the old row by setting `valid_to`, then insert a new classification row. The database enforces `valid_to > valid_from`, confidence score bounds, current value uniqueness, one current primary value per type, source text validity, and restrictive foreign keys. Full mutation workflow policy remains application-level and no trigger-based immutable framework is added.

Current value uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `resource_id`, and `classification_value_id` where `valid_to IS NULL`. Historical rows with `valid_to` set may reuse the same value.

Current primary-per-type uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `resource_id`, and `classification_type_id` where `is_primary = true AND valid_to IS NULL`. Multiple current non-primary values of the same classification type are allowed. Current primary values for different classification types are also allowed, and historical primary rows may be reused after they are closed.

`AssignResourceClassificationCommand` is the application write path for assignment-only classification facts. Its command fields are `tenant_id`, `resource_id`, `classification_type_id`, `classification_value_id`, `is_primary`, `confidence_score`, `valid_from`, and nullable `source`. The handler validates confidence bounds, timezone-aware `valid_from`, and nonblank provided `source` before opening a Unit of Work; locks the tenant-scoped resource with `get_for_update`; validates active `ClassificationType`; validates active `ClassificationValue`; verifies that the value belongs to the requested type through `ClassificationValue.classification_type_id`; rejects duplicate current classifications with `ResourceClassificationRepository.find_current(...)`; rejects conflicting current primary classifications with `get_current_primary(...)`; appends exactly one current `ResourceClassification` with `valid_to=NULL`; and commits once as the final meaningful operation. It does not close rows, demote primaries, replace values, create catalog entries, call `flush()`, or duplicate persistence error translation. Known race conflicts still surface through the `SQLAlchemyUnitOfWork.commit()` translator for `uq_resource_classification_current_value` and `uq_resource_classification_current_primary_type`.

Tenant-first indexes support these query patterns:

- `ix_resource_classification_tenant_resource_value` supports lookup by tenant and resource, and exact resource/value history.
- `ix_resource_classification_tenant_resource_type` supports lookup by tenant, resource, and classification type.
- `ix_resource_classification_tenant_value` supports lookup by tenant and classification value.
- `ix_resource_classification_tenant_type_value` supports lookup by tenant, classification type, and classification value.
- `ix_resource_classification_tenant_valid_to` supports current and historical validity-window scans.

## Labels and resource labels

`label` rows are tenant-owned key/value definitions for lightweight operational annotations. They are separate from controlled classifications: classifications use global managed catalogs and type/value governance, while labels are local to a tenant and support operational grouping without changing canonical resource identity.

Label keys are canonicalized by policy, not by trigger: direct SQL inserts must provide a trimmed, lowercase, non-empty `key`. Label values must be trimmed and non-empty, but value case is preserved. This makes keys effectively case-insensitive through canonical lowercase storage while values remain case-sensitive. The database enforces `key = lower(key)`, `key = btrim(key)`, `value = btrim(value)`, and non-empty key/value checks.

Each tenant can define a `(key, value)` pair only once through `UNIQUE (tenant_id, key, value)`. `is_active` is intentionally not part of that key: inactive labels remain the historical definition for existing assignments, and reactivation should update the existing row rather than create a duplicate. Labels also expose `UNIQUE (tenant_id, id)` so tenant-safe child foreign keys can reference them.

Optional label metadata includes nullable `display_name`, `description`, and `color`. If present, `display_name` and `description` must not be empty or whitespace-only. `color` is retained because it is useful persistence metadata for UI and reporting, but it is constrained to `#RRGGBB` hex format and remains case-preserving within that format.

`resource_label` rows are tenant-owned temporal assignment facts. They use composite foreign keys so `(tenant_id, resource_id)` references `resource(tenant_id, id)` and `(tenant_id, label_id)` references `label(tenant_id, id)`. Deletes of referenced resources and labels are restrictive, and tenant deletion is restricted while labels exist.

A current resource-label assignment has `valid_to IS NULL`; historical rows keep their validity window. Changes follow an append-oriented policy: close the old assignment with `valid_to`, then insert a new row. The database enforces `valid_to > valid_from`, source text validity, current assignment uniqueness, and restrictive foreign keys. It does not add a trigger-based immutable framework.

Current assignment uniqueness is enforced by a tenant-first partial unique index over `tenant_id`, `resource_id`, and `label_id` where `valid_to IS NULL`. Historical rows may reuse the same assignment after closure. The schema intentionally does not enforce one-value-per-key, so different values for the same key can be assigned to one resource when the tenant workflow requires it.

`AssignResourceLabelCommand` is the application write path for assignment-only resource labels. Its command fields are `tenant_id`, `resource_id`, `label_id`, `valid_from`, and nullable `source`. The handler validates timezone-aware `valid_from` and nonblank provided `source` before opening a Unit of Work; locks the tenant-scoped resource with `get_for_update`; validates the tenant-scoped active label with `uow.labels.get_by_id(tenant_id, label_id)`; rejects duplicate current assignments with `ResourceLabelRepository.find_current(...)`; appends exactly one current `ResourceLabel` with `valid_to=NULL`; and commits once as the final meaningful operation. It does not close rows, replace labels, create or reactivate label definitions, inspect or normalize label key/value fields, enforce primary semantics, enforce one value per key, call `flush()`, or duplicate persistence error translation. Known race conflicts still surface through the `SQLAlchemyUnitOfWork.commit()` translator for `uq_resource_label_current`.

Indexes are scoped to observed query patterns without duplicating leftmost-prefix coverage:

- `UNIQUE (tenant_id, key, value)` supports tenant/key and exact tenant/key/value label definition lookups.
- `ix_label_tenant_id_is_active` supports tenant-local active/inactive label filtering.
- `ix_resource_label_tenant_resource_label` supports tenant/resource history and exact resource/label assignment lookup.
- `ix_resource_label_tenant_label_id` supports tenant/label reverse lookup across resources.
- `ix_resource_label_tenant_valid_to` supports current and historical validity-window scans.

## Organization hierarchy

The database rejects direct self-parenting through `parent_organization_id IS NULL OR parent_organization_id <> id`. More complex hierarchy cycles, such as `A -> B -> A`, are intentionally deferred to the application or service layer in a later stage.

## Catalog seed

Run:

- `make db-seed`

The seed inserts only a minimal baseline for managed reference catalogs. It is idempotent, deterministic by catalog `code`, and does not overwrite existing catalog rows.
If a seeded system catalog `code` already exists with a different deterministic UUID, the seed exits with a clear conflict error instead of creating a duplicate or silently accepting the mismatch. Inserts use PostgreSQL conflict handling so concurrent seed runs do not create duplicate rows.
Baseline seed data now includes lifecycle statuses (`active`, `inactive`, `archived`), criticalities (`low`, `medium`, `high`, `critical`), and exposure levels (`internal`, `restricted`, `public`).
Seeded catalog rows are retrievable through the managed catalog Unit of Work properties by deterministic code. Classification values are retrieved through `uow.classification_values` with both `classification_type_id` and value `code`; there is no fallback across classification types.

## Tests

Run:

- `make db-test`

Database tests create and destroy an isolated `resource_monitoring_test` database. They do not use the normal development database for destructive migration checks.
