# ADR-RI-004: Preserve temporal validity for identifiers and relations

## Status
Accepted

## Context
Identifiers and relationships change over time and must support historical interpretation without destroying the current truth.

## Decision
Represent identifier and relationship facts with explicit validity windows and event timestamps so the model can distinguish between current validity and historical record.

## Consequences
The model supports auditability, historical analysis, and later decomposition into event-driven or time-versioned stores without losing the logical current state.
