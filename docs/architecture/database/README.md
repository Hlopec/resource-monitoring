# Resource Inventory database architecture

This directory contains the architectural documentation for the Resource Inventory bounded context.

## Scope

These documents describe the logical domain model, lifecycle semantics, indexing and partitioning strategy, and the architectural decisions needed to support a future PostgreSQL-backed implementation for:

- tens of millions of resources;
- hundreds of millions of historical, technological, and vulnerability records;
- read replicas;
- tenant-based sharding;
- horizontal scaling;
- future extraction of bounded contexts into separate services.

The documentation is intentionally architecture-first. It does not introduce SQLAlchemy models, Alembic migrations, SQL schema, API routes, repositories, collectors, or business logic.

## Document map

- [domain-model.md](domain-model.md) — responsibilities, entities, relationships, lifecycle policies, and constraints.
- [data-lifecycle.md](data-lifecycle.md) — mutable, immutable, versioned, historical, derived, and ephemeral policies.
- [indexing-strategy.md](indexing-strategy.md) — logical indexes and their purpose.
- [partitioning-strategy.md](partitioning-strategy.md) — evolution from single primary to sharded deployment.
- [erd/resource-inventory.mmd](erd/resource-inventory.mmd) — Mermaid ERD for the Resource Inventory domain.
- [adr](adr) — architecture decision records for the core design choices.
