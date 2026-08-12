from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.application.errors import ConcurrentModificationError
from app.application.ports.resources import ResourceRepository
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Organization,
    Resource,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import (
    SQLAlchemyUnitOfWork,
    UnitOfWorkNotActiveError,
)
from app.persistence.sqlalchemy.repositories import (
    SQLAlchemyResourceRepository,
    apply_for_update,
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


def _session_factory(engine: Engine) -> sessionmaker[TrackingSession]:
    return sessionmaker(
        bind=engine,
        class_=TrackingSession,
        expire_on_commit=False,
    )


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _tenant(slug: str | None = None) -> Tenant:
    tenant_slug = slug or _slug("tenant")
    return Tenant(
        slug=tenant_slug,
        display_name=tenant_slug.title(),
        status="active",
    )


def _organization(tenant_id: UUID, canonical_name: str) -> Organization:
    return Organization(
        tenant_id=tenant_id,
        canonical_name=canonical_name,
        display_name=canonical_name.title(),
        status="active",
    )


def _catalog_ids(session: Session) -> tuple[UUID, UUID, UUID, UUID]:
    seed_catalogs(session)
    session.flush()
    resource_type_id = session.scalar(
        select(ResourceType.id).where(ResourceType.code == "domain")
    )
    lifecycle_status_id = session.scalar(
        select(LifecycleStatus.id).where(LifecycleStatus.code == "active")
    )
    criticality_id = session.scalar(
        select(Criticality.id).where(Criticality.code == "medium")
    )
    exposure_level_id = session.scalar(
        select(ExposureLevel.id).where(ExposureLevel.code == "public")
    )
    assert resource_type_id is not None
    assert lifecycle_status_id is not None
    assert criticality_id is not None
    assert exposure_level_id is not None
    return resource_type_id, lifecycle_status_id, criticality_id, exposure_level_id


def _resource(
    session: Session,
    tenant_id: UUID,
    canonical_name: str,
    *,
    resource_type_id: UUID | None = None,
) -> Resource:
    (
        default_resource_type_id,
        lifecycle_status_id,
        criticality_id,
        exposure_level_id,
    ) = _catalog_ids(session)
    now = datetime.now(UTC)
    return Resource(
        tenant_id=tenant_id,
        resource_type_id=resource_type_id or default_resource_type_id,
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


def _insert_tenant(session: Session, slug: str | None = None) -> Tenant:
    tenant = _tenant(slug)
    session.add(tenant)
    session.flush()
    return tenant


def _insert_resource(
    session: Session,
    tenant_id: UUID,
    canonical_name: str,
) -> Resource:
    resource = _resource(session, tenant_id, canonical_name)
    session.add(resource)
    session.flush()
    return resource


def _resource_by_name(
    engine: Engine,
    tenant_id: UUID,
    canonical_name: str,
) -> Resource | None:
    with Session(engine) as session:
        return session.scalar(
            select(Resource).where(
                Resource.tenant_id == tenant_id,
                Resource.canonical_name == canonical_name,
            )
        )


def _resource_count(engine: Engine, tenant_id: UUID, canonical_name: str) -> int:
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(Resource)
                .where(
                    Resource.tenant_id == tenant_id,
                    Resource.canonical_name == canonical_name,
                )
            )
            or 0
        )


def _accepts_resource_repository(repository: ResourceRepository) -> ResourceRepository:
    return repository


def test_resource_repository_satisfies_protocol_and_uses_injected_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        repository = SQLAlchemyResourceRepository(session)

        assert _accepts_resource_repository(repository) is repository
        assert repository.session is session
        assert repository.__class__.__module__.startswith("app.persistence.sqlalchemy")
        assert not hasattr(repository, "commit")
        assert not hasattr(repository, "rollback")


