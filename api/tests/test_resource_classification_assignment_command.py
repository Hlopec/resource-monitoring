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

from app.application.commands import AssignResourceClassificationCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import (
    AssignResourceClassificationHandler,
    GetResourceDetailsHandler,
)
from app.application.queries import GetResourceDetailsQuery
from app.application.results import ResourceClassificationAssignedResult
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


class FakeClassificationTypeRepository:
    def __init__(
        self,
        events: list[str],
        classification_types: dict[UUID, object],
    ) -> None:
        self._events = events
        self._classification_types = classification_types

    def get_by_id(self, classification_type_id: UUID) -> object | None:
        self._events.append("classification_types.get_by_id")
        return self._classification_types.get(classification_type_id)


class FakeClassificationValueRepository:
    def __init__(
        self,
        events: list[str],
        classification_values: dict[UUID, object],
    ) -> None:
        self._events = events
        self._classification_values = classification_values

    def get_by_id(self, classification_value_id: UUID) -> object | None:
        self._events.append("classification_values.get_by_id")
        return self._classification_values.get(classification_value_id)


class FakeResourceClassificationRepository:
    def __init__(
        self,
        events: list[str],
        *,
        current: ResourceClassification | object | None = None,
        current_primary: ResourceClassification | object | None = None,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._current = current
        self._current_primary = current_primary
        self._fail_on_add = fail_on_add
        self.added: list[ResourceClassification] = []
        self.flushes = 0

    def find_current(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        classification_type_id: UUID,
        classification_value_id: UUID,
    ) -> ResourceClassification | object | None:
        self._events.append("resource_classifications.find_current")
        return self._current

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        classification_type_id: UUID,
    ) -> ResourceClassification | object | None:
        self._events.append("resource_classifications.get_current_primary")
        return self._current_primary

    def add(self, classification: ResourceClassification) -> None:
        self._events.append("resource_classifications.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(classification)

    def flush(self) -> None:
        self._events.append("resource_classifications.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        resource_id: UUID,
        classification_type: object,
        classification_value: object,
        resource_exists: bool = True,
        classification_type_exists: bool = True,
        classification_value_exists: bool = True,
        current: ResourceClassification | object | None = None,
        current_primary: ResourceClassification | object | None = None,
        fail_on_add: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self._fail_on_commit = fail_on_commit
        self.resource = SimpleNamespace(id=resource_id, tenant_id=tenant_id)
        self.resources = FakeResourceRepository(
            self.events,
            {(tenant_id, resource_id): self.resource} if resource_exists else {},
        )
        self.classification_types = FakeClassificationTypeRepository(
            self.events,
            (
                {classification_type.id: classification_type}
                if classification_type_exists
                else {}
            ),
        )
        self.classification_values = FakeClassificationValueRepository(
            self.events,
            (
                {classification_value.id: classification_value}
                if classification_value_exists
                else {}
            ),
        )
        self.resource_classifications = FakeResourceClassificationRepository(
            self.events,
            current=current,
            current_primary=current_primary,
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
    classification_type_id: UUID | None = None,
    classification_value_id: UUID | None = None,
    is_primary: bool = False,
    confidence_score: Decimal = Decimal("0.9000"),
    valid_from: datetime | None = None,
    source: str | None = "manual",
) -> AssignResourceClassificationCommand:
    return AssignResourceClassificationCommand(
        tenant_id=tenant_id or uuid4(),
        resource_id=resource_id or uuid4(),
        classification_type_id=classification_type_id or uuid4(),
        classification_value_id=classification_value_id or uuid4(),
        is_primary=is_primary,
        confidence_score=confidence_score,
        valid_from=valid_from or _now(),
        source=source,
    )


def _uow_for_command(
    command: AssignResourceClassificationCommand,
    *,
    classification_type_active: bool = True,
    classification_value_active: bool = True,
    value_type_id: UUID | None = None,
    resource_exists: bool = True,
    classification_type_exists: bool = True,
    classification_value_exists: bool = True,
    current: ResourceClassification | object | None = None,
    current_primary: ResourceClassification | object | None = None,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    classification_type = SimpleNamespace(
        id=command.classification_type_id,
        is_active=classification_type_active,
    )
    classification_value = SimpleNamespace(
        id=command.classification_value_id,
        classification_type_id=value_type_id or command.classification_type_id,
        is_active=classification_value_active,
    )
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        classification_type=classification_type,
        classification_value=classification_value,
        resource_exists=resource_exists,
        classification_type_exists=classification_type_exists,
        classification_value_exists=classification_value_exists,
        current=current,
        current_primary=current_primary,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def _current_classification_for_command(
    command: AssignResourceClassificationCommand,
    *,
    classification_value_id: UUID | None = None,
    valid_to: datetime | None = None,
) -> ResourceClassification:
    return ResourceClassification(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        classification_type_id=command.classification_type_id,
        classification_value_id=(
            classification_value_id or command.classification_value_id
        ),
        is_primary=command.is_primary,
        confidence_score=command.confidence_score,
        valid_from=_now(-10),
        valid_to=valid_to,
        source=command.source,
    )


def test_assign_resource_classification_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "resource_id",
        "classification_type_id",
        "classification_value_id",
        "is_primary",
        "confidence_score",
        "valid_from",
        "source",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.classification_value_id = uuid4()


def test_resource_classification_assigned_result_is_immutable_and_entity_free() -> None:
    result = ResourceClassificationAssignedResult(
        resource_id=uuid4(),
        classification_id=uuid4(),
        classification_type_id=uuid4(),
        classification_value_id=uuid4(),
        is_primary=True,
        valid_from=_now(),
        source="manual",
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceClassification)
    with pytest.raises(FrozenInstanceError):
        result.classification_value_id = uuid4()


@pytest.mark.parametrize(
    ("command", "expected_fields"),
    (
        (_command(confidence_score=Decimal("-0.0001")), ("confidence_score",)),
        (_command(confidence_score=Decimal("1.0001")), ("confidence_score",)),
        (_command(valid_from=datetime(2026, 1, 1)), ("valid_from",)),
        (_command(source=""), ("source",)),
        (_command(source="   "), ("source",)),
    ),
)
def test_pre_uow_validation_failures_do_not_create_unit_of_work(
    command: AssignResourceClassificationCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_pre_uow_validation_gathers_deterministic_failures() -> None:
    command = _command(
        confidence_score=Decimal("-1"),
        valid_from=datetime(2026, 1, 1),
        source=" ",
    )
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "confidence_score",
        "valid_from",
        "source",
    )


def test_missing_resource_stops_before_classification_type_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == command.resource_id
    assert uow.events == ["enter", "resources.get_for_update", "exit"]
    assert uow.resource_classifications.added == []
    assert uow.commits == 0


def test_wrong_tenant_resource_matches_not_found_behavior() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert "classification_types.get_by_id" not in uow.events
    assert "classification_values.get_by_id" not in uow.events
    assert "resource_classifications.find_current" not in uow.events
    assert uow.commits == 0


def test_missing_classification_type_stops_before_value_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, classification_type_exists=False)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ClassificationType"
    assert exc_info.value.lookup_field == "classification_type_id"
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "classification_types.get_by_id",
        "exit",
    ]
    assert uow.resource_classifications.added == []
    assert uow.commits == 0


def test_inactive_classification_type_stops_before_classification_mutation() -> None:
    command = _command()
    uow = _uow_for_command(command, classification_type_active=False)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ClassificationType"
    assert exc_info.value.conflict_field == "classification_type_id"
    assert "classification_values.get_by_id" not in uow.events
    assert "resource_classifications.find_current" not in uow.events
    assert uow.commits == 0


def test_missing_classification_value_stops_before_classification_mutation() -> None:
    command = _command()
    uow = _uow_for_command(command, classification_value_exists=False)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ClassificationValue"
    assert exc_info.value.lookup_field == "classification_value_id"
    assert "resource_classifications.find_current" not in uow.events
    assert uow.resource_classifications.added == []
    assert uow.commits == 0


def test_inactive_classification_value_stops_before_classification_mutation() -> None:
    command = _command()
    uow = _uow_for_command(command, classification_value_active=False)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ClassificationValue"
    assert exc_info.value.conflict_field == "classification_value_id"
    assert "resource_classifications.find_current" not in uow.events
    assert uow.resource_classifications.added == []
    assert uow.commits == 0


def test_type_value_mismatch_stops_before_classification_reads() -> None:
    command = _command()
    uow = _uow_for_command(command, value_type_id=uuid4())
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ClassificationValue"
    assert exc_info.value.conflict_field == "classification_type_id"
    assert exc_info.value.conflict_value == command.classification_type_id
    assert "resource_classifications.find_current" not in uow.events
    assert uow.resource_classifications.added == []
    assert uow.commits == 0


def test_successful_non_primary_assignment_adds_one_classification_and_commits_last() -> None:
    command = _command(is_primary=False, source=None)
    uow = _uow_for_command(command)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.resource_id == command.resource_id
    assert result.classification_id == uow.resource_classifications.added[0].id
    assert result.classification_type_id == command.classification_type_id
    assert result.classification_value_id == command.classification_value_id
    assert result.is_primary is False
    assert result.valid_from == command.valid_from
    assert result.source is None
    assert len(uow.resource_classifications.added) == 1
    classification = uow.resource_classifications.added[0]
    assert classification.tenant_id == command.tenant_id
    assert classification.resource_id == command.resource_id
    assert classification.classification_type_id == command.classification_type_id
    assert classification.classification_value_id == command.classification_value_id
    assert classification.is_primary is False
    assert classification.confidence_score == command.confidence_score
    assert classification.valid_from == command.valid_from
    assert classification.valid_to is None
    assert classification.source is None
    assert uow.resource_classifications.flushes == 0
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "classification_types.get_by_id",
        "classification_values.get_by_id",
        "resource_classifications.find_current",
        "resource_classifications.add",
        "commit",
        "exit",
    ]


