"""Application-facing Resource collection query service contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.pagination import ResourceListCursor


@dataclass(frozen=True)
class ResourceSummaryProjection:
    """Technology-neutral Resource summary row returned by query services."""

    resource_id: UUID
    tenant_id: UUID
    resource_type_id: UUID
    lifecycle_status_id: UUID
    canonical_name: str
    display_name: str | None
    primary_organization_id: UUID | None
    primary_ownership_role_id: UUID | None
    record_version: int
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ResourceQueryPage:
    """Technology-neutral Resource query page with probe-row state removed."""

    items: Sequence[ResourceSummaryProjection]
    next_position: ResourceListCursor | None


@dataclass(frozen=True)
class ResourceIdentifierLookupProjection:
    """Technology-neutral row for an exact current identifier lookup."""

    resource_id: UUID
    tenant_id: UUID
    canonical_name: str
    display_name: str | None
    identifier_id: UUID
    identifier_type_id: UUID
    namespace: str | None
    normalized_value: str
    original_value: str
    is_primary: bool


@dataclass(frozen=True)
class ResourceAliasLookupProjection:
    """Technology-neutral row for an exact alias lookup."""

    resource_id: UUID
    tenant_id: UUID
    canonical_name: str
    display_name: str | None
    alias_id: UUID
    alias_type: str
    normalized_value: str
    alias_value: str


class ResourceQueryService(Protocol):
    """Tenant-scoped read service for Resource collection projections."""

    def find_by_identifier(
        self,
        tenant_id: UUID,
        *,
        identifier_type_id: UUID,
        namespace: str | None,
        normalized_value: str,
    ) -> ResourceIdentifierLookupProjection | None:
        """Return one Resource projection by exact current identifier."""
        ...

    def find_by_alias(
        self,
        tenant_id: UUID,
        *,
        alias_type: str,
        normalized_value: str,
    ) -> ResourceAliasLookupProjection | None:
        """Return one Resource projection by exact alias."""
        ...

    def list_resources(
        self,
        tenant_id: UUID,
        *,
        resource_type_id: UUID | None,
        lifecycle_status_id: UUID | None,
        organization_id: UUID | None,
        after: ResourceListCursor | None,
        limit: int,
    ) -> ResourceQueryPage:
        """Return one keyset page of Resource summaries."""
        ...
