# ADR-RI-006: Use controlled JSONB for flexible metadata only

## Status
Accepted

## Context
Some metadata is naturally flexible and may evolve faster than the core schema, but unstructured storage can weaken queryability, validation, and portability if it is used too broadly.

## Decision
Use JSONB only for bounded, flexible metadata that is not the primary query surface. Structured domain fields remain the preferred representation for first-class facts.

## Alternatives considered
- Storing all flexible payloads in JSONB.
- Expanding the core schema for every possible metadata variant.
- Using a separate key-value or document store for metadata.

## Benefits
- Keeps the core model queryable and auditable.
- Supports tenant-specific metadata shapes when needed.
- Avoids overfitting the relational schema to ephemeral extensions.

## Drawbacks
- JSONB is less strict than typed columns.
- Some query patterns become more complex and less index-friendly.

## Consequences
The model remains queryable and auditable while still allowing extension for metadata-heavy or tenant-specific needs.

## Future implications
JSONB should remain a bounded extension mechanism. If a metadata shape becomes common and heavily queried, it should migrate into structured columns or dedicated tables.

### Allowed JSONB usage
- metadata payloads attached to a merge decision;
- unstructured evidence for a relationship or ownership record;
- tenant-specific extension data that does not require strong relational semantics.

### Forbidden JSONB usage
- core identity, lifecycle state, ownership, relationship semantics, or classification assignments where structured columns are required;
- fields that need frequent filtering, unique constraints, or join semantics;
- any replacement for the canonical schema of resource inventory facts.
