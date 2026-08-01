# Resource Inventory integrity audit

## Scope

This audit covers the Resource Inventory database foundation through Alembic head `202607300008`. It verifies SQLAlchemy metadata, Alembic migrations, PostgreSQL constraints and indexes, tenant isolation, temporal invariants, restrictive delete policy, ORM relationships, documentation alignment, and scaling assumptions for Stage `02.0`.

No corrective schema migration is required by this audit. The only confirmed gaps are cross-model invariant test coverage and the absence of a consolidated audit document.

## Findings

### Confirmed defects

- Cross-model invariant coverage was incomplete. Model-specific tests covered individual tables, but there was no single test module proving that resource history, aliases, merges, and multiple temporal fact tables interact without weakening tenant isolation or delete policy.
- A consolidated audit artifact did not exist for the full Resource Inventory schema.

### Accepted trade-offs

- `resource` keeps mutable current snapshot fields while `resource_state` stores temporal state history. Database synchronization triggers are intentionally absent; keeping the snapshot equal to the current `resource_state` row is future application/service responsibility.
- `resource_identifier` keeps both hash and normalized value indexes. The hash index accelerates first-pass lookup, while normalized lookup remains mandatory for collision safety.
- Several temporal tables keep both exact lookup indexes and current-row partial unique indexes. These are retained because enforcement indexes and history query indexes serve different purposes even when leftmost prefixes overlap.
- `resource_merge` omits a shorter `(tenant_id, target_resource_id)` index because `(tenant_id, target_resource_id, merged_at)` covers target lookup by leftmost prefix and also supports incoming merge history ordering.
- Merge cycle prevention is enforced by a PostgreSQL trigger, but opposing concurrent inserts may still require future service-layer serialization or advisory locking.
- Complex organization hierarchy cycles remain deferred to the application/service layer; the database only rejects direct self-parenting.

### Deferred concerns

- Future partitioning should be tenant-first for high-volume fact/history tables, but this stage does not implement partitioning or sharding.
- Canonical resource resolution is derived from `resource_merge`; reusable service/query helpers and cache strategies are future work.
- Alias conflict resolution and alias transfer during merges are future service-layer responsibilities.
- Resource snapshot/state synchronization is future service-layer responsibility.
- Merge authorization, review workflow, and rollback workflow are outside this database foundation stage.

### Verified correct invariants

- Tenant-owned child rows use tenant-aware composite foreign keys where cross-tenant references matter.
- Tenant-owned parent rows that need composite child references expose `UNIQUE (tenant_id, id)`.
- Global managed catalogs do not contain `tenant_id`.
- Delete policy is restrictive; no broad `ON DELETE CASCADE`, ORM `delete-orphan`, or destructive cascade is present.
- Temporal rows use `valid_to IS NULL` for current facts and retain historical rows with `valid_to IS NOT NULL`.
- Partial unique indexes enforce duplicate-current and current-primary rules.
- Merge lineage is separate from resource relationships and rejects self, direct-cycle, and indirect-cycle merges.
- Alembic revisions are linear through `202607300008`.

## Table audit

### `tenant`

- Primary key: `id` UUIDv7.
- Tenant scope: top-level isolation boundary; not tenant-owned.
- Foreign keys: none.
- Unique constraints: unique `slug`.
- Check constraints: non-empty and lowercase `slug`.
- Indexes: primary key and unique slug indexes.
- Temporal/current semantics: mutable administrative row with `created_at` and `updated_at`; no current-row predicate.
- Delete behavior: restrictive through dependent tenant-owned rows.
- ORM relationships: `organizations`, `labels`; passive deletes.
- Policy: mutable tenant metadata.
- Query patterns: tenant lookup by slug and id.
- Scaling implications: tenant id is the leading key for operational tables and future tenant partitioning/sharding.

