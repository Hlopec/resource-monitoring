from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    RelationshipType,
    Resource,
    ResourceRelationship,
    ResourceType,
    Tenant,
)


def _seed_catalogs(session: Session) -> None:
    seed_catalogs(session)
    session.flush()


def _tenant(session: Session, slug: str) -> Tenant:
    tenant = Tenant(slug=slug, display_name=slug.title(), status="active")
    session.add(tenant)
    session.flush()
    return tenant


def _resource(session: Session, tenant: Tenant, name: str) -> Resource:
    resource_type_id = session.scalar(select(ResourceType.id).where(ResourceType.code == "domain"))
    lifecycle_status_id = session.scalar(
        select(LifecycleStatus.id).where(LifecycleStatus.code == "active")
    )
    criticality_id = session.scalar(select(Criticality.id).where(Criticality.code == "medium"))
    exposure_level_id = session.scalar(
        select(ExposureLevel.id).where(ExposureLevel.code == "public")
    )
    now = datetime.now(UTC)
    resource = Resource(
        tenant_id=tenant.id,
        resource_type_id=resource_type_id,
        canonical_name=name,
        display_name=name,
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(resource)
    session.flush()
    return resource


def _relationship_type_id(session: Session, code: str = "depends_on") -> UUID:
    relationship_type_id = session.scalar(
        select(RelationshipType.id).where(RelationshipType.code == code)
    )
    assert relationship_type_id is not None
    return relationship_type_id


def _supports_relationship_type_id(session: Session) -> UUID:
    relationship_type = RelationshipType(
        id=UUID("01984000-0000-7000-8000-000000000402"),
        code="supports",
        display_name="Supports",
        inverse_code="depends_on",
        is_directional=True,
        is_transitive=False,
    )
    session.add(relationship_type)
    session.flush()
    return relationship_type.id


def _relationship(
    source_resource: Resource,
    target_resource: Resource,
    relationship_type_id: UUID,
    *,
    confidence_score: Decimal = Decimal("0.9500"),
    valid_to: datetime | None = None,
    source: str | None = "manual",
) -> ResourceRelationship:
    return ResourceRelationship(
        tenant_id=source_resource.tenant_id,
        source_resource_id=source_resource.id,
        target_resource_id=target_resource.id,
        relationship_type_id=relationship_type_id,
        confidence_score=confidence_score,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_to=valid_to,
        source=source,
    )


def _relationship_refs(session: Session) -> tuple[Resource, Resource, UUID]:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    source_resource = _resource(session, tenant, "source.example.com")
    target_resource = _resource(session, tenant, "target.example.com")
    return source_resource, target_resource, _relationship_type_id(session)


def test_resource_relationship_valid_same_tenant_directed_insert(
    db_session: Session,
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    relationship = _relationship(source_resource, target_resource, relationship_type_id)
    db_session.add(relationship)
    db_session.flush()

    assert relationship.valid_to is None
    assert relationship.source_resource_id == source_resource.id
    assert relationship.target_resource_id == target_resource.id


def test_resource_relationship_allows_null_source(db_session: Session) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(
        _relationship(source_resource, target_resource, relationship_type_id, source=None)
    )
    db_session.flush()


@pytest.mark.parametrize("confidence_score", [Decimal("0.0000"), Decimal("1.0000")])
def test_resource_relationship_confidence_score_allows_boundaries(
    db_session: Session, confidence_score: Decimal
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    relationship = _relationship(
        source_resource,
        target_resource,
        relationship_type_id,
        confidence_score=confidence_score,
    )
    db_session.add(relationship)
    db_session.flush()

    assert relationship.confidence_score == confidence_score


@pytest.mark.parametrize("confidence_score", [Decimal("-0.0001"), Decimal("1.0001")])
def test_resource_relationship_confidence_score_rejects_invalid_values(
    db_session: Session, confidence_score: Decimal
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(
        _relationship(
            source_resource,
            target_resource,
            relationship_type_id,
            confidence_score=confidence_score,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_relationship_reverse_direction_is_allowed(db_session: Session) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))
    db_session.add(_relationship(target_resource, source_resource, relationship_type_id))
    db_session.flush()


def test_resource_relationship_same_endpoints_different_type_is_allowed(
    db_session: Session,
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    supports_type_id = _supports_relationship_type_id(db_session)
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))
    db_session.add(_relationship(source_resource, target_resource, supports_type_id))
    db_session.flush()


def test_resource_relationship_historical_reuse_is_allowed(db_session: Session) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    historical = _relationship(source_resource, target_resource, relationship_type_id)
    historical.valid_to = historical.valid_from + timedelta(seconds=1)
    db_session.add(historical)
    db_session.flush()
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))
    db_session.flush()


def test_resource_relationship_rejects_cross_tenant_source(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    source_resource = _resource(db_session, tenant_a, "source.example.com")
    target_resource = _resource(db_session, tenant_b, "target.example.com")
    relationship = _relationship(source_resource, target_resource, _relationship_type_id(db_session))
    # The target composite FK is valid for tenant B; the source composite FK is
    # invalid because the referenced source resource belongs to tenant A.
    relationship.tenant_id = tenant_b.id
    db_session.add(relationship)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_relationship_rejects_cross_tenant_target(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    source_resource = _resource(db_session, tenant_b, "source.example.com")
    target_resource = _resource(db_session, tenant_a, "target.example.com")
    relationship = _relationship(source_resource, target_resource, _relationship_type_id(db_session))
    # The source composite FK is valid for tenant B; the target composite FK is
    # invalid because the referenced target resource belongs to tenant A.
    relationship.tenant_id = tenant_b.id
    db_session.add(relationship)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_relationship_rejects_invalid_relationship_type(
    db_session: Session,
) -> None:
    source_resource, target_resource, _ = _relationship_refs(db_session)
    db_session.add(
        _relationship(
            source_resource,
            target_resource,
            UUID("01984000-0000-7000-8000-ffffffffffff"),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_relationship_rejects_self_relationship(db_session: Session) -> None:
    source_resource, _, relationship_type_id = _relationship_refs(db_session)
    db_session.add(_relationship(source_resource, source_resource, relationship_type_id))

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("delta", [timedelta(0), -timedelta(seconds=1)])
def test_resource_relationship_valid_to_must_be_after_valid_from(
    db_session: Session, delta: timedelta
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    relationship = _relationship(source_resource, target_resource, relationship_type_id)
    relationship.valid_to = relationship.valid_from + delta
    db_session.add(relationship)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("source", ["", "   "])
def test_resource_relationship_source_must_not_be_empty_when_present(
    db_session: Session, source: str
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(
        _relationship(source_resource, target_resource, relationship_type_id, source=source)
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_relationship_duplicate_current_is_rejected(db_session: Session) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))
    db_session.flush()
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_source_resource_delete_is_restricted_while_relationship_exists(
    db_session: Session,
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == source_resource.id))
        db_session.flush()


def test_target_resource_delete_is_restricted_while_relationship_exists(
    db_session: Session,
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == target_resource.id))
        db_session.flush()


def test_relationship_type_delete_is_restricted_while_relationship_exists(
    db_session: Session,
) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    db_session.add(_relationship(source_resource, target_resource, relationship_type_id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(RelationshipType).where(RelationshipType.id == relationship_type_id)
        )
        db_session.flush()


def test_resource_relationship_orm_relationships(db_session: Session) -> None:
    source_resource, target_resource, relationship_type_id = _relationship_refs(db_session)
    relationship = _relationship(source_resource, target_resource, relationship_type_id)
    db_session.add(relationship)
    db_session.flush()

    assert relationship.source_resource is source_resource
    assert relationship.target_resource is target_resource
    assert relationship.relationship_type.id == relationship_type_id
    assert relationship in source_resource.outgoing_relationships
    assert relationship in target_resource.incoming_relationships
