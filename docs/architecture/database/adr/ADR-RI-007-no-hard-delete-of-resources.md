# ADR-RI-007: Do not hard-delete resources

## Status
Accepted

## Context
Resources and their relationships are long-lived and often require auditability and rollback support.

## Decision
Do not hard-delete resources. Instead, resources should be logically retired or superseded, and historical facts should remain available for review.

## Consequences
The domain retains a durable audit trail and supports the merge and rollback model required by the deduplication design.
