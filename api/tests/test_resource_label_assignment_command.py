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

from app.application.commands import AssignResourceLabelCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import AssignResourceLabelHandler, GetResourceDetailsHandler
from app.application.queries import GetResourceDetailsQuery
from app.application.results import ResourceLabelAssignedResult
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
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


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


class FakeLabelRepository:
    def __init__(
        self,
        events: list[str],
        labels: dict[tuple[UUID, UUID], object],
    ) -> None:
        self._events = events
        self._labels = labels

    def get_by_id(self, tenant_id: UUID, label_id: UUID) -> object | None:
        self._events.append("labels.get_by_id")
        return self._labels.get((tenant_id, label_id))


class FakeResourceLabelRepository:
    def __init__(
        self,
        events: list[str],
        *,
        current: ResourceLabel | object | None = None,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._current = current
        self._fail_on_add = fail_on_add
        self.added: list[ResourceLabel] = []
        self.flushes = 0

    def find_current(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        label_id: UUID,
    ) -> ResourceLabel | object | None:
        self._events.append("resource_labels.find_current")
        return self._current

    def add(self, resource_label: ResourceLabel) -> None:
        self._events.append("resource_labels.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(resource_label)

    def flush(self) -> None:
        self._events.append("resource_labels.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        resource_id: UUID,
        label_id: UUID,
        resource_exists: bool = True,
        label_exists: bool = True,
        label_active: bool = True,
        current: ResourceLabel | object | None = None,
        fail_on_add: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self._fail_on_commit = fail_on_commit
        self.resource = SimpleNamespace(id=resource_id, tenant_id=tenant_id)
        self.label = SimpleNamespace(
            id=label_id,
            tenant_id=tenant_id,
            is_active=label_active,
        )
        self.resources = FakeResourceRepository(
            self.events,
            {(tenant_id, resource_id): self.resource} if resource_exists else {},
        )
        self.labels = FakeLabelRepository(
            self.events,
            {(tenant_id, label_id): self.label} if label_exists else {},
        )
        self.resource_labels = FakeResourceLabelRepository(
            self.events,
            current=current,
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


def _command(
    *,
    tenant_id: UUID | None = None,
    resource_id: UUID | None = None,
    label_id: UUID | None = None,
    valid_from: datetime | None = None,
    source: str | None = "manual",
) -> AssignResourceLabelCommand:
    return AssignResourceLabelCommand(
        tenant_id=tenant_id or uuid4(),
        resource_id=resource_id or uuid4(),
        label_id=label_id or uuid4(),
        valid_from=valid_from or _now(),
        source=source,
    )


def _uow_for_command(
    command: AssignResourceLabelCommand,
    *,
    resource_exists: bool = True,
    label_exists: bool = True,
    label_active: bool = True,
    current: ResourceLabel | object | None = None,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        label_id=command.label_id,
        resource_exists=resource_exists,
        label_exists=label_exists,
        label_active=label_active,
        current=current,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def _current_label_for_command(
    command: AssignResourceLabelCommand,
    *,
    valid_to: datetime | None = None,
) -> ResourceLabel:
    return ResourceLabel(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        label_id=command.label_id,
        valid_from=_now(-10),
        valid_to=valid_to,
        source=command.source,
    )


def test_assign_resource_label_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "resource_id",
        "label_id",
        "valid_from",
        "source",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.label_id = uuid4()


def test_resource_label_assigned_result_is_immutable_and_entity_free() -> None:
    result = ResourceLabelAssignedResult(
        resource_id=uuid4(),
        resource_label_id=uuid4(),
        label_id=uuid4(),
        valid_from=_now(),
        source="manual",
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceLabel)
    with pytest.raises(FrozenInstanceError):
        result.label_id = uuid4()


@pytest.mark.parametrize(
    ("command", "expected_fields"),
    (
        (_command(valid_from=datetime(2026, 1, 1)), ("valid_from",)),
        (_command(source=""), ("source",)),
        (_command(source="   "), ("source",)),
    ),
)
def test_pre_uow_validation_failures_do_not_create_unit_of_work(
    command: AssignResourceLabelCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_pre_uow_validation_gathers_deterministic_failures() -> None:
    command = _command(valid_from=datetime(2026, 1, 1), source=" ")
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "valid_from",
        "source",
    )


def test_missing_resource_stops_before_label_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == command.resource_id
    assert uow.events == ["enter", "resources.get_for_update", "exit"]
    assert uow.resource_labels.added == []
    assert uow.commits == 0


def test_wrong_tenant_resource_matches_not_found_behavior() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert "labels.get_by_id" not in uow.events
    assert "resource_labels.find_current" not in uow.events
    assert uow.commits == 0


def test_missing_label_stops_before_assignment_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, label_exists=False)
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Label"
    assert exc_info.value.lookup_field == "label_id"
    assert exc_info.value.lookup_value == command.label_id
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "labels.get_by_id",
        "exit",
    ]
    assert uow.resource_labels.added == []
    assert uow.commits == 0


def test_inactive_label_stops_before_assignment_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, label_active=False)
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Label"
    assert exc_info.value.conflict_field == "label_id"
    assert exc_info.value.conflict_value == command.label_id
    assert "resource_labels.find_current" not in uow.events
    assert uow.resource_labels.added == []
    assert uow.commits == 0


def test_successful_assignment_adds_one_label_and_commits_last() -> None:
    command = _command(source=None)
    uow = _uow_for_command(command)
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.resource_id == command.resource_id
    assert result.resource_label_id == uow.resource_labels.added[0].id
    assert result.label_id == command.label_id
    assert result.valid_from == command.valid_from
    assert result.source is None
    assert len(uow.resource_labels.added) == 1
    resource_label = uow.resource_labels.added[0]
    assert resource_label.tenant_id == command.tenant_id
    assert resource_label.resource_id == command.resource_id
    assert resource_label.label_id == command.label_id
    assert resource_label.valid_from == command.valid_from
    assert resource_label.valid_to is None
    assert resource_label.source is None
    assert uow.resource_labels.flushes == 0
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "labels.get_by_id",
        "resource_labels.find_current",
        "resource_labels.add",
        "commit",
        "exit",
    ]


def test_duplicate_current_label_is_rejected_before_mutation() -> None:
    command = _command()
    current = _current_label_for_command(command)
    uow = _uow_for_command(command, current=current)
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceLabel"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.conflict_value == command.label_id
    assert uow.resource_labels.added == []
    assert uow.commits == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "labels.get_by_id",
        "resource_labels.find_current",
        "exit",
    ]


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = AssignResourceLabelHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.resource_label_id == succeeding_uow.resource_labels.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = AssignResourceLabelHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_resource_and_label(session: Session) -> tuple[UUID, UUID, UUID]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    resource = _resource(session, tenant.id, _slug("resource"))
    label = _label(tenant.id)
    session.add_all([resource, label])
    session.flush()
    return tenant.id, resource.id, label.id