### `organization`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned with `tenant_id`; exposes `UNIQUE (tenant_id, id)`.
- Foreign keys: `tenant_id -> tenant.id`; composite parent FK `(tenant_id, parent_organization_id) -> organization(tenant_id, id)`.
- Unique constraints: `UNIQUE (tenant_id, id)`; partial unique `(tenant_id, external_key) WHERE external_key IS NOT NULL`.
- Check constraints: non-empty `canonical_name`; direct self-parent rejected.
- Indexes: tenant/status, tenant/canonical name, partial external key uniqueness.
- Temporal/current semantics: mutable hierarchy row; logical archive through `archived_at`.
- Delete behavior: restrictive tenant and parent references; ownership history restricts organization deletion.
- ORM relationships: `tenant`, `parent`, `children`, `resource_ownerships`; passive deletes for collections.
- Policy: hierarchy cycles beyond direct self-parent are deferred.
- Query patterns: tenant-scoped hierarchy, status filtering, canonical name lookup, external key lookup.
- Scaling implications: tenant-first indexes support tenant-local hierarchy reads.

### `resource`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned with `tenant_id`; exposes `UNIQUE (tenant_id, id)`.
- Foreign keys: `tenant_id`, `resource_type_id`, `lifecycle_status_id`, `criticality_id`, `exposure_level_id`.
- Unique constraints: `UNIQUE (tenant_id, id)`.
- Check constraints: non-empty canonical/display names; `source_priority` in `0..1000`; confidence in `0..1`; positive `record_version`; `first_seen_at <= last_seen_at`.
- Indexes: tenant-first indexes for type, lifecycle status, criticality, exposure, canonical name, and last seen.
- Temporal/current semantics: mutable current snapshot; no `valid_to`.
- Delete behavior: restrictive from identifiers, ownership, relationships, classifications, labels, state, aliases, and merges.
- ORM relationships: identifiers, ownerships, outgoing/incoming relationships, classifications, label assignments, state history, aliases, outgoing merge, incoming merges.
- Policy: no hard-delete of resources with dependent evidence; optimistic locking via `record_version`.
- Query patterns: current resource lookup/filter by tenant and catalog dimensions.
- Scaling implications: tenant-first filters support 10M+ resources and future tenant partitioning.

### `resource_identifier`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; composite FK `(tenant_id, resource_id) -> resource(tenant_id, id)`.
- Foreign keys: tenant-safe resource FK; `identifier_type_id -> identifier_type.id`.
- Unique constraints: partial unique current value and current primary indexes.
- Check constraints: non-empty namespace when present; non-empty normalized/original/hash values; confidence bounds; temporal order.
- Indexes: tenant/resource, tenant/type/hash, tenant/type/normalized, tenant/valid_to, partial current value, partial current primary.
- Temporal/current semantics: current row has `valid_to IS NULL`; historical rows retain closed windows.
- Delete behavior: restrictive resource and identifier type references.
- ORM relationships: `resource`.
- Policy: append-oriented identity evidence; `value_hash` is lookup acceleration only.
- Query patterns: identifier matching by tenant/type/hash then normalized value; resource history; current primary lookup.
- Scaling implications: hash and normalized indexes support high-cardinality 100M+ identifier rows.

### `resource_ownership`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; composite FKs to resource and organization.
- Foreign keys: `(tenant_id, resource_id) -> resource(tenant_id, id)`, `(tenant_id, organization_id) -> organization(tenant_id, id)`, `ownership_role_id -> ownership_role.id`.
- Unique constraints: partial current ownership and partial current primary ownership indexes.
- Check constraints: confidence bounds; temporal order; non-empty source when present.
- Indexes: tenant/resource, tenant/organization, tenant/role, tenant/valid_to, tenant/resource/role, partial current ownership, partial current primary.
- Temporal/current semantics: current owner has `valid_to IS NULL`; historical reuse allowed.
- Delete behavior: restrictive references to resource, organization, and role.
- ORM relationships: resource, organization, ownership role.
- Policy: append-oriented ownership facts; one current primary owner per role.
- Query patterns: tenant/resource ownership, organization reverse lookup, role filtering, current/historical scans.
- Scaling implications: tenant-first indexes support large ownership history and tenant partitioning.

