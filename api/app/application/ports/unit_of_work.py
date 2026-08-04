"""Application-facing Unit of Work protocol."""

from types import TracebackType
from typing import Protocol, Self

from app.application.ports.catalogs import (
    ClassificationValueRepository,
    ManagedCatalogRepository,
)
from app.application.ports.organizations import OrganizationRepository
from app.application.ports.resources import ResourceRepository
from app.application.ports.tenants import TenantRepository
from app.application.ports.temporal import (
    ResourceClassificationRepository,
    ResourceIdentifierRepository,
    ResourceLabelRepository,
    ResourceOwnershipRepository,
    ResourceRelationshipRepository,
    ResourceStateRepository,
)
from app.models import (
    ClassificationType,
    Criticality,
    ExposureLevel,
    IdentifierType,
    LifecycleStatus,
    OwnershipRole,
    RelationshipType,
    ResourceType,
)


class UnitOfWork(Protocol):
    """Transactional boundary owned by one application command or use case.

    Concrete implementations enter a session/transaction on ``__enter__`` and
    close it on ``__exit__``. They roll back when an exception is raised and also
    when the context exits without an explicit successful ``commit()``.
    Repository instances exposed by a concrete Unit of Work share its session and
    must not commit independently.
    """

    tenants: TenantRepository
    organizations: OrganizationRepository
    resources: ResourceRepository
    resource_types: ManagedCatalogRepository[ResourceType]
    identifier_types: ManagedCatalogRepository[IdentifierType]
    relationship_types: ManagedCatalogRepository[RelationshipType]
    ownership_roles: ManagedCatalogRepository[OwnershipRole]
    classification_types: ManagedCatalogRepository[ClassificationType]
    classification_values: ClassificationValueRepository
    lifecycle_statuses: ManagedCatalogRepository[LifecycleStatus]
    criticalities: ManagedCatalogRepository[Criticality]
    exposure_levels: ManagedCatalogRepository[ExposureLevel]
    resource_identifiers: ResourceIdentifierRepository
    resource_ownerships: ResourceOwnershipRepository
    resource_relationships: ResourceRelationshipRepository
    resource_classifications: ResourceClassificationRepository
    resource_labels: ResourceLabelRepository
    resource_states: ResourceStateRepository

    def __enter__(self) -> Self:
        """Open the Unit of Work and return the active instance."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Close the Unit of Work, rolling back when required."""
        ...

    def commit(self) -> None:
        """Commit the current transaction explicitly."""
        ...

    def rollback(self) -> None:
        """Roll back the current transaction explicitly."""
        ...
