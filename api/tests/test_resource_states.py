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
    Resource,
    ResourceState,
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


def _catalog_ids(session: Session) -> tuple[UUID, UUID, UUID, UUID]:
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
    return resource_type_id, lifecycle_status_id, criticality_id, exposure_level_id


def _resource(session: Session, tenant: Tenant, name: str = "example.com") -> Resource:
    resource_type_id, lifecycle_status_id, criticality_id, exposure_level_id = _catalog_ids(
        session
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


def _state(
    resource: Resource,
    *,
    lifecycle_status_id: UUID | None = None,
    criticality_id: UUID | None = None,
    exposure_level_id: UUID | None = None,
    source_priority: int = 100,
    confidence_score: Decimal = Decimal("0.9500"),
    valid_to: datetime | None = None,
    source: str | None = "manual",
) -> ResourceState:
    return ResourceState(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        lifecycle_status_id=lifecycle_status_id or resource.lifecycle_status_id,
        criticality_id=criticality_id or resource.criticality_id,
        exposure_level_id=exposure_level_id or resource.exposure_level_id,
        source_priority=source_priority,
        confidence_score=confidence_score,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_to=valid_to,
        source=source,
    )


def _state_refs(session: Session) -> Resource:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    return _resource(session, tenant)


def test_resource_state_valid_insert(db_session: Session) -> None:
    resource = _state_refs(db_session)
    state = _state(resource)
    db_session.add(state)
    db_session.flush()

    assert state.id is not None
    assert state.valid_to is None


def test_resource_state_historical_row_with_valid_to(db_session: Session) -> None:
    resource = _state_refs(db_session)
    state = _state(resource)
    state.valid_to = state.valid_from + timedelta(seconds=1)
    db_session.add(state)
    db_session.flush()

    assert state.valid_to is not None


@pytest.mark.parametrize("confidence_score", [Decimal("0.0000"), Decimal("1.0000")])
def test_resource_state_confidence_score_allows_boundaries(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource = _state_refs(db_session)
    state = _state(resource, confidence_score=confidence_score)
    db_session.add(state)
    db_session.flush()

    assert state.confidence_score == confidence_score


def test_resource_state_allows_zero_source_priority(db_session: Session) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource, source_priority=0))
    db_session.flush()


def test_resource_state_source_may_be_null(db_session: Session) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource, source=None))
    db_session.flush()


def test_resource_state_historical_reuse_is_allowed(db_session: Session) -> None:
    resource = _state_refs(db_session)
    historical = _state(resource)
    historical.valid_to = historical.valid_from + timedelta(seconds=1)
    db_session.add(historical)
    db_session.flush()
    db_session.add(_state(resource))
    db_session.flush()


def test_resource_state_allows_new_current_after_old_current_closed(
    db_session: Session,
) -> None:
    resource = _state_refs(db_session)
    old_current = _state(resource)
    db_session.add(old_current)
    db_session.flush()
    old_current.valid_to = datetime.now(UTC)
    db_session.flush()
    db_session.add(_state(resource))
    db_session.flush()


def test_resource_state_allows_current_for_different_resources(
    db_session: Session,
) -> None:
    _seed_catalogs(db_session)
    tenant = _tenant(db_session, "tenant-a")
    first = _resource(db_session, tenant, "first.example.com")
    second = _resource(db_session, tenant, "second.example.com")
    db_session.add(_state(first))
    db_session.add(_state(second))
    db_session.flush()


def test_resource_state_orm_relationships(db_session: Session) -> None:
    resource = _state_refs(db_session)
    state = _state(resource)
    db_session.add(state)
    db_session.flush()

    assert state.resource is resource
    assert state.lifecycle_status.id == resource.lifecycle_status_id
    assert state.criticality.id == resource.criticality_id
    assert state.exposure_level.id == resource.exposure_level_id
    assert state in resource.state_history


def test_resource_state_rejects_invalid_resource(db_session: Session) -> None:
    resource = _state_refs(db_session)
    state = _state(resource)
    state.resource_id = UUID("01984000-0000-7000-8000-ffffffffffff")
    db_session.add(state)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_state_resource_id_resource" in str(exc_info.value.orig)


def test_resource_state_rejects_cross_tenant_resource(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a)
    state = _state(resource)
    state.tenant_id = tenant_b.id
    db_session.add(state)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_state_resource_id_resource" in str(exc_info.value.orig)


@pytest.mark.parametrize(
    ("field", "constraint_name"),
    [
        ("lifecycle_status_id", "fk_resource_state_lifecycle_status"),
        ("criticality_id", "fk_resource_state_criticality"),
        ("exposure_level_id", "fk_resource_state_exposure_level"),
    ],
)
def test_resource_state_rejects_invalid_reference_catalog(
    db_session: Session, field: str, constraint_name: str
) -> None:
    resource = _state_refs(db_session)
    state = _state(resource)
    setattr(state, field, UUID("01984000-0000-7000-8000-ffffffffffff"))
    db_session.add(state)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert constraint_name in str(exc_info.value.orig)


@pytest.mark.parametrize("confidence_score", [Decimal("-0.0001"), Decimal("1.0001")])
def test_resource_state_confidence_score_rejects_invalid_values(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource, confidence_score=confidence_score))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_state_confidence_score_range" in str(exc_info.value.orig)


def test_resource_state_rejects_negative_source_priority(db_session: Session) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource, source_priority=-1))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_state_source_priority_non_negative" in str(exc_info.value.orig)


@pytest.mark.parametrize("delta", [timedelta(0), -timedelta(seconds=1)])
def test_resource_state_valid_to_must_be_after_valid_from(
    db_session: Session, delta: timedelta
) -> None:
    resource = _state_refs(db_session)
    state = _state(resource)
    state.valid_to = state.valid_from + delta
    db_session.add(state)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_state_valid_time_order" in str(exc_info.value.orig)


@pytest.mark.parametrize("source", ["", "   "])
def test_resource_state_source_must_not_be_empty_when_present(
    db_session: Session, source: str
) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource, source=source))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_state_source_not_empty" in str(exc_info.value.orig)


def test_resource_state_duplicate_current_is_rejected(db_session: Session) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource))
    db_session.flush()
    db_session.add(_state(resource))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_resource_state_current" in str(exc_info.value.orig)


def test_resource_state_restricts_resource_delete(db_session: Session) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == resource.id))
        db_session.flush()


@pytest.mark.parametrize(
    "model",
    [LifecycleStatus, Criticality, ExposureLevel],
)
def test_resource_state_restricts_reference_catalog_delete(
    db_session: Session, model: type[LifecycleStatus] | type[Criticality] | type[ExposureLevel]
) -> None:
    resource = _state_refs(db_session)
    db_session.add(_state(resource))
    db_session.flush()
    referenced_id = getattr(resource, f"{model.__tablename__}_id")
    db_session.expire_all()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(model).where(model.id == referenced_id))
        db_session.flush()
