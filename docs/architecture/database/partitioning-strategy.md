# Partitioning strategy

## Evolutionary approach

Partitioning should be introduced as an evolutionary strategy, not as a premature default. The central resource table is a poor early partitioning target because partitioning it too early can complicate:

- global and tenant-local uniqueness;
- foreign keys;
- migrations;
- ORM behavior;
- cross-partition queries.

## Initial state

The initial deployment should use a single PostgreSQL primary for the core Resource Inventory model. This keeps the design simple while allowing the logical model to mature.

## Second phase: primary plus read replicas

Once read demand increases, the deployment can add read replicas for query offloading. The logical model is compatible with this pattern because the core domain remains shared and tenant-aware.

## Third phase: tenant-based horizontal sharding

Tenant-based horizontal sharding becomes the preferred strategy once tenant isolation and write volume require stronger physical separation. The sharding key should be tenant_id, and the system should ensure that tenant-local integrity rules remain enforced within each shard.

## Partitioning candidates for later domains

The issue calls for future partitioning candidates in historical and high-volume domains. The likely candidates are:

- resource_state_history
- resource_relationship_history
- resource_identifier_history
- resource_merge

Later domains that are expected to become the largest partitioned tables include:

- observations;
- technology detections;
- finding events;
- audit events;
- outbox events.

## Recommended strategies

The logical partitioning strategies should follow the workload profile:

- HASH(tenant_id) for tenant-local distribution;
- RANGE(event timestamp) for time-based retention and archival;
- HASH tenant + RANGE time for the strongest balance between tenant isolation and temporal access patterns.

## Key architectural implication

Partitioning is a scaling mechanism, not a replacement for domain design. The logical model must remain tenant-aware, temporally expressive, and sufficiently stable to survive re-sharding over time.
