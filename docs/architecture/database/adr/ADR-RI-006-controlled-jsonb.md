# ADR-RI-006: Use controlled JSONB for flexible metadata only

## Status
Accepted

## Context
Some metadata is naturally flexible and may evolve faster than the core schema, but overusing unstructured data can weaken queryability.

## Decision
Use JSONB only for bounded, flexible metadata that is not the primary query surface. Structured domain fields remain the preferred representation for first-class facts.

## Consequences
The model remains queryable and auditable while still allowing extension for metadata-heavy or tenant-specific needs.
