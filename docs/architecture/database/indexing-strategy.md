# Logical indexing strategy

## Design goals

The indexing strategy must support:

- fast lookup by tenant and resource identifier;
- efficient traversal of relationship and ownership graphs;
- historical queries by time and validity window;
- deduplication and merge review queries;
- scaling to large, tenant-sharded deployments.

## Required logical indexes

### Core entities

- `(tenant_id, resource_id)` for resource lookups and joins.
- `(tenant_id, organization_id)` for organization-scoped queries.
- `(tenant_id, resource_type_id)` for type-based filtering.
- `(tenant_id, created_at)` for time-bounded scans.

### Resource identifiers

- `(tenant_id, identifier_type_id, normalized_value)` for deterministic identity matching.
- `(tenant_id, resource_id, identifier_type_id)` for reverse lookups.

### Ownership and relationships

- `(tenant_id, resource_id, valid_to)` for current ownership and relationship lookups.
- `(tenant_id, source_resource_id, relationship_type_id, valid_to)` for directed relationship queries.
- `(tenant_id, target_resource_id, relationship_type_id, valid_to)` for reverse relationship queries.
- `(tenant_id, organization_id, ownership_role_id, valid_to)` for ownership policy queries.

### Classification and labels

- `(tenant_id, resource_id, classification_value_id)` for classification lookups.
- `(tenant_id, resource_id, label_id)` for label lookups.

### Temporal and history tables

- `(tenant_id, resource_id, changed_at DESC)` for resource state history.
- `(tenant_id, resource_id, event_time DESC)` for historical relationship and identifier records.

## Important constraints

All potentially large tenant-owned entities must include both:

- tenant_id;
- created_at or a relevant event timestamp.

This is required for localized scans, partitioning, and replication behavior.

## Indexing evolution

The initial implementation should not over-index every table. The priority is to support the primary read paths for resource identity, relationship traversal, ownership review, and merge audit. As the system grows, additional composite indexes or partial indexes can be added based on actual workload patterns.
