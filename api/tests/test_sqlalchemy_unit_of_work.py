from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.application.ports.unit_of_work import UnitOfWork
from app.db.session import get_session, transaction_session
from app.models import Tenant
from app.persistence.sqlalchemy import (
    SQLAlchemyUnitOfWork,
    UnitOfWorkNotActiveError,
    UnitOfWorkStateError,
)


class TrackingSession(Session):
    closed_by_unit_of_work = False

    def close(self) -> None:
        self.closed_by_unit_of_work = True
        super().close()


class CountingSessionFactory:
    def __init__(self, maker: sessionmaker[TrackingSession]) -> None:
        self._maker = maker
        self.calls = 0
        self.sessions: list[TrackingSession] = []

    def __call__(self) -> TrackingSession:
        self.calls += 1
        session = self._maker()
        self.sessions.append(session)
        return session


@pytest.fixture()
def session_factory(migrated_engine: Engine) -> CountingSessionFactory:
    maker = sessionmaker(
        bind=migrated_engine,
        class_=TrackingSession,
        expire_on_commit=False,
    )
    return CountingSessionFactory(maker)


def _slug(prefix: str = "tenant") -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _tenant(slug: str | None = None, display_name: str | None = None) -> Tenant:
    tenant_slug = slug or _slug()
    return Tenant(
        slug=tenant_slug,
        display_name=display_name or tenant_slug.title(),
        status="active",
    )


def _insert_tenant(engine: Engine, slug: str | None = None) -> tuple[UUID, str]:
    tenant = _tenant(slug)
    with Session(engine) as session:
        session.add(tenant)
        session.flush()
        tenant_id = tenant.id
        tenant_slug = tenant.slug
        session.commit()
    return tenant_id, tenant_slug


def _tenant_by_slug(engine: Engine, slug: str) -> Tenant | None:
    with Session(engine) as session:
        return session.scalar(select(Tenant).where(Tenant.slug == slug))


def _tenant_count(engine: Engine, slug: str) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count()).select_from(Tenant).where(Tenant.slug == slug)
        ) or 0


def _accepts_unit_of_work(unit_of_work: UnitOfWork) -> UnitOfWork:
    return unit_of_work


def test_sqlalchemy_unit_of_work_satisfies_application_protocol(
    session_factory: CountingSessionFactory,
) -> None:
    unit_of_work: UnitOfWork = SQLAlchemyUnitOfWork(session_factory)

    assert _accepts_unit_of_work(unit_of_work) is unit_of_work


