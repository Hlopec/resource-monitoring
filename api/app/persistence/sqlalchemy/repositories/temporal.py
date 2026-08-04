"""SQLAlchemy adapters for tenant-scoped temporal fact repositories."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.application.ports.temporal import (
    ResourceClassificationRepository,
    ResourceIdentifierRepository,
    ResourceLabelRepository,
    ResourceOwnershipRepository,
    ResourceRelationshipRepository,
    ResourceStateRepository,
)
from app.models import (
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceOwnership,
    ResourceRelationship,
    ResourceState,
)
from app.persistence.sqlalchemy.repositories.tenant_scoped import (
    TenantScopedSQLAlchemyRepository,
)

TemporalT = TypeVar(
    "TemporalT",
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceOwnership,
    ResourceRelationship,
    ResourceState,
)


def current_temporal_statement(
    repository: TenantScopedSQLAlchemyRepository[TemporalT],
    tenant_id: UUID,
) -> Select[tuple[TemporalT]]:
    """Build the shared current-row predicate for temporal fact rows."""
    return repository.tenant_statement(tenant_id).where(
        repository.model_type.valid_to.is_(None)
    )


class SQLAlchemyResourceIdentifierRepository(
    TenantScopedSQLAlchemyRepository[ResourceIdentifier],
    ResourceIdentifierRepository,
):
    """Tenant-scoped adapter for resource identifier facts."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceIdentifier)

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceIdentifier]:
        return self._scalars(
            current_temporal_statement(self, tenant_id)
            .where(ResourceIdentifier.resource_id == resource_id)
            .order_by(
                ResourceIdentifier.identifier_type_id,
                ResourceIdentifier.namespace,
                ResourceIdentifier.normalized_value,
                ResourceIdentifier.id,
            )
        )

    def find_current_by_value(
        self,
        tenant_id: UUID,
        identifier_type_id: UUID,
        normalized_value: str,
        namespace: str | None = None,
    ) -> ResourceIdentifier | None:
        return self._scalar(
            current_temporal_statement(self, tenant_id)
            .where(
                ResourceIdentifier.identifier_type_id == identifier_type_id,
                ResourceIdentifier.namespace == namespace,
                ResourceIdentifier.normalized_value == normalized_value,
            )
            .order_by(ResourceIdentifier.id)
        )


class SQLAlchemyResourceOwnershipRepository(
    TenantScopedSQLAlchemyRepository[ResourceOwnership],
    ResourceOwnershipRepository,
):
    """Tenant-scoped adapter for resource ownership facts."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceOwnership)

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceOwnership]:
        return self._scalars(
            current_temporal_statement(self, tenant_id)
            .where(ResourceOwnership.resource_id == resource_id)
            .order_by(
                ResourceOwnership.ownership_role_id,
                ResourceOwnership.is_primary.desc(),
                ResourceOwnership.organization_id,
                ResourceOwnership.id,
            )
        )

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        ownership_role_id: UUID,
    ) -> ResourceOwnership | None:
        return self._scalar(
            current_temporal_statement(self, tenant_id)
            .where(
                ResourceOwnership.resource_id == resource_id,
                ResourceOwnership.ownership_role_id == ownership_role_id,
                ResourceOwnership.is_primary.is_(True),
            )
            .order_by(ResourceOwnership.id)
        )


class SQLAlchemyResourceRelationshipRepository(
    TenantScopedSQLAlchemyRepository[ResourceRelationship],
    ResourceRelationshipRepository,
):
    """Tenant-scoped adapter for resource relationship facts."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceRelationship)

    def list_current_outgoing(
        self,
        tenant_id: UUID,
        source_resource_id: UUID,
    ) -> Sequence[ResourceRelationship]:
        return self._scalars(
            current_temporal_statement(self, tenant_id)
            .where(ResourceRelationship.source_resource_id == source_resource_id)
            .order_by(
                ResourceRelationship.relationship_type_id,
                ResourceRelationship.target_resource_id,
                ResourceRelationship.id,
            )
        )

    def list_current_incoming(
        self,
        tenant_id: UUID,
        target_resource_id: UUID,
    ) -> Sequence[ResourceRelationship]:
        return self._scalars(
            current_temporal_statement(self, tenant_id)
            .where(ResourceRelationship.target_resource_id == target_resource_id)
            .order_by(
                ResourceRelationship.relationship_type_id,
                ResourceRelationship.source_resource_id,
                ResourceRelationship.id,
            )
        )


class SQLAlchemyResourceClassificationRepository(
    TenantScopedSQLAlchemyRepository[ResourceClassification],
    ResourceClassificationRepository,
):
    """Tenant-scoped adapter for resource classification facts."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceClassification)

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceClassification]:
        return self._scalars(
            current_temporal_statement(self, tenant_id)
            .where(ResourceClassification.resource_id == resource_id)
            .order_by(
                ResourceClassification.classification_type_id,
                ResourceClassification.classification_value_id,
                ResourceClassification.id,
            )
        )

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        classification_type_id: UUID,
    ) -> ResourceClassification | None:
        return self._scalar(
            current_temporal_statement(self, tenant_id)
            .where(
                ResourceClassification.resource_id == resource_id,
                ResourceClassification.classification_type_id == classification_type_id,
                ResourceClassification.is_primary.is_(True),
            )
            .order_by(ResourceClassification.id)
        )


class SQLAlchemyResourceLabelRepository(
    TenantScopedSQLAlchemyRepository[ResourceLabel],
    ResourceLabelRepository,
):
    """Tenant-scoped adapter for resource label assignment facts."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceLabel)

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceLabel]:
        return self._scalars(
            current_temporal_statement(self, tenant_id)
            .where(ResourceLabel.resource_id == resource_id)
            .order_by(ResourceLabel.label_id, ResourceLabel.id)
        )


class SQLAlchemyResourceStateRepository(
    TenantScopedSQLAlchemyRepository[ResourceState],
    ResourceStateRepository,
):
    """Tenant-scoped adapter for resource state history."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceState)

    def get_current(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceState | None:
        return self._scalar(
            current_temporal_statement(self, tenant_id)
            .where(ResourceState.resource_id == resource_id)
            .order_by(ResourceState.id)
        )

    def list_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceState]:
        return self._scalars(
            self.tenant_statement(tenant_id)
            .where(ResourceState.resource_id == resource_id)
            .order_by(ResourceState.valid_from, ResourceState.id)
        )
