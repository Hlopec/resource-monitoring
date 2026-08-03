from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.application.ports.organizations import OrganizationRepository
from app.application.ports.tenants import TenantRepository
from app.models import Organization, Tenant
from app.persistence.sqlalchemy import (
    SQLAlchemyUnitOfWork,
    UnitOfWorkNotActiveError,
)
from app.persistence.sqlalchemy.repositories import (
    SQLAlchemyOrganizationRepository,
    SQLAlchemyTenantRepository,
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


def _organization(
    tenant_id: UUID,
    canonical_name: str,
    *,
    parent_organization_id: UUID | None = None,
    external_key: str | None = None,
) -> Organization:
    return Organization(
        tenant_id=tenant_id,
        parent_organization_id=parent_organization_id,
        canonical_name=canonical_name,
        display_name=canonical_name.title(),
        external_key=external_key,
        status="active",
    )


def _insert_tenant(session: Session, slug: str | None = None) -> Tenant:
    tenant = _tenant(slug)
    session.add(tenant)
    session.flush()
    return tenant


def _insert_organization(
    session: Session,
    tenant_id: UUID,
    canonical_name: str,
    *,
    parent_organization_id: UUID | None = None,
    external_key: str | None = None,
) -> Organization:
    organization = _organization(
        tenant_id,
        canonical_name,
        parent_organization_id=parent_organization_id,
        external_key=external_key,
    )
    session.add(organization)
    session.flush()
    return organization


def _tenant_by_slug(engine: Engine, slug: str) -> Tenant | None:
    with Session(engine) as session:
        return session.scalar(select(Tenant).where(Tenant.slug == slug))


def _organization_by_name(
    engine: Engine,
    tenant_id: UUID,
    canonical_name: str,
) -> Organization | None:
    with Session(engine) as session:
        return session.scalar(
            select(Organization).where(
                Organization.tenant_id == tenant_id,
                Organization.canonical_name == canonical_name,
            )
        )


def _accepts_tenant_repository(repository: TenantRepository) -> TenantRepository:
    return repository


def _accepts_organization_repository(
    repository: OrganizationRepository,
) -> OrganizationRepository:
    return repository


def test_tenant_repository_satisfies_protocol_and_uses_injected_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        repository = SQLAlchemyTenantRepository(session)

        assert _accepts_tenant_repository(repository) is repository
        assert repository.session is session


def test_tenant_add_attaches_and_commit_persists(migrated_engine: Engine) -> None:
    slug = _slug("tenant-commit")
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(slug)
        unit_of_work.tenants.add(tenant)
        assert tenant in unit_of_work.session
        unit_of_work.commit()

    assert _tenant_by_slug(migrated_engine, slug) is not None


def test_tenant_add_rolls_back_without_commit(migrated_engine: Engine) -> None:
    slug = _slug("tenant-rollback")
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        unit_of_work.tenants.add(_tenant(slug))

    assert _tenant_by_slug(migrated_engine, slug) is None


def test_tenant_lookup_and_existence_methods(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant = _insert_tenant(setup_session, _slug("tenant-lookup"))
        tenant_id = tenant.id
        tenant_slug = tenant.slug
        setup_session.commit()

    with SessionLocal() as session:
        repository = SQLAlchemyTenantRepository(session)

        assert repository.get_by_id(tenant_id) is not None
        assert repository.get_by_id(uuid4()) is None
        assert repository.get_by_slug(tenant_slug) is not None
        assert repository.get_by_slug("missing-tenant") is None
        assert repository.exists_by_slug(tenant_slug) is True
        assert repository.exists_by_slug("missing-tenant") is False


def test_tenant_duplicate_slug_raises_original_integrity_error(
    migrated_engine: Engine,
) -> None:
    slug = _slug("duplicate-tenant")
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        unit_of_work.tenants.add(_tenant(slug))
        unit_of_work.tenants.add(_tenant(slug))
        with pytest.raises(IntegrityError):
            unit_of_work.tenants.flush()


def test_tenant_repository_does_not_commit_or_rollback(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        repository = SQLAlchemyTenantRepository(session)
        repository.add(_tenant(_slug("tenant-no-tx")))
        repository.flush()

        assert session.commits == 0
        assert session.rollbacks == 0
        assert session.closes == 0


def test_organization_repository_satisfies_protocol_and_uses_injected_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as session:
        repository = SQLAlchemyOrganizationRepository(session)

        assert _accepts_organization_repository(repository) is repository
        assert repository.session is session


def test_organization_add_commit_and_rollback(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    committed_name = _slug("org-commit")
    rolled_back_name = _slug("org-rollback")

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(_slug("org-tenant"))
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        tenant_id = tenant.id
        unit_of_work.organizations.add(_organization(tenant_id, committed_name))
        unit_of_work.commit()

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        unit_of_work.organizations.add(_organization(tenant_id, rolled_back_name))

    assert _organization_by_name(migrated_engine, tenant_id, committed_name) is not None
    assert _organization_by_name(migrated_engine, tenant_id, rolled_back_name) is None


def test_organization_tenant_scoped_lookup_methods(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant_a = _insert_tenant(setup_session, "tenant-a")
        tenant_b = _insert_tenant(setup_session, "tenant-b")
        organization = _insert_organization(
            setup_session,
            tenant_a.id,
            "platform",
            external_key="platform-ext",
        )
        setup_session.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        organization_id = organization.id

    with SessionLocal() as session:
        repository = SQLAlchemyOrganizationRepository(session)

        assert repository.get_by_id(tenant_a_id, organization_id) is not None
        assert repository.get_by_id(tenant_b_id, organization_id) is None
        assert repository.get_by_canonical_name(tenant_a_id, "platform") is not None
        assert repository.get_by_canonical_name(tenant_b_id, "platform") is None
        assert repository.get_by_external_key(tenant_a_id, "platform-ext") is not None
        assert repository.get_by_external_key(tenant_b_id, "platform-ext") is None
        assert repository.exists(tenant_a_id, organization_id) is True
        assert repository.exists(tenant_b_id, organization_id) is False
        assert repository.exists(tenant_a_id, uuid4()) is False


def test_organization_list_children_is_tenant_scoped_and_stably_ordered(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        tenant_a = _insert_tenant(setup_session, "tenant-a")
        tenant_b = _insert_tenant(setup_session, "tenant-b")
        parent_a = _insert_organization(setup_session, tenant_a.id, "parent-a")
        parent_b = _insert_organization(setup_session, tenant_b.id, "parent-b")
        expected_second = _insert_organization(
            setup_session,
            tenant_a.id,
            "beta",
            parent_organization_id=parent_a.id,
        )
        expected_first = _insert_organization(
            setup_session,
            tenant_a.id,
            "alpha",
            parent_organization_id=parent_a.id,
        )
        _insert_organization(
            setup_session,
            tenant_b.id,
            "aardvark",
            parent_organization_id=parent_b.id,
        )
        setup_session.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        parent_a_id = parent_a.id
        parent_b_id = parent_b.id
        first_id = expected_first.id
        second_id = expected_second.id

    with SessionLocal() as session:
        repository = SQLAlchemyOrganizationRepository(session)

        children = repository.list_children(tenant_a_id, parent_a_id)
        assert [child.id for child in children] == [first_id, second_id]
        assert repository.list_children(tenant_b_id, parent_a_id) == []
        assert repository.list_children(tenant_b_id, parent_b_id)[0].tenant_id == tenant_b_id


def test_organization_duplicate_external_key_fails_within_one_tenant(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(_slug("org-duplicate"))
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        unit_of_work.organizations.add(
            _organization(tenant.id, "first", external_key="same")
        )
        unit_of_work.organizations.add(
            _organization(tenant.id, "second", external_key="same")
        )

        with pytest.raises(IntegrityError):
            unit_of_work.organizations.flush()


def test_organization_same_external_key_and_canonical_name_allowed_across_tenants(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant_a = _tenant(_slug("org-cross-a"))
        tenant_b = _tenant(_slug("org-cross-b"))
        unit_of_work.tenants.add(tenant_a)
        unit_of_work.tenants.add(tenant_b)
        unit_of_work.tenants.flush()
        unit_of_work.organizations.add(
            _organization(tenant_a.id, "shared-name", external_key="shared-ext")
        )
        unit_of_work.organizations.add(
            _organization(tenant_b.id, "shared-name", external_key="shared-ext")
        )
        unit_of_work.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id

    assert _organization_by_name(migrated_engine, tenant_a_id, "shared-name") is not None
    assert _organization_by_name(migrated_engine, tenant_b_id, "shared-name") is not None


def test_unit_of_work_repository_properties_follow_lifecycle(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    unit_of_work = SQLAlchemyUnitOfWork(SessionLocal)

    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.tenants
    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.organizations

    with unit_of_work:
        assert isinstance(unit_of_work.tenants, SQLAlchemyTenantRepository)
        assert isinstance(unit_of_work.organizations, SQLAlchemyOrganizationRepository)
        assert unit_of_work.tenants.session is unit_of_work.session
        assert unit_of_work.organizations.session is unit_of_work.session
        unit_of_work.commit()
        with pytest.raises(UnitOfWorkNotActiveError):
            _ = unit_of_work.tenants
        with pytest.raises(UnitOfWorkNotActiveError):
            _ = unit_of_work.organizations

    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.tenants
    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.organizations


def test_unit_of_work_repository_instances_are_not_reused(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SQLAlchemyUnitOfWork(SessionLocal) as first:
        with SQLAlchemyUnitOfWork(SessionLocal) as second:
            assert first.tenants is not second.tenants
            assert first.organizations is not second.organizations
            assert first.tenants.session is not second.tenants.session
            assert first.organizations.session is not second.organizations.session


def test_committed_multi_repository_transaction_persists_all_writes(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("multi-commit")

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(slug)
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        unit_of_work.organizations.add(_organization(tenant.id, "platform"))
        unit_of_work.commit()
        tenant_id = tenant.id

    assert _tenant_by_slug(migrated_engine, slug) is not None
    assert _organization_by_name(migrated_engine, tenant_id, "platform") is not None


def test_uncommitted_multi_repository_transaction_rolls_back_all_writes(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("multi-rollback")

    with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
        tenant = _tenant(slug)
        unit_of_work.tenants.add(tenant)
        unit_of_work.tenants.flush()
        tenant_id = tenant.id
        unit_of_work.organizations.add(_organization(tenant_id, "platform"))

    assert _tenant_by_slug(migrated_engine, slug) is None
    assert _organization_by_name(migrated_engine, tenant_id, "platform") is None


def test_failed_multi_repository_transaction_leaves_no_partial_writes(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("multi-failed")

    with pytest.raises(IntegrityError):
        with SQLAlchemyUnitOfWork(SessionLocal) as unit_of_work:
            tenant = _tenant(slug)
            unit_of_work.tenants.add(tenant)
            unit_of_work.tenants.flush()
            unit_of_work.organizations.add(
                _organization(tenant.id, "first", external_key="same")
            )
            unit_of_work.organizations.add(
                _organization(tenant.id, "second", external_key="same")
            )
            unit_of_work.organizations.flush()

    assert _tenant_by_slug(migrated_engine, slug) is None
