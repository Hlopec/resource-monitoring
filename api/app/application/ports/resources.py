"""Resource repository contract."""

from typing import Protocol
from uuid import UUID

from app.models import Resource


class ResourceRepository(Protocol):
    """Tenant-aware aggregate-oriented persistence contract for resources."""

    def get_by_id(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Resource | None:
        """Return a resource within tenant scope, or ``None`` when absent."""
        ...

    def get_for_update(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Resource | None:
        """Return a resource for an explicit concurrent mutation workflow."""
        ...

    def get_by_canonical_name(
        self,
        tenant_id: UUID,
        canonical_name: str,
    ) -> Resource | None:
        """Return a resource by tenant-local canonical name."""
        ...

    def exists(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> bool:
        """Return whether a resource exists within tenant scope."""
        ...

    def add(self, resource: Resource) -> None:
        """Add a resource to the current Unit of Work."""
        ...
