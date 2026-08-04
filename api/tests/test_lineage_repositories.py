from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.application.ports.lineage import (
    ResourceAliasRepository,
    ResourceMergeRepository,
)
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Resource,
    ResourceAlias,
    ResourceMerge,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork, UnitOfWorkNotActiveError
from app.persistence.sqlalchemy.repositories import (
    SQLAlchemyResourceAliasRepository,
    SQLAlchemyResourceMergeRepository,
)


class TrackingSession(Session):
    commits = 0
    rollbacks = 0
    closes = 0

    def commit(self) -> None:
        self.commits += 1
        super().commit()

    def rollback(self) -> None:
        self.rollbacks += 1
        super().rollback()

    def close(self) -> None:
        self.closes += 1
        super().close()


@dataclass(frozen=True)
class LineageRefs:
    tenant_id: UUID
    other_tenant_id: UUID
    source_resource_id: UUID
    target_resource_id: UUID
    other_resource_id: UUID
    other_tenant_resource_id: UUID


def _session_factory(engine: Engine) -> sessionmaker[TrackingSession]:
    return sessionmaker(
        bind=engine,
        class_=TrackingSession,
        expire_on_commit=False,
    )


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _seed_refs(session: Session) -> LineageRefs:
    seed_catalogs(session)
    session.flush()
    tenant = Tenant(slug=_slug("tenant-a"), display_name="Tenant A", status="active")
    other_tenant = Tenant(
        slug=_slug("tenant-b"),
        display_name="Tenant B",
        status="active",
    )
    session.add_all([tenant, other_tenant])
    session.flush()

    source = _resource(session, tenant.id, _slug("source"))
    target = _resource(session, tenant.id, _slug("target"))
    other = _resource(session, tenant.id, _slug("other"))
    other_tenant_resource = _resource(
        session,
        other_tenant.id,
        _slug("other-tenant"),
    )
    session.add_all([source, target, other, other_tenant_resource])
    session.flush()
    return LineageRefs(
        tenant_id=tenant.id,
        other_tenant_id=other_tenant.id,
        source_resource_id=source.id,
        target_resource_id=target.id,
        other_resource_id=other.id,
        other_tenant_resource_id=other_tenant_resource.id,
    )


def _resource(session: Session, tenant_id: UUID, canonical_name: str) -> Resource:
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
    return Resource(
        tenant_id=tenant_id,
        resource_type_id=resource_type_id,
        canonical_name=canonical_name,
        display_name=canonical_name,
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )


def _alias(
    refs: LineageRefs,
    *,
    resource_id: UUID | None = None,
    alias_type: str = "hostname",
    alias_value: str = "Example.COM",
    normalized_value: str = "example.com",
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> ResourceAlias:
    first_seen_at = first_seen_at or datetime.now(UTC)
    last_seen_at = last_seen_at or first_seen_at
    return ResourceAlias(
        tenant_id=refs.tenant_id,
        resource_id=resource_id or refs.source_resource_id,
        alias_type=alias_type,
        alias_value=alias_value,
        normalized_value=normalized_value,
        source="manual",
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


def _merge(
    refs: LineageRefs,
    *,
    source_resource_id: UUID | None = None,
    target_resource_id: UUID | None = None,
    merged_at: datetime | None = None,
) -> ResourceMerge:
    return ResourceMerge(
        tenant_id=refs.tenant_id,
        source_resource_id=source_resource_id or refs.source_resource_id,
        target_resource_id=target_resource_id or refs.target_resource_id,
        reason="duplicate",
        source="manual",
        merged_at=merged_at or datetime.now(UTC),
    )


def _count_by_id(session: Session, model_type: type[object], entity_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(model_type).where(model_type.id == entity_id)
        )
        or 0
    )


def _method_names(repository: object) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(repository, inspect.ismethod)
        if not name.startswith("_")
    }


def _accepts_alias_repository(
    repository: ResourceAliasRepository,
) -> ResourceAliasRepository:
    return repository


def _accepts_merge_repository(
    repository: ResourceMergeRepository,
) -> ResourceMergeRepository:
    return repository


