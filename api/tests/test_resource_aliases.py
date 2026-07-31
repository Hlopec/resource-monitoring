from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    Resource,
    ResourceAlias,
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
    assert resource_type_id is not None
    assert lifecycle_status_id is not None
    assert criticality_id is not None
    assert exposure_level_id is not None
    now = datetime.now(UTC)
    resource = Resource(
        tenant_id=tenant.id,
        resource_type_id=resource_type_id,
        canonical_name=name,
        display_name=name,
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(resource)
    session.flush()
    return resource


def _alias(
    resource: Resource,
    *,
    alias_type: str = "hostname",
    alias_value: str = "Example.COM",
    normalized_value: str = "example.com",
    source: str | None = "manual",
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> ResourceAlias:
    first_seen_at = first_seen_at or datetime.now(UTC)
    last_seen_at = last_seen_at or first_seen_at
    return ResourceAlias(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        alias_type=alias_type,
        alias_value=alias_value,
        normalized_value=normalized_value,
        source=source,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


def _alias_refs(session: Session) -> Resource:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    return _resource(session, tenant, "example.com")


def test_resource_alias_valid_insert_and_uuidv7(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    alias = _alias(resource)
    db_session.add(alias)
    db_session.flush()

    assert alias.id is not None
    assert alias.id.version == 7


def test_resource_alias_orm_relationships(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    alias = _alias(resource)
    db_session.add(alias)
    db_session.flush()

    assert alias.resource is resource
    assert alias in resource.aliases


def test_resource_alias_same_key_allowed_in_different_tenants(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    first = _resource(db_session, tenant_a, "first.example.com")
    second = _resource(db_session, tenant_b, "second.example.com")
    db_session.add(_alias(first))
    db_session.add(_alias(second))
    db_session.flush()


def test_resource_alias_same_normalized_value_with_different_types_allowed(
    db_session: Session,
) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource, alias_type="hostname"))
    db_session.add(_alias(resource, alias_type="dns_name"))
    db_session.flush()


def test_resource_alias_duplicate_key_is_rejected(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource))
    db_session.flush()
    db_session.add(_alias(resource, alias_value="example.com"))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_resource_alias_tenant_alias_type_normalized_value" in str(
        exc_info.value.orig
    )


def test_resource_alias_duplicate_key_for_another_resource_is_rejected(
    db_session: Session,
) -> None:
    _seed_catalogs(db_session)
    tenant = _tenant(db_session, "tenant-a")
    first = _resource(db_session, tenant, "first.example.com")
    second = _resource(db_session, tenant, "second.example.com")
    db_session.add(_alias(first))
    db_session.flush()
    db_session.add(_alias(second, alias_value="example.com"))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_resource_alias_tenant_alias_type_normalized_value" in str(
        exc_info.value.orig
    )


@pytest.mark.parametrize("alias_type", ["", "   "])
def test_resource_alias_rejects_empty_alias_type(
    db_session: Session, alias_type: str
) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource, alias_type=alias_type))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_alias_alias_type_not_empty" in str(exc_info.value.orig)


@pytest.mark.parametrize("alias_value", ["", "   "])
def test_resource_alias_rejects_empty_alias_value(
    db_session: Session, alias_value: str
) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource, alias_value=alias_value))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_alias_alias_value_not_empty" in str(exc_info.value.orig)


@pytest.mark.parametrize("normalized_value", ["", "   "])
def test_resource_alias_rejects_empty_normalized_value(
    db_session: Session, normalized_value: str
) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource, normalized_value=normalized_value))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_alias_normalized_value_not_empty" in str(exc_info.value.orig)


def test_resource_alias_source_may_be_null(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource, source=None))
    db_session.flush()


@pytest.mark.parametrize("source", ["", "   "])
def test_resource_alias_rejects_empty_source(
    db_session: Session, source: str
) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource, source=source))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_alias_source_not_empty" in str(exc_info.value.orig)


def test_resource_alias_last_seen_equal_first_seen_allowed(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    seen_at = datetime.now(UTC)
    db_session.add(_alias(resource, first_seen_at=seen_at, last_seen_at=seen_at))
    db_session.flush()


def test_resource_alias_last_seen_after_first_seen_allowed(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    seen_at = datetime.now(UTC)
    db_session.add(
        _alias(
            resource,
            first_seen_at=seen_at,
            last_seen_at=seen_at + timedelta(seconds=1),
        )
    )
    db_session.flush()


def test_resource_alias_rejects_last_seen_before_first_seen(
    db_session: Session,
) -> None:
    resource = _alias_refs(db_session)
    seen_at = datetime.now(UTC)
    db_session.add(
        _alias(
            resource,
            first_seen_at=seen_at,
            last_seen_at=seen_at - timedelta(seconds=1),
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_alias_seen_at_order" in str(exc_info.value.orig)


def test_resource_alias_rejects_invalid_resource(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    alias = _alias(resource)
    alias.resource_id = UUID("01984000-0000-7000-8000-ffffffffffff")
    db_session.add(alias)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_alias_resource_id_resource" in str(exc_info.value.orig)


def test_resource_alias_rejects_cross_tenant_resource(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a, "example.com")
    alias = _alias(resource)
    alias.tenant_id = tenant_b.id
    db_session.add(alias)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_alias_resource_id_resource" in str(exc_info.value.orig)


def test_resource_alias_restricts_resource_delete(db_session: Session) -> None:
    resource = _alias_refs(db_session)
    db_session.add(_alias(resource))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == resource.id))
        db_session.flush()
