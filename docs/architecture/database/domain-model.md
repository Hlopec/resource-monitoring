# Resource Inventory domain model

## Purpose

The Resource Inventory bounded context is responsible for representing the canonical inventory of digital resources that an organization manages, the identities that reference them, the relationships between them, and the lifecycle history of those facts. It is intentionally modeled as a shared, tenant-aware foundation that can support future bounded contexts such as observations, technology detections, finding events, audit events, and outbox events without forcing those domains into the core model.

## Boundaries

The Resource Inventory model owns:

- a tenant and organization hierarchy;
- resource types and the abstract resource entity;
- resource identities and identifiers;
- ownership and relationship facts;
- classification, labels, and lifecycle state history;
- merge and deduplication audit evidence.

It does not own the semantics of downstream observations or remediation workflows. Those later domains may depend on Resource Inventory as an external reference domain.

## Core entities

### Tenant

A tenant is the top-level isolation boundary for all data in the domain. Every tenant-owned entity carries a tenant identifier and is governed by tenant-local constraints and, later, tenant-based sharding.

### Organization

Organizations are hierarchical containers that represent the reporting and administrative boundaries within a tenant. They are modeled as a parent-child hierarchy to support ownership and policy propagation while still allowing direct resource ownership at the resource level.

### Resource type

A resource type hierarchy supports polymorphic classification of resources while preserving a stable taxonomy for the domain. Resource types can be organized as a tree so that downstream logic can reason about inheritance and category grouping.

### Resource

Resource is the central entity. It represents a logical resource record that may be referenced by many identifiers and related to many other resources. It is the primary place for the current logical state of the resource, while historical facts remain in versioned or event-based structures.

### Resource identifier

A resource identifier captures a specific identifier value associated with a given identifier type. The model supports deterministic identity matching using normalized values and provides a place for audit evidence about how identifiers were observed and interpreted.

### Ownership role and resource ownership

Ownership roles define the purpose of an ownership relationship, while resource ownership records the association between a resource and an organization or actor boundary. Ownership is treated as a first-class fact that can change over time and must be reproducible through temporal validity.

### Relationship type and resource relationship

Resource relationships model directed associations between resources, such as parent-child, dependency, or containment relationships. Temporal validity is essential because relationships change over time and can be superseded.

### Classification type, classification value, and resource classification

Classification values provide a flexible but controlled vocabulary for tagging resources. Resource classification records the assignment of a classification value to a resource within a specific domain, enabling future extension without creating a wide-open free-form tag model.

### Label and resource label

Labels provide lightweight case-specific annotation without changing the canonical resource definition. Resource labels attach a label to a resource, while the label vocabulary remains tenant-scoped and governed by policies.

### Resource state history

Resource state history records the timeline of lifecycle changes for a resource, including state changes, effective timestamps, and audit context. It is designed to preserve historical state without mutating the logical resource record in place.

### Resource merge

Resource merge records the act of consolidating two or more resources into a single canonical resource. This entity stores merge evidence, policy decisions, reviewer identity, and rollback or review status so that merge operations remain auditable and reversible where required.

## Six conceptual extension entities

The issue requires the ERD to include six conceptual extension entities that represent future domains that depend on Resource Inventory but remain outside the core domain. These are documented conceptually as external dependencies rather than implemented entities:

1. Resource observation
2. Technology detection
3. Finding event
4. Audit event
5. Outbox event
6. Vulnerability record

They are not part of the core data ownership model; rather, they reference resources and may later form their own bounded contexts.

## Design principles

### Hybrid resource model

The domain uses a hybrid resource model:

- a canonical resource record for the durable logical identity;
- a set of identifiers that allow deterministic matching;
- historical and relationship facts that preserve evolving context;
- flexible classification and labeling that can be extended without breaking the core model.

This hybrid model avoids overloading the core resource entity with all possible context and keeps the model scalable for later decomposition.

### Tenant from day one

Every tenant-owned entity must include a tenant identifier. This is a mandatory design constraint, not an afterthought. It enables future tenant-based sharding, multi-tenant isolation, and consistent authorization policies.

### UUIDv7 for major entities

UUIDv7 is the recommended major-entity key strategy for entities that need a globally sortable identifier without exposing an increasing integer sequence. It is suited to distributed writes and future partitioning strategies.

### Temporal validity and system time

The model distinguishes between:

- valid_from / valid_to for logical validity of facts;
- created_at for the time the record was created;
- updated_at for the last mutation to the record;
- changed_at for state transitions or event application times.

This distinction prevents ambiguity when historical facts are reinterpreted or when the system needs to preserve the time a change was observed versus the time it became valid.

## Lifecycle policies

The model distinguishes between mutable, immutable, versioned, historical, derived, and ephemeral facts:

- Mutable facts: current ownership, current classification, current labels.
- Immutable facts: identifier types, relationship types, ownership roles, classification types.
- Versioned facts: resource state history and relationship history.
- Historical facts: merge audit records and prior ownership facts.
- Derived facts: aggregated classification or ownership summaries.
- Ephemeral facts: transient review state or temporary deduplication signals.

## Constraints and rules

- Every tenant-owned entity must carry tenant_id.
- Every major entity should have a stable UUIDv7 primary key.
- Resource identifiers must be normalized before use in deterministic matching.
- Resource merges must never be silent; they require evidence and review policy.
- Hard deletion is not the default for resources. A resource should be logically retired or superseded rather than deleted outright.
- Controlled JSONB usage is reserved for flexible metadata that is not the primary query surface and should be treated as a bounded extension, not a substitute for structured domain fields.

## Notes on future decomposition

As the platform grows, this model can be split into separate bounded contexts. The core Resource Inventory model remains the canonical source of resource identity and relationships, while later domains can own their own specialized event and observation data.