def test_resource_add_commit_and_rollback(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    committed_name = _slug("resource-commit")
    rolled_back_name = _slug("resource-rollback")

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(_slug("resource-tenant"))
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        tenant_id = tenant.id
        unit_of_work.resources.add(
            _resource(unit_of_work.session, tenant_id, committed_name)
        )
        unit_of_work.commit()

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        unit_of_work.resources.add(
            _resource(unit_of_work.session, tenant_id, rolled_back_name)
        )

    assert _resource_by_name(migrated_engine, tenant_id, committed_name) is not None
    assert _resource_by_name(migrated_engine, tenant_id, rolled_back_name) is None


def test_explicit_resource_flush_does_not_commit(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(_slug("resource-flush"))
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        resource = _resource(unit_of_work.session, tenant.id, "flushed.example.com")
        unit_of_work.resources.add(resource)
        unit_of_work.resources.flush()
        session = unit_of_work.resources.session

        assert resource.created_at is not None
        assert session.commits == 0
        assert session.rollbacks == 0

    assert _resource_by_name(migrated_engine, tenant.id, "flushed.example.com") is None


def test_failed_commit_leaves_no_partial_resource_rows(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("resource-failed")

    with pytest.raises(IntegrityError):
        with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
            tenant = _tenant(slug)
            unit_of_work.tenants.add(tenant)
            unit_of_work.tenants.flush()
            unit_of_work.resources.add(
                _resource(
                    unit_of_work.session,
                    tenant.id,
                    "bad-fk.example.com",
                    resource_type_id=uuid4(),
                )
            )
            unit_of_work.commit()

    with Session(migrated_engine) as session:
        assert session.scalar(select(Tenant).where(Tenant.slug == slug)) is None


def test_resource_id_lookup_is_tenant_scoped_and_non_locking(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant_a = _insert_tenant(setup_session, "tenant-a")
        tenant_b = _insert_tenant(setup_session, "tenant-b")
        resource = _insert_resource(setup_session, tenant_a.id, "lookup.example.com")
        setup_session.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        resource_id = resource.id

    with SessionLocal() as session:
        repository = SQLAlchemyResourceRepository(session)
        statement_sql = str(
            repository.tenant_entity_statement(tenant_a_id, resource_id).compile(
                dialect=migrated_engine.dialect
            )
        )

        assert repository.get_by_id(tenant_a_id, resource_id) is not None
        assert repository.get_by_id(tenant_a_id, uuid4()) is None
        assert repository.get_by_id(tenant_b_id, resource_id) is None
        assert "resource.tenant_id" in statement_sql
        assert "resource.id" in statement_sql
        assert "FOR UPDATE" not in statement_sql


def test_resource_canonical_name_lookup_matches_actual_constraints(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant_a = _insert_tenant(setup_session, "tenant-a")
        tenant_b = _insert_tenant(setup_session, "tenant-b")
        first = _insert_resource(setup_session, tenant_a.id, "shared.example.com")
        second = _insert_resource(setup_session, tenant_a.id, "shared.example.com")
        cross_tenant = _insert_resource(
            setup_session,
            tenant_b.id,
            "shared.example.com",
        )
        setup_session.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        expected_id = min(first.id, second.id)
        cross_tenant_id = cross_tenant.id

    with SessionLocal() as session:
        repository = SQLAlchemyResourceRepository(session)

        loaded = repository.get_by_canonical_name(tenant_a_id, "shared.example.com")
        assert loaded is not None
        assert loaded.id == expected_id
        assert repository.get_by_canonical_name(tenant_a_id, "missing.example.com") is None
        assert repository.get_by_canonical_name(uuid4(), "shared.example.com") is None
        assert (
            repository.get_by_canonical_name(tenant_b_id, "shared.example.com").id
            == cross_tenant_id
        )

    assert _resource_count(migrated_engine, tenant_a_id, "shared.example.com") == 2
    assert _resource_count(migrated_engine, tenant_b_id, "shared.example.com") == 1


def test_resource_existence_is_tenant_scoped(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant_a = _insert_tenant(setup_session, "tenant-a")
        tenant_b = _insert_tenant(setup_session, "tenant-b")
        resource = _insert_resource(setup_session, tenant_a.id, "exists.example.com")
        setup_session.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        resource_id = resource.id

    with SessionLocal() as session:
        repository = SQLAlchemyResourceRepository(session)

        assert repository.exists(tenant_a_id, resource_id) is True
        assert repository.exists(tenant_a_id, uuid4()) is False
        assert repository.exists(tenant_b_id, resource_id) is False


def test_resource_get_for_update_is_explicit_and_tenant_scoped(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant = _insert_tenant(setup_session, "tenant-a")
        resource = _insert_resource(setup_session, tenant.id, "locked.example.com")
        setup_session.commit()
        tenant_id = tenant.id
        resource_id = resource.id

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        repository = unit_of_work.resources
        locked_statement = apply_for_update(
            repository.tenant_entity_statement(tenant_id, resource_id)
        )
        locked_sql = str(locked_statement.compile(dialect=migrated_engine.dialect))
        unlocked_sql = str(
            repository.tenant_entity_statement(tenant_id, resource_id).compile(
                dialect=migrated_engine.dialect
            )
        )

        locked = repository.get_for_update(tenant_id, resource_id)
        wrong_tenant = repository.get_for_update(uuid4(), resource_id)

        assert locked is not None
        assert wrong_tenant is None
        assert "resource.tenant_id" in locked_sql
        assert "resource.id" in locked_sql
        assert "FOR UPDATE" in locked_sql
        assert "FOR UPDATE" not in unlocked_sql


def test_missing_required_resource_foreign_key_propagates_integrity_error(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(_slug("resource-missing-fk"))
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        unit_of_work.resources.add(
            _resource(
                unit_of_work.session,
                tenant.id,
                "missing-fk.example.com",
                resource_type_id=uuid4(),
            )
        )

        with pytest.raises(IntegrityError):
            unit_of_work.resources.flush()


def test_resource_optimistic_concurrency_uses_sqlalchemy_versioning(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant = _insert_tenant(setup_session, _slug("resource-version"))
        resource = _insert_resource(setup_session, tenant.id, "versioned.example.com")
        setup_session.commit()
        tenant_id = tenant.id
        resource_id = resource.id

    first = SQLAlchemyUnitOfWork(SessionLocal)
    second = SQLAlchemyUnitOfWork(SessionLocal)
    with first:
        with second:
            first_resource = first.resources.get_by_id(tenant_id, resource_id)
            second_resource = second.resources.get_by_id(tenant_id, resource_id)
            assert first_resource is not None
            assert second_resource is not None
            assert first_resource.record_version == 1
            assert second_resource.record_version == 1

            first_resource.display_name = "Updated by first session"
            first.commit()
            assert first_resource.record_version == 2

            second_resource.display_name = "Updated by stale second session"
            with pytest.raises(ConcurrentModificationError) as exc_info:
                second.commit()
            assert isinstance(exc_info.value.__cause__, StaleDataError)

    with SQLAlchemyUnitOfWork(SessionLocal) as replacement:
        loaded = replacement.resources.get_by_id(tenant_id, resource_id)
        assert loaded is not None
        assert loaded.record_version == 2


def test_unit_of_work_resource_repository_lifecycle_and_session_sharing(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    unit_of_work = SQLAlchemyUnitOfWork(SessionLocal)

    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.resources

    with unit_of_work:
        assert isinstance(unit_of_work.resources, SQLAlchemyResourceRepository)
        assert unit_of_work.resources.session is unit_of_work.session
        assert unit_of_work.resources.session is unit_of_work.tenants.session
        assert unit_of_work.resources.session is unit_of_work.organizations.session
        unit_of_work.commit()
        with pytest.raises(UnitOfWorkNotActiveError):
            _ = unit_of_work.resources

    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.resources


def test_resource_repository_instances_are_distinct_across_unit_of_work_instances(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SQLAlchemyUnitOfWork(SessionLocal) as first:
        with SQLAlchemyUnitOfWork(SessionLocal) as second:
            assert first.resources is not second.resources
            assert first.resources.session is not second.resources.session


def test_committed_tenant_organization_resource_transaction_persists_all_rows(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("resource-multi-commit")

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(slug)
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        unit_of_work.organizations.add(_organization(tenant.id, "platform"))
        unit_of_work.resources.add(
            _resource(unit_of_work.session, tenant.id, "atomic.example.com")
        )
        unit_of_work.commit()
        tenant_id = tenant.id

    with Session(migrated_engine) as session:
        assert session.scalar(select(Tenant).where(Tenant.slug == slug)) is not None
        assert (
            session.scalar(
                select(Organization).where(
                    Organization.tenant_id == tenant_id,
                    Organization.canonical_name == "platform",
                )
            )
            is not None
        )
        assert _resource_by_name(migrated_engine, tenant_id, "atomic.example.com") is not None


def test_uncommitted_tenant_organization_resource_transaction_rolls_back_all_rows(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("resource-multi-rollback")

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(slug)
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        tenant_id = tenant.id
        unit_of_work.organizations.add(_organization(tenant_id, "platform"))
        unit_of_work.resources.add(
            _resource(unit_of_work.session, tenant_id, "atomic.example.com")
        )

    with Session(migrated_engine) as session:
        assert session.scalar(select(Tenant).where(Tenant.slug == slug)) is None
        assert (
            session.scalar(
                select(Organization).where(
                    Organization.tenant_id == tenant_id,
                    Organization.canonical_name == "platform",
                )
            )
            is None
        )
        assert _resource_by_name(migrated_engine, tenant_id, "atomic.example.com") is None


def test_failed_tenant_organization_resource_transaction_leaves_no_partial_rows(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("resource-multi-failed")

    with pytest.raises(IntegrityError):
        with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
            tenant = _tenant(slug)
            unit_of_work.tenants.add(tenant)
            unit_of_work.tenants.flush()
            unit_of_work.organizations.add(_organization(tenant.id, "platform"))
            unit_of_work.resources.add(
                _resource(
                    unit_of_work.session,
                    tenant.id,
                    "bad-atomic.example.com",
                    resource_type_id=uuid4(),
                )
            )
            unit_of_work.resources.flush()

    with Session(migrated_engine) as session:
        assert session.scalar(select(Tenant).where(Tenant.slug == slug)) is None
