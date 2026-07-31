# Resource Inventory domain model

## Purpose

The Resource Inventory bounded context represents the canonical inventory of digital resources that an organization manages. The model is intentionally centered on durable identity, tenant isolation, temporal validity, and auditable merge behavior so that future downstream domains can depend on it without embedding their own lifecycle semantics in the core schema.

## Scope and boundaries

The core model owns:

- tenant and organization hierarchy;
- resource types and the abstract resource entity;
- resource identifiers and deterministic identity evidence;
- ownership and relationship facts;
- classifications, labels, state history, and merge evidence.

The model does not treat downstream observations, technology detections, finding events, audit events, outbox events, or vulnerability records as part of the core Resource Inventory ERD. Those domains may be modeled later as separate bounded contexts that reference Resource Inventory as a shared dependency.

## Core entities

### Tenant

A tenant is the top-level isolation boundary for all data in the domain. The logical tenant row uses `id`, `slug`, `display_name`, `status`, `created_at`, and `updated_at`. Every tenant-owned entity carries a tenant identifier and remains scoped to tenant-local governance and future tenant-based sharding.

### Organization

Organizations define the administrative and reporting boundary within a tenant. They form a hierarchical structure that can be used for ownership propagation and policy scope. The logical model includes `organization_type_id`, `canonical_name`, `external_key`, `status`, `created_at`, `updated_at`, and `archived_at`. If `organization_type_id` or lifecycle-related reference values are introduced later, they are treated as managed reference catalogs and are not part of the core resource-inventory implementation in this PR.

### Resource type

Resource types define a stable taxonomy for the domain and support future inheritance-based grouping without overloading the resource entity with every possible subtype distinction. The logical fields are `id`, `code`, `display_name`, `parent_type_id`, `category`, `schema_version`, `is_system`, `is_active`, `created_at`, and `updated_at`.

### Resource

Resource is the canonical logical record. It stores the current state of the resource, including lifecycle status, criticality, exposure level, identity confidence, and temporal observation markers. The entity includes a `record_version` field for optimistic concurrency control.

The resource table does not carry `valid_from` and `valid_to` because those are represented by versioned relationships, ownership assignments, identifiers, and state-history rows rather than by the core resource row itself. The logical reference fields `lifecycle_status_id`, `criticality_id`, and `exposure_level_id` are modeled as foreign keys to managed reference catalogs, even though those catalog entities may be detailed later during the implementation stage.

`source_priority` is constrained to the range `0..1000`, `confidence_score` is constrained to `0.0000..1.0000`, and `record_version` must remain greater than zero. Resource archive behavior is logical through `archived_at`.

### Resource identifier

Resource identifier stores a specific identifier value for a resource, using an identifier type and a normalized representation. Each assignment remains temporally versioned so that the identity evidence can be audited and superseded when required.

Current identifier uniqueness is scoped to `tenant_id`, `identifier_type_id`, namespace, and `normalized_value`, with `NULL` namespace treated as the empty namespace for uniqueness. `value_hash` is only a lookup accelerator; identity matching still requires full `normalized_value` comparison after hash lookup, and hash collisions must not conflict when normalized values differ.

### Ownership role and resource ownership

Ownership roles describe the purpose of an ownership relationship and remain global managed catalog values. Resource ownership stores the association between a resource and an organization with a validity window, an optional source, a primary marker, and a confidence score. Ownership is not modeled as a mutable current-state record in the same way as a simple flag; it is a temporally versioned assignment fact.

The implemented ownership table enforces tenant-safe composite foreign keys to both `resource` and `organization`. A current row has `valid_to IS NULL`; changing ownership closes the old row with `valid_to` and inserts a new row. Current ownership uniqueness is scoped to `tenant_id`, `resource_id`, `organization_id`, and `ownership_role_id`, while current primary ownership is limited to one row per `tenant_id`, `resource_id`, and `ownership_role_id`. Referenced resources, organizations, and ownership roles use restrictive deletes so historical ownership evidence is not removed implicitly.

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

### Resource state history

Resource state history is immutable append-only evidence of lifecycle transitions. It stores the state, confidence, reason, and source event that caused the transition. Its `lifecycle_status_id`, `criticality_id`, and `exposure_level_id` fields are logical foreign keys to the same managed reference catalogs used by `resource`.

### Resource merge

Resource merge stores the evidence and policy outcome of the consolidation of two resources into one canonical resource. It is designed for auditability, review, rollback, and policy enforcement.

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
- The same pattern should be applied to identifiers, ownership rows, classifications, labels, and merge records.

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
- `changed_at` expresses state-transition application time.
