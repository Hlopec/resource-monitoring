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

from app.application.commands import AssignResourceIdentifierCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import (
    AssignResourceIdentifierHandler,
    GetResourceDetailsHandler,
)
from app.application.queries import GetResourceDetailsQuery
from app.application.results import ResourceIdentifierAssignedResult
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    IdentifierType,
    LifecycleStatus,
    Resource,
    ResourceIdentifier,
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


class FakeIdentifierTypeRepository:
    def __init__(
        self,
        events: list[str],
        identifier_types: dict[UUID, object],
    ) -> None:
        self._events = events
        self._identifier_types = identifier_types

    def get_by_id(self, identifier_type_id: UUID) -> object | None:
        self._events.append("identifier_types.get_by_id")
        return self._identifier_types.get(identifier_type_id)


class FakeResourceIdentifierRepository:
    def __init__(
        self,
        events: list[str],
        *,
        current_by_value: ResourceIdentifier | object | None = None,
        current_primary: ResourceIdentifier | object | None = None,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._current_by_value = current_by_value
        self._current_primary = current_primary
        self._fail_on_add = fail_on_add
        self.added: list[ResourceIdentifier] = []
        self.flushes = 0

    def find_current_by_value(
        self,
        tenant_id: UUID,
        identifier_type_id: UUID,
        normalized_value: str,
        namespace: str | None = None,
    ) -> ResourceIdentifier | object | None:
        self._events.append("resource_identifiers.find_current_by_value")
        return self._current_by_value

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        identifier_type_id: UUID,
    ) -> ResourceIdentifier | object | None:
        self._events.append("resource_identifiers.get_current_primary")
        return self._current_primary

    def add(self, identifier: ResourceIdentifier) -> None:
        self._events.append("resource_identifiers.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(identifier)

    def flush(self) -> None:
        self._events.append("resource_identifiers.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        resource_id: UUID,
        identifier_type: object,
        resource_exists: bool = True,
        current_by_value: ResourceIdentifier | object | None = None,
        current_primary: ResourceIdentifier | object | None = None,
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
        self.identifier_types = FakeIdentifierTypeRepository(
            self.events,
            {identifier_type.id: identifier_type},
        )
        self.resource_identifiers = FakeResourceIdentifierRepository(
            self.events,
            current_by_value=current_by_value,
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


def _catalog(active: bool = True) -> object:
    return SimpleNamespace(id=uuid4(), is_active=active)


def _command(
    *,
    tenant_id: UUID | None = None,
    resource_id: UUID | None = None,
    identifier_type_id: UUID | None = None,
    original_value: str = "Example.COM",
    normalized_value: str = "example.com",
    value_hash: str = "hash-example.com",
    namespace: str | None = None,
    is_primary: bool = False,
    confidence_score: Decimal = Decimal("0.9000"),
    valid_from: datetime | None = None,
) -> AssignResourceIdentifierCommand:
    return AssignResourceIdentifierCommand(
        tenant_id=tenant_id or uuid4(),
        resource_id=resource_id or uuid4(),
        identifier_type_id=identifier_type_id or uuid4(),
        original_value=original_value,
        normalized_value=normalized_value,
        value_hash=value_hash,
        namespace=namespace,
        is_primary=is_primary,
        confidence_score=confidence_score,
        valid_from=valid_from or _now(),
    )


def _uow_for_command(
    command: AssignResourceIdentifierCommand,
    *,
    identifier_type_active: bool = True,
    resource_exists: bool = True,
    current_by_value: ResourceIdentifier | object | None = None,
    current_primary: ResourceIdentifier | object | None = None,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        identifier_type=SimpleNamespace(
            id=command.identifier_type_id,
            is_active=identifier_type_active,
        ),
        resource_exists=resource_exists,
        current_by_value=current_by_value,
        current_primary=current_primary,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def _current_identifier_for_command(
    command: AssignResourceIdentifierCommand,
    *,
    resource_id: UUID | None = None,
    valid_to: datetime | None = None,
) -> ResourceIdentifier:
    return ResourceIdentifier(
        tenant_id=command.tenant_id,
        resource_id=resource_id or command.resource_id,
        identifier_type_id=command.identifier_type_id,
        namespace=command.namespace,
        normalized_value=command.normalized_value,
        original_value=command.original_value,
        value_hash=command.value_hash,
        is_primary=command.is_primary,
        confidence_score=command.confidence_score,
        valid_from=_now(-10),
        valid_to=valid_to,
    )


def test_assign_resource_identifier_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "resource_id",
        "identifier_type_id",
        "original_value",
        "normalized_value",
        "value_hash",
        "namespace",
        "is_primary",
        "confidence_score",
        "valid_from",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.normalized_value = "changed.example.com"


def test_resource_identifier_assigned_result_is_immutable_and_entity_free() -> None:
    result = ResourceIdentifierAssignedResult(
        resource_id=uuid4(),
        identifier_id=uuid4(),
        identifier_type_id=uuid4(),
        original_value="Example.COM",
        normalized_value="example.com",
        value_hash="hash-example.com",
        namespace=None,
        is_primary=True,
        valid_from=_now(),
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceIdentifier)
    with pytest.raises(FrozenInstanceError):
        result.normalized_value = "changed.example.com"


@pytest.mark.parametrize(
    ("command", "expected_fields"),
    (
        (_command(original_value=""), ("original_value",)),
        (_command(original_value="   "), ("original_value",)),
        (_command(normalized_value=""), ("normalized_value",)),
        (_command(normalized_value="   "), ("normalized_value",)),
        (_command(value_hash=""), ("value_hash",)),
        (_command(value_hash="   "), ("value_hash",)),
        (_command(namespace=""), ("namespace",)),
        (_command(namespace="   "), ("namespace",)),
        (_command(confidence_score=Decimal("-0.0001")), ("confidence_score",)),
        (_command(confidence_score=Decimal("1.0001")), ("confidence_score",)),
        (_command(valid_from=datetime(2026, 1, 1)), ("valid_from",)),
    ),
)
def test_pre_uow_validation_failures_do_not_create_unit_of_work(
    command: AssignResourceIdentifierCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_pre_uow_validation_gathers_deterministic_failures() -> None:
    command = _command(
        original_value=" ",
        normalized_value="",
        value_hash=" ",
        namespace="",
        confidence_score=Decimal("-1"),
        valid_from=datetime(2026, 1, 1),
    )
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "original_value",
        "normalized_value",
        "value_hash",
        "namespace",
        "confidence_score",
        "valid_from",
    )


def test_missing_resource_stops_before_identifier_type_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == command.resource_id
    assert uow.events == ["enter", "resources.get_for_update", "exit"]
    assert uow.resource_identifiers.added == []
    assert uow.commits == 0


def test_wrong_tenant_matches_resource_not_found_behavior() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert "identifier_types.get_by_id" not in uow.events
    assert "resource_identifiers.find_current_by_value" not in uow.events
    assert uow.commits == 0


def test_missing_identifier_type_stops_before_identifier_reads() -> None:
    command = _command()
    uow = _uow_for_command(command)
    uow.identifier_types._identifier_types.clear()
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "IdentifierType"
    assert exc_info.value.lookup_field == "identifier_type_id"
    assert "resource_identifiers.find_current_by_value" not in uow.events
    assert uow.resource_identifiers.added == []
    assert uow.commits == 0


def test_inactive_identifier_type_stops_before_identifier_mutation() -> None:
    command = _command()
    uow = _uow_for_command(command, identifier_type_active=False)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "IdentifierType"
    assert exc_info.value.conflict_field == "identifier_type_id"
    assert "resource_identifiers.find_current_by_value" not in uow.events
    assert uow.resource_identifiers.added == []
    assert uow.commits == 0


def test_successful_non_primary_assignment_adds_one_identifier_and_commits_last() -> None:
    command = _command(
        original_value="Example.COM",
        normalized_value="example.com",
        value_hash="hash-example.com",
        namespace=None,
    )
    uow = _uow_for_command(command)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.resource_id == command.resource_id
    assert result.identifier_id == uow.resource_identifiers.added[0].id
    assert result.identifier_type_id == command.identifier_type_id
    assert result.original_value == command.original_value
    assert result.normalized_value == command.normalized_value
    assert result.value_hash == command.value_hash
    assert result.namespace is None
    assert result.is_primary is False
    assert result.valid_from == command.valid_from
    assert len(uow.resource_identifiers.added) == 1
    identifier = uow.resource_identifiers.added[0]
    assert identifier.tenant_id == command.tenant_id
    assert identifier.resource_id == command.resource_id
    assert identifier.identifier_type_id == command.identifier_type_id
    assert identifier.original_value == "Example.COM"
    assert identifier.normalized_value == "example.com"
    assert identifier.value_hash == "hash-example.com"
    assert identifier.namespace is None
    assert identifier.is_primary is False
    assert identifier.confidence_score == command.confidence_score
    assert identifier.valid_from == command.valid_from
    assert identifier.valid_to is None
    assert uow.resource_identifiers.flushes == 0
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "identifier_types.get_by_id",
        "resource_identifiers.find_current_by_value",
        "resource_identifiers.add",
        "commit",
        "exit",
    ]


def test_successful_first_primary_assignment_checks_current_primary() -> None:
    command = _command(is_primary=True, namespace="dns")
    uow = _uow_for_command(command)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.is_primary is True
    assert len(uow.resource_identifiers.added) == 1
    assert uow.resource_identifiers.added[0].is_primary is True
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "identifier_types.get_by_id",
        "resource_identifiers.find_current_by_value",
        "resource_identifiers.get_current_primary",
        "resource_identifiers.add",
        "commit",
        "exit",
    ]


def test_duplicate_same_resource_assignment_is_rejected_before_mutation() -> None:
    command = _command()
    current = _current_identifier_for_command(command)
    uow = _uow_for_command(command, current_by_value=current)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceIdentifier"
    assert exc_info.value.conflict_field == "current_value"
    assert exc_info.value.conflict_value == command.normalized_value
    assert uow.resource_identifiers.added == []
    assert uow.commits == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "identifier_types.get_by_id",
        "resource_identifiers.find_current_by_value",
        "exit",
    ]


def test_current_identifier_for_other_resource_defers_to_persistence_boundary() -> None:
    command = _command()
    current = _current_identifier_for_command(command, resource_id=uuid4())
    uow = _uow_for_command(command, current_by_value=current)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.identifier_id == uow.resource_identifiers.added[0].id
    assert uow.commits == 1
    assert uow.events[-3:] == ["resource_identifiers.add", "commit", "exit"]


def test_existing_current_primary_is_rejected_before_mutation() -> None:
    command = _command(is_primary=True)
    current_primary = _current_identifier_for_command(command)
    uow = _uow_for_command(command, current_primary=current_primary)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceIdentifier"
    assert exc_info.value.conflict_field == "current_primary"
    assert exc_info.value.conflict_value == command.identifier_type_id
    assert uow.resource_identifiers.added == []
    assert uow.commits == 0
    assert "resource_identifiers.add" not in uow.events


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = AssignResourceIdentifierHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.identifier_id == succeeding_uow.resource_identifiers.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = AssignResourceIdentifierHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_resource(session: Session) -> tuple[UUID, UUID, UUID]:
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
    return tenant.id, resource.id, _catalog_id(session, IdentifierType, "fqdn")


def _seed_two_resources(session: Session) -> tuple[UUID, UUID, UUID, UUID]:
    tenant_id, first_resource_id, identifier_type_id = _seed_resource(session)
    now = _now(-20)
    second = Resource(
        tenant_id=tenant_id,
        resource_type_id=_catalog_id(session, ResourceType, "domain"),
        canonical_name=_slug("resource"),
        display_name="Second Resource",
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(second)
    session.flush()
    return tenant_id, first_resource_id, second.id, identifier_type_id


def _identifier_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceIdentifier)
            .where(
                ResourceIdentifier.tenant_id == tenant_id,
                ResourceIdentifier.resource_id == resource_id,
            )
        )
        or 0
    )


