from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.application.commands import TransitionResourceStateCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import (
    GetResourceDetailsHandler,
    TransitionResourceStateHandler,
)
from app.application.queries import GetResourceDetailsQuery
from app.application.results import ResourceStateTransitionedResult
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
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


class TrackableCurrentState:
    def __init__(
        self,
        events: list[str],
        *,
        state_id: UUID | None = None,
        lifecycle_status_id: UUID,
        criticality_id: UUID,
        exposure_level_id: UUID,
        source_priority: int = 100,
        confidence_score: Decimal = Decimal("0.9000"),
        valid_from: datetime,
        source: str | None = "collector",
    ) -> None:
        self.events = events
        self.id = state_id or uuid4()
        self.lifecycle_status_id = lifecycle_status_id
        self.criticality_id = criticality_id
        self.exposure_level_id = exposure_level_id
        self.source_priority = source_priority
        self.confidence_score = confidence_score
        self.valid_from = valid_from
        self._valid_to: datetime | None = None
        self.source = source

    @property
    def valid_to(self) -> datetime | None:
        return self._valid_to

    @valid_to.setter
    def valid_to(self, value: datetime | None) -> None:
        self.events.append("current_state.close")
        self._valid_to = value


class FakeResourceRepository:
    def __init__(
        self,
        events: list[str],
        resources: dict[tuple[UUID, UUID], object],
    ) -> None:
        self._events = events
        self._resources = resources

    def get_for_update(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append("resources.get_for_update")
        return self._resources.get((tenant_id, resource_id))


class FakeCatalogRepository:
    def __init__(
        self,
        events: list[str],
        event_name: str,
        catalogs: dict[UUID, object],
    ) -> None:
        self._events = events
        self._event_name = event_name
        self._catalogs = catalogs

    def get_by_id(self, catalog_id: UUID) -> object | None:
        self._events.append(self._event_name)
        return self._catalogs.get(catalog_id)


class FakeResourceStateRepository:
    def __init__(
        self,
        events: list[str],
        current_state: TrackableCurrentState | None,
        *,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._current_state = current_state
        self._fail_on_add = fail_on_add
        self.added: list[ResourceState] = []
        self.flushes = 0

    def get_current(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append("resource_states.get_current")
        return self._current_state

    def add(self, state: ResourceState) -> None:
        self._events.append("resource_states.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(state)

    def flush(self) -> None:
        self._events.append("resource_states.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        resource_id: UUID,
        lifecycle_status: object,
        criticality: object,
        exposure_level: object,
        current_state: TrackableCurrentState | None,
        resource_exists: bool = True,
        fail_on_add: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self._fail_on_commit = fail_on_commit
        self.resource = SimpleNamespace(
            id=resource_id,
            tenant_id=tenant_id,
            lifecycle_status_id=uuid4(),
            criticality_id=uuid4(),
            exposure_level_id=uuid4(),
            source_priority=10,
            confidence_score=Decimal("0.1000"),
            last_seen_at=_now(-20),
        )
        self.resources = FakeResourceRepository(
            self.events,
            {(tenant_id, resource_id): self.resource} if resource_exists else {},
        )
        self.lifecycle_statuses = FakeCatalogRepository(
            self.events,
            "lifecycle_statuses.get_by_id",
            {lifecycle_status.id: lifecycle_status},
        )
        self.criticalities = FakeCatalogRepository(
            self.events,
            "criticalities.get_by_id",
            {criticality.id: criticality},
        )
        self.exposure_levels = FakeCatalogRepository(
            self.events,
            "exposure_levels.get_by_id",
            {exposure_level.id: exposure_level},
        )
        self.resource_states = FakeResourceStateRepository(
            self.events,
            current_state,
            fail_on_add=fail_on_add,
        )

    def __enter__(self) -> FakeUnitOfWork:
        self.events.append("enter")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        self.exited = True
        self.events.append("exit")
        return False

    def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1
        if self._fail_on_commit:
            raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1


class FakeUnitOfWorkFactory:
    def __init__(self, *units_of_work: FakeUnitOfWork) -> None:
        self._units_of_work = list(units_of_work)
        self.created: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        uow = self._units_of_work.pop(0)
        self.created.append(uow)
        return uow


def _now(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _catalog(active: bool = True) -> object:
    return SimpleNamespace(id=uuid4(), is_active=active)


def _command(
    *,
    tenant_id: UUID | None = None,
    resource_id: UUID | None = None,
    lifecycle_status_id: UUID | None = None,
    criticality_id: UUID | None = None,
    exposure_level_id: UUID | None = None,
    source_priority: int = 100,
    confidence_score: Decimal = Decimal("0.9000"),
    transitioned_at: datetime | None = None,
    source: str | None = "collector",
) -> TransitionResourceStateCommand:
    return TransitionResourceStateCommand(
        tenant_id=tenant_id or uuid4(),
        resource_id=resource_id or uuid4(),
        lifecycle_status_id=lifecycle_status_id or uuid4(),
        criticality_id=criticality_id or uuid4(),
        exposure_level_id=exposure_level_id or uuid4(),
        source_priority=source_priority,
        confidence_score=confidence_score,
        transitioned_at=transitioned_at or _now(),
        source=source,
    )


def _uow_for_command(
    command: TransitionResourceStateCommand,
    *,
    current_state: TrackableCurrentState | None = None,
    lifecycle_active: bool = True,
    criticality_active: bool = True,
    exposure_active: bool = True,
    resource_exists: bool = True,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        lifecycle_status=SimpleNamespace(
            id=command.lifecycle_status_id,
            is_active=lifecycle_active,
        ),
        criticality=SimpleNamespace(
            id=command.criticality_id,
            is_active=criticality_active,
        ),
        exposure_level=SimpleNamespace(
            id=command.exposure_level_id,
            is_active=exposure_active,
        ),
        current_state=current_state,
        resource_exists=resource_exists,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def _current_for_command(
    events: list[str],
    command: TransitionResourceStateCommand,
    *,
    valid_from: datetime | None = None,
) -> TrackableCurrentState:
    return TrackableCurrentState(
        events,
        lifecycle_status_id=command.lifecycle_status_id,
        criticality_id=command.criticality_id,
        exposure_level_id=command.exposure_level_id,
        source_priority=command.source_priority,
        confidence_score=command.confidence_score,
        valid_from=valid_from or _now(-10),
        source=command.source,
    )


def test_transition_resource_state_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "resource_id",
        "lifecycle_status_id",
        "criticality_id",
        "exposure_level_id",
        "source_priority",
        "confidence_score",
        "transitioned_at",
        "source",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.source_priority = 200


def test_resource_state_transitioned_result_is_immutable_and_entity_free() -> None:
    result = ResourceStateTransitionedResult(
        resource_id=uuid4(),
        previous_state_id=None,
        new_state_id=uuid4(),
        transitioned_at=_now(),
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceState)
    with pytest.raises(FrozenInstanceError):
        result.previous_state_id = uuid4()


@pytest.mark.parametrize(
    ("command", "expected_fields"),
    (
        (_command(source_priority=-1), ("source_priority",)),
        (_command(source_priority=1001), ("source_priority",)),
        (_command(confidence_score=Decimal("-0.0001")), ("confidence_score",)),
        (_command(confidence_score=Decimal("1.0001")), ("confidence_score",)),
        (
            _command(transitioned_at=datetime(2026, 1, 1)),
            ("transitioned_at",),
        ),
        (_command(source=""), ("source",)),
        (_command(source="   "), ("source",)),
    ),
)
def test_pre_uow_validation_failures_do_not_create_unit_of_work(
    command: TransitionResourceStateCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_missing_resource_stops_before_catalog_and_state_reads() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert uow.events == ["enter", "resources.get_for_update", "exit"]
    assert uow.resource_states.added == []
    assert uow.commits == 0


def test_wrong_tenant_matches_resource_not_found_behavior() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert "resource_states.get_current" not in uow.events
    assert uow.commits == 0


@pytest.mark.parametrize(
    ("catalog_name", "event_name", "entity_type"),
    (
        ("lifecycle_statuses", "lifecycle_statuses.get_by_id", "LifecycleStatus"),
        ("criticalities", "criticalities.get_by_id", "Criticality"),
        ("exposure_levels", "exposure_levels.get_by_id", "ExposureLevel"),
    ),
)
def test_missing_catalog_stops_before_state_mutation(
    catalog_name: str,
    event_name: str,
    entity_type: str,
) -> None:
    command = _command()
    uow = _uow_for_command(command)
    getattr(uow, catalog_name)._catalogs.clear()
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == entity_type
    assert event_name in uow.events
    assert "current_state.close" not in uow.events
    assert "resource_states.add" not in uow.events
    assert uow.commits == 0


@pytest.mark.parametrize(
    "flag",
    ("lifecycle_active", "criticality_active", "exposure_active"),
)
def test_inactive_catalog_stops_before_state_mutation(flag: str) -> None:
    command = _command()
    uow = _uow_for_command(command, **{flag: False})
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError):
        handler.handle(command)

    assert "current_state.close" not in uow.events
    assert "resource_states.add" not in uow.events
    assert uow.commits == 0


def test_first_state_creation_adds_one_current_state_and_commits_last() -> None:
    command = _command(source=None)
    uow = _uow_for_command(command, current_state=None)
    original_last_seen_at = uow.resource.last_seen_at
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.previous_state_id is None
    assert result.new_state_id == uow.resource_states.added[0].id
    assert result.transitioned_at == command.transitioned_at
    assert len(uow.resource_states.added) == 1
    new_state = uow.resource_states.added[0]
    assert new_state.tenant_id == command.tenant_id
    assert new_state.resource_id == command.resource_id
    assert new_state.valid_from == command.transitioned_at
    assert new_state.valid_to is None
    assert new_state.source is None
    assert uow.resource.lifecycle_status_id == command.lifecycle_status_id
    assert uow.resource.criticality_id == command.criticality_id
    assert uow.resource.exposure_level_id == command.exposure_level_id
    assert uow.resource.source_priority == command.source_priority
    assert uow.resource.confidence_score == command.confidence_score
    assert uow.resource.last_seen_at == original_last_seen_at
    assert uow.commits == 1
    assert uow.resource_states.flushes == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "lifecycle_statuses.get_by_id",
        "criticalities.get_by_id",
        "exposure_levels.get_by_id",
        "resource_states.get_current",
        "resource_states.add",
        "commit",
        "exit",
    ]


def test_existing_state_transition_closes_current_and_adds_replacement() -> None:
    command = _command(source_priority=200, source="manual")
    current = TrackableCurrentState(
        [],
        lifecycle_status_id=uuid4(),
        criticality_id=uuid4(),
        exposure_level_id=uuid4(),
        source_priority=50,
        confidence_score=Decimal("0.5000"),
        valid_from=_now(-10),
        source="collector",
    )
    uow = _uow_for_command(command, current_state=current)
    current.events = uow.events
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.previous_state_id == current.id
    assert result.new_state_id == uow.resource_states.added[0].id
    assert current.valid_to == command.transitioned_at
    assert current.valid_from < current.valid_to
    assert current.source_priority == 50
    replacement = uow.resource_states.added[0]
    assert replacement.valid_from == command.transitioned_at
    assert replacement.valid_to is None
    assert replacement.source_priority == command.source_priority
    assert uow.commits == 1
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "lifecycle_statuses.get_by_id",
        "criticalities.get_by_id",
        "exposure_levels.get_by_id",
        "resource_states.get_current",
        "current_state.close",
        "resource_states.add",
        "commit",
        "exit",
    ]


@pytest.mark.parametrize("minutes", (-20, -10))
def test_temporal_ordering_rejects_earlier_or_equal_transition(minutes: int) -> None:
    command = _command(transitioned_at=_now(minutes))
    current = TrackableCurrentState(
        [],
        lifecycle_status_id=uuid4(),
        criticality_id=uuid4(),
        exposure_level_id=uuid4(),
        valid_from=_now(-10),
    )
    uow = _uow_for_command(command, current_state=current)
    current.events = uow.events
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert exc_info.value.failures[0].field == "transitioned_at"
    assert current.valid_to is None
    assert uow.resource_states.added == []
    assert uow.commits == 0


def test_no_op_transition_is_rejected_without_mutation() -> None:
    command = _command()
    current = _current_for_command([], command, valid_from=_now(-10))
    uow = _uow_for_command(command, current_state=current)
    current.events = uow.events
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceState"
    assert exc_info.value.conflict_field == "state"
    assert current.valid_to is None
    assert uow.resource_states.added == []
    assert uow.commits == 0


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command(source_priority=250)
    current = TrackableCurrentState(
        [],
        lifecycle_status_id=uuid4(),
        criticality_id=uuid4(),
        exposure_level_id=uuid4(),
        valid_from=_now(-10),
    )
    failing_uow = _uow_for_command(command, current_state=current, fail_on_add=True)
    current.events = failing_uow.events
    succeeding_uow = _uow_for_command(command, current_state=None)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = TransitionResourceStateHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.new_state_id == succeeding_uow.resource_states.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, current_state=None, fail_on_commit=True)
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(RuntimeError, match="commit failed"):
        handler.handle(command)

    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.exited is True
    assert uow.events[-2:] == ["commit", "exit"]


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _catalog_id(session: Session, model_type: type[object], code: str) -> UUID:
    entity_id = session.scalar(select(model_type.id).where(model_type.code == code))
    assert entity_id is not None
    return entity_id


def _seed_resource(session: Session) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    resource_type_id = _catalog_id(session, ResourceType, "domain")
    lifecycle_status_id = _catalog_id(session, LifecycleStatus, "active")
    criticality_id = _catalog_id(session, Criticality, "medium")
    exposure_level_id = _catalog_id(session, ExposureLevel, "public")
    resource = Resource(
        tenant_id=tenant.id,
        resource_type_id=resource_type_id,
        canonical_name=_slug("resource"),
        display_name="Resource",
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=_now(-30),
        last_seen_at=_now(-20),
    )
    session.add(resource)
    session.flush()
    return (
        tenant.id,
        resource.id,
        lifecycle_status_id,
        criticality_id,
        exposure_level_id,
        resource_type_id,
    )


def _current_state_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceState)
            .where(
                ResourceState.tenant_id == tenant_id,
                ResourceState.resource_id == resource_id,
                ResourceState.valid_to.is_(None),
            )
        )
        or 0
    )


def test_sqlalchemy_first_state_transition_persists_and_reads_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, lifecycle_id, criticality_id, exposure_id, _ = (
            _seed_resource(setup_session)
        )
        resource = setup_session.get(Resource, resource_id)
        assert resource is not None
        original_last_seen_at = resource.last_seen_at
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        lifecycle_status_id=lifecycle_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_id,
        transitioned_at=_now(-5),
        source="manual",
    )
    handler = TransitionResourceStateHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    assert result.previous_state_id is None
    with SessionLocal() as verification:
        state = verification.get(ResourceState, result.new_state_id)
        resource = verification.get(Resource, resource_id)
        assert state is not None
        assert state.valid_from == command.transitioned_at
        assert state.valid_to is None
        assert state.source == command.source
        assert resource is not None
        assert resource.lifecycle_status_id == command.lifecycle_status_id
        assert resource.criticality_id == command.criticality_id
        assert resource.exposure_level_id == command.exposure_level_id
        assert resource.source_priority == command.source_priority
        assert resource.confidence_score == command.confidence_score
        assert resource.last_seen_at == original_last_seen_at
        assert _current_state_count(verification, tenant_id, resource_id) == 1

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, resource_id)
    )
    assert details.state is not None
    assert details.state.id == result.new_state_id


