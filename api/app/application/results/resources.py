"""Resource result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class ResourceReadResult:
    """Transport-neutral resource lookup result."""

    id: UUID
    tenant_id: UUID
    canonical_name: str
    display_name: str | None


@dataclass(frozen=True)
class ResourceCreatedResult:
    """Result returned after a base resource record is created."""

    resource_id: UUID
    tenant_id: UUID
    canonical_name: str
    record_version: int


@dataclass(frozen=True)
class ResourceStateTransitionedResult:
    """Result returned after a resource state transition is committed."""

    resource_id: UUID
    previous_state_id: UUID | None
    new_state_id: UUID
    transitioned_at: datetime


@dataclass(frozen=True)
class ResourceIdentifierAssignedResult:
    """Result returned after a resource identifier assignment is committed."""

    resource_id: UUID
    identifier_id: UUID
    identifier_type_id: UUID
    original_value: str
    normalized_value: str
    value_hash: str
    namespace: str | None
    is_primary: bool
    valid_from: datetime


@dataclass(frozen=True)
class ResourceOwnershipAssignedResult:
    """Result returned after a resource ownership assignment is committed."""

    resource_id: UUID
    ownership_id: UUID
    organization_id: UUID
    ownership_role_id: UUID
    is_primary: bool
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceRelationshipAssignedResult:
    """Result returned after a resource relationship assignment is committed."""

    relationship_id: UUID
    source_resource_id: UUID
    relationship_type_id: UUID
    target_resource_id: UUID
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceAliasAssignedResult:
    """Result returned after a resource alias assignment is committed."""

    alias_id: UUID
    resource_id: UUID
    alias_type: str
    alias_value: str
    normalized_value: str
    first_seen_at: datetime
    last_seen_at: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceMergedResult:
    """Result returned after a resource merge lineage edge is committed."""

    merge_id: UUID
    source_resource_id: UUID
    target_resource_id: UUID
    merged_at: datetime
    reason: str | None
    source: str | None


@dataclass(frozen=True)
class CanonicalResourceResolvedResult:
    """Result returned after resolving direct merge lineage."""

    requested_resource_id: UUID
    canonical_resource_id: UUID
    immediate_target_resource_id: UUID | None
    merge_depth: int
    is_canonical: bool
    canonical_resource: ResourceReadResult


@dataclass(frozen=True)
class ResourceSummaryResult:
    """Compact Resource summary projection for collection queries."""

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
class ResourcePageResult:
    """Immutable Resource summary page."""

    items: tuple[ResourceSummaryResult, ...]
    next_cursor: str | None
    page_size: int


@dataclass(frozen=True)
class ResourceClassificationAssignedResult:
    """Result returned after a resource classification assignment is committed."""

    resource_id: UUID
    classification_id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    is_primary: bool
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceLabelAssignedResult:
    """Result returned after a resource label assignment is committed."""

    resource_id: UUID
    resource_label_id: UUID
    label_id: UUID
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceStateResult:
    """Current resource state projection."""

    id: UUID
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID
    source_priority: int
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceIdentifierResult:
    """Current resource identifier projection."""

    id: UUID
    identifier_type_id: UUID
    namespace: str | None
    normalized_value: str
    original_value: str
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime


@dataclass(frozen=True)
class ResourceOwnershipResult:
    """Current resource ownership projection."""

    id: UUID
    organization_id: UUID
    ownership_role_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceClassificationResult:
    """Current resource classification projection."""

    id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceLabelResult:
    """Current resource label assignment projection."""

    id: UUID
    label_id: UUID
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class ResourceAliasResult:
    """Resource alias projection."""

    id: UUID
    alias_type: str
    alias_value: str
    normalized_value: str
    source: str | None
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class ResourceMergeResult:
    """Direct outgoing resource merge projection."""

    id: UUID
    source_resource_id: UUID
    target_resource_id: UUID
    reason: str | None
    source: str | None
    merged_at: datetime


@dataclass(frozen=True)
class ResourceDetailsResult:
    """Fully materialized resource details projection."""

    id: UUID
    tenant_id: UUID
    organization_id: UUID | None
    resource_type_id: UUID
    canonical_name: str
    display_name: str
    record_version: int
    created_at: datetime
    updated_at: datetime
    state: ResourceStateResult | None
    identifiers: tuple[ResourceIdentifierResult, ...]
    ownership: tuple[ResourceOwnershipResult, ...]
    classifications: tuple[ResourceClassificationResult, ...]
    labels: tuple[ResourceLabelResult, ...]
    aliases: tuple[ResourceAliasResult, ...]
    outgoing_merge: ResourceMergeResult | None
