"""Resource alias and merge lineage repository contracts."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.models import Resource, ResourceAlias, ResourceMerge


class ResourceAliasRepository(Protocol):
    """Tenant-aware persistence contract for resource aliases."""

    def find_resource_by_alias(
        self,
        tenant_id: UUID,
        alias_type: str,
        normalized_value: str,
    ) -> Resource | None:
        """Return the resource currently associated with an alias key."""
        ...

    def list_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceAlias]:
        """Return aliases recorded for a resource."""
        ...

    def add(self, alias: ResourceAlias) -> None:
        """Add an alias row to the current Unit of Work."""
        ...


class ResourceMergeRepository(Protocol):
    """Tenant-aware persistence contract for resource merge lineage."""

    def get_outgoing_merge(
        self,
        tenant_id: UUID,
        source_resource_id: UUID,
    ) -> ResourceMerge | None:
        """Return the outgoing merge for a source resource."""
        ...

    def list_incoming_merges(
        self,
        tenant_id: UUID,
        target_resource_id: UUID,
    ) -> Sequence[ResourceMerge]:
        """Return incoming merges for a target resource."""
        ...

    def add(self, merge: ResourceMerge) -> None:
        """Add a merge row to the current Unit of Work."""
        ...