def _current_identifier_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceIdentifier)
            .where(
                ResourceIdentifier.tenant_id == tenant_id,
                ResourceIdentifier.resource_id == resource_id,
                ResourceIdentifier.valid_to.is_(None),
            )
        )
        or 0
    )


def test_sqlalchemy_assignment_persists_and_reads_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, identifier_type_id = _seed_resource(setup_session)
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        identifier_type_id=identifier_type_id,
        original_value="Example.COM",
        normalized_value="example.com",
        value_hash="hash-example.com",
        namespace="dns",
        is_primary=True,
        valid_from=_now(-5),
    )
    handler = AssignResourceIdentifierHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    assert result.resource_id == resource_id
    with SessionLocal() as verification:
        identifier = verification.get(ResourceIdentifier, result.identifier_id)
        assert identifier is not None
        assert identifier.tenant_id == tenant_id
        assert identifier.resource_id == resource_id
        assert identifier.identifier_type_id == identifier_type_id
        assert identifier.original_value == "Example.COM"
        assert identifier.normalized_value == "example.com"
        assert identifier.value_hash == "hash-example.com"
        assert identifier.namespace == "dns"
        assert identifier.is_primary is True
        assert identifier.confidence_score == command.confidence_score
        assert identifier.valid_from == command.valid_from
        assert identifier.valid_to is None
        assert _current_identifier_count(verification, tenant_id, resource_id) == 1

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, resource_id)
    )
    assert len(details.identifiers) == 1
    assert details.identifiers[0].id == result.identifier_id
    assert details.identifiers[0].normalized_value == "example.com"