def test_successful_first_primary_assignment_checks_current_primary() -> None:
    command = _command(is_primary=True, source="manual")
    uow = _uow_for_command(command)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.is_primary is True
    assert len(uow.resource_classifications.added) == 1
    assert uow.resource_classifications.added[0].is_primary is True
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "classification_types.get_by_id",
        "classification_values.get_by_id",
        "resource_classifications.find_current",
        "resource_classifications.get_current_primary",
        "resource_classifications.add",
        "commit",
        "exit",
    ]


def test_duplicate_current_classification_is_rejected_before_mutation() -> None:
    command = _command()
    current = _current_classification_for_command(command)
    uow = _uow_for_command(command, current=current)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceClassification"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.conflict_value == command.classification_value_id
    assert uow.resource_classifications.added == []
    assert uow.commits == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "classification_types.get_by_id",
        "classification_values.get_by_id",
        "resource_classifications.find_current",
        "exit",
    ]


def test_existing_current_primary_is_rejected_before_mutation() -> None:
    command = _command(is_primary=True)
    current_primary = _current_classification_for_command(
        command,
        classification_value_id=uuid4(),
    )
    uow = _uow_for_command(command, current_primary=current_primary)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceClassification"
    assert exc_info.value.conflict_field == "current_primary"
    assert exc_info.value.conflict_value == command.classification_type_id
    assert uow.resource_classifications.added == []
    assert uow.commits == 0
    assert "resource_classifications.add" not in uow.events


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = AssignResourceClassificationHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.classification_id == succeeding_uow.resource_classifications.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = AssignResourceClassificationHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_resource_and_classification_catalogs(
    session: Session,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    now = _now(-30)
    resource = Resource(
        tenant_id=tenant.id,
        resource_type_id=_catalog_id(session, ResourceType, "domain"),
        canonical_name=_slug("resource"),
        display_name="Resource",
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(resource)
    session.flush()
    return (
        tenant.id,
        resource.id,
        _catalog_id(session, ClassificationType, "environment"),
        _catalog_id(session, ClassificationValue, "production"),
        _catalog_id(session, ClassificationValue, "staging"),
    )


def _add_classification_type_and_value(session: Session) -> tuple[UUID, UUID]:
    classification_type = ClassificationType(
        code=_slug("classification-type"),
        display_name="Classification Type",
    )
    session.add(classification_type)
    session.flush()
    classification_value = ClassificationValue(
        classification_type_id=classification_type.id,
        code=_slug("classification-value"),
        display_name="Classification Value",
    )
    session.add(classification_value)
    session.flush()
    return classification_type.id, classification_value.id


def _classification_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceClassification)
            .where(
                ResourceClassification.tenant_id == tenant_id,
                ResourceClassification.resource_id == resource_id,
            )
        )
        or 0
    )


