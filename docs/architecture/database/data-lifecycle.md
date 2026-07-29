# Data lifecycle policies

## Policy matrix

| Entity | Policy | Notes |
| --- | --- | --- |
| tenant | mutable, audited | Tenant records may be updated but should remain under explicit change control. |
| organization | mutable, audited | Organization hierarchy changes are tracked and reviewed. |
| resource_type | mutable, schema-versioned | Reference values may evolve, but changes should be versioned and constrained. |
| resource | mutable, optimistic version, state history | The resource row is mutable, but its lifecycle is guarded by `record_version` and state-history append-only rows. |
| resource_identifier | immutable record, temporally versioned | Identifier assignments remain durable and are superseded by new validity windows rather than overwritten. |
| resource_ownership | immutable assignment record, temporally versioned | Ownership is a fact with a validity period, not a simple current-state flag. |
| resource_relationship | temporally versioned relationship | Relationships can change over time and must remain historically reconstructable. |
| resource_classification | immutable assignment record, temporally versioned | Classification assignments are versioned facts even when the current classification is updated. |
| resource_state_history | immutable append-only | Each transition is preserved as an audit record. |
| resource_merge | immutable append-only | Merge decisions are never silently overwritten. |

## Policy categories

### Mutable facts

Mutable facts represent the current accepted state of the system, such as organization structure or the current logical resource record. These rows may be updated, but the update path should always be auditable.

### Immutable facts

Immutable facts are stable reference values such as identifier types, relationship types, ownership roles, and classification types. These values should change rarely and should be governed by controlled reference-data processes.

### Versioned facts

Versioned facts include identifiers, ownership, relationships, and classifications. Each record is given a validity window so that the current fact and the historical fact can both be represented.

### Historical facts

Historical facts preserve the record of change. Resource state history and resource merge rows are primary examples because they document the reason and evidence behind a state transition or merge decision.

### Derived facts

Derived facts may be introduced later for read-heavy workloads, such as denormalized ownership summaries or materialized relationship counts. They are not the source of truth and must be clearly marked as derived.

### Ephemeral facts

Ephemeral facts are temporary working state used during review, deduplication, or workflow execution. They should not be confused with authoritative domain records.

## Temporal validity model

The model separates:

- `valid_from` / `valid_to` for logical validity of a relationship, ownership, identifier, or classification assignment;
- `created_at` / `updated_at` for record lifecycle metadata;
- `changed_at` for state-transition application time;
- `record_version` for optimistic concurrency control on the mutable primary resource row.

## Delete behavior

Hard deletes are not the default policy. Instead:

- resources may be archived or superseded;
- relationship, ownership, and classification rows become invalid rather than physically removed;
- merge operations preserve evidence and review state;
- restrictive foreign keys prevent accidental deletion of referenced core facts.

Physical deletion remains acceptable only for transient review rows or data that is explicitly marked as removable and has no remaining audit dependency.