def _resource(session: Session, tenant_id: UUID, canonical_name: str) -> Resource:
    now = _now(-30)
    return Resource(
        tenant_id=tenant_id,
        resource_type_id=_catalog_id(session, ResourceType, "domain"),
        canonical_name=canonical_name,
        display_name=canonical_name,
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )


def _label(
    tenant_id: UUID,
    *,
    key: str | None = None,
    value: str | None = None,
    is_active: bool = True,
) -> Label:
    return Label(
        tenant_id=tenant_id,
        key=key or _slug("label"),
        value=value or "Production",
        is_active=is_active,
    )


def _label_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceLabel)
            .where(
                ResourceLabel.tenant_id == tenant_id,
                ResourceLabel.resource_id == resource_id,
            )
        )
        or 0
    )


def _current_label_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceLabel)
            .where(
                ResourceLabel.tenant_id == tenant_id,
                ResourceLabel.resource_id == resource_id,
                ResourceLabel.valid_to.is_(None),
            )
        )
        or 0
    )


def test_sqlalchemy_assignment_persists_and_reads_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, label_id = _seed_resource_and_label(setup_session)
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        label_id=label_id,
        valid_from=_now(-5),
        source="manual",
    )
    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    assert result.resource_id == resource_id
    with SessionLocal() as verification:
        resource_label = verification.get(ResourceLabel, result.resource_label_id)
        assert resource_label is not None
        assert resource_label.tenant_id == tenant_id
        assert resource_label.resource_id == resource_id
        assert resource_label.label_id == label_id
        assert resource_label.valid_from == command.valid_from
        assert resource_label.valid_to is None
        assert resource_label.source == "manual"
        assert _current_label_count(verification, tenant_id, resource_id) == 1

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, resource_id)
    )
    assert len(details.labels) == 1
    assert details.labels[0].id == result.resource_label_id
    assert details.labels[0].label_id == label_id
    assert details.labels[0].valid_from == command.valid_from
    assert details.labels[0].source == "manual"


def test_sqlalchemy_wrong_tenant_label_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, _ = _seed_resource_and_label(setup_session)
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.flush()
        other_label = _label(other_tenant.id)
        setup_session.add(other_label)
        setup_session.commit()
        other_label_id = other_label.id
    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                label_id=other_label_id,
            )
        )

    assert exc_info.value.entity_type == "Label"
    with SessionLocal() as verification:
        assert _label_count(verification, tenant_id, resource_id) == 0


