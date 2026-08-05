from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.application.commands import EnsureResourceExistsCommand
from app.application.errors import EntityNotFoundError, ValidationError, ValidationFailure
from app.application.handlers import (
    CommandHandler,
    EnsureResourceExistsHandler,
    GetResourceByIdHandler,
    QueryHandler,
)
from app.application.ports import UnitOfWork, UnitOfWorkFactory
from app.application.queries import GetResourceByIdQuery
from app.application.results import ResourceReadResult
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


class FakeResourceRepository:
    def __init__(self, events: list[str], resources: dict[tuple[UUID, UUID], object]):
        self._events = events
        self._resources = resources

    def get_by_id(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append("get_by_id")
        return self._resources.get((tenant_id, resource_id))

    def exists(self, tenant_id: UUID, resource_id: UUID) -> bool:
        self._events.append("exists")
        return (tenant_id, resource_id) in self._resources


class FakeUnitOfWork:
    def __init__(self, resources: dict[tuple[UUID, UUID], object]) -> None:
        self.events: list[str] = []
        self.resources = FakeResourceRepository(self.events, resources)
        self.commits = 0
        self.rollbacks = 0
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> FakeUnitOfWork:
        self.entered += 1
        self.events.append("enter")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        self.exited += 1
        if self.commits == 0:
            self.rollbacks += 1
            self.events.append("rollback")
        self.events.append("exit")
        return False

    def commit(self) -> None:
        self.commits += 1
        self.events.append("commit")

    def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append("rollback")


class FakeUnitOfWorkFactory:
    def __init__(self, resources: dict[tuple[UUID, UUID], object]) -> None:
        self._resources = resources
        self.created: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        uow = FakeUnitOfWork(self._resources)
        self.created.append(uow)
        return uow


def _accepts_unit_of_work_factory(factory: UnitOfWorkFactory) -> UnitOfWorkFactory:
    return factory


def _accepts_unit_of_work(uow: UnitOfWork) -> UnitOfWork:
    return uow


def _accepts_command_handler(
    handler: CommandHandler[EnsureResourceExistsCommand, None],
) -> CommandHandler[EnsureResourceExistsCommand, None]:
    return handler


def _accepts_query_handler(
    handler: QueryHandler[GetResourceByIdQuery, ResourceReadResult],
) -> QueryHandler[GetResourceByIdQuery, ResourceReadResult]:
    return handler


def test_commands_are_immutable_transport_independent_data() -> None:
    command = EnsureResourceExistsCommand(uuid4(), uuid4())

    assert is_dataclass(command)
    with pytest.raises(FrozenInstanceError):
        command.resource_id = uuid4()
    assert not hasattr(command, "execute")
    assert not hasattr(command, "commit")


def test_queries_are_immutable_transport_independent_data() -> None:
    query = GetResourceByIdQuery(uuid4(), uuid4())

    assert is_dataclass(query)
    with pytest.raises(FrozenInstanceError):
        query.resource_id = uuid4()
    assert not hasattr(query, "commit")


def test_results_are_immutable_typed_application_contracts() -> None:
    result = ResourceReadResult(
        id=uuid4(),
        tenant_id=uuid4(),
        canonical_name="example.com",
        display_name="Example",
    )

    assert is_dataclass(result)
    with pytest.raises(FrozenInstanceError):
        result.canonical_name = "changed.example.com"
    assert not isinstance(result, dict)


def test_unit_of_work_factory_is_structural_and_creates_fresh_units() -> None:
    factory = FakeUnitOfWorkFactory({})

    assert _accepts_unit_of_work_factory(factory) is factory
    first = factory()
    second = factory()

    assert _accepts_unit_of_work(first) is first
    assert first is not second
    assert factory.created == [first, second]


def test_query_handler_uses_one_unit_of_work_and_never_commits() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    resource = SimpleNamespace(
        id=resource_id,
        tenant_id=tenant_id,
        canonical_name="example.com",
        display_name="Example",
    )
    factory = FakeUnitOfWorkFactory({(tenant_id, resource_id): resource})
    handler = GetResourceByIdHandler(factory)

    result = handler.handle(GetResourceByIdQuery(tenant_id, resource_id))

    assert _accepts_query_handler(handler) is handler
    assert result == ResourceReadResult(
        id=resource_id,
        tenant_id=tenant_id,
        canonical_name="example.com",
        display_name="Example",
    )
    assert len(factory.created) == 1
    uow = factory.created[0]
    assert uow.commits == 0
    assert uow.rollbacks == 1
    assert uow.events == ["enter", "get_by_id", "rollback", "exit"]


def test_query_handler_rolls_back_on_not_found() -> None:
    factory = FakeUnitOfWorkFactory({})
    handler = GetResourceByIdHandler(factory)

    with pytest.raises(EntityNotFoundError):
        handler.handle(GetResourceByIdQuery(uuid4(), uuid4()))

    uow = factory.created[0]
    assert uow.commits == 0
    assert uow.rollbacks == 1
    assert uow.events == ["enter", "get_by_id", "rollback", "exit"]


def test_command_handler_commits_exactly_once_after_validation() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    factory = FakeUnitOfWorkFactory(
        {(tenant_id, resource_id): object()},
    )
    handler = EnsureResourceExistsHandler(factory)

    result = handler.handle(EnsureResourceExistsCommand(tenant_id, resource_id))

    assert _accepts_command_handler(handler) is handler
    assert result is None
    assert len(factory.created) == 1
    uow = factory.created[0]
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == ["enter", "exists", "commit", "exit"]


def test_command_handler_does_not_commit_when_validation_fails() -> None:
    factory = FakeUnitOfWorkFactory({})
    handler = EnsureResourceExistsHandler(factory)

    with pytest.raises(EntityNotFoundError):
        handler.handle(EnsureResourceExistsCommand(uuid4(), uuid4()))

    uow = factory.created[0]
    assert uow.commits == 0
    assert uow.rollbacks == 1
    assert uow.events == ["enter", "exists", "rollback", "exit"]


def test_application_validation_error_carries_typed_failures() -> None:
    failure = ValidationFailure(field="canonical_name", message="required")
    error = ValidationError("Invalid command", failures=(failure,))

    assert error.failures == (failure,)
    assert str(error) == "Invalid command"


def test_reference_handler_is_compatible_with_sqlalchemy_unit_of_work(
    migrated_engine,
) -> None:
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    handler = GetResourceByIdHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError):
        handler.handle(GetResourceByIdQuery(uuid4(), uuid4()))