def test_sqlalchemy_wrong_tenant_leaves_identifiers_unchanged(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, identifier_type_id = _seed_resource(setup_session)
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.commit()
        other_tenant_id = other_tenant.id
    handler = AssignResourceIdentifierHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError):
        handler.handle(
            _command(
                tenant_id=other_tenant_id,
                resource_id=resource_id,
                identifier_type_id=identifier_type_id,
            )
        )

    with SessionLocal() as verification:
        assert _identifier_count(verification, tenant_id, resource_id) == 0


def test_sqlalchemy_cross_resource_collision_uses_persistence_translation(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, first_resource_id, second_resource_id, identifier_type_id = (
            _seed_two_resources(setup_session)
        )
        setup_session.commit()
    handler = AssignResourceIdentifierHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    first = _command(
        tenant_id=tenant_id,
        resource_id=first_resource_id,
        identifier_type_id=identifier_type_id,
        normalized_value="shared.example.com",
        value_hash="hash-shared",
        valid_from=_now(-10),
    )
    second = _command(
        tenant_id=tenant_id,
        resource_id=second_resource_id,
        identifier_type_id=identifier_type_id,
        normalized_value="shared.example.com",
        value_hash="hash-shared",
        valid_from=_now(-5),
    )
    first_result = handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(second)

    assert exc_info.value.entity_type == "ResourceIdentifier"
    assert exc_info.value.conflict_field == "current_value"
    assert exc_info.value.constraint == "uq_resource_identifier_current_value"
    assert isinstance(exc_info.value.__cause__, IntegrityError)
    with SessionLocal() as verification:
        assert verification.get(ResourceIdentifier, first_result.identifier_id) is not None
        assert _current_identifier_count(verification, tenant_id, first_resource_id) == 1
        assert _identifier_count(verification, tenant_id, second_resource_id) == 0

    fresh_result = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=second_resource_id,
            identifier_type_id=identifier_type_id,
            normalized_value="fresh.example.com",
            value_hash="hash-fresh",
        )
    )
    assert fresh_result.identifier_id is not None


