from __future__ import annotations

from datetime import UTC, datetime
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
    ResourceMerge,
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


def _merge(
    source_resource: Resource,
    target_resource: Resource,
    *,
    reason: str | None = "duplicate",
    source: str | None = "manual",
) -> ResourceMerge:
    return ResourceMerge(
        tenant_id=source_resource.tenant_id,
        source_resource_id=source_resource.id,
        target_resource_id=target_resource.id,
        reason=reason,
        source=source,
        merged_at=datetime.now(UTC),
    )


def _merge_refs(session: Session, count: int = 3) -> list[Resource]:
    _seed_catalogs(session)
    tenant = _tenant(session, "tenant-a")
    return [
        _resource(session, tenant, f"resource-{index}.example.com")
        for index in range(count)
    ]


def test_resource_merge_valid_insert(db_session: Session) -> None:
    source, target, _ = _merge_refs(db_session)
    merge = _merge(source, target)
    db_session.add(merge)
    db_session.flush()

    assert merge.id is not None
    assert merge.id.version == 7


def test_resource_merge_allows_multiple_incoming_merges(db_session: Session) -> None:
    first, second, target = _merge_refs(db_session)
    db_session.add(_merge(first, target))
    db_session.add(_merge(second, target))
    db_session.flush()


def test_resource_merge_allows_valid_chain(db_session: Session) -> None:
    first, second, third = _merge_refs(db_session)
    db_session.add(_merge(first, second))
    db_session.flush()
    db_session.add(_merge(second, third))
    db_session.flush()


def test_resource_merge_orm_relationships(db_session: Session) -> None:
    source, target, other_source = _merge_refs(db_session)
    merge = _merge(source, target)
    incoming = _merge(other_source, target)
    db_session.add(merge)
    db_session.add(incoming)
    db_session.flush()

    assert merge.source_resource is source
    assert merge.target_resource is target
    assert source.outgoing_merge is merge
    assert merge in target.incoming_merges
    assert incoming in target.incoming_merges


def test_resource_merge_rejects_self_merge(db_session: Session) -> None:
    source, _, _ = _merge_refs(db_session)
    db_session.add(_merge(source, source))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "resource_merge cycle detected: self-merge rejected" in str(
        exc_info.value.orig
    )


def test_resource_merge_rejects_duplicate_outgoing_merge(db_session: Session) -> None:
    source, first_target, second_target = _merge_refs(db_session)
    db_session.add(_merge(source, first_target))
    db_session.flush()
    db_session.add(_merge(source, second_target))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "uq_resource_merge_tenant_source_resource_id" in str(exc_info.value.orig)


def test_resource_merge_rejects_invalid_source_resource(db_session: Session) -> None:
    source, target, _ = _merge_refs(db_session)
    merge = _merge(source, target)
    merge.source_resource_id = UUID("01984000-0000-7000-8000-ffffffffffff")
    db_session.add(merge)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_merge_source_resource_id_resource" in str(exc_info.value.orig)


def test_resource_merge_rejects_invalid_target_resource(db_session: Session) -> None:
    source, target, _ = _merge_refs(db_session)
    merge = _merge(source, target)
    merge.target_resource_id = UUID("01984000-0000-7000-8000-ffffffffffff")
    db_session.add(merge)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_merge_target_resource_id_resource" in str(exc_info.value.orig)


