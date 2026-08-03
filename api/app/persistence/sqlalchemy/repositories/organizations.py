"""SQLAlchemy implementation of the Organization repository contract."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.application.ports.organizations import OrganizationRepository
from app.models import Organization
from app.persistence.sqlalchemy.repositories.tenant_scoped import (
    TenantScopedSQLAlchemyRepository,
)


class SQLAlchemyOrganizationRepository(
    TenantScopedSQLAlchemyRepository[Organization],
    OrganizationRepository,
):
    """Tenant-scoped SQLAlchemy adapter for organization lookup and creation."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, Organization)

    def get_by_id(
        self,
        tenant_id: UUID,
        organization_id: UUID,
    ) -> Organization | None:
        return self.get_tenant_entity(tenant_id, organization_id)

    def get_by_canonical_name(
        self,
        tenant_id: UUID,
        canonical_name: str,
    ) -> Organization | None:
        return self._scalar(
            self.tenant_statement(tenant_id)
            .where(Organization.canonical_name == canonical_name)
            .order_by(Organization.canonical_name, Organization.id)
        )

    def get_by_external_key(
        self,
        tenant_id: UUID,
        external_key: str,
    ) -> Organization | None:
        return self._scalar(
            self.tenant_statement(tenant_id).where(
                Organization.external_key == external_key
            )
        )

    def exists(
        self,
        tenant_id: UUID,
        organization_id: UUID,
    ) -> bool:
        return self.exists_tenant_entity(tenant_id, organization_id)

    def list_children(
        self,
        tenant_id: UUID,
        parent_organization_id: UUID,
    ) -> Sequence[Organization]:
        return self._scalars(
            self.tenant_statement(tenant_id)
            .where(Organization.parent_organization_id == parent_organization_id)
            .order_by(Organization.canonical_name, Organization.id)
        )
