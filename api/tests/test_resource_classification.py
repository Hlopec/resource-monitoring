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
    ClassificationType,
    ClassificationValue,
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Resource,
    ResourceClassification,
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


def _classification_value(
    session: Session, code: str = "production"
) -> ClassificationValue:
    value = session.scalar(
        select(ClassificationValue).where(ClassificationValue.code == code)
    )
    assert value is not None
    return value


def _extra_classification_value(
    session: Session,
) -> ClassificationValue:
    classification_type = ClassificationType(
        id=UUID("01984000-0000-7000-8000-000000000502"),
        code="sensitivity",
        display_name="Sensitivity",
    )
    classification_value = ClassificationValue(
        id=UUID("01984000-0000-7000-8000-000000000603"),
        classification_type_id=classification_type.id,
        code="confidential",
        display_name="Confidential",
    )
    session.add_all([classification_type, classification_value])
    session.flush()
    return classification_value


def _classification(
    resource: Resource,
    classification_value: ClassificationValue,
    *,
    is_primary: bool = False,
    confidence_score: Decimal = Decimal("0.9500"),
    valid_to: datetime | None = None,
    source: str | None = "manual",
) -> ResourceClassification:
    return ResourceClassification(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        classification_type_id=classification_value.classification_type_id,
        classification_value_id=classification_value.id,
        is_primary=is_primary,
        confidence_score=confidence_score,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_to=valid_to,
        source=source,
    )


def _classification_refs(session: Session) -> tuple[Resource, ClassificationValue]:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    resource = _resource(session, tenant)
    return resource, _classification_value(session)


