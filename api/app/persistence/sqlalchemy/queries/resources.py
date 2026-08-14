"""SQLAlchemy Resource collection query service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, case, exists, nulls_last, or_, select
from sqlalchemy.orm import Session

from app.application.pagination import ResourceListCursor
from app.application.ports.resource_queries import (
    ResourceAliasProjection,
    ResourceAliasLookupProjection,
    ResourceClassificationHistoryProjection,
    ResourceClassificationProjection,
    ResourceDetailsProjection,
    ResourceHistoryProjection,
    ResourceIdentifierHistoryProjection,
    ResourceIdentifierProjection,
    ResourceIdentifierLookupProjection,
    ResourceLabelHistoryProjection,
    ResourceLabelProjection,
    ResourceMergeProjection,
    ResourceOwnershipHistoryProjection,
    ResourceOwnershipProjection,
    ResourceQueryPage,
    ResourceQueryService,
    ResourceRelationshipProjection,
    ResourceRelationshipsProjection,
    ResourceStateHistoryProjection,
    ResourceStateProjection,
    ResourceSummaryProjection,
)
from app.models import (
    Label,
    Resource,
    ResourceAlias,
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceMerge,
    ResourceOwnership,
    ResourceRelationship,
    ResourceState,
)

PRIMARY_OWNER_ROLE_ID = UUID("01984000-0000-7000-8000-000000000301")


class SQLAlchemyResourceQueryService(ResourceQueryService):
    """SQLAlchemy adapter for Resource summary collection queries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_identifier(
        self,
        tenant_id: UUID,
        *,
        identifier_type_id: UUID,
        namespace: str | None,
        normalized_value: str,
    ) -> ResourceIdentifierLookupProjection | None:
        statement = (
            select(
                Resource.id.label("resource_id"),
                Resource.tenant_id,
                Resource.canonical_name,
                Resource.display_name,
                ResourceIdentifier.id.label("identifier_id"),
                ResourceIdentifier.identifier_type_id,
                ResourceIdentifier.namespace,
                ResourceIdentifier.normalized_value,
                ResourceIdentifier.original_value,
                ResourceIdentifier.is_primary,
            )
            .join(
                Resource,
                and_(
                    Resource.tenant_id == ResourceIdentifier.tenant_id,
                    Resource.id == ResourceIdentifier.resource_id,
                ),
            )
            .where(
                ResourceIdentifier.tenant_id == tenant_id,
                Resource.tenant_id == tenant_id,
                ResourceIdentifier.identifier_type_id == identifier_type_id,
                ResourceIdentifier.normalized_value == normalized_value,
                ResourceIdentifier.valid_to.is_(None),
            )
        )
        if namespace is None:
            statement = statement.where(ResourceIdentifier.namespace.is_(None))
        else:
            statement = statement.where(ResourceIdentifier.namespace == namespace)

        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return ResourceIdentifierLookupProjection(
            resource_id=row.resource_id,
            tenant_id=row.tenant_id,
            canonical_name=row.canonical_name,
            display_name=row.display_name,
            identifier_id=row.identifier_id,
            identifier_type_id=row.identifier_type_id,
            namespace=row.namespace,
            normalized_value=row.normalized_value,
            original_value=row.original_value,
            is_primary=row.is_primary,
        )

    def find_by_alias(
        self,
        tenant_id: UUID,
        *,
        alias_type: str,
        normalized_value: str,
    ) -> ResourceAliasLookupProjection | None:
        statement = (
            select(
                Resource.id.label("resource_id"),
                Resource.tenant_id,
                Resource.canonical_name,
                Resource.display_name,
                ResourceAlias.id.label("alias_id"),
                ResourceAlias.alias_type,
                ResourceAlias.normalized_value,
                ResourceAlias.alias_value,
            )
            .join(
                Resource,
                and_(
                    Resource.tenant_id == ResourceAlias.tenant_id,
                    Resource.id == ResourceAlias.resource_id,
                ),
            )
            .where(
                ResourceAlias.tenant_id == tenant_id,
                Resource.tenant_id == tenant_id,
                ResourceAlias.alias_type == alias_type,
                ResourceAlias.normalized_value == normalized_value,
            )
        )

        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return ResourceAliasLookupProjection(
            resource_id=row.resource_id,
            tenant_id=row.tenant_id,
            canonical_name=row.canonical_name,
            display_name=row.display_name,
            alias_id=row.alias_id,
            alias_type=row.alias_type,
            normalized_value=row.normalized_value,
            alias_value=row.alias_value,
        )

    def list_resources(
        self,
        tenant_id: UUID,
        *,
        resource_type_id: UUID | None,
        lifecycle_status_id: UUID | None,
        organization_id: UUID | None,
        label_id: UUID | None,
        classification_type_id: UUID | None,
        classification_value_id: UUID | None,
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
        if label_id is not None:
            statement = statement.where(
                exists()
                .where(
                    ResourceLabel.tenant_id == tenant_id,
                    ResourceLabel.tenant_id == Resource.tenant_id,
                    ResourceLabel.resource_id == Resource.id,
                    ResourceLabel.label_id == label_id,
                    ResourceLabel.valid_to.is_(None),
                )
                .correlate(Resource)
            )
        if classification_type_id is not None:
            classification_filter = exists().where(
                ResourceClassification.tenant_id == tenant_id,
                ResourceClassification.tenant_id == Resource.tenant_id,
                ResourceClassification.resource_id == Resource.id,
                ResourceClassification.classification_type_id
                == classification_type_id,
                ResourceClassification.valid_to.is_(None),
            )
            if classification_value_id is not None:
                classification_filter = classification_filter.where(
                    ResourceClassification.classification_value_id
                    == classification_value_id
                )
            statement = statement.where(classification_filter.correlate(Resource))
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

    def get_resource_details(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceDetailsProjection | None:
        current_primary_owner_join = and_(
            ResourceOwnership.tenant_id == Resource.tenant_id,
            ResourceOwnership.tenant_id == tenant_id,
            ResourceOwnership.resource_id == Resource.id,
            ResourceOwnership.ownership_role_id == PRIMARY_OWNER_ROLE_ID,
            ResourceOwnership.is_primary.is_(True),
            ResourceOwnership.valid_to.is_(None),
        )
        outgoing_merge_join = and_(
            ResourceMerge.tenant_id == Resource.tenant_id,
            ResourceMerge.tenant_id == tenant_id,
            ResourceMerge.source_resource_id == Resource.id,
        )
        current_state_join = and_(
            ResourceState.tenant_id == Resource.tenant_id,
            ResourceState.tenant_id == tenant_id,
            ResourceState.resource_id == Resource.id,
            ResourceState.valid_to.is_(None),
        )
        core_statement = (
            select(
                Resource.id,
                Resource.tenant_id,
                Resource.resource_type_id,
                Resource.canonical_name,
                Resource.display_name,
                Resource.record_version,
                Resource.created_at,
                Resource.updated_at,
                ResourceOwnership.id.label("primary_ownership_id"),
                ResourceOwnership.organization_id.label("primary_organization_id"),
                ResourceOwnership.ownership_role_id.label(
                    "primary_ownership_role_id"
                ),
                ResourceOwnership.is_primary.label("primary_ownership_is_primary"),
                ResourceOwnership.confidence_score.label(
                    "primary_ownership_confidence_score"
                ),
                ResourceOwnership.valid_from.label("primary_ownership_valid_from"),
                ResourceOwnership.source.label("primary_ownership_source"),
                ResourceMerge.id.label("merge_id"),
                ResourceMerge.source_resource_id.label("merge_source_resource_id"),
                ResourceMerge.target_resource_id.label("merge_target_resource_id"),
                ResourceMerge.reason.label("merge_reason"),
                ResourceMerge.source.label("merge_source"),
                ResourceMerge.merged_at.label("merge_merged_at"),
                ResourceState.id.label("state_id"),
                ResourceState.lifecycle_status_id.label("state_lifecycle_status_id"),
                ResourceState.criticality_id.label("state_criticality_id"),
                ResourceState.exposure_level_id.label("state_exposure_level_id"),
                ResourceState.source_priority.label("state_source_priority"),
                ResourceState.confidence_score.label("state_confidence_score"),
                ResourceState.valid_from.label("state_valid_from"),
                ResourceState.source.label("state_source"),
            )
            .outerjoin(ResourceOwnership, current_primary_owner_join)
            .outerjoin(ResourceMerge, outgoing_merge_join)
            .outerjoin(ResourceState, current_state_join)
            .where(Resource.tenant_id == tenant_id, Resource.id == resource_id)
        )
        core = self._session.execute(core_statement).one_or_none()
        if core is None:
            return None

        primary_ownership = None
        if core.primary_ownership_id is not None:
            primary_ownership = ResourceOwnershipProjection(
                id=core.primary_ownership_id,
                organization_id=core.primary_organization_id,
                ownership_role_id=core.primary_ownership_role_id,
                is_primary=core.primary_ownership_is_primary,
                confidence_score=core.primary_ownership_confidence_score,
                valid_from=core.primary_ownership_valid_from,
                source=core.primary_ownership_source,
            )

        outgoing_merge = None
        if core.merge_id is not None:
            outgoing_merge = ResourceMergeProjection(
                id=core.merge_id,
                source_resource_id=core.merge_source_resource_id,
                target_resource_id=core.merge_target_resource_id,
                reason=core.merge_reason,
                source=core.merge_source,
                merged_at=core.merge_merged_at,
            )

        state = None
        if core.state_id is not None:
            state = ResourceStateProjection(
                id=core.state_id,
                lifecycle_status_id=core.state_lifecycle_status_id,
                criticality_id=core.state_criticality_id,
                exposure_level_id=core.state_exposure_level_id,
                source_priority=core.state_source_priority,
                confidence_score=core.state_confidence_score,
                valid_from=core.state_valid_from,
                source=core.state_source,
            )

        return ResourceDetailsProjection(
            id=core.id,
            tenant_id=core.tenant_id,
            organization_id=(
                primary_ownership.organization_id
                if primary_ownership is not None
                else None
            ),
            resource_type_id=core.resource_type_id,
            canonical_name=core.canonical_name,
            display_name=core.display_name,
            record_version=core.record_version,
            created_at=core.created_at,
            updated_at=core.updated_at,
            state=state,
            primary_ownership=primary_ownership,
            identifiers=self._list_current_identifiers(tenant_id, resource_id),
            ownership=self._list_current_ownership(tenant_id, resource_id),
            classifications=self._list_current_classifications(tenant_id, resource_id),
            labels=self._list_current_labels(tenant_id, resource_id),
            aliases=self._list_aliases(tenant_id, resource_id),
            outgoing_merge=outgoing_merge,
        )

    def get_resource_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceHistoryProjection | None:
        core_statement = select(
            Resource.id,
            Resource.tenant_id,
            Resource.resource_type_id,
            Resource.canonical_name,
            Resource.display_name,
        ).where(Resource.tenant_id == tenant_id, Resource.id == resource_id)
        core = self._session.execute(core_statement).one_or_none()
        if core is None:
            return None

        return ResourceHistoryProjection(
            id=core.id,
            tenant_id=core.tenant_id,
            resource_type_id=core.resource_type_id,
            canonical_name=core.canonical_name,
            display_name=core.display_name,
            states=self._list_state_history(tenant_id, resource_id),
            ownership=self._list_ownership_history(tenant_id, resource_id),
            labels=self._list_label_history(tenant_id, resource_id),
            classifications=self._list_classification_history(tenant_id, resource_id),
            identifiers=self._list_identifier_history(tenant_id, resource_id),
        )

    def get_resource_relationships(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceRelationshipsProjection | None:
        core_statement = select(Resource.id, Resource.tenant_id).where(
            Resource.tenant_id == tenant_id,
            Resource.id == resource_id,
        )
        core = self._session.execute(core_statement).one_or_none()
        if core is None:
            return None

        direction_rank = case(
            (ResourceRelationship.source_resource_id == resource_id, 0),
            else_=1,
        )
        statement = (
            select(
                ResourceRelationship.id,
                ResourceRelationship.relationship_type_id,
                ResourceRelationship.source_resource_id,
                ResourceRelationship.target_resource_id,
                ResourceRelationship.confidence_score,
                ResourceRelationship.valid_from,
                ResourceRelationship.source,
                ResourceRelationship.created_at,
            )
            .where(
                ResourceRelationship.tenant_id == tenant_id,
                ResourceRelationship.valid_to.is_(None),
                or_(
                    ResourceRelationship.source_resource_id == resource_id,
                    ResourceRelationship.target_resource_id == resource_id,
                ),
            )
            .order_by(
                direction_rank,
                ResourceRelationship.relationship_type_id,
                ResourceRelationship.source_resource_id,
                ResourceRelationship.target_resource_id,
                ResourceRelationship.id,
            )
        )
        relationships = tuple(
            ResourceRelationshipProjection(
                id=row.id,
                relationship_type_id=row.relationship_type_id,
                source_resource_id=row.source_resource_id,
                target_resource_id=row.target_resource_id,
                direction=_relationship_direction(row, resource_id),
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
                source=row.source,
                created_at=row.created_at,
            )
            for row in self._session.execute(statement)
        )
        return ResourceRelationshipsProjection(
            resource_id=core.id,
            tenant_id=core.tenant_id,
            relationships=relationships,
        )

    def _list_current_ownership(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceOwnershipProjection, ...]:
        statement = (
            select(
                ResourceOwnership.id,
                ResourceOwnership.organization_id,
                ResourceOwnership.ownership_role_id,
                ResourceOwnership.is_primary,
                ResourceOwnership.confidence_score,
                ResourceOwnership.valid_from,
                ResourceOwnership.source,
            )
            .where(
                ResourceOwnership.tenant_id == tenant_id,
                ResourceOwnership.resource_id == resource_id,
                ResourceOwnership.valid_to.is_(None),
            )
            .order_by(
                ResourceOwnership.ownership_role_id,
                ResourceOwnership.is_primary.desc(),
                ResourceOwnership.organization_id,
                ResourceOwnership.id,
            )
        )
        return tuple(
            ResourceOwnershipProjection(
                id=row.id,
                organization_id=row.organization_id,
                ownership_role_id=row.ownership_role_id,
                is_primary=row.is_primary,
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
                source=row.source,
            )
            for row in self._session.execute(statement)
        )

    def _list_current_labels(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceLabelProjection, ...]:
        statement = (
            select(
                ResourceLabel.id,
                ResourceLabel.label_id,
                ResourceLabel.valid_from,
                ResourceLabel.source,
            )
            .join(
                Label,
                and_(
                    Label.tenant_id == ResourceLabel.tenant_id,
                    Label.id == ResourceLabel.label_id,
                ),
            )
            .where(
                ResourceLabel.tenant_id == tenant_id,
                ResourceLabel.resource_id == resource_id,
                ResourceLabel.valid_to.is_(None),
            )
            .order_by(Label.key, Label.value, ResourceLabel.label_id, ResourceLabel.id)
        )
        return tuple(
            ResourceLabelProjection(
                id=row.id,
                label_id=row.label_id,
                valid_from=row.valid_from,
                source=row.source,
            )
            for row in self._session.execute(statement)
        )

    def _list_current_classifications(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceClassificationProjection, ...]:
        statement = (
            select(
                ResourceClassification.id,
                ResourceClassification.classification_type_id,
                ResourceClassification.classification_value_id,
                ResourceClassification.is_primary,
                ResourceClassification.confidence_score,
                ResourceClassification.valid_from,
                ResourceClassification.source,
            )
            .where(
                ResourceClassification.tenant_id == tenant_id,
                ResourceClassification.resource_id == resource_id,
                ResourceClassification.valid_to.is_(None),
            )
            .order_by(
                ResourceClassification.classification_type_id,
                ResourceClassification.classification_value_id,
                ResourceClassification.id,
            )
        )
        return tuple(
            ResourceClassificationProjection(
                id=row.id,
                classification_type_id=row.classification_type_id,
                classification_value_id=row.classification_value_id,
                is_primary=row.is_primary,
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
                source=row.source,
            )
            for row in self._session.execute(statement)
        )

    def _list_current_identifiers(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceIdentifierProjection, ...]:
        statement = (
            select(
                ResourceIdentifier.id,
                ResourceIdentifier.identifier_type_id,
                ResourceIdentifier.namespace,
                ResourceIdentifier.normalized_value,
                ResourceIdentifier.original_value,
                ResourceIdentifier.is_primary,
                ResourceIdentifier.confidence_score,
                ResourceIdentifier.valid_from,
            )
            .where(
                ResourceIdentifier.tenant_id == tenant_id,
                ResourceIdentifier.resource_id == resource_id,
                ResourceIdentifier.valid_to.is_(None),
            )
            .order_by(
                ResourceIdentifier.identifier_type_id,
                ResourceIdentifier.namespace.is_not(None),
                ResourceIdentifier.namespace,
                ResourceIdentifier.normalized_value,
                ResourceIdentifier.id,
            )
        )
        return tuple(
            ResourceIdentifierProjection(
                id=row.id,
                identifier_type_id=row.identifier_type_id,
                namespace=row.namespace,
                normalized_value=row.normalized_value,
                original_value=row.original_value,
                is_primary=row.is_primary,
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
            )
            for row in self._session.execute(statement)
        )

    def _list_aliases(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceAliasProjection, ...]:
        statement = (
            select(
                ResourceAlias.id,
                ResourceAlias.alias_type,
                ResourceAlias.alias_value,
                ResourceAlias.normalized_value,
                ResourceAlias.source,
                ResourceAlias.first_seen_at,
                ResourceAlias.last_seen_at,
            )
            .where(
                ResourceAlias.tenant_id == tenant_id,
                ResourceAlias.resource_id == resource_id,
            )
            .order_by(
                ResourceAlias.alias_type,
                ResourceAlias.normalized_value,
                ResourceAlias.id,
            )
        )
        return tuple(
            ResourceAliasProjection(
                id=row.id,
                alias_type=row.alias_type,
                alias_value=row.alias_value,
                normalized_value=row.normalized_value,
                source=row.source,
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
            )
            for row in self._session.execute(statement)
        )

    def _list_state_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceStateHistoryProjection, ...]:
        statement = (
            select(
                ResourceState.id,
                ResourceState.lifecycle_status_id,
                ResourceState.criticality_id,
                ResourceState.exposure_level_id,
                ResourceState.source_priority,
                ResourceState.confidence_score,
                ResourceState.valid_from,
                ResourceState.valid_to,
                ResourceState.source,
            )
            .where(
                ResourceState.tenant_id == tenant_id,
                ResourceState.resource_id == resource_id,
            )
            .order_by(
                ResourceState.valid_from,
                nulls_last(ResourceState.valid_to),
                ResourceState.id,
            )
        )
        return tuple(
            ResourceStateHistoryProjection(
                id=row.id,
                lifecycle_status_id=row.lifecycle_status_id,
                criticality_id=row.criticality_id,
                exposure_level_id=row.exposure_level_id,
                source_priority=row.source_priority,
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source=row.source,
            )
            for row in self._session.execute(statement)
        )

    def _list_ownership_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceOwnershipHistoryProjection, ...]:
        statement = (
            select(
                ResourceOwnership.id,
                ResourceOwnership.organization_id,
                ResourceOwnership.ownership_role_id,
                ResourceOwnership.is_primary,
                ResourceOwnership.confidence_score,
                ResourceOwnership.valid_from,
                ResourceOwnership.valid_to,
                ResourceOwnership.source,
            )
            .where(
                ResourceOwnership.tenant_id == tenant_id,
                ResourceOwnership.resource_id == resource_id,
            )
            .order_by(
                ResourceOwnership.valid_from,
                nulls_last(ResourceOwnership.valid_to),
                ResourceOwnership.ownership_role_id,
                ResourceOwnership.organization_id,
                ResourceOwnership.id,
            )
        )
        return tuple(
            ResourceOwnershipHistoryProjection(
                id=row.id,
                organization_id=row.organization_id,
                ownership_role_id=row.ownership_role_id,
                is_primary=row.is_primary,
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source=row.source,
            )
            for row in self._session.execute(statement)
        )

    def _list_label_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceLabelHistoryProjection, ...]:
        statement = (
            select(
                ResourceLabel.id,
                ResourceLabel.label_id,
                ResourceLabel.valid_from,
                ResourceLabel.valid_to,
                ResourceLabel.source,
            )
            .join(
                Label,
                and_(
                    Label.tenant_id == ResourceLabel.tenant_id,
                    Label.id == ResourceLabel.label_id,
                ),
            )
            .where(
                ResourceLabel.tenant_id == tenant_id,
                ResourceLabel.resource_id == resource_id,
            )
            .order_by(
                ResourceLabel.valid_from,
                nulls_last(ResourceLabel.valid_to),
                Label.key,
                Label.value,
                ResourceLabel.label_id,
                ResourceLabel.id,
            )
        )
        return tuple(
            ResourceLabelHistoryProjection(
                id=row.id,
                label_id=row.label_id,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source=row.source,
            )
            for row in self._session.execute(statement)
        )

    def _list_classification_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceClassificationHistoryProjection, ...]:
        statement = (
            select(
                ResourceClassification.id,
                ResourceClassification.classification_type_id,
                ResourceClassification.classification_value_id,
                ResourceClassification.is_primary,
                ResourceClassification.confidence_score,
                ResourceClassification.valid_from,
                ResourceClassification.valid_to,
                ResourceClassification.source,
            )
            .where(
                ResourceClassification.tenant_id == tenant_id,
                ResourceClassification.resource_id == resource_id,
            )
            .order_by(
                ResourceClassification.valid_from,
                nulls_last(ResourceClassification.valid_to),
                ResourceClassification.classification_type_id,
                ResourceClassification.classification_value_id,
                ResourceClassification.is_primary,
                ResourceClassification.id,
            )
        )
        return tuple(
            ResourceClassificationHistoryProjection(
                id=row.id,
                classification_type_id=row.classification_type_id,
                classification_value_id=row.classification_value_id,
                is_primary=row.is_primary,
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source=row.source,
            )
            for row in self._session.execute(statement)
        )

    def _list_identifier_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[ResourceIdentifierHistoryProjection, ...]:
        statement = (
            select(
                ResourceIdentifier.id,
                ResourceIdentifier.identifier_type_id,
                ResourceIdentifier.namespace,
                ResourceIdentifier.normalized_value,
                ResourceIdentifier.original_value,
                ResourceIdentifier.is_primary,
                ResourceIdentifier.confidence_score,
                ResourceIdentifier.valid_from,
                ResourceIdentifier.valid_to,
            )
            .where(
                ResourceIdentifier.tenant_id == tenant_id,
                ResourceIdentifier.resource_id == resource_id,
            )
            .order_by(
                ResourceIdentifier.valid_from,
                nulls_last(ResourceIdentifier.valid_to),
                ResourceIdentifier.identifier_type_id,
                ResourceIdentifier.namespace.is_not(None),
                ResourceIdentifier.namespace,
                ResourceIdentifier.normalized_value,
                ResourceIdentifier.id,
            )
        )
        return tuple(
            ResourceIdentifierHistoryProjection(
                id=row.id,
                identifier_type_id=row.identifier_type_id,
                namespace=row.namespace,
                normalized_value=row.normalized_value,
                original_value=row.original_value,
                is_primary=row.is_primary,
                confidence_score=row.confidence_score,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
            )
            for row in self._session.execute(statement)
        )


def _relationship_direction(row: object, resource_id: UUID) -> str:
    if row.source_resource_id == resource_id:
        return "outgoing"
    if row.target_resource_id == resource_id:
        return "incoming"
    raise AssertionError(
        "ResourceRelationship row is not connected to requested Resource"
    )
