from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

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
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork
from app.persistence.sqlalchemy.repositories import (
    SQLAlchemyRepository,
    TenantScopedSQLAlchemyRepository,
    apply_for_update,
    bind_repository,
    entity_select,
    tenant_entity_select,
    tenant_select,
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


class TenantInfrastructureRepository(SQLAlchemyRepository[Tenant]):
    pass


class OrganizationInfrastructureRepository(
    TenantScopedSQLAlchemyRepository[Organization]
):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Organization)


class ResourceInfrastructureRepository(TenantScopedSQLAlchemyRepository[Resource]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Resource)


class ResourceTypeInfrastructureRepository(SQLAlchemyRepository[ResourceType]):
    def get_by_id(self, entity_id: UUID) -> ResourceType | None:
        return self._scalar(entity_select(ResourceType, entity_id))


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


def _organization(tenant_id: UUID, name: str) -> Organization:
    return Organization(
        tenant_id=tenant_id,
        canonical_name=name,
        display_name=name.title(),
        status="active",
    )


def _catalog_ids(session: Session) -> dict[str, UUID]:
    seed_catalogs(session)
    session.flush()
    values = {
        "resource_type_id": session.scalar(
            select(ResourceType.id).where(ResourceType.code == "domain")
        ),
        "lifecycle_status_id": session.scalar(
            select(LifecycleStatus.id).where(LifecycleStatus.code == "active")
        ),
        "criticality_id": session.scalar(
            select(Criticality.id).where(Criticality.code == "medium")
        ),
        "exposure_level_id": session.scalar(
            select(ExposureLevel.id).where(ExposureLevel.code == "public")
        ),
    }
    assert all(value is not None for value in values.values())
    return values