def test_resource_classification_valid_same_tenant_assignment(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    classification = _classification(resource, classification_value, is_primary=True)
    db_session.add(classification)
    db_session.flush()

    assert classification.id is not None
    assert classification.valid_to is None
    assert classification.classification_type_id == classification_value.classification_type_id


def test_resource_classification_historical_row_with_valid_to(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    classification = _classification(resource, classification_value)
    classification.valid_to = classification.valid_from + timedelta(seconds=1)
    db_session.add(classification)
    db_session.flush()

    assert classification.valid_to is not None


def test_resource_classification_allows_null_source(db_session: Session) -> None:
    resource, classification_value = _classification_refs(db_session)
    db_session.add(_classification(resource, classification_value, source=None))
    db_session.flush()


@pytest.mark.parametrize("confidence_score", [Decimal("0.0000"), Decimal("1.0000")])
def test_resource_classification_confidence_score_allows_boundaries(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource, classification_value = _classification_refs(db_session)
    classification = _classification(
        resource,
        classification_value,
        confidence_score=confidence_score,
    )
    db_session.add(classification)
    db_session.flush()

    assert classification.confidence_score == confidence_score


def test_resource_classification_allows_current_values_from_different_types(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    extra_value = _extra_classification_value(db_session)
    db_session.add(_classification(resource, classification_value))
    db_session.add(_classification(resource, extra_value))
    db_session.flush()


def test_resource_classification_allows_multiple_current_non_primary_values_same_type(
    db_session: Session,
) -> None:
    resource, production = _classification_refs(db_session)
    staging = _classification_value(db_session, "staging")
    db_session.add(_classification(resource, production, is_primary=False))
    db_session.add(_classification(resource, staging, is_primary=False))
    db_session.flush()


def test_resource_classification_allows_current_primary_values_for_different_types(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    extra_value = _extra_classification_value(db_session)
    db_session.add(_classification(resource, classification_value, is_primary=True))
    db_session.add(_classification(resource, extra_value, is_primary=True))
    db_session.flush()


def test_resource_classification_historical_reuse_same_value_is_allowed(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    historical = _classification(resource, classification_value)
    historical.valid_to = historical.valid_from + timedelta(seconds=1)
    db_session.add(historical)
    db_session.flush()
    db_session.add(_classification(resource, classification_value))
    db_session.flush()


def test_resource_classification_historical_primary_reuse_is_allowed(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    historical = _classification(resource, classification_value, is_primary=True)
    historical.valid_to = historical.valid_from + timedelta(seconds=1)
    db_session.add(historical)
    db_session.flush()
    db_session.add(_classification(resource, classification_value, is_primary=True))
    db_session.flush()


def test_resource_classification_allows_new_primary_after_old_primary_closed(
    db_session: Session,
) -> None:
    resource, production = _classification_refs(db_session)
    staging = _classification_value(db_session, "staging")
    historical = _classification(resource, production, is_primary=True)
    historical.valid_to = historical.valid_from + timedelta(seconds=1)
    db_session.add(historical)
    db_session.flush()
    db_session.add(_classification(resource, staging, is_primary=True))
    db_session.flush()


def test_resource_classification_rejects_cross_tenant_resource(
    db_session: Session,
) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    resource = _resource(db_session, tenant_a)
    classification_value = _classification_value(db_session)
    classification = _classification(resource, classification_value)
    # Catalog FKs are valid; only the tenant-aware resource FK is invalid.
    classification.tenant_id = tenant_b.id
    db_session.add(classification)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_classification_resource_id_resource" in str(exc_info.value.orig)


def test_resource_classification_rejects_invalid_classification_value(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    classification = _classification(resource, classification_value)
    classification.classification_value_id = UUID("01984000-0000-7000-8000-ffffffffffff")
    db_session.add(classification)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert (
        "fk_resource_classification_type_value"
        in str(exc_info.value.orig)
    )


def test_resource_classification_rejects_classification_value_type_mismatch(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    extra_value = _extra_classification_value(db_session)
    classification = _classification(resource, classification_value)
    classification.classification_type_id = extra_value.classification_type_id
    db_session.add(classification)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert (
        "fk_resource_classification_type_value"
        in str(exc_info.value.orig)
    )


@pytest.mark.parametrize("confidence_score", [Decimal("-0.0001"), Decimal("1.0001")])
def test_resource_classification_confidence_score_rejects_invalid_values(
    db_session: Session, confidence_score: Decimal
) -> None:
    resource, classification_value = _classification_refs(db_session)
    db_session.add(
        _classification(
            resource,
            classification_value,
            confidence_score=confidence_score,
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_classification_confidence_score_range" in str(exc_info.value.orig)


@pytest.mark.parametrize("delta", [timedelta(0), -timedelta(seconds=1)])
def test_resource_classification_valid_to_must_be_after_valid_from(
    db_session: Session, delta: timedelta
) -> None:
    resource, classification_value = _classification_refs(db_session)
    classification = _classification(resource, classification_value)
    classification.valid_to = classification.valid_from + delta
    db_session.add(classification)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_classification_valid_time_order" in str(exc_info.value.orig)


@pytest.mark.parametrize("source", ["", "   "])
def test_resource_classification_source_must_not_be_empty_when_present(
    db_session: Session, source: str
) -> None:
    resource, classification_value = _classification_refs(db_session)
    db_session.add(_classification(resource, classification_value, source=source))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_classification_source_not_empty" in str(exc_info.value.orig)


def test_resource_classification_duplicate_current_value_is_rejected(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    db_session.add(_classification(resource, classification_value))
    db_session.flush()
    db_session.add(_classification(resource, classification_value))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_resource_classification_current_value" in str(exc_info.value.orig)


def test_resource_classification_rejects_two_current_primary_values_same_type(
    db_session: Session,
) -> None:
    resource, production = _classification_refs(db_session)
    staging = _classification_value(db_session, "staging")
    db_session.add(_classification(resource, production, is_primary=True))
    db_session.flush()
    db_session.add(_classification(resource, staging, is_primary=True))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_resource_classification_current_primary_type" in str(exc_info.value.orig)


def test_resource_delete_is_restricted_while_classification_history_exists(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    db_session.add(_classification(resource, classification_value))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == resource.id))
        db_session.flush()


def test_classification_value_delete_is_restricted_while_classification_exists(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    db_session.add(_classification(resource, classification_value))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(ClassificationValue).where(ClassificationValue.id == classification_value.id)
        )
        db_session.flush()


def test_classification_type_delete_is_restricted_while_classification_exists(
    db_session: Session,
) -> None:
    resource, classification_value = _classification_refs(db_session)
    db_session.add(_classification(resource, classification_value))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(ClassificationType).where(
                ClassificationType.id == classification_value.classification_type_id
            )
        )
        db_session.flush()


def test_resource_classification_orm_relationships(db_session: Session) -> None:
    resource, classification_value = _classification_refs(db_session)
    classification = _classification(resource, classification_value)
    db_session.add(classification)
    db_session.flush()

    assert classification.resource is resource
    assert classification.classification_value is classification_value
    assert classification.classification_type.id == classification_value.classification_type_id
    assert classification in resource.classifications
