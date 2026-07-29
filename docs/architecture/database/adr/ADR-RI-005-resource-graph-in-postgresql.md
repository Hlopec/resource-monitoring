# ADR-RI-005: Use PostgreSQL as the initial resource graph store

## Status
Accepted

## Context
The Resource Inventory model requires a relational foundation that can express graph-like relationships, temporal validity, and strong constraints while remaining practical for the initial implementation. A graph database may eventually be useful for analytics or path traversal, but it should not be the first implementation chosen.

## Decision
Use PostgreSQL as the initial store for the Resource Inventory domain because it provides a strong relational model, rich constraints, and a practical path to future scaling through read replicas and sharding.

## Alternatives considered
- A native graph database for the core relationship model.
- A document store for the entire domain.
- A PostgreSQL relational model with future derived read models.

## Benefits
- Supports relationship semantics, temporal validity, and strong constraints in a single store.
- Fits the current architecture-first scope and does not introduce an extra runtime dependency.
- Enables future partitioning and read-replica patterns without redesigning the logical model.

## Drawbacks
- Graph traversal is less elegant than in a dedicated graph database.
- Very large traversals may later require derived read models or specialized indexes.

## Consequences
The initial architecture remains grounded in a mature relational engine while leaving room for future partitioned and distributed deployments.

## Future implications
A graph database may be introduced later as a derived read model or an auxiliary graph index, but it is not part of the initial core design.