def test_resource_merge_rejects_cross_tenant_source(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    source = _resource(db_session, tenant_a, "source.example.com")
    target = _resource(db_session, tenant_b, "target.example.com")
    merge = _merge(source, target)
    merge.tenant_id = tenant_b.id
    db_session.add(merge)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_merge_source_resource_id_resource" in str(exc_info.value.orig)


def test_resource_merge_rejects_cross_tenant_target(db_session: Session) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    source = _resource(db_session, tenant_a, "source.example.com")
    target = _resource(db_session, tenant_b, "target.example.com")
    db_session.add(_merge(source, target))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "fk_resource_merge_target_resource_id_resource" in str(exc_info.value.orig)


@pytest.mark.parametrize("reason", ["", "   "])
def test_resource_merge_rejects_empty_reason(
    db_session: Session, reason: str
) -> None:
    source, target, _ = _merge_refs(db_session)
    db_session.add(_merge(source, target, reason=reason))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_merge_reason_not_empty" in str(exc_info.value.orig)


def test_resource_merge_reason_may_be_null(db_session: Session) -> None:
    source, target, _ = _merge_refs(db_session)
    db_session.add(_merge(source, target, reason=None))
    db_session.flush()


@pytest.mark.parametrize("source_value", ["", "   "])
def test_resource_merge_rejects_empty_source(
    db_session: Session, source_value: str
) -> None:
    source, target, _ = _merge_refs(db_session)
    db_session.add(_merge(source, target, source=source_value))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "ck_resource_merge_source_not_empty" in str(exc_info.value.orig)


def test_resource_merge_source_may_be_null(db_session: Session) -> None:
    source, target, _ = _merge_refs(db_session)
    db_session.add(_merge(source, target, source=None))
    db_session.flush()


def test_resource_merge_restricts_source_resource_delete(db_session: Session) -> None:
    source, target, _ = _merge_refs(db_session)
    db_session.add(_merge(source, target))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == source.id))
        db_session.flush()


def test_resource_merge_restricts_target_resource_delete(db_session: Session) -> None:
    source, target, _ = _merge_refs(db_session)
    db_session.add(_merge(source, target))
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(Resource).where(Resource.id == target.id))
        db_session.flush()


def test_resource_merge_rejects_direct_cycle(db_session: Session) -> None:
    first, second, _ = _merge_refs(db_session)
    db_session.add(_merge(first, second))
    db_session.flush()
    db_session.add(_merge(second, first))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "prevent_resource_merge_cycle" in str(exc_info.value.orig)


def test_resource_merge_rejects_three_node_cycle(db_session: Session) -> None:
    first, second, third = _merge_refs(db_session)
    db_session.add(_merge(first, second))
    db_session.add(_merge(second, third))
    db_session.flush()
    db_session.add(_merge(third, first))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "prevent_resource_merge_cycle" in str(exc_info.value.orig)


def test_resource_merge_rejects_longer_indirect_cycle(db_session: Session) -> None:
    first, second, third, fourth = _merge_refs(db_session, count=4)
    db_session.add(_merge(first, second))
    db_session.add(_merge(second, third))
    db_session.add(_merge(third, fourth))
    db_session.flush()
    db_session.add(_merge(fourth, second))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "prevent_resource_merge_cycle" in str(exc_info.value.orig)


def test_resource_merge_cycle_detection_is_tenant_scoped(
    db_session: Session,
) -> None:
    _seed_catalogs(db_session)
    tenant_a = _tenant(db_session, "tenant-a")
    tenant_b = _tenant(db_session, "tenant-b")
    first_a = _resource(db_session, tenant_a, "first-a.example.com")
    second_a = _resource(db_session, tenant_a, "second-a.example.com")
    first_b = _resource(db_session, tenant_b, "first-b.example.com")
    second_b = _resource(db_session, tenant_b, "second-b.example.com")
    db_session.add(_merge(first_a, second_a))
    db_session.flush()
    db_session.add(_merge(second_b, first_b))
    db_session.flush()


def test_resource_merge_allows_valid_long_chain(db_session: Session) -> None:
    first, second, third, fourth, fifth = _merge_refs(db_session, count=5)
    db_session.add(_merge(first, second))
    db_session.add(_merge(second, third))
    db_session.add(_merge(third, fourth))
    db_session.add(_merge(fourth, fifth))
    db_session.flush()


def test_resource_merge_endpoint_update_that_creates_cycle_is_rejected(
    db_session: Session,
) -> None:
    first, second, third = _merge_refs(db_session)
    first_merge = _merge(first, second)
    db_session.add(first_merge)
    db_session.add(_merge(third, first))
    db_session.flush()

    first_merge.target_resource_id = third.id

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "prevent_resource_merge_cycle" in str(exc_info.value.orig)
