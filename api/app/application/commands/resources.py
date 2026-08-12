"""Resource command contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class CreateResourceCommand:
    """Command to create a base resource record within one tenant."""

    tenant_id: UUID
    resource_type_id: UUID
    canonical_name: str
    display_name: str
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID
    source_priority: int
    confidence_score: Decimal
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class EnsureResourceExistsCommand:
    """Reference command that validates a resource exists within a tenant."""

    tenant_id: UUID
    resource_id: UUID


@dataclass(frozen=True)
class TransitionResourceStateCommand:
    """Command to replace the current state row for one resource."""

    tenant_id: UUID
    resource_id: UUID
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID
    source_priority: int
    confidence_score: Decimal
    transitioned_at: datetime
    source: str | None


@dataclass(frozen=True)
class AssignResourceIdentifierCommand:
    """Command to append one current identifier row for a resource."""

    tenant_id: UUID
    resource_id: UUID
    identifier_type_id: UUID
    original_value: str
    normalized_value: str
    value_hash: str
    namespace: str | None
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime


@dataclass(frozen=True)
class AssignResourceOwnershipCommand:
    """Command to append one current ownership row for a resource."""

    tenant_id: UUID
    resource_id: UUID
    organization_id: UUID
    ownership_role_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class AssignResourceRelationshipCommand:
    """Command to append one current relationship row between two resources."""

    tenant_id: UUID
    source_resource_id: UUID
    relationship_type_id: UUID
    target_resource_id: UUID
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class AssignResourceAliasCommand:
    """Command to append one alias row for a resource."""

    tenant_id: UUID
    resource_id: UUID
    alias_type: str
    alias_value: str
    normalized_value: str
    source: str | None
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class MergeResourceCommand:
    """Command to record one immutable merge lineage edge."""

    tenant_id: UUID
    source_resource_id: UUID
    target_resource_id: UUID
    reason: str | None
    source: str | None
    merged_at: datetime


@dataclass(frozen=True)
class AssignResourceClassificationCommand:
    """Command to append one current classification row for a resource."""

    tenant_id: UUID
    resource_id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    is_primary: bool
    confidence_score: Decimal
    valid_from: datetime
    source: str | None


@dataclass(frozen=True)
class AssignResourceLabelCommand:
    """Command to append one current label assignment row for a resource."""

    tenant_id: UUID
    resource_id: UUID
    label_id: UUID
    valid_from: datetime
    source: str | None
