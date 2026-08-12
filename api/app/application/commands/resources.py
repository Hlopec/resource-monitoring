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
