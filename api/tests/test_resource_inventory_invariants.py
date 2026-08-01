from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    ClassificationValue,
    Criticality,
    ExposureLevel,
    IdentifierType,
    Label,
    LifecycleStatus,
    Organization,
    OwnershipRole,
    RelationshipType,
    Resource,
    ResourceAlias,
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceMerge,
    ResourceOwnership,
    ResourceRelationship,
    ResourceState,
    ResourceType,
    Tenant,
)


EXPECTED_TABLES = {
    "tenant",
    "organization",
    "resource_type",
    "identifier_type",
    "lifecycle_status",
    "criticality",
    "exposure_level",
    "resource",
    "resource_identifier",
    "resource_ownership",
    "resource_relationship",
    "resource_classification",
    "label",
    "resource_label",
    "resource_state",
    "resource_alias",
    "resource_merge",
    "ownership_role",
    "relationship_type",
    "classification_type",
    "classification_value",
}


def _seed_catalogs(session: Session) -> None:
    seed_catalogs(session)
    session.flush()


def _tenant(session: Session, slug: str) -> Tenant:
    tenant = Tenant(slug=slug, display_name=slug.title(), status="active")
    session.add(tenant)
    session.flush()
    return tenant


def _organization(session: Session, tenant: Tenant, name: str) -> Organization:
    organization = Organization(
        tenant_id=tenant.id,
        canonical_name=name,
        display_name=name.title(),
        status="active",
    )
    session.add(organization)
    session.flush()
    return organization


def _catalog_ids(session: Session) -> dict[str, UUID]:
    values = {
        "resource_type_id": session.scalar(
            select(ResourceType.id).where(ResourceType.code == "domain")
        ),
        "identifier_type_id": session.scalar(
            select(IdentifierType.id).where(IdentifierType.code == "fqdn")
        ),
        "lifecycle_status_id": session.scalar(
            select(LifecycleStatus.id).where(LifecycleStatus.code == "active")
        ),
        "criticality_id": session.scalar(
            select(Criticality.id).where(Criticality.code == "medium")
        ),
        "exposure_level_id": session.scalar(
            select(ExposureLevel.id).where(ExposureLevel.code == "public")
        ),
        "ownership_role_id": session.scalar(
            select(OwnershipRole.id).where(OwnershipRole.code == "owner")
        ),
        "relationship_type_id": session.scalar(
            select(RelationshipType.id).where(RelationshipType.code == "depends_on")
        ),
        "classification_value_id": session.scalar(
            select(ClassificationValue.id).where(ClassificationValue.code == "production")
        ),
        "classification_type_id": session.scalar(
            select(ClassificationValue.classification_type_id).where(
                ClassificationValue.code == "production"
            )
        ),
    }
    assert all(value is not None for value in values.values())
    return values