def test_sqlalchemy_existing_state_transition_preserves_history(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, lifecycle_id, criticality_id, exposure_id, _ = (
            _seed_resource(setup_session)
        )
        current = ResourceState(
            tenant_id=tenant_id,
            resource_id=resource_id,
            lifecycle_status_id=lifecycle_id,
            criticality_id=criticality_id,
            exposure_level_id=exposure_id,
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-10),
            source="collector",
        )
        setup_session.add(current)
        setup_session.commit()
        previous_state_id = current.id
        previous_valid_from = current.valid_from
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        lifecycle_status_id=lifecycle_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_id,
        source_priority=200,
        confidence_score=Decimal("0.8000"),
        transitioned_at=_now(-5),
        source="manual",
    )
    handler = TransitionResourceStateHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    assert result.previous_state_id == previous_state_id
    with SessionLocal() as verification:
        history = list(
            verification.scalars(
                select(ResourceState)
                .where(
                    ResourceState.tenant_id == tenant_id,
                    ResourceState.resource_id == resource_id,
                )
                .order_by(ResourceState.valid_from, ResourceState.id)
            )
        )
        assert len(history) == 2
        assert history[0].id == previous_state_id
        assert history[0].valid_from == previous_valid_from
        assert history[0].valid_to == command.transitioned_at
        assert history[0].source == "collector"
        assert history[1].id == result.new_state_id
        assert history[1].valid_to is None
        assert history[1].source_priority == command.source_priority
        assert _current_state_count(verification, tenant_id, resource_id) == 1