def _current_classification_count(
    session: Session,
    tenant_id: UUID,
    resource_id: UUID,
) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceClassification)
            .where(
                ResourceClassification.tenant_id == tenant_id,
                ResourceClassification.resource_id == resource_id,
                ResourceClassification.valid_to.is_(None),
            )
        )
        or 0
    )


def test_sqlalchemy_assignment_persists_and_reads_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, classification_type_id, production_id, _ = (
            _seed_resource_and_classification_catalogs(setup_session)
        )
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        classification_type_id=classification_type_id,
        classification_value_id=production_id,
        is_primary=True,
        confidence_score=Decimal("0.8000"),
        valid_from=_now(-5),
        source="manual",
    )
    handler = AssignResourceClassificationHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal)
    )

    result = handler.handle(command)

    assert result.resource_id == resource_id
    with SessionLocal() as verification:
        classification = verification.get(
            ResourceClassification,
            result.classification_id,
        )
        assert classification is not None
        assert classification.tenant_id == tenant_id
        assert classification.resource_id == resource_id
        assert classification.classification_type_id == classification_type_id
        assert classification.classification_value_id == production_id
        assert classification.is_primary is True
        assert classification.confidence_score == Decimal("0.8000")
        assert classification.valid_from == command.valid_from
        assert classification.valid_to is None
        assert classification.source == "manual"
        assert _current_classification_count(verification, tenant_id, resource_id) == 1

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, resource_id)
    )
    assert len(details.classifications) == 1
    assert details.classifications[0].id == result.classification_id
    assert details.classifications[0].classification_value_id == production_id


