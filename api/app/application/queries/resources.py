"""Resource query contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetResourceByIdQuery:
    """Reference query for tenant-scoped resource lookup by id."""

    tenant_id: UUID
    resource_id: UUID