### `resource_relationship`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; tenant-safe source and target resource FKs.
- Foreign keys: `(tenant_id, source_resource_id)` and `(tenant_id, target_resource_id)` to `resource(tenant_id, id)`; `relationship_type_id -> relationship_type.id`.
- Unique constraints: partial current edge uniqueness.
- Check constraints: source not target; confidence bounds; temporal order; non-empty source when present.
- Indexes: tenant/source, tenant/target, tenant/type, tenant/source/type, tenant/target/type, tenant/valid_to, partial current edge.
- Temporal/current semantics: current edge has `valid_to IS NULL`; historical reuse allowed.
- Delete behavior: restrictive resource and relationship type references.
- ORM relationships: source resource, target resource, relationship type.
- Policy: directed graph fact, not merge lineage; broad graph cycle detection deferred.
- Query patterns: graph traversal by source/target/type and current/history scans.
- Scaling implications: tenant-first graph indexes are necessary for 100M+ edge rows.

### `resource_classification`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; composite FK to resource.
- Foreign keys: `(tenant_id, resource_id) -> resource(tenant_id, id)`, `classification_type_id -> classification_type.id`, composite `(classification_type_id, classification_value_id) -> classification_value(classification_type_id, id)`.
- Unique constraints: partial current value and partial current primary per type.
- Check constraints: confidence bounds; temporal order; non-empty source when present.
- Indexes: tenant/resource/value, tenant/resource/type, tenant/value, tenant/type/value, tenant/valid_to, partial current indexes.
- Temporal/current semantics: current classification has `valid_to IS NULL`; historical reuse allowed.
- Delete behavior: restrictive resource and catalog references.
- ORM relationships: resource, classification type, classification value.
- Policy: append-oriented controlled classification facts.
- Query patterns: tenant/resource classification, type/value filtering, primary value lookup.
- Scaling implications: tenant-first indexes support high-volume classification facts.

### `label`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; exposes `UNIQUE (tenant_id, id)`.
- Foreign keys: `tenant_id -> tenant.id`.
- Unique constraints: `UNIQUE (tenant_id, id)`; `UNIQUE (tenant_id, key, value)`.
- Check constraints: key/value non-empty and trimmed; key lowercase; optional display/description/color non-empty; color hex format.
- Indexes: tenant/is_active plus unique indexes.
- Temporal/current semantics: mutable tenant-local definition with active flag.
- Delete behavior: restrictive from `resource_label`.
- ORM relationships: tenant, resource assignments.
- Policy: tenant-owned operational annotation vocabulary, not global catalog.
- Query patterns: tenant/key/value lookup, active label filtering.
- Scaling implications: tenant-first uniqueness keeps label lookups local.

### `resource_label`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; composite FKs to resource and label.
- Foreign keys: `(tenant_id, resource_id) -> resource(tenant_id, id)`, `(tenant_id, label_id) -> label(tenant_id, id)`.
- Unique constraints: partial current assignment uniqueness.
- Check constraints: temporal order; non-empty source when present.
- Indexes: tenant/resource/label, tenant/label, tenant/valid_to, partial current assignment.
- Temporal/current semantics: current assignment has `valid_to IS NULL`; historical reuse allowed.
- Delete behavior: restrictive resource and label references.
- ORM relationships: resource, label.
- Policy: append-oriented label assignment fact.
- Query patterns: resource labels, label reverse lookup, current/history scans.
- Scaling implications: tenant-first indexes support large assignment history.

### `resource_state`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; composite FK to resource.
- Foreign keys: `(tenant_id, resource_id) -> resource(tenant_id, id)`, catalog FKs to lifecycle status, criticality, and exposure level.
- Unique constraints: partial current state uniqueness.
- Check constraints: non-negative `source_priority`; confidence bounds; temporal order; non-empty source when present.
- Indexes: tenant/resource/valid_from, tenant/lifecycle status, tenant/criticality, tenant/exposure level, tenant/valid_to, partial current state.
- Temporal/current semantics: one current row per resource with `valid_to IS NULL`.
- Delete behavior: restrictive resource and catalog references.
- ORM relationships: resource, lifecycle status, criticality, exposure level.
- Policy: append-oriented state history; current row should match the mutable resource snapshot by future service policy.
- Query patterns: resource state timeline, catalog filtering, current/history scans.
- Scaling implications: tenant-first indexes support state history growth and tenant partitioning.