def test_sqlalchemy_type_value_mismatch_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, classification_type_id, _, _ = (
            _seed_resource_and_classification_catalogs(setup_session)
        )
        _, other_value_id = _add_classification_type_and_value(setup_session)
        setup_session.commit()
    handler = AssignResourceClassificationHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal)
    )

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                classification_type_id=classification_type_id,
                classification_value_id=other_value_id,
            )
        )

    assert exc_info.value.entity_type == "ClassificationValue"
    assert exc_info.value.conflict_field == "classification_type_id"
    with SessionLocal() as verification:
        assert _classification_count(verification, tenant_id, resource_id) == 0


def test_sqlalchemy_inactive_classification_value_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, classification_type_id, production_id, _ = (
            _seed_resource_and_classification_catalogs(setup_session)
        )
        value = setup_session.get(ClassificationValue, production_id)
        assert value is not None
        value.is_active = False
        setup_session.commit()
    handler = AssignResourceClassificationHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal)
    )

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                classification_type_id=classification_type_id,
                classification_value_id=production_id,
            )
        )

    assert exc_info.value.entity_type == "ClassificationValue"
    assert exc_info.value.conflict_field == "classification_value_id"
    with SessionLocal() as verification:
        assert _classification_count(verification, tenant_id, resource_id) == 0


def test_sqlalchemy_duplicate_current_classification_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, classification_type_id, production_id, _ = (
            _seed_resource_and_classification_catalogs(setup_session)
        )
        setup_session.commit()
    handler = AssignResourceClassificationHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal)
    )
    first = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        classification_type_id=classification_type_id,
        classification_value_id=production_id,
        valid_from=_now(-10),
    )
    first_result = handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                classification_type_id=classification_type_id,
                classification_value_id=production_id,
                valid_from=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceClassification"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.__cause__ is None
    with SessionLocal() as verification:
        assert (
            verification.get(ResourceClassification, first_result.classification_id)
            is not None
        )
        assert _classification_count(verification, tenant_id, resource_id) == 1


