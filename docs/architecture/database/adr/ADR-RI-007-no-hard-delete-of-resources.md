# ADR-RI-007: Do not hard-delete resources

## Status
Accepted

## Context
Resources and their relationships are long-lived and often require auditability and rollback support. Broad `ON DELETE CASCADE` behavior would also be unsafe because a single deletion could erase the evidence needed for historical analysis or a rollback decision.

## Decision
Do not hard-delete resources. Instead, resources should be archived, superseded, or logically retired, and historical facts should remain available for review. Relationship and ownership rows should be invalidated using temporal validity rather than removed. Restrictive foreign key behavior should be used so the system preserves evidence and avoids accidental loss.

## Alternatives considered
- Broad `ON DELETE CASCADE` for related rows.
- Immediate physical deletion after a merge or archive operation.
- Soft deletes only on the resource row while leaving dependent records intact.

## Benefits
- Preserves auditability and rollback capability.
- Prevents accidental loss of merge or ownership evidence.
- Makes the model safer for historical reconciliation.

## Drawbacks
- Requires more storage and cleanup discipline over time.
- Some read paths must explicitly filter out archived or superseded records.

## Consequences
The domain retains a durable audit trail and supports the merge and rollback model required by the deduplication design.

## Future implications
Physical deletion remains acceptable only for transient review rows or data without remaining audit dependencies. The default lifecycle remains archive/supersede rather than delete.