def test_commit_persists_insert_and_closes_session(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    slug = _slug("commit")

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.session.add(_tenant(slug))
        unit_of_work.commit()

    assert _tenant_by_slug(migrated_engine, slug) is not None
    assert session_factory.calls == 1
    assert session_factory.sessions[0].closed_by_unit_of_work is True


def test_commit_persists_update_visible_from_separate_session(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    tenant_id, _ = _insert_tenant(migrated_engine, _slug("update"))

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        loaded = unit_of_work.session.get(Tenant, tenant_id)
        assert loaded is not None
        loaded.display_name = "Updated Tenant"
        unit_of_work.commit()

    with Session(migrated_engine) as verification_session:
        verified = verification_session.get(Tenant, tenant_id)
        assert verified is not None
        assert verified.display_name == "Updated Tenant"


def test_context_exit_after_commit_does_not_rollback(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    slug = _slug("committed")

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.session.add(_tenant(slug))
        unit_of_work.commit()

    assert _tenant_by_slug(migrated_engine, slug) is not None


def test_exit_without_commit_rolls_back_insert(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    slug = _slug("rollback-insert")

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.session.add(_tenant(slug))

    assert _tenant_by_slug(migrated_engine, slug) is None
    assert session_factory.sessions[0].closed_by_unit_of_work is True


def test_exit_without_commit_rolls_back_update(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    tenant_id, _ = _insert_tenant(migrated_engine, _slug("rollback-update"))

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        loaded = unit_of_work.session.get(Tenant, tenant_id)
        assert loaded is not None
        loaded.display_name = "Rolled Back"

    with Session(migrated_engine) as verification_session:
        verified = verification_session.get(Tenant, tenant_id)
        assert verified is not None
        assert verified.display_name != "Rolled Back"


def test_exit_without_commit_rolls_back_delete(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    tenant_id, tenant_slug = _insert_tenant(migrated_engine, _slug("rollback-delete"))

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        loaded = unit_of_work.session.get(Tenant, tenant_id)
        assert loaded is not None
        unit_of_work.session.delete(loaded)

    assert _tenant_by_slug(migrated_engine, tenant_slug) is not None


def test_exit_without_commit_rolls_back_explicitly_flushed_row(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    slug = _slug("rollback-flush")

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.session.add(_tenant(slug))
        unit_of_work.session.flush()

    assert _tenant_by_slug(migrated_engine, slug) is None


def test_exception_triggers_rollback_propagates_and_closes_session(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    class ExpectedError(RuntimeError):
        pass

    slug = _slug("exception")
    expected = ExpectedError("expected")

    with pytest.raises(ExpectedError) as exc_info:
        with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.session.add(_tenant(slug))
            unit_of_work.session.flush()
            raise expected

    assert exc_info.value is expected
    assert _tenant_by_slug(migrated_engine, slug) is None
    assert session_factory.sessions[0].closed_by_unit_of_work is True


def test_explicit_rollback_removes_pending_work_and_exit_is_safe(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    slug = _slug("explicit-rollback")

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.session.add(_tenant(slug))
        unit_of_work.session.flush()
        unit_of_work.rollback()
        unit_of_work.rollback()
        with pytest.raises(UnitOfWorkStateError):
            unit_of_work.commit()

    assert _tenant_by_slug(migrated_engine, slug) is None
    assert session_factory.sessions[0].closed_by_unit_of_work is True


def test_failed_flush_marks_unit_of_work_failed_and_cleans_up(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    slug = _slug("failed-flush")
    _insert_tenant(migrated_engine, slug)

    unit_of_work = SQLAlchemyUnitOfWork(session_factory)
    with unit_of_work:
        unit_of_work.session.add(_tenant(slug))
        with pytest.raises(IntegrityError):
            unit_of_work.session.flush()
        with pytest.raises(UnitOfWorkStateError):
            unit_of_work.commit()

    assert session_factory.sessions[0].closed_by_unit_of_work is True
    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.session

    replacement_slug = _slug("after-failed-flush")
    with SQLAlchemyUnitOfWork(session_factory) as replacement:
        replacement.session.add(_tenant(replacement_slug))
        replacement.commit()

    assert _tenant_by_slug(migrated_engine, replacement_slug) is not None


def test_failed_commit_raises_original_error_allows_cleanup_rollback(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    slug = _slug("failed-commit")
    _insert_tenant(migrated_engine, slug)

    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.session.add(_tenant(slug))
        with pytest.raises(IntegrityError):
            unit_of_work.commit()
        unit_of_work.rollback()
        with pytest.raises(UnitOfWorkStateError):
            unit_of_work.commit()

    assert session_factory.sessions[0].closed_by_unit_of_work is True
    assert _tenant_count(migrated_engine, slug) == 1


def test_lifecycle_operations_require_active_single_use_context(
    session_factory: CountingSessionFactory,
) -> None:
    unit_of_work = SQLAlchemyUnitOfWork(session_factory)

    with pytest.raises(UnitOfWorkNotActiveError):
        _ = unit_of_work.session
    with pytest.raises(UnitOfWorkNotActiveError):
        unit_of_work.commit()
    with pytest.raises(UnitOfWorkNotActiveError):
        unit_of_work.rollback()

    with unit_of_work:
        with pytest.raises(UnitOfWorkStateError):
            unit_of_work.__enter__()

    with pytest.raises(UnitOfWorkStateError):
        unit_of_work.__enter__()


def test_second_commit_and_rollback_after_commit_are_rejected(
    session_factory: CountingSessionFactory,
) -> None:
    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.commit()
        with pytest.raises(UnitOfWorkStateError):
            unit_of_work.commit()
        with pytest.raises(UnitOfWorkStateError):
            unit_of_work.rollback()
        with pytest.raises(UnitOfWorkNotActiveError):
            _ = unit_of_work.session


def test_each_unit_of_work_gets_distinct_session_and_identity_map(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    tenant_id, _ = _insert_tenant(migrated_engine, _slug("identity"))

    with SQLAlchemyUnitOfWork(session_factory) as first:
        with SQLAlchemyUnitOfWork(session_factory) as second:
            first_session = first.session
            second_session = second.session
            assert first_session is first.session
            assert first_session is not second_session
            assert first_session.get(Tenant, tenant_id) is not second_session.get(
                Tenant, tenant_id
            )

    assert session_factory.calls == 2


def test_closing_one_unit_of_work_does_not_close_another(
    migrated_engine: Engine,
    session_factory: CountingSessionFactory,
) -> None:
    first = SQLAlchemyUnitOfWork(session_factory)
    second = SQLAlchemyUnitOfWork(session_factory)
    first.__enter__()
    second.__enter__()
    try:
        second_session = second.session
        first.__exit__(None, None, None)

        assert session_factory.sessions[0].closed_by_unit_of_work is True
        assert second_session.closed_by_unit_of_work is False
        assert second_session.execute(select(Tenant.id)).all() == []
    finally:
        second.__exit__(None, None, None)

    with migrated_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


def test_injected_factory_is_called_once_per_unit_of_work(
    session_factory: CountingSessionFactory,
) -> None:
    with SQLAlchemyUnitOfWork(session_factory) as unit_of_work:
        assert unit_of_work.session is unit_of_work.session

    assert session_factory.calls == 1
    assert len(session_factory.sessions) == 1


def test_existing_session_helpers_remain_compatible(migrated_engine: Engine) -> None:
    slug = _slug("transaction-session")

    session_generator = get_session()
    yielded_session = next(session_generator)
    try:
        assert isinstance(yielded_session, Session)
    finally:
        session_generator.close()

    with transaction_session() as session:
        session.add(_tenant(slug))

    assert _tenant_by_slug(migrated_engine, slug) is not None
