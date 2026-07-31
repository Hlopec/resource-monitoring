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
    Label,
    LifecycleStatus,
    Resource,
    ResourceLabel,
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


def _label(
    tenant: Tenant,
    *,
    key: str = "environment",
    value: str = "Production",
) -> Label:
    return Label(
        tenant_id=tenant.id,
        key=key,
        value=value,
        is_active=True,
    )


def _assignment(
    resource: Resource,
    label: Label,
    *,
    valid_to: datetime | None = None,
    source: str | None = "manual",
) -> ResourceLabel:
    return ResourceLabel(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        label_id=label.id,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_to=valid_to,
        source=source,
    )


def _assignment_refs(session: Session) -> tuple[Resource, Label]:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    resource = _resource(session, tenant, "example.com")
    label = _label(tenant)
    session.add(label)
    session.flush()
    return resource, label


def test_resource_label_valid_same_tenant_assignment(db_session: Session) -> None:
    resource, label = _assignment_refs(db_session)
    assignment = _assignment(resource, label)
    db_session.add(assignment)
    db_session.flush()

    assert assignment.id is not None
    assert assignment.valid_to is None


def test_resource_label_historical_row_with_valid_to(db_session: Session) -> None:
    resource, label = _assignment_refs(db_session)
    assignment = _assignment(resource, label)
    assignment.valid_to = assignment.valid_from + timedelta(seconds=1)
    db_session.add(assignment)
    db_session.flush()

    assert assignment.valid_to is not None


def test_resource_label_allows_null_source(db_session: Session) -> None:
    resource, label = _assignment_refs(db_session)
    db_session.add(_assignment(resource, label, source=None))
    db_session.flush()


def test_resource_label_historical_reuse_is_allowed(db_session: Session) -> None:
    resource, label = _assignment_refs(db_session)
    historical = _assignment(resource, label)
    historical.valid_to = historical.valid_from + timedelta(seconds=1)
    db_session.add(historical)
    db_session.flush()
    db_session.add(_assignment(resource, label))
    db_session.flush()


def test_resource_label_allows_multiple_labels_on_one_resource(db_session: Session) -> None:
    resource, label = _assignment_refs(db_session)
    other_label = _label(label.tenant, key="owner", value="Security")
    db_session.add(other_label)
    db_session.flush()
    db_session.add(_assignment(resource, label))
    db_session.add(_assignment(resource, other_label))
    db_session.flush()


def test_resource_label_allows_same_label_on_different_resources(db_session: Session) -> None:
    resource, label = _assignment_refs(db_session)
    other_resource = _resource(db_session, label.tenant, "other.example.com")
    db_session.add(_assignment(resource, label))
    db_session.add(_assignment(other_resource, label))
    db_session.flush()


def test_resource_label_allows_different_values_same_key_simultaneously(
    db_session: Session,
) -> None:
    resource, label = _assignment_refs(db_session)
    other_label = _label(label.tenant, key="environment", value="Staging")
    db_session.add(other_label)
    db_session.flush()
    db_session.add(_assignment(resource, label))
    db_session.add(_assignment(resource, other_label))
    db_session.flush()


def test_resource_label_orm_relationships(db_session: Session) -> None:
    resource, label = _assignment_refs(db_session)
    assignment = _assignment(resource, label)
    db_session.add(assignment)
    db_session.flush()

    assert assignment.resource is resource
    assert assignment.label is label
    assert assignment in resource.label_assignments
    assert assignment in label.resource_assignments


def test_resource_label_rejects_invalid_resource(db_session: Session) -> None:
    _, label = _assignment_refs(db_session)
    assignment = ResourceLabel(
        tenant_id=label.tenant_id,
        resource_id=UUID("01984000-0000-7000-8000-ffffffffffff"),
        label_id=label.id,
        valid_from=datetime.now(UTC),
        source="manual",
    )
    db_session.add(assignment)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_label_resource_id_resource" in str(exc_info.value.orig)


def test_resource_label_rejects_invalid_label(db_session: Session) -> None:
    resource, _ = _assignment_refs(db_session)
    assignment = ResourceLabel(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        label_id=UUID("01984000-0000-7000-8000-ffffffffffff"),
        valid_from=datetime.now(UTC),
        source="manual",
    )
    db_session.add(assignment)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_label_label_id_label" in str(exc_info.value.orig)


def test_resource_label_rejects_cross_tenant_resource(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a, "example.com")
    label = _label(tenant_b)
    db_session.add(label)
    db_session.flush()
    assignment = _assignment(resource, label)
    # The label composite FK is valid for tenant B; the resource composite FK is invalid.
    assignment.tenant_id = tenant_b.id
    db_session.add(assignment)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_label_resource_id_resource" in str(exc_info.value.orig)


def test_resource_label_rejects_cross_tenant_label(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a, "example.com")
    label = _label(tenant_b)
    db_session.add(label)
    db_session.flush()
    assignment = _assignment(resource, label)
    # The resource composite FK is valid for tenant A; the label composite FK is invalid.
    assignment.tenant_id = tenant_a.id
    db_session.add(assignment)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_label_label_id_label" in str(exc_info.value.orig)


def test_resource_label_rejects_resource_label_tenant_mismatch(
    db_session: Session,
) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a, "example.com")
    label = _label(tenant_b)
    db_session.add(label)
    db_session.flush()
    assignment = _assignment(resource, label)
    db_session.add(assignment)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_label_label_id_label" in str(exc_info.value.orig)


@pytest.mark.parametrize("delta", [timedelta(0), -timedelta(seconds=1)])
def test_resource_label_valid_to_must_be_after_valid_from(
    db_session: Session, delta: timedelta
) -> None:
    resource, label = _assignment_refs(db_session)
    assignment = _assignment(resource, label)
    assignment.valid_to = assignment.valid_from + delta
    db_session.add(assignment)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_label_valid_time_order" in str(exc_info.value.orig)


@pytest.mark.parametrize("source", ["", "   "])
def test_resource_label_source_must_not_be_empty_when_present(
    db_session: Session, source: str
) -> None:
    resource, label = _assignment_refs(db_session)
    db_session.add(_assignment(resource, label, source=source))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_label_source_not_empty" in str(exc_info.value.orig)


def test_resource_label_duplicate_current_assignment_is_rejected(
    db_session: Session,
) -> None:
    resource, label = _assignment_refs(db_session)
    db_session.add(_assignment(resource, label))
    db_session.flush()
    db_session.add(_assignment(resource, label))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_resource_label_current" in str(exc_info.value.orig)


def test_resource_delete_is_restricted_while_resource_label_exists(
    db_session: Session,
) -> None:
    resource, label = _assignment_refs(db_session)
    db_session.add(_assignment(resource, label))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == resource.id))
        db_session.flush()


def test_label_delete_is_restricted_while_resource_label_exists(
    db_session: Session,
) -> None:
    resource, label = _assignment_refs(db_session)
    db_session.add(_assignment(resource, label))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Label).where(Label.id == label.id))
        db_session.flush()
