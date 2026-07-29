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

A tenant is the top-level isolation boundary for all data in the domain. Every tenant-owned entity carries a tenant identifier and remains scoped to tenant-local governance and future tenant-based sharding.

### Organization

Organizations define the administrative and reporting boundary within a tenant. They form a hierarchical structure that can be used for ownership propagation and policy scope.

### Resource type

Resource types define a stable taxonomy for the domain and support future inheritance-based grouping without overloading the resource entity with every possible subtype distinction.

### Resource

Resource is the canonical logical record. It stores the current state of the resource, including lifecycle status, criticality, exposure level, identity confidence, and temporal observation markers. The entity includes a `record_version` field for optimistic concurrency control.

The resource table does not carry `valid_from` and `valid_to` because those are represented by versioned relationships, ownership assignments, identifiers, and state-history rows rather than by the core resource row itself.

### Resource identifier

Resource identifier stores a specific identifier value for a resource, using an identifier type and a normalized representation. Each assignment remains temporally versioned so that the identity evidence can be audited and superseded when required.

### Ownership role and resource ownership

Ownership roles describe the purpose of an ownership relationship. Resource ownership stores the association between a resource and an organization with a validity window, a source, and a confidence score. Ownership is not modeled as a mutable current-state record in the same way as a simple flag; it is a temporally versioned assignment fact.

### Relationship type and resource relationship

Resource relationships capture directed associations such as dependency, containment, or parent-child links. Each relationship is temporally versioned and may be superseded over time.

### Classification type, classification value, and resource classification

Classification values provide a controlled vocabulary for tagging resources. Resource classification records the assignment of a classification value to a resource with a temporal validity window so the model can preserve the history of the assignment.

### Label and resource label

Labels provide lightweight annotations without changing canonical identity. Resource label attachments remain temporal facts so that labels can be removed or superseded without losing audit context.

### Resource state history

Resource state history is immutable append-only evidence of lifecycle transitions. It stores the state, confidence, reason, and source event that caused the transition.

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

## Constraints and governance

The design applies the following constraints:

- `tenant_id` is mandatory for every tenant-owned row.
- `resource_relationship.source_resource_id` must not equal `resource_relationship.target_resource_id`.
- `confidence_score` must satisfy $0.0000 \leq confidence_score \leq 1.0000$.
- `valid_to` must be null or greater than `valid_from`.
- Relationship and assignment rows must belong to the same tenant as both the source and target resources.
- Primary keys, foreign keys, unique constraints, partial unique constraints, and check constraints are part of the logical design even if the initial implementation is still documentation-first.

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
