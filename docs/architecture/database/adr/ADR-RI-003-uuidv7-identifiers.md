# ADR-RI-003: Use UUIDv7 for major entity identifiers

## Status
Accepted

## Context
The system must support distributed writes, future sharding, and a key strategy that is globally sortable without relying on incrementing integer sequences.

## Decision
Use UUIDv7 as the preferred primary key strategy for major entities in the Resource Inventory domain.

## Consequences
This improves write distribution and future partitioning compatibility while providing a stable identifier format for cross-system exchange.
