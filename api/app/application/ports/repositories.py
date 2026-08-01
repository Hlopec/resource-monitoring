"""Repository protocol conventions for future application use cases."""

from typing import Protocol, TypeVar
from uuid import UUID

EntityT = TypeVar("EntityT", covariant=True)


class TenantScopedLookupRepository(Protocol[EntityT]):
    """Minimal tenant-owned lookup convention.

    Future tenant-owned repository contracts must require explicit tenant scope.
    A miss caused by tenant mismatch is reported the same way as an absent row.
    """

    def get_by_id(self, tenant_id: UUID, entity_id: UUID) -> EntityT | None:
        """Return an entity within a tenant scope, or ``None`` when absent."""
        ...

    def exists(self, tenant_id: UUID, entity_id: UUID) -> bool:
        """Return whether an entity exists within a tenant scope."""
        ...


class GlobalCatalogLookupRepository(Protocol[EntityT]):
    """Minimal convention for global managed catalog lookups."""

    def get_by_code(self, code: str) -> EntityT | None:
        """Return a global catalog entity by code, or ``None`` when absent."""
        ...
