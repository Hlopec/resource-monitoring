"""Resource query contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

DEFAULT_RESOURCE_PAGE_SIZE = 50
MIN_RESOURCE_PAGE_SIZE = 1
MAX_RESOURCE_PAGE_SIZE = 200


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
class GetResourceHistoryQuery:
    """Query for tenant-scoped temporal Resource fact history."""

    tenant_id: UUID
    resource_id: UUID


@dataclass(frozen=True)
class GetResourceRelationshipsQuery:
    """Query for tenant-scoped direct Resource relationships."""

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


@dataclass(frozen=True)
class FindResourceByIdentifierQuery:
    """Exact current ResourceIdentifier lookup within one tenant."""

    tenant_id: UUID
    identifier_type_id: UUID
    namespace: str | None
    normalized_value: str


@dataclass(frozen=True)
class FindResourceByAliasQuery:
    """Exact ResourceAlias lookup within one tenant."""

    tenant_id: UUID
    alias_type: str
    normalized_value: str


@dataclass(frozen=True)
class ListResourcesQuery:
    """Query for tenant-scoped Resource summary listing."""

    tenant_id: UUID
    resource_type_id: UUID | None = None
    lifecycle_status_id: UUID | None = None
    organization_id: UUID | None = None
    label_id: UUID | None = None
    classification_type_id: UUID | None = None
    classification_value_id: UUID | None = None
    page_size: int = DEFAULT_RESOURCE_PAGE_SIZE
    cursor: str | None = None
