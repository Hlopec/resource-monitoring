# Resource Inventory domain model

## Purpose

The Resource Inventory bounded context represents the canonical inventory of digital resources that an organization manages. The model is intentionally centered on durable identity, tenant isolation, temporal validity, and auditable merge behavior so that future downstream domains can depend on it without embedding their own lifecycle semantics in the core schema.

## Scope and boundaries

The core model owns:

- tenant and organization hierarchy;
- resource types and the abstract resource entity;
- resource identifiers, aliases, and deterministic identity evidence;
- ownership and relationship facts;
- classifications, labels, resource state history, and merge evidence.

The model does not treat downstream observations, technology detections, finding events, audit events, outbox events, or vulnerability records as part of the core Resource Inventory ERD. Those domains may be modeled later as separate bounded contexts that reference Resource Inventory as a shared dependency.

## Core entities

### Tenant

A tenant is the top-level isolation boundary for all data in the domain. The logical tenant row uses `id`, `slug`, `display_name`, `status`, `created_at`, and `updated_at`. Every tenant-owned entity carries a tenant identifier and remains scoped to tenant-local governance and future tenant-based sharding.

### Organization

Organizations define the administrative and reporting boundary within a tenant. They form a hierarchical structure that can be used for ownership propagation and policy scope. The logical model includes `organization_type_id`, `canonical_name`, `external_key`, `status`, `created_at`, `updated_at`, and `archived_at`. If `organization_type_id` or lifecycle-related reference values are introduced later, they are treated as managed reference catalogs and are not part of the core resource-inventory implementation in this PR.

### Resource type

Resource types define a stable taxonomy for the domain and support future inheritance-based grouping without overloading the resource entity with every possible subtype distinction. The logical fields are `id`, `code`, `display_name`, `parent_type_id`, `category`, `schema_version`, `is_system`, `is_active`, `created_at`, and `updated_at`.

### Resource

Resource is the canonical logical record. It stores the current mutable snapshot of the resource, including lifecycle status, criticality, exposure level, source priority, confidence score, and temporal observation markers. The entity includes a `record_version` field for optimistic concurrency control.

The resource table does not carry `valid_from` and `valid_to` because those are represented by versioned relationships, ownership assignments, identifiers, and state-history rows rather than by the core resource row itself. The logical reference fields `lifecycle_status_id`, `criticality_id`, and `exposure_level_id` are modeled as foreign keys to managed reference catalogs, even though those catalog entities may be detailed later during the implementation stage.

`source_priority` is constrained to the range `0..1000`, `confidence_score` is constrained to `0.0000..1.0000`, and `record_version` must remain greater than zero. Resource archive behavior is logical through `archived_at`. The snapshot fields on `resource` are intentionally retained for fast current-state reads; by service-layer policy they should equal the current `resource_state` row (`valid_to IS NULL`), while `resource_state` records the temporal history for those same state dimensions.

The first Resource collection query orders Resource rows by `created_at ASC, id ASC` and uses keyset pagination over that tuple. Existing indexes support tenant plus type and tenant plus lifecycle-status filters, but the schema does not yet define a composite `(tenant_id, created_at, id)` index for the default list order. Query correctness does not depend on the composite index; it is a deferred scaling migration for high-volume collection reads.

### Resource identifier

Resource identifier stores a specific identifier value for a resource, using an identifier type and a normalized representation. Each assignment remains temporally versioned so that the identity evidence can be audited and superseded when required.

Current identifier uniqueness is scoped to `tenant_id`, `identifier_type_id`, namespace, and `normalized_value`, with `NULL` namespace treated as the empty namespace for uniqueness. `value_hash` is only a lookup accelerator; identity matching still requires full `normalized_value` comparison after hash lookup, and hash collisions must not conflict when normalized values differ.

Application exact identifier lookup uses current rows only (`valid_to IS NULL`) and matches tenant, identifier type, namespace, and normalized value exactly. `original_value` remains stored evidence and is not a lookup key. The application query does not generate or trust a new hash value; it compares the full stored normalized value.

### Resource alias

`resource_alias` stores tenant-owned alternate names or lookup keys that point to a resource but are not canonical deterministic identifiers. Aliases preserve historical lookup names such as old hostnames, display names, imported external aliases, or source-system naming artifacts. They differ from `resource_identifier`: identifiers are typed identity evidence used by matching policy, while aliases are operational lookup history and must not replace identifier matching rules.

The table uses a tenant-aware composite foreign key from `(tenant_id, resource_id)` to `resource(tenant_id, id)`, so PostgreSQL rejects cross-tenant alias rows. Within one tenant, `UNIQUE (tenant_id, alias_type, normalized_value)` ensures one alias lookup key resolves to exactly one resource. The same alias key can exist in different tenants, and the same normalized value can exist under different alias types.

