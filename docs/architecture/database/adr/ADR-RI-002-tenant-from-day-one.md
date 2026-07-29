# ADR-RI-002: Tenant isolation is a first-class design constraint

## Status
Accepted

## Context
The domain must support multi-tenant operation and future sharding without redesigning the model.

## Decision
Every tenant-owned entity carries tenant_id and the design assumes tenant-based isolation as a primary constraint from the start.

## Consequences
The model supports future sharding and clear isolation boundaries while keeping authorization and data governance semantics consistent.
