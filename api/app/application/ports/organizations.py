"""Organization repository contract."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.models import Organization


class OrganizationRepository(Protocol):
    """Tenant-aware persistence contract for organizations."""

    def get_by_id(
        self,
        tenant_id: UUID,
        organization_id: UUID,
    ) -> Organization | None:
        """Return an organization within tenant scope, or ``None`` when absent."""
        ...

    def get_by_canonical_name(
        self,
        tenant_id: UUID,
        canonical_name: str,
    ) -> Organization | None:
        """Return an organization by tenant-local canonical name."""
        ...

    def get_by_external_key(
        self,
        tenant_id: UUID,
        external_key: str,
    ) -> Organization | None:
        """Return an organization by tenant-local external key."""
        ...

    def exists(
        self,
        tenant_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """Return whether an organization exists within tenant scope."""
        ...

    def list_children(
        self,
        tenant_id: UUID,
        parent_organization_id: UUID,
    ) -> Sequence[Organization]:
        """Return direct children for an organization within tenant scope."""
        ...

    def add(self, organization: Organization) -> None:
        """Add an organization to the current Unit of Work."""
        ...
