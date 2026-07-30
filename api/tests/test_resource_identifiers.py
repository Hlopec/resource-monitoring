from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.seed.catalogs import CatalogSeedConflict, seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    IdentifierType,
    LifecycleStatus,
    Resource,
    ResourceIdentifier,
    ResourceType,
    Tenant,
)


def _seed_references(session: Session) -> dict[str, object]:
    seed_catalogs(session)
    session.flush()
    tenant = Tenant(slug="tenant-a", display_name="Tenant A", status="active")
    session.add(tenant)
    session.flush()
    return {
        "tenant": tenant,
        "resource_type": session.scalar(select(ResourceType).where(ResourceType.code == "domain")),
        "identifier_type": session.scalar(select(IdentifierType).where(IdentifierType.code == "fqdn")),
        "lifecycle_status": session.scalar(
            select(LifecycleStatus).where(LifecycleStatus.code == "active")
        ),
        "criticality": session.scalar(select(Criticality).where(Criticality.code == "medium")),
        "exposure_level": session.scalar(
            select(ExposureLevel).where(ExposureLevel.code == "public")
        ),
    }


def _resource(session: Session, canonical_name: str = "example.com") -> Resource:
    refs = _seed_references(session)
    now = datetime.now(UTC)
    resource = Resource(
        tenant_id=refs["tenant"].id,
        resource_type_id=refs["resource_type"].id,
        canonical_name=canonical_name,
        display_name=canonical_name,
        lifecycle_status_id=refs["lifecycle_status"].id,
        criticality_id=refs["criticality"].id,
        exposure_level_id=refs["exposure_level"].id,
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(resource)
    session.flush()
    return resource


def _identifier(
    resource: Resource,
    identifier_type_id: UUID,
    normalized_value: str = "example.com",
    value_hash: str = "same-hash",
    namespace: str | None = None,
    is_primary: bool = False,
    valid_to: datetime | None = None,
) -> ResourceIdentifier:
    return ResourceIdentifier(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        identifier_type_id=identifier_type_id,
        namespace=namespace,
        normalized_value=normalized_value,
        original_value=normalized_value,
        value_hash=value_hash,
        is_primary=is_primary,
        confidence_score=Decimal("0.9500"),
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_to=valid_to,
    )


def test_resource_tenant_fk(db_session: Session) -> None:
    refs = _seed_references(db_session)
    now = datetime.now(UTC)
    db_session.add(
        Resource(
            tenant_id=UUID("01984000-0000-7000-8000-ffffffffffff"),
            resource_type_id=refs["resource_type"].id,
            canonical_name="example.com",
            display_name="example.com",
            lifecycle_status_id=refs["lifecycle_status"].id,
            criticality_id=refs["criticality"].id,
            exposure_level_id=refs["exposure_level"].id,
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_lookup_fks(db_session: Session) -> None:
    refs = _seed_references(db_session)
    now = datetime.now(UTC)
    db_session.add(
        Resource(
            tenant_id=refs["tenant"].id,
            resource_type_id=refs["resource_type"].id,
            canonical_name="example.com",
            display_name="example.com",
            lifecycle_status_id=UUID("01984000-0000-7000-8000-ffffffffffff"),
            criticality_id=refs["criticality"].id,
            exposure_level_id=refs["exposure_level"].id,
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["canonical_name", "display_name"])
def test_resource_names_must_be_non_empty(db_session: Session, field: str) -> None:
    refs = _seed_references(db_session)
    now = datetime.now(UTC)
    payload = {
        "tenant_id": refs["tenant"].id,
        "resource_type_id": refs["resource_type"].id,
        "canonical_name": "example.com",
        "display_name": "example.com",
        "lifecycle_status_id": refs["lifecycle_status"].id,
        "criticality_id": refs["criticality"].id,
        "exposure_level_id": refs["exposure_level"].id,
        "first_seen_at": now,
        "last_seen_at": now,
    }
    payload[field] = ""
    db_session.add(Resource(**payload))

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("source_priority", [-1, 1001])
def test_resource_source_priority_boundaries(
    db_session: Session, source_priority: int
) -> None:
    resource = _resource(db_session)
    resource.source_priority = source_priority

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("confidence_score", [Decimal("-0.0001"), Decimal("1.0001")])
def test_resource_confidence_score_boundaries(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource = _resource(db_session)
    resource.confidence_score = confidence_score

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_record_version_must_be_positive(db_session: Session) -> None:
    resource = _resource(db_session)
    resource.record_version = 0

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_first_seen_must_not_be_after_last_seen(db_session: Session) -> None:
    resource = _resource(db_session)
    resource.first_seen_at = datetime.now(UTC)
    resource.last_seen_at = resource.first_seen_at - timedelta(seconds=1)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_identifier_rejects_cross_tenant_resource(db_session: Session) -> None:
    resource = _resource(db_session)
    other_tenant = Tenant(slug="tenant-b", display_name="Tenant B", status="active")
    db_session.add(other_tenant)
    db_session.flush()
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    identifier = _identifier(resource, identifier_type_id)
    identifier.tenant_id = other_tenant.id
    db_session.add(identifier)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_resource_identifier_valid_to_must_be_after_valid_from(db_session: Session) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    identifier = _identifier(resource, identifier_type_id)
    identifier.valid_to = identifier.valid_from
    db_session.add(identifier)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["normalized_value", "original_value", "value_hash"])
def test_resource_identifier_values_must_be_non_empty(
    db_session: Session, field: str
) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    identifier = _identifier(resource, identifier_type_id)
    setattr(identifier, field, "")
    db_session.add(identifier)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("confidence_score", [Decimal("-0.0001"), Decimal("1.0001")])
def test_resource_identifier_confidence_score_boundaries(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    identifier = _identifier(resource, identifier_type_id)
    identifier.confidence_score = confidence_score
    db_session.add(identifier)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_current_identifier_is_rejected(db_session: Session) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    db_session.add(_identifier(resource, identifier_type_id, namespace=None))
    db_session.flush()
    db_session.add(_identifier(resource, identifier_type_id, namespace=None))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_historical_identifier_can_be_reused_after_valid_to(db_session: Session) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    db_session.add(
        _identifier(
            resource,
            identifier_type_id,
            valid_to=datetime.now(UTC),
        )
    )
    db_session.flush()
    db_session.add(_identifier(resource, identifier_type_id))
    db_session.flush()


def test_hash_collision_allows_distinct_normalized_values(db_session: Session) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    db_session.add(
        _identifier(
            resource,
            identifier_type_id,
            normalized_value="example.com",
            value_hash="collision",
        )
    )
    db_session.add(
        _identifier(
            resource,
            identifier_type_id,
            normalized_value="different.example.com",
            value_hash="collision",
        )
    )
    db_session.flush()


def test_one_current_primary_per_resource_and_identifier_type(db_session: Session) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    db_session.add(
        _identifier(
            resource,
            identifier_type_id,
            normalized_value="example.com",
            is_primary=True,
        )
    )
    db_session.flush()
    db_session.add(
        _identifier(
            resource,
            identifier_type_id,
            normalized_value="www.example.com",
            is_primary=True,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_historical_primary_identifier_is_preserved(db_session: Session) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    db_session.add(
        _identifier(
            resource,
            identifier_type_id,
            normalized_value="old.example.com",
            is_primary=True,
            valid_to=datetime.now(UTC),
        )
    )
    db_session.flush()
    db_session.add(
        _identifier(
            resource,
            identifier_type_id,
            normalized_value="new.example.com",
            is_primary=True,
        )
    )
    db_session.flush()


def test_resource_identifier_seed_idempotency(db_session: Session) -> None:
    first = seed_catalogs(db_session)
    db_session.flush()
    second = seed_catalogs(db_session)
    db_session.flush()

    assert first.inserted == 20
    assert first.existing == 0
    assert second.inserted == 0
    assert second.existing == 20


def test_resource_identifier_seed_deterministic_id_conflict(db_session: Session) -> None:
    db_session.add(
        LifecycleStatus(
            code="active",
            display_name="Conflicting active",
            is_system=True,
        )
    )
    db_session.flush()

    with pytest.raises(CatalogSeedConflict, match="active"):
        seed_catalogs(db_session)


def test_resource_delete_is_restricted_by_identifier(db_session: Session) -> None:
    resource = _resource(db_session)
    identifier_type_id = db_session.scalar(
        select(IdentifierType.id).where(IdentifierType.code == "fqdn")
    )
    db_session.add(_identifier(resource, identifier_type_id))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == resource.id))
        db_session.flush()


def test_lookup_delete_is_restricted_by_resource(db_session: Session) -> None:
    resource = _resource(db_session)

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(LifecycleStatus).where(LifecycleStatus.id == resource.lifecycle_status_id)
        )
        db_session.flush()
