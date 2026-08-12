"""Resource query contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetResourceByIdQuery:
    """Reference query for tenant-scoped resource lookup by id."""

    tenant_id: UUID
    resource_id: UUID


@dataclass(frozen=True)
class GetResourceDetailsQuery:
    """Query for a fully materialized tenant-scoped resource projection."""

    tenant_id: UUID
    resource_id: UUID


@dataclass(frozen=True)
class GetResourceByCanonicalNameQuery:
    """Query for a fully materialized resource projection by canonical name."""

    tenant_id: UUID
    canonical_name: str


@dataclass(frozen=True)
class ResolveCanonicalResourceQuery:
    """Query for resolving a resource through direct merge lineage."""

    tenant_id: UUID
    resource_id: UUID
