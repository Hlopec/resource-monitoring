# ADR-RI-001: Use a hybrid resource model

## Status
Accepted

## Context
The Resource Inventory domain must support a large, evolving graph of resources, identifiers, relationships, and historical facts without overloading the resource entity with every possible context.

## Decision
Use a hybrid model where:

- the canonical resource is the durable logical identity;
- identifiers support deterministic matching;
- relationships and historical facts preserve the evolving graph;
- classifications and labels provide flexible but controlled annotation.

## Consequences
This keeps the core entity stable and simplifies future decomposition into bounded contexts while still supporting large-scale identity and graph operations.