Alias normalization is deliberately not implemented in model events, database triggers, or migrations. Future callers must supply `normalized_value` explicitly. The database enforces non-empty `alias_type`, `alias_value`, and `normalized_value`, optional non-empty `source`, and `last_seen_at >= first_seen_at`. Resource deletes are restrictive while aliases reference the resource.

Application exact alias lookup uses the tenant-local `alias_type` plus `normalized_value` key and returns the Resource directly referenced by that alias row. `alias_value` remains evidence/display data and does not participate in matching. Alias lookup does not follow merge lineage; canonical resolution is derived separately from `resource_merge`.

### Ownership role and resource ownership

Ownership roles describe the purpose of an ownership relationship and remain global managed catalog values. Resource ownership stores the association between a resource and an organization with a validity window, an optional source, a primary marker, and a confidence score. Ownership is not modeled as a mutable current-state record in the same way as a simple flag; it is a temporally versioned assignment fact.

The implemented ownership table enforces tenant-safe composite foreign keys to both `resource` and `organization`. A current row has `valid_to IS NULL`; changing ownership closes the old row with `valid_to` and inserts a new row. Current ownership uniqueness is scoped to `tenant_id`, `resource_id`, `organization_id`, and `ownership_role_id`, while current primary ownership is limited to one row per `tenant_id`, `resource_id`, and `ownership_role_id`. This means a resource can have different current primary organizations for different ownership roles.

Resource list organization filtering uses the current primary `owner` role row as the compact ownership projection and filter source. Historical ownership rows, current non-primary rows, and current primary rows for other roles do not participate in that list projection. This role-specific interpretation preserves one row per Resource without a `DISTINCT` workaround. Referenced resources, organizations, and ownership roles use restrictive deletes so historical ownership evidence is not removed implicitly.

### Relationship type and resource relationship

Relationship types remain global managed catalog values. Resource relationships capture directed associations such as dependency, containment, or parent-child links. Each relationship is temporally versioned and may be superseded over time.

The implemented relationship table stores directed edges from `source_resource_id` to `target_resource_id`; `A -> B` and `B -> A` are different facts and endpoints are never sorted. Tenant-safe composite foreign keys require both source and target resources to belong to the row tenant. Direct self-reference is rejected, but broader graph cycle detection is outside this stage.

A current relationship row has `valid_to IS NULL`; changing an endpoint, relationship type, confidence score, or source should close the old row and insert a new temporal fact. Current uniqueness is scoped to `tenant_id`, `source_resource_id`, `target_resource_id`, and `relationship_type_id`, while historical reuse remains allowed. Referenced resources and relationship types use restrictive deletes.

### Classification type, classification value, and resource classification

Classification types and values remain global managed catalog values. Classification values provide a controlled vocabulary for classifying resources, and each value belongs to exactly one classification type.

The implemented `resource_classification` table stores tenant-owned temporal assignment facts. It uses a tenant-safe composite foreign key so `(tenant_id, resource_id)` must reference a resource in the same tenant. It also stores `classification_type_id` next to `classification_value_id` so PostgreSQL can enforce one current primary value per resource and classification type with a declarative partial unique index. A composite catalog foreign key from `(classification_type_id, classification_value_id)` to `classification_value(classification_type_id, id)` proves that the stored value belongs to the stored type.

A current classification row has `valid_to IS NULL`; historical rows keep their validity window. Changing a classification value, confidence score, source, or primary designation should close the old row and insert a new temporal fact. Current duplicate value assignments are unique per `tenant_id`, `resource_id`, and `classification_value_id`, while historical reuse remains allowed. Multiple current non-primary values of the same type are allowed, but only one current primary row is allowed per `tenant_id`, `resource_id`, and `classification_type_id`. Referenced resources, classification values, and classification types use restrictive deletes.

### Label and resource label

Labels provide tenant-scoped, free-form operational annotations without changing canonical identity. They differ from controlled classifications: classifications use global managed catalogs and type/value governance, while labels are tenant-owned key/value definitions for local workflow, grouping, and annotation.

The implemented `label` table is tenant-owned and uses canonical `key` plus case-sensitive `value`. Label keys must be trimmed, lowercase, and non-empty. Label values must be trimmed and non-empty, but value case is preserved so `Production` and `production` are different values. A tenant can define each canonical `(key, value)` only once, regardless of `is_active`; deactivation preserves the definition for existing assignments instead of allowing duplicate recreation. Optional `display_name`, `description`, and `color` metadata do not participate in identity. Color is optional and, when present, must use `#RRGGBB` hex format.