def test_sqlalchemy_wrong_tenant_leaves_state_unchanged(migrated_engine: Engine) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, lifecycle_id, criticality_id, exposure_id, _ = (
            _seed_resource(setup_session)
        )
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        state = ResourceState(
            tenant_id=tenant_id,
            resource_id=resource_id,
            lifecycle_status_id=lifecycle_id,
            criticality_id=criticality_id,
            exposure_level_id=exposure_id,
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-10),
            source="collector",
        )
        setup_session.add_all([other_tenant, state])
        setup_session.commit()
        state_id = state.id
        other_tenant_id = other_tenant.id
    handler = TransitionResourceStateHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError):
        handler.handle(
            _command(
                tenant_id=other_tenant_id,
                resource_id=resource_id,
                lifecycle_status_id=lifecycle_id,
                criticality_id=criticality_id,
                exposure_level_id=exposure_id,
            )
        )

    with SessionLocal() as verification:
        state = verification.get(ResourceState, state_id)
        assert state is not None
        assert state.valid_to is None
        assert _current_state_count(verification, tenant_id, resource_id) == 1


def test_sqlalchemy_catalog_failure_leaves_original_current_state(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, lifecycle_id, criticality_id, exposure_id, _ = (
            _seed_resource(setup_session)
        )
        state = ResourceState(
            tenant_id=tenant_id,
            resource_id=resource_id,
            lifecycle_status_id=lifecycle_id,
            criticality_id=criticality_id,
            exposure_level_id=exposure_id,
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-10),
            source="collector",
        )
        setup_session.add(state)
        setup_session.commit()
        state_id = state.id
    handler = TransitionResourceStateHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError):
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                lifecycle_status_id=uuid4(),
                criticality_id=criticality_id,
                exposure_level_id=exposure_id,
                source_priority=200,
            )
        )

    with SessionLocal() as verification:
        state = verification.get(ResourceState, state_id)
        assert state is not None
        assert state.valid_to is None
        assert _current_state_count(verification, tenant_id, resource_id) == 1