def test_sqlalchemy_inactive_label_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, label_id = _seed_resource_and_label(setup_session)
        label = setup_session.get(Label, label_id)
        assert label is not None
        label.is_active = False
        setup_session.commit()
    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                label_id=label_id,
            )
        )

    assert exc_info.value.entity_type == "Label"
    assert exc_info.value.conflict_field == "label_id"
    with SessionLocal() as verification:
        assert _label_count(verification, tenant_id, resource_id) == 0


def test_sqlalchemy_duplicate_current_label_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, label_id = _seed_resource_and_label(setup_session)
        setup_session.commit()
    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    first = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        label_id=label_id,
        valid_from=_now(-10),
    )
    first_result = handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                label_id=label_id,
                valid_from=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceLabel"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.__cause__ is None
    with SessionLocal() as verification:
        assert verification.get(ResourceLabel, first_result.resource_label_id) is not None
        assert _label_count(verification, tenant_id, resource_id) == 1


def test_sqlalchemy_historical_label_is_preserved_when_assigning_new_current(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, label_id = _seed_resource_and_label(setup_session)
        historical = ResourceLabel(
            tenant_id=tenant_id,
            resource_id=resource_id,
            label_id=label_id,
            valid_from=_now(-30),
            valid_to=_now(-20),
            source="legacy",
        )
        setup_session.add(historical)
        setup_session.commit()
        historical_id = historical.id
        historical_valid_from = historical.valid_from
        historical_valid_to = historical.valid_to
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        label_id=label_id,
        valid_from=_now(-5),
    )
    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    with SessionLocal() as verification:
        history = list(
            verification.scalars(
                select(ResourceLabel)
                .where(
                    ResourceLabel.tenant_id == tenant_id,
                    ResourceLabel.resource_id == resource_id,
                )
                .order_by(ResourceLabel.valid_from, ResourceLabel.id)
            )
        )
        assert [row.id for row in history] == [historical_id, result.resource_label_id]
        assert history[0].valid_from == historical_valid_from
        assert history[0].valid_to == historical_valid_to
        assert history[0].source == "legacy"
        assert history[1].valid_to is None
        assert history[1].label_id == label_id


def test_sqlalchemy_multiple_different_labels_on_same_resource_are_allowed(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, first_label_id = _seed_resource_and_label(setup_session)
        second_label = _label(tenant_id, key=_slug("label"), value="Staging")
        setup_session.add(second_label)
        setup_session.commit()
        second_label_id = second_label.id
    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            label_id=first_label_id,
            valid_from=_now(-10),
        )
    )
    second = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            label_id=second_label_id,
            valid_from=_now(-5),
        )
    )

    with SessionLocal() as verification:
        current = list(
            verification.scalars(
                select(ResourceLabel)
                .where(
                    ResourceLabel.tenant_id == tenant_id,
                    ResourceLabel.resource_id == resource_id,
                    ResourceLabel.valid_to.is_(None),
                )
                .order_by(ResourceLabel.label_id, ResourceLabel.id)
            )
        )
        assert {row.id for row in current} == {
            first.resource_label_id,
            second.resource_label_id,
        }


def test_sqlalchemy_same_label_on_different_resources_is_allowed(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, label_id = _seed_resource_and_label(setup_session)
        other_resource = _resource(setup_session, tenant_id, _slug("other-resource"))
        setup_session.add(other_resource)
        setup_session.commit()
        other_resource_id = other_resource.id
    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            label_id=label_id,
            valid_from=_now(-10),
        )
    )
    second = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=other_resource_id,
            label_id=label_id,
            valid_from=_now(-5),
        )
    )

    with SessionLocal() as verification:
        assert verification.get(ResourceLabel, first.resource_label_id) is not None
        assert verification.get(ResourceLabel, second.resource_label_id) is not None


def test_sqlalchemy_persistence_boundary_translates_unchecked_label_conflict(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, label_id = _seed_resource_and_label(setup_session)
        setup_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            resource = uow.resources.get_for_update(tenant_id, resource_id)
            assert resource is not None
            first = ResourceLabel(
                tenant_id=tenant_id,
                resource_id=resource_id,
                label_id=label_id,
                valid_from=_now(-10),
                source="manual",
            )
            second = ResourceLabel(
                tenant_id=tenant_id,
                resource_id=resource_id,
                label_id=label_id,
                valid_from=_now(-5),
                source="manual",
            )
            uow.resource_labels.add(first)
            uow.resource_labels.add(second)
            uow.commit()

    assert exc_info.value.entity_type == "ResourceLabel"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.constraint == "uq_resource_label_current"
    assert isinstance(exc_info.value.__cause__, IntegrityError)
    with SessionLocal() as verification:
        assert _label_count(verification, tenant_id, resource_id) == 0

    handler = AssignResourceLabelHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    fresh_result = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            label_id=label_id,
            valid_from=_now(),
        )
    )
    assert fresh_result.resource_label_id is not None