`resource_label` stores tenant-owned temporal assignment facts between a resource and a label. It uses tenant-safe composite foreign keys to both `resource(tenant_id, id)` and `label(tenant_id, id)`, so PostgreSQL rejects cross-tenant resource/label assignments. A current assignment row has `valid_to IS NULL`; historical rows keep their validity window. Duplicate current assignment of the same label to the same resource is rejected, while historical reuse, multiple labels on one resource, the same label on different resources, and multiple values for the same key are allowed. Referenced tenants, resources, and labels use restrictive deletes.

### Resource state

`resource_state` is tenant-owned temporal history for resource lifecycle status, criticality, exposure level, source priority, and confidence score. A current row has `valid_to IS NULL`; historical rows retain their validity window. Exactly one current state row is allowed per `tenant_id` and `resource_id` through a PostgreSQL partial unique index.

The table uses a tenant-aware composite foreign key from `(tenant_id, resource_id)` to `resource(tenant_id, id)`, so PostgreSQL rejects cross-tenant state rows. `lifecycle_status_id`, `criticality_id`, and `exposure_level_id` are restrictive foreign keys to global managed reference catalogs. Referenced resources and catalog rows are not deleted implicitly while state history exists.

Resource state changes follow the same append-oriented policy as other temporal facts: close the previous current row by setting `valid_to`, insert a new row with the replacement state, and keep the resource snapshot synchronized in the application or service layer. The intended invariant is `resource` mutable state snapshot equals the current `resource_state` row. This stage deliberately does not add triggers or service workflow code. Migration `202607300007` backfills one current state row for each existing resource using the resource snapshot values, `first_seen_at` as deterministic `valid_from`, `valid_to = NULL`, and `source = 'migration_backfill'`.

Tenant-first indexes support resource history/current lookup by `(tenant_id, resource_id, valid_from)`, catalog-based filtering by lifecycle status, criticality, and exposure level, and validity-window scans by `(tenant_id, valid_to)`. The database also enforces non-negative `source_priority`, confidence bounds, `valid_to > valid_from`, and non-empty source text when source is present.

### Resource merge

`resource_merge` stores immutable directed merge lineage from `source_resource_id` to `target_resource_id`. A row means `source_resource_id -> target_resource_id`: the source resource remains stored in `resource`, and no destructive consolidation or row rewriting happens in this database foundation stage.

Merge lineage is separate from `resource_relationship`. Relationships model domain graph facts such as dependency or containment; merge lineage models canonical-resource resolution after deduplication. A resource may have only one outgoing merge edge within a tenant through `UNIQUE (tenant_id, source_resource_id)`, while a target resource may have multiple incoming edges, allowing `A -> C` and `B -> C`. Canonical resolution remains derived from the merge graph and is not stored on `resource`; columns such as `canonical_resource_id`, `merged_into_resource_id`, `is_canonical`, or `is_merged` are intentionally absent.

Tenant isolation is enforced with composite foreign keys from `(tenant_id, source_resource_id)` and `(tenant_id, target_resource_id)` to `resource(tenant_id, id)`. The database rejects self-merges, empty `reason`, empty `source`, cross-tenant endpoints, duplicate outgoing edges, and direct or indirect cycles through the `prevent_resource_merge_cycle()` trigger function and `trg_resource_merge_prevent_cycle` trigger. The trigger traverses outgoing merge edges within the same tenant before insert and before endpoint updates. Opposing concurrent inserts can still require future service-layer serialization or advisory locking; that concurrency policy is deliberately outside this issue.

Canonical resource resolution is derived rather than stored. The application resolver currently derives it by validating the requested tenant-owned resource, following direct tenant-scoped outgoing `resource_merge` edges, and loading the terminal resource. It reports the first immediate target separately from the terminal canonical target, returns the input resource for an unmerged resource, follows `A -> B -> C` to `C`, ignores incoming branches, and remains read-only: it does not rewrite lineage, compress paths, cache canonical ids, migrate facts, or delete source resources.

The application resolver also includes defensive guards around corrupt lineage: a per-invocation visited set for cycles, a maximum depth of 64 traversed edges with rejection before a 65th traversal, tenant-scoped lookup at every step, and a conflict if a terminal target is missing despite the schema's foreign-key expectations.

A tenant-scoped recursive CTE remains a possible future optimization for the same derivation:

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

When no outgoing merge exists, the CTE returns the input resource. For a valid chain such as `A -> B -> C`, it returns `C`. Future service-layer canonicalization can wrap this query and define serialization, conflict handling, alias transfer policy, and user workflow. This schema does not automatically move aliases, rewrite identifiers, transfer relationships, delete source resources, cache canonical targets, compress paths, or resolve alias conflicts.

## Type-specific extension entities

The model also supports type-specific extension entities when the domain needs:

