# ADR-RI-004: Preserve temporal validity for identifiers and relations

## Status
Accepted

## Context
Identifiers and relationships change over time and must support historical interpretation without destroying the current truth. The model must distinguish between the time a fact became valid and the time the record was created or modified.

## Decision
Represent identifier, ownership, relationship, and classification facts with explicit validity windows using `valid_from` and `valid_to`. The model also keeps record metadata such as `created_at`, `updated_at`, and `changed_at` to distinguish between logical validity and system-time metadata.

## Alternatives considered
- Using only `created_at` and `updated_at` for all facts.
- Treating the current row as the only truth and discarding historical versions.
- Encoding historical state only in application logic.

## Benefits
- Preserves a complete audit trail.
- Makes historical reconstruction possible without ambiguity.
- Separates logical validity from record metadata.

## Drawbacks
- Slightly more complex query semantics for the current-state view.
- Requires discipline when writing temporal predicates.

## Consequences
The model supports auditability, historical analysis, and later decomposition into event-driven or time-versioned stores without losing the logical current state.

## Future implications
The temporal model is foundational for later event-sourcing or materialized-view approaches without forcing those patterns into the initial design.
