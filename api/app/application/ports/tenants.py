"""Tenant repository contract."""

from typing import Protocol
from uuid import UUID

from app.models import Tenant


class TenantRepository(Protocol):
    """Persistence contract for tenant lookup and creation."""

    def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        """Return a tenant by id, or ``None`` when absent."""
        ...

    def get_by_slug(self, slug: str) -> Tenant | None:
        """Return a tenant by normalized slug, or ``None`` when absent."""
        ...

    def exists_by_slug(self, slug: str) -> bool:
        """Return whether a tenant exists for the normalized slug."""
        ...

    def add(self, tenant: Tenant) -> None:
        """Add a tenant to the current Unit of Work."""
        ...