def _resource(session: Session, tenant_id: UUID, name: str) -> Resource:
    catalog_ids = _catalog_ids(session)
    now = datetime.now(UTC)
    resource = Resource(
        tenant_id=tenant_id,
        resource_type_id=catalog_ids["resource_type_id"],
        canonical_name=name,
        display_name=name,
        lifecycle_status_id=catalog_ids["lifecycle_status_id"],
        criticality_id=catalog_ids["criticality_id"],
        exposure_level_id=catalog_ids["exposure_level_id"],
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(resource)
    session.flush()
    return resource


def _tenant_by_slug(engine: Engine, slug: str) -> Tenant | None:
    with Session(engine) as session:
        return session.scalar(select(Tenant).where(Tenant.slug == slug))


def test_repository_stores_injected_session_and_add_attaches_without_commit(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        repository = TenantInfrastructureRepository(session)
        tenant = _tenant(_slug("attached"))

        repository.add(tenant)

        assert repository.session is session
        assert tenant in session
        assert session.commits == 0
        assert session.rollbacks == 0
        assert session.closes == 0


def test_explicit_flush_synchronizes_defaults_without_committing(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        repository = TenantInfrastructureRepository(session)
        tenant = _tenant(_slug("flush"))
        repository.add(tenant)

        assert tenant.created_at is None

        repository.flush()

        assert tenant.created_at is not None
        assert session.commits == 0
        assert session.rollbacks == 0
        assert session.closes == 0


def test_exit_without_unit_of_work_commit_rolls_back_repository_added_rows(
    migrated_engine: Engine,
) -> None:
    slug = _slug("rollback")
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        repository = TenantInfrastructureRepository(unit_of_work.session)
        repository.add(_tenant(slug))
        repository.flush()

    assert _tenant_by_slug(migrated_engine, slug) is None


def test_unit_of_work_commit_persists_repository_added_rows(
    migrated_engine: Engine,
) -> None:
    slug = _slug("commit")
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        repository = TenantInfrastructureRepository(unit_of_work.session)
        repository.add(_tenant(slug))
        repository.flush()
        unit_of_work.commit()

    assert _tenant_by_slug(migrated_engine, slug) is not None


def test_repositories_share_unit_of_work_session_and_bind_helper(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        first = TenantInfrastructureRepository(unit_of_work.session)
        second = bind_repository(TenantInfrastructureRepository, unit_of_work.session)

        assert first.session is unit_of_work.session
        assert second.session is unit_of_work.session
        assert first.session is second.session


def test_distinct_unit_of_work_instances_get_distinct_repository_sessions(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as first:
        with SQLAlchemyUnitOfWork(SessionLocal) as second:
            first_repository = TenantInfrastructureRepository(first.session)
            second_repository = TenantInfrastructureRepository(second.session)

            assert first_repository.session is not second_repository.session


def test_repository_infrastructure_does_not_close_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        session = unit_of_work.session
        repository = TenantInfrastructureRepository(session)
        repository.add(_tenant(_slug("no-close")))
        repository.flush()

        assert session.closes == 0

    assert session.closes == 1


def test_tenant_scoped_lookup_requires_tenant_and_rejects_cross_tenant_access(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        tenant_a = _tenant("tenant-a")
        tenant_b = _tenant("tenant-b")
        session.add_all([tenant_a, tenant_b])
        session.flush()
        organization = _organization(tenant_a.id, "platform")
        session.add(organization)
        session.commit()
        organization_id = organization.id
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id

    with SessionLocal() as session:
        repository = OrganizationInfrastructureRepository(session)

        assert repository.get_tenant_entity(tenant_a_id, organization_id) is not None
        assert repository.get_tenant_entity(tenant_b_id, organization_id) is None
        assert repository.exists_tenant_entity(tenant_a_id, organization_id) is True
        assert repository.exists_tenant_entity(tenant_b_id, organization_id) is False

        parameters = inspect.signature(repository.get_tenant_entity).parameters
        assert parameters["tenant_id"].default is inspect.Parameter.empty
        assert parameters["entity_id"].default is inspect.Parameter.empty


def test_tenant_statement_helpers_include_tenant_scope(migrated_engine: Engine) -> None:
    tenant_id = uuid4()
    entity_id = uuid4()

    scoped = tenant_select(Organization, tenant_id)
    scoped_entity = tenant_entity_select(Organization, tenant_id, entity_id)
    scoped_sql = str(scoped.compile(dialect=migrated_engine.dialect))
    scoped_entity_sql = str(scoped_entity.compile(dialect=migrated_engine.dialect))

    assert "organization.tenant_id" in scoped_sql
    assert "organization.tenant_id" in scoped_entity_sql
    assert "organization.id" in scoped_entity_sql


def test_global_catalog_lookup_is_usable_without_tenant_context(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        seed_catalogs(session)
        session.flush()
        resource_type_id = session.scalar(
            select(ResourceType.id).where(ResourceType.code == "domain")
        )
        assert resource_type_id is not None
        session.commit()

    with SessionLocal() as session:
        repository = ResourceTypeInfrastructureRepository(session)

        assert repository.get_by_id(resource_type_id) is not None


def test_explicit_for_update_helper_only_locks_when_requested(
    migrated_engine: Engine,
) -> None:
    tenant_id = uuid4()
    entity_id = uuid4()
    unlocked = tenant_entity_select(Resource, tenant_id, entity_id)
    locked = apply_for_update(unlocked)

    unlocked_sql = str(unlocked.compile(dialect=migrated_engine.dialect))
    locked_sql = str(locked.compile(dialect=migrated_engine.dialect))

    assert "FOR UPDATE" not in unlocked_sql
    assert "FOR UPDATE" in locked_sql


def test_resource_optimistic_concurrency_remains_sqlalchemy_managed(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant = _tenant(_slug("versioned"))
        setup_session.add(tenant)
        setup_session.flush()
        resource = _resource(setup_session, tenant.id, "versioned.example.com")
        tenant_id = tenant.id
        resource_id = resource.id
        setup_session.commit()

    first = SQLAlchemyUnitOfWork(SessionLocal)
    second = SQLAlchemyUnitOfWork(SessionLocal)
    with first:
        with second:
            first_repository = ResourceInfrastructureRepository(first.session)
            second_repository = ResourceInfrastructureRepository(second.session)
            first_resource = first_repository.get_tenant_entity(tenant_id, resource_id)
            second_resource = second_repository.get_tenant_entity(tenant_id, resource_id)
            assert first_resource is not None
            assert second_resource is not None

            first_resource.display_name = "Updated by first session"
            first.commit()
            assert first_resource.record_version == 2

            second_resource.display_name = "Updated by stale second session"
            with pytest.raises(StaleDataError):
                second.commit()
            second.rollback()