### `resource_alias`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; composite FK to resource.
- Foreign keys: `(tenant_id, resource_id) -> resource(tenant_id, id)`.
- Unique constraints: `UNIQUE (tenant_id, alias_type, normalized_value)`.
- Check constraints: non-empty alias type/value/normalized value; non-empty source when present; `last_seen_at >= first_seen_at`.
- Indexes: tenant/resource, tenant/alias type, tenant/last seen, unique tenant/type/normalized lookup.
- Temporal/current semantics: observation interval with first/last seen; not a `valid_to` temporal table.
- Delete behavior: restrictive resource reference.
- ORM relationships: resource.
- Policy: lookup history distinct from deterministic identifiers; no automatic alias transfer during merge.
- Query patterns: exact alias resolution, aliases by resource, type filtering, recency scans.
- Scaling implications: tenant/type/normalized uniqueness supports high-cardinality alias lookup.

### `resource_merge`

- Primary key: `id` UUIDv7.
- Tenant scope: tenant-owned; composite source and target resource FKs.
- Foreign keys: `(tenant_id, source_resource_id)` and `(tenant_id, target_resource_id)` to `resource(tenant_id, id)`.
- Unique constraints: `UNIQUE (tenant_id, source_resource_id)` for deterministic outgoing lineage.
- Check constraints: source not target; non-empty reason/source when present.
- Indexes: unique tenant/source, tenant/target/merged_at, tenant/merged_at.
- Temporal/current semantics: immutable lineage edge; no `valid_to`.
- Delete behavior: restrictive source and target resource references.
- ORM relationships: source resource, target resource, scalar outgoing merge, incoming merge collection.
- Policy: merge lineage distinct from resource relationships; canonical resource is derived recursively.
- Query patterns: outgoing canonical resolution, incoming merge history, tenant merge timeline.
- Scaling implications: target history index covers `(tenant_id, target_resource_id)` by leftmost prefix and avoids redundant short index.

### Managed catalogs

- Tables: `resource_type`, `identifier_type`, `relationship_type`, `ownership_role`, `classification_type`, `classification_value`, `lifecycle_status`, `criticality`, `exposure_level`.
- Primary key: `id` UUIDv7 on each catalog.
- Tenant scope: global managed reference data; no `tenant_id`.
- Foreign keys: `resource_type.parent_type_id -> resource_type.id`; `classification_value.classification_type_id -> classification_type.id`.
- Unique constraints: unique `code` for top-level catalogs; `classification_value` unique by `(classification_type_id, code)` and `(classification_type_id, id)`.
- Check constraints: non-empty lowercase catalog codes.
- Indexes: primary/unique indexes from PK and uniqueness constraints.
- Temporal/current semantics: mutable managed records with `is_active`; no temporal windows.
- Delete behavior: restrictive references from operational/fact rows.
- ORM relationships: resource type parent, classification type values, classification value type.
- Policy: global managed catalogs are seeded deterministically and remain tenant-independent.
- Query patterns: lookup by code and FK resolution.
- Scaling implications: small global tables; partitioning is not needed.

## Index decisions

- Retained tenant-first operational indexes because tenant filtering is the dominant access pattern and future partitioning/sharding boundary.
- Retained partial unique indexes on temporal current rows because they enforce business invariants and cannot be replaced by non-unique history indexes.
- Retained intentional short/long pairs where exact current/history access differs from enforcement or reverse lookup.
- Omitted no existing index in this audit; no exact duplicate or harmful redundant index was confirmed.
- No new index was added because no missing high-volume query index was proven.

## Scaling assessment

- `10M+ resources`: `resource` has tenant-first filters for type, lifecycle, criticality, exposure, canonical name, and last seen. UUIDv7 primary keys keep inserts distributed but time-sortable.
- `100M+ fact/history rows`: temporal and lineage tables consistently use tenant-first indexes and current-row partial unique indexes. History scans have `valid_to` or timeline indexes where needed.
- Horizontal application scaling: database constraints remain authoritative for tenant isolation, uniqueness, and cycles. Merge race serialization is deferred because no service layer exists yet.
- Future partitioning: tenant-owned high-volume tables are candidates for tenant/hash or tenant-time partitioning. Global catalogs and small administrative tables are not partitioning candidates.
- Sharding constraints: composite FKs include tenant id, which preserves a viable tenant-sharding path. Cross-tenant references are rejected by PostgreSQL.
