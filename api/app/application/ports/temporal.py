"""Temporal Resource Inventory repository contracts."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.models import (
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceOwnership,
    ResourceRelationship,
    ResourceState,
)


class ResourceIdentifierRepository(Protocol):
    """Tenant-aware persistence contract for resource identifiers."""

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceIdentifier]:
        """Return current identifiers for a resource."""
        ...

    def find_current_by_value(
        self,
        tenant_id: UUID,
        identifier_type_id: UUID,
        normalized_value: str,
        namespace: str | None = None,
    ) -> ResourceIdentifier | None:
        """Return a current identifier by tenant/type/namespace/value."""
        ...

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        identifier_type_id: UUID,
    ) -> ResourceIdentifier | None:
        """Return the current primary identifier for a resource and type."""
        ...

    def add(self, identifier: ResourceIdentifier) -> None:
        """Add an identifier row to the current Unit of Work."""
        ...


class ResourceOwnershipRepository(Protocol):
    """Tenant-aware persistence contract for resource ownership facts."""

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceOwnership]:
        """Return current ownership rows for a resource."""
        ...

    def find_current(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        organization_id: UUID,
        ownership_role_id: UUID,
    ) -> ResourceOwnership | None:
        """Return a current ownership row by resource, organization, and role."""
        ...

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        ownership_role_id: UUID,
    ) -> ResourceOwnership | None:
        """Return the current primary owner for a resource and role."""
        ...

    def add(self, ownership: ResourceOwnership) -> None:
        """Add an ownership row to the current Unit of Work."""
        ...


class ResourceRelationshipRepository(Protocol):
    """Tenant-aware persistence contract for resource relationship facts."""

    def list_current_outgoing(
        self,
        tenant_id: UUID,
        source_resource_id: UUID,
    ) -> Sequence[ResourceRelationship]:
        """Return current outgoing relationships for a source resource."""
        ...

    def list_current_incoming(
        self,
        tenant_id: UUID,
        target_resource_id: UUID,
    ) -> Sequence[ResourceRelationship]:
        """Return current incoming relationships for a target resource."""
        ...

    def add(self, relationship: ResourceRelationship) -> None:
        """Add a relationship row to the current Unit of Work."""
        ...


class ResourceClassificationRepository(Protocol):
    """Tenant-aware persistence contract for resource classification facts."""

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceClassification]:
        """Return current classifications for a resource."""
        ...

    def find_current(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        classification_type_id: UUID,
        classification_value_id: UUID,
    ) -> ResourceClassification | None:
        """Return a current classification row by resource, type, and value."""
        ...

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        classification_type_id: UUID,
    ) -> ResourceClassification | None:
        """Return the current primary classification for a type."""
        ...

    def add(self, classification: ResourceClassification) -> None:
        """Add a classification row to the current Unit of Work."""
        ...


class ResourceLabelRepository(Protocol):
    """Tenant-aware persistence contract for resource label assignments."""

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceLabel]:
        """Return current label assignments for a resource."""
        ...

    def add(self, assignment: ResourceLabel) -> None:
        """Add a label assignment row to the current Unit of Work."""
        ...


class ResourceStateRepository(Protocol):
    """Tenant-aware persistence contract for resource state history."""

    def get_current(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceState | None:
        """Return the current resource state row."""
        ...

    def list_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceState]:
        """Return state history for a resource."""
        ...

    def add(self, state: ResourceState) -> None:
        """Add a state row to the current Unit of Work."""
        ...
