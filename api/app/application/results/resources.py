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