def _resource(session: Session, tenant: Tenant, name: str) -> Resource:
    catalog_ids = _catalog_ids(session)
    now = datetime.now(UTC)
    resource = Resource(
        tenant_id=tenant.id,
        resource_type_id=catalog_ids["resource_type_id"],
        canonical_name=name,
        display_name=name,
        lifecycle_status_id=catalog_ids["lifecycle_status_id"],
        criticality_id=catalog_ids["criticality_id"],
        exposure_level_id=catalog_ids["exposure_level_id"],
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(resource)
    session.flush()
    return resource


def _label(session: Session, tenant: Tenant) -> Label:
    label = Label(
        tenant_id=tenant.id,
        key="environment",
        value="Production",
        is_active=True,
    )
    session.add(label)
    session.flush()
    return label


def _identifier(resource: Resource, identifier_type_id: UUID) -> ResourceIdentifier:
    return ResourceIdentifier(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        identifier_type_id=identifier_type_id,
        normalized_value=f"id:{resource.id}",
        original_value=f"id:{resource.id}",
        value_hash=f"hash:{resource.id}",
        is_primary=True,
        confidence_score=Decimal("0.9500"),
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
    )


def _state(resource: Resource) -> ResourceState:
    return ResourceState(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        lifecycle_status_id=resource.lifecycle_status_id,
        criticality_id=resource.criticality_id,
        exposure_level_id=resource.exposure_level_id,
        source_priority=resource.source_priority,
        confidence_score=resource.confidence_score,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        source="test",
    )


def _alias(resource: Resource) -> ResourceAlias:
    now = datetime.now(UTC)
    return ResourceAlias(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        alias_type="hostname",
        alias_value=f"Alias {resource.id}",
        normalized_value=f"alias-{resource.id}",
        first_seen_at=now,
        last_seen_at=now,
        source="test",
    )


def _setup(session: Session) -> tuple[Tenant, Resource, Resource]:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    first = _resource(session, tenant, "first.example.com")
    second = _resource(session, tenant, "second.example.com")
    return tenant, first, second


def test_metadata_contains_all_resource_inventory_tables() -> None:
    assert EXPECTED_TABLES.issubset(Base.metadata.tables.keys())


def test_cross_tenant_references_are_rejected_across_fact_models(
    db_session: Session,
) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource_a = _resource(db_session, tenant_a, "a.example.com")
    resource_b = _resource(db_session, tenant_b, "b.example.com")
    db_session.commit()

    alias = _alias(resource_a)
    alias.tenant_id = tenant_b.id
    db_session.add(alias)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    state = _state(resource_a)
    state.tenant_id = tenant_b.id
    db_session.add(state)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    merge = ResourceMerge(
        tenant_id=tenant_a.id,
        source_resource_id=resource_a.id,
        target_resource_id=resource_b.id,
        merged_at=datetime.now(UTC),
    )
    db_session.add(merge)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_current_facts_from_different_temporal_models_can_coexist(
    db_session: Session,
) -> None:
    tenant, resource, target = _setup(db_session)
    catalog_ids = _catalog_ids(db_session)
    organization = _organization(db_session, tenant, "platform")
    label = _label(db_session, tenant)
    db_session.add(_identifier(resource, catalog_ids["identifier_type_id"]))
    db_session.add(
        ResourceOwnership(
            tenant_id=tenant.id,
            resource_id=resource.id,
            organization_id=organization.id,
            ownership_role_id=catalog_ids["ownership_role_id"],
            is_primary=True,
            confidence_score=Decimal("0.9000"),
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db_session.add(
        ResourceRelationship(
            tenant_id=tenant.id,
            source_resource_id=resource.id,
            target_resource_id=target.id,
            relationship_type_id=catalog_ids["relationship_type_id"],
            confidence_score=Decimal("0.9000"),
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db_session.add(
        ResourceClassification(
            tenant_id=tenant.id,
            resource_id=resource.id,
            classification_type_id=catalog_ids["classification_type_id"],
            classification_value_id=catalog_ids["classification_value_id"],
            is_primary=True,
            confidence_score=Decimal("0.9000"),
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db_session.add(
        ResourceLabel(
            tenant_id=tenant.id,
            resource_id=resource.id,
            label_id=label.id,
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db_session.add(_state(resource))
    db_session.flush()


def test_resource_deletion_is_restricted_by_history_aliases_and_merges(
    db_session: Session,
) -> None:
    tenant, resource, target = _setup(db_session)
    db_session.add(_state(resource))
    db_session.add(_alias(resource))
    db_session.add(
        ResourceMerge(
            tenant_id=tenant.id,
            source_resource_id=resource.id,
            target_resource_id=target.id,
            merged_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == resource.id))
        db_session.flush()


def test_catalog_deletion_is_restricted_when_referenced(db_session: Session) -> None:
    _, resource, _ = _setup(db_session)
    lifecycle_status_id = resource.lifecycle_status_id
    db_session.add(_state(resource))
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(LifecycleStatus).where(LifecycleStatus.id == lifecycle_status_id)
        )
        db_session.flush()


def test_merge_does_not_rewrite_existing_resource_facts(db_session: Session) -> None:
    tenant, source, target = _setup(db_session)
    organization = _organization(db_session, tenant, "platform")
    label = _label(db_session, tenant)
    catalog_ids = _catalog_ids(db_session)
    identifier = _identifier(source, catalog_ids["identifier_type_id"])
    alias = _alias(source)
    state = _state(source)
    label_assignment = ResourceLabel(
        tenant_id=tenant.id,
        resource_id=source.id,
        label_id=label.id,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
    )
    ownership = ResourceOwnership(
        tenant_id=tenant.id,
        resource_id=source.id,
        organization_id=organization.id,
        ownership_role_id=catalog_ids["ownership_role_id"],
        is_primary=True,
        confidence_score=Decimal("0.9000"),
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add_all([identifier, alias, state, label_assignment, ownership])
    db_session.flush()

    db_session.add(
        ResourceMerge(
            tenant_id=tenant.id,
            source_resource_id=source.id,
            target_resource_id=target.id,
            merged_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    assert identifier.resource_id == source.id
    assert alias.resource_id == source.id
    assert state.resource_id == source.id
    assert label_assignment.resource_id == source.id
    assert ownership.resource_id == source.id


def test_orm_collections_do_not_delete_children_when_parent_delete_fails(
    db_session: Session,
) -> None:
    _, resource, _ = _setup(db_session)
    alias = _alias(resource)
    db_session.add(alias)
    db_session.commit()

    db_session.delete(resource)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    remaining_alias = db_session.get(ResourceAlias, alias.id)
    assert remaining_alias is not None
