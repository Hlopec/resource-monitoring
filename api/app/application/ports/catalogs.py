"""Global managed catalog repository contracts."""

from collections.abc import Sequence
from typing import Protocol, TypeAlias, TypeVar
from uuid import UUID

from app.models import (
    ClassificationType,
    ClassificationValue,
    Criticality,
    ExposureLevel,
    IdentifierType,
    LifecycleStatus,
    OwnershipRole,
    RelationshipType,
    ResourceType,
)

ManagedCatalogEntity: TypeAlias = (
    ResourceType
    | IdentifierType
    | RelationshipType
    | OwnershipRole
    | ClassificationType
    | ClassificationValue
    | LifecycleStatus
    | Criticality
    | ExposureLevel
)
CatalogT = TypeVar("CatalogT", bound=ManagedCatalogEntity, covariant=True)


class ManagedCatalogRepository(Protocol[CatalogT]):
    """Read-only repository contract for global managed catalogs."""

    def get_by_id(self, catalog_id: UUID) -> CatalogT | None:
        """Return a catalog row by id, or ``None`` when absent."""
        ...

    def get_by_code(self, code: str) -> CatalogT | None:
        """Return a catalog row by globally managed code."""
        ...

    def list_active(self) -> Sequence[CatalogT]:
        """Return active globally managed catalog rows."""
        ...


class ClassificationValueRepository(Protocol):
    """Read-only contract for classification values scoped by classification type."""

    def get_by_id(self, catalog_id: UUID) -> ClassificationValue | None:
        """Return a classification value by id, or ``None`` when absent."""
        ...

    def get_by_type_and_code(
        self,
        classification_type_id: UUID,
        code: str,
    ) -> ClassificationValue | None:
        """Return a classification value by type and code."""
        ...

    def list_active_for_type(
        self,
        classification_type_id: UUID,
    ) -> Sequence[ClassificationValue]:
        """Return active values for a classification type."""
        ...
