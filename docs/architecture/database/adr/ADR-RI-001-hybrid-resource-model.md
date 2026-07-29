# ADR-RI-001: Use a hybrid resource model

## Status
Accepted

## Context
The Resource Inventory domain must support a large, evolving graph of resources, identifiers, relationships, and historical facts without overloading the resource entity with every possible context. The design must also preserve future flexibility for subtype-specific extensions without turning the core model into a generic JSONB dump.

## Decision
Use a hybrid resource model with:

- a canonical `resource` row for durable logical identity;
- a set of structured identifier and relationship rows for deterministic matching and graph semantics;
- controlled classification and label rows for annotations;
- optional subtype-specific extension tables when the workload needs strict constraints or PostgreSQL-specific types.

## Alternatives considered
- A separate table for each resource type.
- A single generic JSONB-only table.
- A hybrid resource model with core plus type extensions.

## Benefits
- Preserves a stable core identity model.
- Avoids schema explosion from one table per subtype.
- Allows subtype-specific optimization when it is justified.
- Keeps the model queryable and auditable.

## Drawbacks
- Requires a more deliberate model than a single generic table.
- Some subtype logic must be implemented as extension tables rather than as a single monolithic entity.

## Consequences
This keeps the core entity stable and simplifies future bounded-context decomposition while still supporting large-scale identity and graph operations.

## Future implications
The hybrid model can evolve toward more specialized bounded contexts over time while preserving a shared core inventory.