def test_sqlalchemy_current_primary_conflict_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, identifier_type_id = _seed_resource(setup_session)
        setup_session.commit()
    handler = AssignResourceIdentifierHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    first = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        identifier_type_id=identifier_type_id,
        normalized_value="primary.example.com",
        value_hash="hash-primary",
        is_primary=True,
        valid_from=_now(-10),
    )
    handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                identifier_type_id=identifier_type_id,
                normalized_value="second-primary.example.com",
                value_hash="hash-second-primary",
                is_primary=True,
                valid_from=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceIdentifier"
    assert exc_info.value.conflict_field == "current_primary"
    assert exc_info.value.__cause__ is None
    with SessionLocal() as verification:
        identifiers = list(
            verification.scalars(
                select(ResourceIdentifier)
                .where(
                    ResourceIdentifier.tenant_id == tenant_id,
                    ResourceIdentifier.resource_id == resource_id,
                )
                .order_by(ResourceIdentifier.valid_from, ResourceIdentifier.id)
            )
        )
        assert len(identifiers) == 1
        assert identifiers[0].normalized_value == "primary.example.com"
        assert identifiers[0].valid_to is None


def test_sqlalchemy_historical_identifier_is_preserved_when_assigning_new_current(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, identifier_type_id = _seed_resource(setup_session)
        historical = ResourceIdentifier(
            tenant_id=tenant_id,
            resource_id=resource_id,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value="example.com",
            original_value="Example.COM",
            value_hash="hash-example.com",
            is_primary=False,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-30),
            valid_to=_now(-20),
        )
        setup_session.add(historical)
        setup_session.commit()
        historical_id = historical.id
        historical_valid_from = historical.valid_from
        historical_valid_to = historical.valid_to
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        identifier_type_id=identifier_type_id,
        normalized_value="example.com",
        value_hash="hash-example.com",
        valid_from=_now(-5),
    )
    handler = AssignResourceIdentifierHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    with SessionLocal() as verification:
        history = list(
            verification.scalars(
                select(ResourceIdentifier)
                .where(
                    ResourceIdentifier.tenant_id == tenant_id,
                    ResourceIdentifier.resource_id == resource_id,
                )
                .order_by(ResourceIdentifier.valid_from, ResourceIdentifier.id)
            )
        )
        assert [row.id for row in history] == [historical_id, result.identifier_id]
        assert history[0].valid_from == historical_valid_from
        assert history[0].valid_to == historical_valid_to
        assert history[1].valid_to is None
        assert history[1].normalized_value == "example.com"
