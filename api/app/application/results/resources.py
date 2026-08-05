"""Resource result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ResourceReadResult:
    """Transport-neutral resource lookup result."""

    id: UUID
    tenant_id: UUID
    canonical_name: str
    display_name: str | None