def test_sqlalchemy_current_primary_conflict_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, classification_type_id, production_id, staging_id = (
            _seed_resource_and_classification_catalogs(setup_session)
        )
        setup_session.commit()
    handler = AssignResourceClassificationHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal)
    )
    first = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        classification_type_id=classification_type_id,
        classification_value_id=production_id,
        is_primary=True,
        valid_from=_now(-10),
    )
    handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                classification_type_id=classification_type_id,
                classification_value_id=staging_id,
                is_primary=True,
                valid_from=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceClassification"
    assert exc_info.value.conflict_field == "current_primary"
    assert exc_info.value.__cause__ is None
    with SessionLocal() as verification:
        classifications = list(
            verification.scalars(
                select(ResourceClassification)
                .where(
                    ResourceClassification.tenant_id == tenant_id,
                    ResourceClassification.resource_id == resource_id,
                )
                .order_by(
                    ResourceClassification.valid_from,
                    ResourceClassification.id,
                )
            )
        )
        assert len(classifications) == 1
        assert classifications[0].classification_value_id == production_id
        assert classifications[0].valid_to is None


def test_sqlalchemy_historical_classification_is_preserved_when_assigning_new_current(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, classification_type_id, production_id, _ = (
            _seed_resource_and_classification_catalogs(setup_session)
        )
        historical = ResourceClassification(
            tenant_id=tenant_id,
            resource_id=resource_id,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            is_primary=False,
            confidence_score=Decimal("0.7000"),
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
        classification_type_id=classification_type_id,
        classification_value_id=production_id,
        valid_from=_now(-5),
    )
    handler = AssignResourceClassificationHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal)
    )

    result = handler.handle(command)

    with SessionLocal() as verification:
        history = list(
            verification.scalars(
                select(ResourceClassification)
                .where(
                    ResourceClassification.tenant_id == tenant_id,
                    ResourceClassification.resource_id == resource_id,
                )
                .order_by(
                    ResourceClassification.valid_from,
                    ResourceClassification.id,
                )
            )
        )
        assert [row.id for row in history] == [historical_id, result.classification_id]
        assert history[0].valid_from == historical_valid_from
        assert history[0].valid_to == historical_valid_to
        assert history[0].source == "legacy"
        assert history[1].valid_to is None
        assert history[1].classification_value_id == production_id


def test_sqlalchemy_persistence_boundary_translates_unchecked_classification_conflict(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, classification_type_id, production_id, _ = (
            _seed_resource_and_classification_catalogs(setup_session)
        )
        setup_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            resource = uow.resources.get_for_update(tenant_id, resource_id)
            assert resource is not None
            first = ResourceClassification(
                tenant_id=tenant_id,
                resource_id=resource_id,
                classification_type_id=classification_type_id,
                classification_value_id=production_id,
                is_primary=False,
                confidence_score=Decimal("0.9000"),
                valid_from=_now(-10),
                source="manual",
            )
            second = ResourceClassification(
                tenant_id=tenant_id,
                resource_id=resource_id,
                classification_type_id=classification_type_id,
                classification_value_id=production_id,
                is_primary=False,
                confidence_score=Decimal("0.8000"),
                valid_from=_now(-5),
                source="manual",
            )
            uow.resource_classifications.add(first)
            uow.resource_classifications.add(second)
            uow.commit()

    assert exc_info.value.entity_type == "ResourceClassification"
    assert exc_info.value.conflict_field == "current_value"
    assert exc_info.value.constraint == "uq_resource_classification_current_value"
    assert isinstance(exc_info.value.__cause__, IntegrityError)
    with SessionLocal() as verification:
        assert _classification_count(verification, tenant_id, resource_id) == 0

    handler = AssignResourceClassificationHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal)
    )
    fresh_result = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            valid_from=_now(),
        )
    )
    assert fresh_result.classification_id is not None