- PostgreSQL-specific types such as `INET`;
- strict constraints;
- frequent subtype-specific queries;
- referential integrity between a resource and its subtype representation;
- performance that JSONB cannot provide efficiently.

These entities are optional and only added when the subtype requires stronger structural guarantees than the generic core model can provide.

### Domain resource

- `resource_id`
- `fqdn`
- `registrable_domain`
- `public_suffix`
- `is_idn`

### IP resource

- `resource_id`
- `address INET`
- `ip_version`
- `is_public`

### URL resource

- `resource_id`
- `scheme`
- `host`
- `port`
- `path`
- `query_hash`
- `normalized_url`

### Network service resource

- `resource_id`
- `ip_resource_id`
- `transport_protocol`
- `port`
- `application_protocol`

### Repository resource

- `resource_id`
- `provider`
- `owner_path`
- `repository_name`
- `provider_repository_id`
- `default_branch`

### Container image resource

- `resource_id`
- `registry`
- `repository`
- `digest`

## Deduplication model

Deduplication is intentionally layered and governed by policy.

### Deterministic identity

Deterministic identity uses stable values such as FQDNs, IP addresses, repository provider IDs, container digests, cloud ARNs, Kubernetes UIDs, or package URLs. These values can be used for direct, reproducible identity matching.

### Correlated identity

Correlated identity uses evidence such as hostname, TLS certificate, HTTP fingerprint, cloud metadata, or repository origin to build a stronger case that two records refer to the same logical resource.

### Probabilistic matching

Probabilistic matching uses rules or AI-based confidence scoring. It is never allowed to merge records automatically without:

- a configured threshold;
- a tenant policy;
- audit evidence;
- a review mechanism;
- a rollback strategy.

## Tenant consistency enforcement

The recommended PostgreSQL enforcement strategy is to use tenant-aware composite keys and tenant-aware composite foreign keys for all tenant-owned child rows. This makes tenant ownership part of the database contract rather than a purely application-level convention.

- Tenant-owned parent entities should have a tenant-scoped candidate key such as `UNIQUE (tenant_id, id)`.
- Tenant-owned child entities should use composite foreign keys such as `FOREIGN KEY (tenant_id, resource_id) REFERENCES resource (tenant_id, id)`.
- `resource_relationship` should use two tenant-aware composite foreign keys:
  - `FOREIGN KEY (tenant_id, source_resource_id) REFERENCES resource (tenant_id, id)`
  - `FOREIGN KEY (tenant_id, target_resource_id) REFERENCES resource (tenant_id, id)`
- The same pattern should be applied to identifiers, ownership rows, classifications, labels, state rows, and merge records.

Application-level validation may duplicate these checks, but it should not replace database enforcement because the database is the last line of defense for consistency.

## Constraints and governance

The design applies the following constraints:

- `tenant_id` is mandatory for every tenant-owned row.
- `resource_relationship.source_resource_id` must not equal `resource_relationship.target_resource_id`.
- `confidence_score` must satisfy $0.0000 \leq confidence_score \leq 1.0000$.
- `valid_to` must be null or greater than `valid_from`.
- Relationship and assignment rows must belong to the same tenant as both the source and target resources.
- Primary keys, foreign keys, unique constraints, partial unique constraints, and check constraints are part of the logical design even if the initial implementation is still documentation-first.

## Catalog scope policy

The documentation adopts a single consistent model for reference catalogs:

- System catalogs such as `resource_type`, `identifier_type`, `lifecycle_status`, `criticality`, `exposure_level`, `relationship_type`, `ownership_role`, `classification_type`, and `classification_value` are global managed reference data.
- Tenant-owned assignment and operational tables always contain `tenant_id`.
- Tenant-specific overrides or extensions may be introduced later as separate entities if the product requires them.
- `label` remains tenant-scoped because labels are operational annotations and not global reference data.

This approach avoids ambiguous duplication of reference catalogs across tenants while still preserving tenant-scoped operational tables.

## Design principles

### Hybrid resource model

The domain uses a hybrid model with:

- a canonical resource row for durable logical identity;
- identifier rows for deterministic matching;
- alias rows for operational lookup history;
- relationship and ownership rows for graph semantics and history;
- classification and label rows for controlled extension.

### Tenant from day one

Tenant isolation is a mandatory constraint and not an afterthought. It supports multi-tenancy, tenant-local uniqueness, and future sharding.

### UUIDv7 for major entities

UUIDv7 is the preferred identifier strategy for major entities because it is globally sortable, distributed-write friendly, and well suited to future partitioning.

### Temporal validity and system time

The model separates logical validity from record metadata:

- `valid_from` / `valid_to` express logical validity;
- `created_at` / `updated_at` express record lifecycle;
- `resource_state.valid_from` expresses logical state-transition effective time.