def test_lineage_repositories_satisfy_protocols_and_use_injected_session(
    db_session: Session,
) -> None:
    alias_repository = SQLAlchemyResourceAliasRepository(db_session)
    merge_repository = SQLAlchemyResourceMergeRepository(db_session)

    assert _accepts_alias_repository(alias_repository) is alias_repository
    assert _accepts_merge_repository(merge_repository) is merge_repository
    for repository in (alias_repository, merge_repository):
        assert repository.session is db_session
        assert repository.__class__.__module__.startswith("app.persistence.sqlalchemy")
        assert {"commit", "rollback", "delete"}.isdisjoint(_method_names(repository))


def test_alias_lookup_and_listing_are_tenant_scoped_and_ordered(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    second = _alias(
        refs,
        alias_type="hostname",
        alias_value="B.EXAMPLE.COM",
        normalized_value="b.example.com",
    )
    first = _alias(
        refs,
        alias_type="dns_name",
        alias_value="A.EXAMPLE.COM",
        normalized_value="a.example.com",
    )
    other_resource_alias = _alias(
        refs,
        resource_id=refs.other_resource_id,
        alias_value="other.example.com",
        normalized_value="other.example.com",
    )
    db_session.add_all([second, first, other_resource_alias])
    db_session.flush()
    repository = SQLAlchemyResourceAliasRepository(db_session)

    found = repository.find_resource_by_alias(
        refs.tenant_id,
        "dns_name",
        "a.example.com",
    )

    assert found is not None
    assert found.id == refs.source_resource_id
    assert repository.find_resource_by_alias(refs.other_tenant_id, "dns_name", "a.example.com") is None
    assert repository.find_resource_by_alias(refs.tenant_id, "hostname", "a.example.com") is None
    assert repository.find_resource_by_alias(refs.tenant_id, "dns_name", "missing") is None
    assert repository.list_for_resource(refs.tenant_id, refs.source_resource_id) == [
        first,
        second,
    ]
    assert repository.list_for_resource(refs.other_tenant_id, refs.source_resource_id) == []


def test_merge_lookup_and_listing_are_tenant_scoped_and_ordered(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    outgoing = _merge(refs, merged_at=datetime.now(UTC))
    earlier_incoming = _merge(
        refs,
        source_resource_id=refs.other_resource_id,
        target_resource_id=refs.target_resource_id,
        merged_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    db_session.add_all([outgoing, earlier_incoming])
    db_session.flush()
    repository = SQLAlchemyResourceMergeRepository(db_session)

    assert repository.get_outgoing_merge(refs.tenant_id, refs.source_resource_id) is outgoing
    assert repository.get_outgoing_merge(refs.tenant_id, refs.target_resource_id) is None
    assert repository.get_outgoing_merge(refs.other_tenant_id, refs.source_resource_id) is None
    assert repository.list_incoming_merges(refs.tenant_id, refs.target_resource_id) == [
        earlier_incoming,
        outgoing,
    ]
    assert repository.list_incoming_merges(refs.other_tenant_id, refs.target_resource_id) == []


@pytest.mark.parametrize(
    ("property_name", "model_type", "factory"),
    (
        ("resource_aliases", ResourceAlias, _alias),
        ("resource_merges", ResourceMerge, _merge),
    ),
)
def test_lineage_add_commit_and_rollback(
    migrated_engine: Engine,
    property_name: str,
    model_type: type[object],
    factory: object,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    committed = factory(refs)
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        getattr(uow, property_name).add(committed)
        uow.commit()

    rolled_back = factory(refs)
    if isinstance(rolled_back, ResourceAlias):
        rolled_back.normalized_value = "rolled-back.example.com"
        rolled_back.alias_value = "rolled-back.example.com"
    else:
        rolled_back.source_resource_id = refs.other_resource_id
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        getattr(uow, property_name).add(rolled_back)

    with SessionLocal() as verification:
        assert _count_by_id(verification, model_type, committed.id) == 1
        assert _count_by_id(verification, model_type, rolled_back.id) == 0


def test_explicit_alias_flush_does_not_commit(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    alias = _alias(refs, normalized_value="flush.example.com")
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_aliases.add(alias)
        uow.resource_aliases.flush()
        assert alias.created_at is not None
        assert uow.resource_aliases.session.commits == 0

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceAlias, alias.id) == 0


def test_lineage_constraint_failure_rolls_back_and_next_unit_of_work_succeeds(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    alias = _alias(refs, normalized_value="atomic.example.com")
    merge = _merge(refs)

    with pytest.raises(IntegrityError):
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            uow.resource_aliases.add(alias)
            uow.resource_merges.add(merge)
            uow.resource_merges.add(_merge(refs))
            uow.commit()

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceAlias, alias.id) == 0
        assert _count_by_id(verification, ResourceMerge, merge.id) == 0

    replacement = _alias(refs, normalized_value="after-failure.example.com")
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_aliases.add(replacement)
        uow.commit()

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceAlias, replacement.id) == 1


def test_lineage_multi_repository_commit_and_rollback_are_atomic(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    committed_alias = _alias(refs, normalized_value="commit.example.com")
    committed_merge = _merge(refs)
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_aliases.add(committed_alias)
        uow.resource_merges.add(committed_merge)
        uow.commit()

    rolled_back_alias = _alias(refs, normalized_value="rollback.example.com")
    rolled_back_merge = _merge(
        refs,
        source_resource_id=refs.other_resource_id,
        target_resource_id=refs.target_resource_id,
    )
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_aliases.add(rolled_back_alias)
        uow.resource_merges.add(rolled_back_merge)

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceAlias, committed_alias.id) == 1
        assert _count_by_id(verification, ResourceMerge, committed_merge.id) == 1
        assert _count_by_id(verification, ResourceAlias, rolled_back_alias.id) == 0
        assert _count_by_id(verification, ResourceMerge, rolled_back_merge.id) == 0


def test_lineage_repositories_preserve_database_constraints(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    alias = _alias(refs)
    db_session.add(alias)
    db_session.flush()
    db_session.add(_alias(refs, alias_value="duplicate.example.com"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    refs = _seed_refs(db_session)
    db_session.add(_merge(refs, target_resource_id=refs.source_resource_id))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("property_name", ("resource_aliases", "resource_merges"))
def test_lineage_repositories_follow_unit_of_work_lifecycle(
    migrated_engine: Engine,
    property_name: str,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    uow = SQLAlchemyUnitOfWork(SessionLocal)

    with pytest.raises(UnitOfWorkNotActiveError):
        getattr(uow, property_name)

    with uow:
        repository = getattr(uow, property_name)
        assert repository.session is uow.session
        uow.commit()
        with pytest.raises(UnitOfWorkNotActiveError):
            getattr(uow, property_name)

    with pytest.raises(UnitOfWorkNotActiveError):
        getattr(uow, property_name)

    rollback_uow = SQLAlchemyUnitOfWork(SessionLocal)
    with rollback_uow:
        getattr(rollback_uow, property_name)
        rollback_uow.rollback()
        with pytest.raises(UnitOfWorkNotActiveError):
            getattr(rollback_uow, property_name)


def test_lineage_repositories_share_unit_of_work_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        expected = uow.session
        assert uow.resource_aliases.session is expected
        assert uow.resource_merges.session is expected
        assert uow.tenants.session is expected
        assert uow.organizations.session is expected
        assert uow.resources.session is expected
        assert uow.resource_identifiers.session is expected
        assert uow.resource_states.session is expected


def test_lineage_repositories_are_distinct_per_unit_of_work(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as first:
        with SQLAlchemyUnitOfWork(SessionLocal) as second:
            assert first.resource_aliases is not second.resource_aliases
            assert first.resource_merges is not second.resource_merges
            assert first.resource_aliases.session is not second.resource_aliases.session


def test_closing_one_unit_of_work_does_not_close_another_lineage_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    first = SQLAlchemyUnitOfWork(SessionLocal)
    second = SQLAlchemyUnitOfWork(SessionLocal)
    first.__enter__()
    second.__enter__()
    try:
        second_session = second.resource_aliases.session
        first.__exit__(None, None, None)

        assert second_session.closes == 0
        assert second.resource_aliases.session is second_session
    finally:
        second.__exit__(None, None, None)
