# Logical indexing strategy

## Design goals

The initial indexing plan is designed to support:

- tenant-scoped lookups for resources and identifiers;
- efficient traversal of ownership and relationship graphs;
- historical queries by validity window and time;
- merge review and deduplication workflows;
- future tenant-sharded deployments.

## Required logical indexes

### Resource

- `(tenant_id, resource_type_id, lifecycle_status_id)`
- `(tenant_id, last_seen_at DESC)`
- `(tenant_id, first_seen_at)`
- `(tenant_id, archived_at)` where `archived_at IS NOT NULL`
- `(tenant_id, criticality_id)` where `archived_at IS NULL`

These indexes support inventory browsing, active-resource prioritization, and lifecycle filtering without scanning unrelated tenants.

### Resource identifier

- `UNIQUE (tenant_id, identifier_type_id, namespace, value_hash) WHERE valid_to IS NULL`
- `(tenant_id, resource_id) WHERE valid_to IS NULL`

The partial unique index ensures there is only one active identifier assignment for a given tenant, identifier type, namespace, and normalized value. The second index supports reverse lookup from a resource to its active identifiers.

`normalized_value` should be indexed directly when the workload needs case-insensitive search, prefix search, or human-readable lookup. `value_hash` should be used for exact equality and uniqueness checks because it is compact and normalized. For deterministic identity matching, the hash is typically the primary comparison key while `normalized_value` remains the display and audit value.

### Resource relationship

- `(tenant_id, source_resource_id, relationship_type_id) WHERE valid_to IS NULL`
- `(tenant_id, target_resource_id, relationship_type_id) WHERE valid_to IS NULL`
- `UNIQUE (tenant_id, source_resource_id, relationship_type_id, target_resource_id) WHERE valid_to IS NULL`

These indexes support relationship traversal and prevent the creation of duplicate active relationships.

### Resource ownership

- `(tenant_id, organization_id, ownership_role_id) WHERE valid_to IS NULL`
- `(tenant_id, resource_id) WHERE valid_to IS NULL`

These indexes support ownership review and efficient current-state ownership lookups.

### Resource state history

- `(tenant_id, resource_id, changed_at DESC)`

This index supports the append-only timeline of state transitions and allows the latest state transition to be read efficiently.

## Constraints and governance

The strategy assumes that every large, tenant-owned table is indexed by tenant first. This supports localized scans, partitioning, replication, and future sharding without requiring a global coordination layer.

The design also assumes the following logical constraints:

- `resource_relationship.source_resource_id != resource_relationship.target_resource_id`
- `confidence_score` is constrained to $0.0000 \leq confidence_score \leq 1.0000$
- `valid_to IS NULL OR valid_to > valid_from`
- relationship and ownership rows must belong to the same tenant as their related resources

## Index evolution

These are the initial logical indexes for the core model. They should be implemented before introducing denormalized read models or other performance-oriented extensions.
