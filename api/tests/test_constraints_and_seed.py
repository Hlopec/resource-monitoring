from __future__ import annotations

import time

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.seed.catalogs import seed_catalogs
from app.models import IdentifierType, Organization, ResourceType, Tenant


def test_tenant_slug_uniqueness(db_session: Session) -> None:
    db_session.add_all(
        [
            Tenant(slug="alpha", display_name="Alpha", status="active"),
            Tenant(slug="alpha", display_name="Alpha duplicate", status="active"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_tenant_slug_must_be_normalized(db_session: Session) -> None:
    db_session.add(Tenant(slug="Not-Normalized", display_name="Bad", status="active"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_catalog_code_uniqueness(db_session: Session) -> None:
    db_session.add_all(
        [
            IdentifierType(
                code="fqdn",
                display_name="FQDN",
                normalization_strategy="lowercase_idna",
                uniqueness_scope="tenant",
            ),
            IdentifierType(
                code="fqdn",
                display_name="Duplicate FQDN",
                normalization_strategy="lowercase_idna",
                uniqueness_scope="tenant",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_tenant_timestamps_are_timezone_aware_and_updated(db_session: Session) -> None:
    tenant = Tenant(slug="alpha", display_name="Alpha", status="active")
    db_session.add(tenant)
    db_session.flush()

    assert tenant.created_at.tzinfo is not None
    assert tenant.updated_at.tzinfo is not None
    initial_updated_at = tenant.updated_at

    time.sleep(0.001)
    tenant.display_name = "Alpha Updated"
    db_session.flush()

    assert tenant.updated_at > initial_updated_at


def test_organization_tenant_aware_hierarchy(db_session: Session) -> None:
    tenant = Tenant(slug="tenant-a", display_name="Tenant A", status="active")
    db_session.add(tenant)
    db_session.flush()

    parent = Organization(
        tenant_id=tenant.id,
        canonical_name="platform",
        display_name="Platform",
        status="active",
    )
    db_session.add(parent)
    db_session.flush()

    child = Organization(
        tenant_id=tenant.id,
        parent_organization_id=parent.id,
        canonical_name="platform-security",
        display_name="Platform Security",
        status="active",
    )
    db_session.add(child)
    db_session.flush()

    assert child.parent_organization_id == parent.id


def test_cross_tenant_parent_is_rejected(db_session: Session) -> None:
    tenant_a = Tenant(slug="tenant-a", display_name="Tenant A", status="active")
    tenant_b = Tenant(slug="tenant-b", display_name="Tenant B", status="active")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    parent = Organization(
        tenant_id=tenant_a.id,
        canonical_name="platform",
        display_name="Platform",
        status="active",
    )
    db_session.add(parent)
    db_session.flush()

    child = Organization(
        tenant_id=tenant_b.id,
        parent_organization_id=parent.id,
        canonical_name="cross-tenant",
        display_name="Cross Tenant",
        status="active",
    )
    db_session.add(child)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_restrictive_delete_behavior(db_session: Session) -> None:
    tenant = Tenant(slug="tenant-a", display_name="Tenant A", status="active")
    db_session.add(tenant)
    db_session.flush()
    db_session.add(
        Organization(
            tenant_id=tenant.id,
            canonical_name="platform",
            display_name="Platform",
            status="active",
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        db_session.flush()


def test_catalog_restrictive_delete_behavior(db_session: Session) -> None:
    parent = ResourceType(
        code="internet",
        display_name="Internet resource",
        category="internet",
    )
    db_session.add(parent)
    db_session.flush()
    db_session.add(
        ResourceType(
            code="domain",
            display_name="Domain",
            parent_type_id=parent.id,
            category="internet",
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(ResourceType).where(ResourceType.id == parent.id))
        db_session.flush()


def test_seed_idempotency(db_session: Session) -> None:
    first = seed_catalogs(db_session)
    db_session.flush()
    second = seed_catalogs(db_session)
    db_session.flush()

    assert first.inserted > 0
    assert first.existing == 0
    assert second.inserted == 0
    assert second.existing == first.inserted
