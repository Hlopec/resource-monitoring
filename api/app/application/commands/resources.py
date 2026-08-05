"""Resource command contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class EnsureResourceExistsCommand:
    """Reference command that validates a resource exists within a tenant."""

    tenant_id: UUID
    resource_id: UUID
