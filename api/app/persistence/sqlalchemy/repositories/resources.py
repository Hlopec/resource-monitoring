"""SQLAlchemy implementation of the Resource repository contract."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.application.ports.resources import ResourceRepository
from app.models import Resource
from app.persistence.sqlalchemy.repositories.tenant_scoped import (
    TenantScopedSQLAlchemyRepository,
)


class SQLAlchemyResourceRepository(
    TenantScopedSQLAlchemyRepository[Resource],
    ResourceRepository,
):
    """Tenant-scoped SQLAlchemy adapter for resource lookup and creation."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, Resource)

    def get_by_id(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Resource | None:
        return self.get_tenant_entity(tenant_id, resource_id)

    def get_for_update(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Resource | None:
        return self.get_tenant_entity(tenant_id, resource_id, for_update=True)

    def get_by_canonical_name(
        self,
        tenant_id: UUID,
        canonical_name: str,
    ) -> Resource | None:
        return self._scalar(
            self.tenant_statement(tenant_id)
            .where(Resource.canonical_name == canonical_name)
            .order_by(Resource.canonical_name, Resource.id)
        )

    def exists(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> bool:
        return self.exists_tenant_entity(tenant_id, resource_id)