def test_sqlalchemy_temporal_failure_leaves_original_current_state(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, lifecycle_id, criticality_id, exposure_id, _ = (
            _seed_resource(setup_session)
        )
        state = ResourceState(
            tenant_id=tenant_id,
            resource_id=resource_id,
            lifecycle_status_id=lifecycle_id,
            criticality_id=criticality_id,
            exposure_level_id=exposure_id,
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-10),
            source="collector",
        )
        setup_session.add(state)
        setup_session.commit()
        state_id = state.id
        valid_from = state.valid_from
    handler = TransitionResourceStateHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(ValidationError):
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                lifecycle_status_id=lifecycle_id,
                criticality_id=criticality_id,
                exposure_level_id=exposure_id,
                transitioned_at=valid_from,
                source_priority=200,
            )
        )

    with SessionLocal() as verification:
        state = verification.get(ResourceState, state_id)
        assert state is not None
        assert state.valid_to is None
        assert _current_state_count(verification, tenant_id, resource_id) == 1


def test_sqlalchemy_constraint_failure_rolls_back_partial_transition(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, lifecycle_id, criticality_id, exposure_id, _ = (
            _seed_resource(setup_session)
        )
        setup_session.commit()
    with pytest.raises(IntegrityError):
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            resource = uow.resources.get_for_update(tenant_id, resource_id)
            assert resource is not None
            first = ResourceState(
                tenant_id=tenant_id,
                resource_id=resource_id,
                lifecycle_status_id=lifecycle_id,
                criticality_id=criticality_id,
                exposure_level_id=exposure_id,
                source_priority=100,
                confidence_score=Decimal("0.9000"),
                valid_from=_now(-5),
                source="manual",
            )
            second = ResourceState(
                tenant_id=tenant_id,
                resource_id=resource_id,
                lifecycle_status_id=lifecycle_id,
                criticality_id=criticality_id,
                exposure_level_id=exposure_id,
                source_priority=200,
                confidence_score=Decimal("0.8000"),
                valid_from=_now(-4),
                source="manual",
            )
            uow.resource_states.add(first)
            uow.resource_states.add(second)
            uow.commit()

    with SessionLocal() as verification:
        assert _current_state_count(verification, tenant_id, resource_id) == 0
    handler = TransitionResourceStateHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    result = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            lifecycle_status_id=lifecycle_id,
            criticality_id=criticality_id,
            exposure_level_id=exposure_id,
            source_priority=100,
            transitioned_at=_now(-3),
        )
    )
    assert result.new_state_id is not None


def test_concurrency_locking_uses_resource_for_update_contract() -> None:
    command = _command(source_priority=300)
    current = TrackableCurrentState(
        [],
        lifecycle_status_id=uuid4(),
        criticality_id=uuid4(),
        exposure_level_id=uuid4(),
        valid_from=_now(-10),
    )
    uow = _uow_for_command(command, current_state=current)
    current.events = uow.events
    handler = TransitionResourceStateHandler(FakeUnitOfWorkFactory(uow))

    handler.handle(command)

    assert uow.events.index("resources.get_for_update") < uow.events.index(
        "resource_states.get_current"
    )
    assert "resources.get_by_id" not in uow.events
