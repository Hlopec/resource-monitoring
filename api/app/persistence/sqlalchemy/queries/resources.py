"""SQLAlchemy Resource collection query service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.application.pagination import ResourceListCursor
from app.application.ports.resource_queries import (
    ResourceQueryPage,
    ResourceQueryService,
    ResourceSummaryProjection,
)
from app.models import Resource, ResourceOwnership

PRIMARY_OWNER_ROLE_ID = UUID("01984000-0000-7000-8000-000000000301")


class SQLAlchemyResourceQueryService(ResourceQueryService):
    """SQLAlchemy adapter for Resource summary collection queries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_resources(
        self,
        tenant_id: UUID,
        *,
        resource_type_id: UUID | None,
        lifecycle_status_id: UUID | None,
        organization_id: UUID | None,
        after: ResourceListCursor | None,
        limit: int,
    ) -> ResourceQueryPage:
        current_primary_owner_join = and_(
            ResourceOwnership.tenant_id == Resource.tenant_id,
            ResourceOwnership.tenant_id == tenant_id,
            ResourceOwnership.resource_id == Resource.id,
            ResourceOwnership.ownership_role_id == PRIMARY_OWNER_ROLE_ID,
            ResourceOwnership.is_primary.is_(True),
            ResourceOwnership.valid_to.is_(None),
        )
        statement = select(
            Resource.id,
            Resource.tenant_id,
            Resource.resource_type_id,
            Resource.lifecycle_status_id,
            Resource.canonical_name,
            Resource.display_name,
            ResourceOwnership.organization_id.label("primary_organization_id"),
            ResourceOwnership.ownership_role_id.label("primary_ownership_role_id"),
            Resource.record_version,
            Resource.first_seen_at,
            Resource.last_seen_at,
            Resource.created_at,
            Resource.updated_at,
        ).outerjoin(ResourceOwnership, current_primary_owner_join).where(
            Resource.tenant_id == tenant_id
        )
        if resource_type_id is not None:
            statement = statement.where(Resource.resource_type_id == resource_type_id)
        if lifecycle_status_id is not None:
            statement = statement.where(
                Resource.lifecycle_status_id == lifecycle_status_id
            )
        if organization_id is not None:
            statement = statement.where(
                ResourceOwnership.organization_id == organization_id
            )
        if after is not None:
            statement = statement.where(
                or_(
                    Resource.created_at > after.created_at,
                    and_(
                        Resource.created_at == after.created_at,
                        Resource.id > after.resource_id,
                    ),
                )
            )
        statement = statement.order_by(Resource.created_at, Resource.id).limit(limit + 1)

        rows = list(self._session.execute(statement))
        visible_rows = rows[:limit]
        items = tuple(
            ResourceSummaryProjection(
                resource_id=row.id,
                tenant_id=row.tenant_id,
                resource_type_id=row.resource_type_id,
                lifecycle_status_id=row.lifecycle_status_id,
                canonical_name=row.canonical_name,
                display_name=row.display_name,
                primary_organization_id=row.primary_organization_id,
                primary_ownership_role_id=row.primary_ownership_role_id,
                record_version=row.record_version,
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in visible_rows
        )
        next_position = None
        if len(rows) > limit and items:
            last_item = items[-1]
            next_position = ResourceListCursor(
                created_at=last_item.created_at,
                resource_id=last_item.resource_id,
            )
        return ResourceQueryPage(items=items, next_position=next_position)
