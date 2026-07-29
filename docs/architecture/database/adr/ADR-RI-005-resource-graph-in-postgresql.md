# ADR-RI-005: Use PostgreSQL as the initial resource graph store

## Status
Accepted

## Context
The Resource Inventory model requires a relational foundation that can express graph-like relationships, temporal validity, and strong constraints while remaining vendor-neutral and practical for the initial implementation.

## Decision
Use PostgreSQL as the initial store for the Resource Inventory domain because it provides a strong relational model, rich constraints, and a practical path to future scaling through read replicas and sharding.

## Consequences
This decision keeps the initial architecture grounded in a mature relational engine while leaving room for future partitioned and distributed deployments.
