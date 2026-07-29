# ADR-RI-002: Tenant isolation is a first-class design constraint

## Status
Accepted

## Context
The domain must support multi-tenant operation and future sharding without redesigning the model. A global identifier space or global coordination layer would be fragile as the system grows, especially when tenants must be isolated by policy and by storage placement.

## Decision
Every tenant-owned entity carries `tenant_id` and the design assumes tenant-based isolation as a primary constraint from the start.

## Alternatives considered
- Adding `tenant_id` later after the core model is stabilized.
- Relying on application-layer filtering without database-level scoping.
- Using a global table without tenant partitioning.

## Benefits
- Enables tenant-scoped uniqueness and authorization.
- Simplifies future tenant-based sharding.
- Avoids the need for a global coordination service between shards.

## Drawbacks
- Adds an extra key to nearly every row.
- Requires disciplined access control and query planning.

## Consequences
The model supports future sharding and clear isolation boundaries while keeping authorization and data governance semantics consistent.

## Future implications
The tenant boundary is expected to become the primary partitioning and replication boundary as the platform scales.
