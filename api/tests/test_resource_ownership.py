from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Organization,
    OwnershipRole,
    Resource,
    ResourceOwnership,
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


def _resource(session: Session, tenant: Tenant, name: str = "example.com") -> Resource:
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


def _role_id(session: Session, code: str = "owner") -> UUID:
    role_id = session.scalar(select(OwnershipRole.id).where(OwnershipRole.code == code))
    assert role_id is not None
    return role_id


def _ownership(
    resource: Resource,
    organization: Organization,
    ownership_role_id: UUID,
    *,
    is_primary: bool = False,
    confidence_score: Decimal = Decimal("0.9500"),
    valid_to: datetime | None = None,
    source: str | None = "manual",
) -> ResourceOwnership:
    return ResourceOwnership(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        organization_id=organization.id,
        ownership_role_id=ownership_role_id,
        is_primary=is_primary,
        confidence_score=confidence_score,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_to=valid_to,
        source=source,
    )


def _ownership_refs(session: Session) -> tuple[Resource, Organization, UUID]:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    organization = _organization(session, tenant, "platform")
    resource = _resource(session, tenant)
    return resource, organization, _role_id(session)


def test_resource_ownership_valid_insert(db_session: Session) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    ownership = _ownership(resource, organization, ownership_role_id, is_primary=True)
    db_session.add(ownership)
    db_session.flush()

    assert ownership.id is not None
    assert ownership.valid_to is None


def test_resource_ownership_rejects_cross_tenant_resource(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a)
    organization = _organization(db_session, tenant_b, "platform")
    ownership = _ownership(resource, organization, _role_id(db_session))
    # The organization composite FK is valid for tenant B; the resource composite
    # FK is invalid because the referenced resource belongs to tenant A.
    ownership.tenant_id = tenant_b.id
    db_session.add(ownership)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_ownership_rejects_cross_tenant_organization(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a)
    organization = _organization(db_session, tenant_b, "platform")
    ownership = _ownership(resource, organization, _role_id(db_session))
    db_session.add(ownership)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_ownership_rejects_invalid_ownership_role(db_session: Session) -> None:
    resource, organization, _ = _ownership_refs(db_session)
    db_session.add(
        _ownership(
            resource,
            organization,
            UUID("01984000-0000-7000-8000-ffffffffffff"),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("confidence_score", [Decimal("0.0000"), Decimal("1.0000")])
def test_resource_ownership_confidence_score_allows_boundaries(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    ownership = _ownership(
        resource,
        organization,
        ownership_role_id,
        confidence_score=confidence_score,
    )
    db_session.add(ownership)
    db_session.flush()

    assert ownership.confidence_score == confidence_score


@pytest.mark.parametrize("confidence_score", [Decimal("-0.0001"), Decimal("1.0001")])
def test_resource_ownership_confidence_score_rejects_invalid_values(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(
        _ownership(
            resource,
            organization,
            ownership_role_id,
            confidence_score=confidence_score,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("delta", [timedelta(0), -timedelta(seconds=1)])
def test_resource_ownership_valid_to_must_be_after_valid_from(
    db_session: Session, delta: timedelta
) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    ownership = _ownership(resource, organization, ownership_role_id)
    ownership.valid_to = ownership.valid_from + delta
    db_session.add(ownership)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_ownership_source_may_be_null(db_session: Session) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(_ownership(resource, organization, ownership_role_id, source=None))
    db_session.flush()


@pytest.mark.parametrize("source", ["", "   "])
def test_resource_ownership_source_must_not_be_empty_when_present(
    db_session: Session, source: str
) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(_ownership(resource, organization, ownership_role_id, source=source))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_ownership_duplicate_current_is_rejected(db_session: Session) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(_ownership(resource, organization, ownership_role_id))
    db_session.flush()
    db_session.add(_ownership(resource, organization, ownership_role_id))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_ownership_historical_reuse_is_allowed(db_session: Session) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(
        _ownership(
            resource,
            organization,
            ownership_role_id,
            valid_to=datetime.now(UTC),
        )
    )
    db_session.flush()
    db_session.add(_ownership(resource, organization, ownership_role_id))
    db_session.flush()


def test_historical_primary_ownership_is_preserved(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant = _tenant(db_session, "tenant-a")
    resource = _resource(db_session, tenant)
    first_org = _organization(db_session, tenant, "platform")
    second_org = _organization(db_session, tenant, "security")
    ownership_role_id = _role_id(db_session)
    historical = _ownership(
        resource,
        first_org,
        ownership_role_id,
        is_primary=True,
    )
    historical.valid_to = historical.valid_from + timedelta(seconds=1)
    db_session.add(historical)
    db_session.flush()

    current = _ownership(
        resource,
        second_org,
        ownership_role_id,
        is_primary=True,
    )
    db_session.add(current)
    db_session.flush()

    ownership_count = db_session.scalar(
        select(func.count())
        .select_from(ResourceOwnership)
        .where(ResourceOwnership.resource_id == resource.id)
    )
    assert ownership_count == 2


def test_resource_ownership_one_current_primary_per_role(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant = _tenant(db_session, "tenant-a")
    resource = _resource(db_session, tenant)
    first_org = _organization(db_session, tenant, "platform")
    second_org = _organization(db_session, tenant, "security")
    ownership_role_id = _role_id(db_session)
    db_session.add(
        _ownership(resource, first_org, ownership_role_id, is_primary=True)
    )
    db_session.flush()
    db_session.add(
        _ownership(resource, second_org, ownership_role_id, is_primary=True)
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_ownership_allows_different_primary_roles(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant = _tenant(db_session, "tenant-a")
    resource = _resource(db_session, tenant)
    first_org = _organization(db_session, tenant, "platform")
    second_org = _organization(db_session, tenant, "security")
    db_session.add(
        _ownership(resource, first_org, _role_id(db_session, "owner"), is_primary=True)
    )
    db_session.add(
        _ownership(
            resource,
            second_org,
            _role_id(db_session, "custodian"),
            is_primary=True,
        )
    )
    db_session.flush()


def test_resource_ownership_delete_is_restricted(db_session: Session) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(_ownership(resource, organization, ownership_role_id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == resource.id))
        db_session.flush()


def test_organization_delete_is_restricted_while_ownership_exists(
    db_session: Session,
) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(_ownership(resource, organization, ownership_role_id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Organization).where(Organization.id == organization.id))
        db_session.flush()


def test_ownership_role_delete_is_restricted_while_ownership_exists(
    db_session: Session,
) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    db_session.add(_ownership(resource, organization, ownership_role_id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(OwnershipRole).where(OwnershipRole.id == ownership_role_id)
        )
        db_session.flush()


def test_resource_ownership_orm_relationships(db_session: Session) -> None:
    resource, organization, ownership_role_id = _ownership_refs(db_session)
    ownership = _ownership(resource, organization, ownership_role_id)
    db_session.add(ownership)
    db_session.flush()

    assert ownership.resource is resource
    assert ownership.organization is organization
    assert ownership.ownership_role.id == ownership_role_id
    assert ownership in resource.ownerships
    assert ownership in organization.resource_ownerships
