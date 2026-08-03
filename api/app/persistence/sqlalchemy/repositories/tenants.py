"""SQLAlchemy implementation of the Tenant repository contract."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ports.tenants import TenantRepository
from app.models import Tenant
from app.persistence.sqlalchemy.repositories.base import SQLAlchemyRepository
from app.persistence.sqlalchemy.repositories.helpers import entity_select


class SQLAlchemyTenantRepository(SQLAlchemyRepository[Tenant], TenantRepository):
    """Session-bound SQLAlchemy adapter for tenant lookup and creation."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        return self._scalar(entity_select(Tenant, tenant_id))

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self._scalar(select(Tenant).where(Tenant.slug == slug))

    def exists_by_slug(self, slug: str) -> bool:
        return self._exists(select(Tenant).where(Tenant.slug == slug))
