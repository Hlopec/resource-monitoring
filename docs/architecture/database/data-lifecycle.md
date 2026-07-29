# Data lifecycle policies

## Policy categories

### Mutable facts

Mutable facts represent the current logical state of the resource as seen by the system. These include the current ownership assignment, current labels, and current classifications.

Mutable facts should be stored in current-state records that can be updated without changing the historical record of earlier states. The current state is not the only truth; it is simply the latest accepted state.

### Immutable facts

Immutable facts are reference values whose meaning is stable over time. Examples include identifier types, relationship types, ownership roles, and classification types.

These values should be defined as low-churn reference entities with strong constraints and limited update policy. They should not be treated as tenant-specific business configuration unless the design later requires it.

### Versioned facts

Versioned facts represent facts that change over time and for which history matters. Examples include resource state history and relationship history.

Versioned records should retain their own timestamp and validity columns so the history can be queried independently of the current state record.

### Historical facts

Historical facts preserve the record of what happened, not just what is currently true. Merge events, ownership changes, and identifier changes should be represented so that investigators can understand how the current state arose.

Historical records should include evidence and review status where applicable.

### Derived facts

Derived facts are computed summaries that are useful for read-heavy workloads but should not be treated as the source of truth. Examples include denormalized ownership summaries or aggregations.

Derived facts may be materialized later for performance, but they must remain clearly derived and not replace the authoritative source records.

### Ephemeral facts

Ephemeral facts are temporary signals that support review workflows, deduplication, or operational actions. These are not canonical state and should be clearly separated from durable domain facts.

Examples include temporary matching confidence signals, review queue state, and rollback markers.

## Temporal validity model

The lifecycle model separates:

- valid_from / valid_to for logical validity;
- created_at for the creation timestamp;
- updated_at for the last mutation;
- changed_at for state transition or event application time.

This separation is critical for model correctness when a fact becomes valid at a different time than it was recorded or when a change is applied retrospectively.

## Delete behavior

Hard deletes are not the default policy. Instead:

- resources should be logically retired when they are no longer active;
- relationships and ownership facts should become invalid rather than removed outright;
- merge operations should retain evidence and not silently discard the prior resource identity.

This approach supports auditability and rollback while protecting the integrity of historical relationships.
