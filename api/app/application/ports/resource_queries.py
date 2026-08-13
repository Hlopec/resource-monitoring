"""Application-facing Resource collection query service contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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


@dataclass(frozen=True)
class ResourceStateProjection:
    """Technology-neutral current ResourceState row for details reads."""

    id: UUID
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID
    source_priority: int
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceIdentifierProjection:
    """Technology-neutral current ResourceIdentifier row for details reads."""

    id: UUID
    identifier_type_id: UUID
    namespace: str | None
    normalized_value: str
    original_value: str
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime


@dataclass(frozen=True)
class ResourceOwnershipProjection:
    """Technology-neutral current ResourceOwnership row for details reads."""

    id: UUID
    organization_id: UUID
    ownership_role_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceClassificationProjection:
    """Technology-neutral current ResourceClassification row for details reads."""

    id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceLabelProjection:
    """Technology-neutral current ResourceLabel row for details reads."""

    id: UUID
    label_id: UUID
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceAliasProjection:
    """Technology-neutral ResourceAlias row for details reads."""

    id: UUID
    alias_type: str
    alias_value: str
    normalized_value: str
    source: str | None
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class ResourceMergeProjection:
    """Technology-neutral direct outgoing ResourceMerge row for details reads."""

    id: UUID
    source_resource_id: UUID
    target_resource_id: UUID
    reason: str | None
    source: str | None
    merged_at: datetime


@dataclass(frozen=True)
class ResourceDetailsProjection:
    """Technology-neutral fully materialized Resource details read model."""

    id: UUID
    tenant_id: UUID
    organization_id: UUID | None
    resource_type_id: UUID
    canonical_name: str
    display_name: str
    record_version: int
    created_at: datetime
    updated_at: datetime
    state: ResourceStateProjection | None
    primary_ownership: ResourceOwnershipProjection | None
    identifiers: tuple[ResourceIdentifierProjection, ...]
    ownership: tuple[ResourceOwnershipProjection, ...]
    classifications: tuple[ResourceClassificationProjection, ...]
    labels: tuple[ResourceLabelProjection, ...]
    aliases: tuple[ResourceAliasProjection, ...]
    outgoing_merge: ResourceMergeProjection | None


@dataclass(frozen=True)
class ResourceStateHistoryProjection:
    """Technology-neutral stored ResourceState interval for history reads."""

    id: UUID
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID
    source_priority: int
    confidence_score: Decimal
    valid_from: datetime
    valid_to: datetime | None
    source: str | None


@dataclass(frozen=True)
class ResourceOwnershipHistoryProjection:
    """Technology-neutral stored ResourceOwnership interval for history reads."""

    id: UUID
    organization_id: UUID
    ownership_role_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    valid_to: datetime | None
    source: str | None


@dataclass(frozen=True)
class ResourceLabelHistoryProjection:
    """Technology-neutral stored ResourceLabel interval for history reads."""

    id: UUID
    label_id: UUID
    valid_from: datetime
    valid_to: datetime | None
    source: str | None


@dataclass(frozen=True)
class ResourceClassificationHistoryProjection:
    """Technology-neutral stored ResourceClassification interval for history reads."""

    id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    valid_to: datetime | None
    source: str | None


@dataclass(frozen=True)
class ResourceIdentifierHistoryProjection:
    """Technology-neutral stored ResourceIdentifier interval for history reads."""

    id: UUID
    identifier_type_id: UUID
    namespace: str | None
    normalized_value: str
    original_value: str
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True)
class ResourceHistoryProjection:
    """Technology-neutral fully materialized Resource temporal history."""

    id: UUID
    tenant_id: UUID
    resource_type_id: UUID
    canonical_name: str
    display_name: str
    states: tuple[ResourceStateHistoryProjection, ...]
    ownership: tuple[ResourceOwnershipHistoryProjection, ...]
    labels: tuple[ResourceLabelHistoryProjection, ...]
    classifications: tuple[ResourceClassificationHistoryProjection, ...]
    identifiers: tuple[ResourceIdentifierHistoryProjection, ...]


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
        label_id: UUID | None,
        classification_type_id: UUID | None,
        classification_value_id: UUID | None,
        after: ResourceListCursor | None,
        limit: int,
    ) -> ResourceQueryPage:
        """Return one keyset page of Resource summaries."""
        ...

    def get_resource_details(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceDetailsProjection | None:
        """Return one fully materialized Resource details projection."""
        ...

    def get_resource_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceHistoryProjection | None:
        """Return one fully materialized Resource temporal history projection."""
        ...
