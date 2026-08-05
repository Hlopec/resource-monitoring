"""SQLAlchemy adapters for resource alias and merge lineage repositories."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.application.ports.lineage import (
    ResourceAliasRepository,
    ResourceMergeRepository,
)
from app.models import Resource, ResourceAlias, ResourceMerge
from app.persistence.sqlalchemy.repositories.tenant_scoped import (
    TenantScopedSQLAlchemyRepository,
)


class SQLAlchemyResourceAliasRepository(
    TenantScopedSQLAlchemyRepository[ResourceAlias],
    ResourceAliasRepository,
):
    """Tenant-scoped adapter for resource alias lookup and persistence."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceAlias)

    def find_resource_by_alias(
        self,
        tenant_id: UUID,
        alias_type: str,
        normalized_value: str,
    ) -> Resource | None:
        statement = (
            select(Resource)
            .join(
                ResourceAlias,
                and_(
                    ResourceAlias.tenant_id == Resource.tenant_id,
                    ResourceAlias.resource_id == Resource.id,
                ),
            )
            .where(
                ResourceAlias.tenant_id == tenant_id,
                Resource.tenant_id == tenant_id,
                ResourceAlias.alias_type == alias_type,
                ResourceAlias.normalized_value == normalized_value,
            )
            .order_by(ResourceAlias.id, Resource.id)
        )
        return self.session.scalar(statement)

    def list_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> Sequence[ResourceAlias]:
        return self._scalars(
            self.tenant_statement(tenant_id)
            .where(ResourceAlias.resource_id == resource_id)
            .order_by(
                ResourceAlias.alias_type,
                ResourceAlias.normalized_value,
                ResourceAlias.id,
            )
        )


class SQLAlchemyResourceMergeRepository(
    TenantScopedSQLAlchemyRepository[ResourceMerge],
    ResourceMergeRepository,
):
    """Tenant-scoped adapter for direct resource merge lineage edges."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, ResourceMerge)

    def get_outgoing_merge(
        self,
        tenant_id: UUID,
        source_resource_id: UUID,
    ) -> ResourceMerge | None:
        return self._scalar(
            self.tenant_statement(tenant_id)
            .where(ResourceMerge.source_resource_id == source_resource_id)
            .order_by(ResourceMerge.id)
        )

    def list_incoming_merges(
        self,
        tenant_id: UUID,
        target_resource_id: UUID,
    ) -> Sequence[ResourceMerge]:
        return self._scalars(
            self.tenant_statement(tenant_id)
            .where(ResourceMerge.target_resource_id == target_resource_id)
            .order_by(ResourceMerge.merged_at, ResourceMerge.id)
        )
