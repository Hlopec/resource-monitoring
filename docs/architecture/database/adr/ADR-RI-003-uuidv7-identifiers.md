# ADR-RI-003: Use UUIDv7 for major entity identifiers

## Status
Accepted

## Context
The system must support distributed writes, future sharding, and a key strategy that is globally sortable without relying on incrementing integer sequences. The identifier strategy must also work well for external integrations and cross-system exchange.

## Decision
Use UUIDv7 as the preferred primary key strategy for major entities in the Resource Inventory domain.

## Alternatives considered
- UUIDv4.
- Auto-incrementing `BIGINT`.
- UUIDv7 for major entities and a smaller surrogate key for highly volatile tables.

## Benefits
- Distributed writes are easier to scale because the key is not centralised on a single sequence.
- UUIDv7 preserves temporal locality in B-tree indexes and is friendly to ordering by creation time.
- Sharding is easier because tenant-scoped writes can be spread without relying on a global counter.
- External integrations can exchange stable identifiers without exposing a database sequence.

## Drawbacks
- Storage overhead is higher than `BIGINT`.
- UUIDv7 is less familiar than UUIDv4 and requires a clear convention in the implementation team.

## Consequences
UUIDv7 provides a practical compromise between distributed write performance, storage overhead, and future partitioning compatibility.

## Future implications
If the system later requires more compact keys for very large, hot tables, a hybrid strategy may be introduced, but the logical identity contract remains UUID-based.
