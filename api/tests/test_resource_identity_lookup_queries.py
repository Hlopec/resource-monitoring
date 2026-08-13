from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.application.errors import EntityNotFoundError, ValidationError
from app.application.handlers import (
    FindResourceByAliasHandler,
    FindResourceByIdentifierHandler,
)
from app.application.queries import FindResourceByAliasQuery, FindResourceByIdentifierQuery
from app.application.results import (
    ResourceAliasLookupResult,
    ResourceIdentifierLookupResult,
    ResourceReadResult,
)


class FakeResourceQueryService:
    def __init__(
        self,
        events: list[str],
        *,
        identifier_projection: object | None = None,
        alias_projection: object | None = None,
    ) -> None:
        self._events = events
        self._identifier_projection = identifier_projection
        self._alias_projection = alias_projection
        self.identifier_calls: list[dict[str, object]] = []
        self.alias_calls: list[dict[str, object]] = []

    def find_by_identifier(
        self,
        tenant_id: UUID,
        *,
        identifier_type_id: UUID,
        namespace: str | None,
        normalized_value: str,
    ) -> object | None:
        self._events.append("resource_queries.find_by_identifier")
        self.identifier_calls.append(
            {
                "tenant_id": tenant_id,
                "identifier_type_id": identifier_type_id,
                "namespace": namespace,
                "normalized_value": normalized_value,
            }
        )
        return self._identifier_projection

    def find_by_alias(
        self,
        tenant_id: UUID,
        *,
        alias_type: str,
        normalized_value: str,
    ) -> object | None:
        self._events.append("resource_queries.find_by_alias")
        self.alias_calls.append(
            {
                "tenant_id": tenant_id,
                "alias_type": alias_type,
                "normalized_value": normalized_value,
            }
        )
        return self._alias_projection


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        identifier_projection: object | None = None,
        alias_projection: object | None = None,
    ) -> None:
        self.events: list[str] = []
        self.resource_queries = FakeResourceQueryService(
            self.events,
            identifier_projection=identifier_projection,
            alias_projection=alias_projection,
        )
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> FakeUnitOfWork:
        self.events.append("enter")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        self.events.append("exit")
        return False

    def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1

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


def _identifier_projection() -> object:
    return SimpleNamespace(
        resource_id=uuid4(),
        tenant_id=uuid4(),
        canonical_name="resource.example.com",
        display_name="Resource",
        identifier_id=uuid4(),
        identifier_type_id=uuid4(),
        namespace=None,
        normalized_value="example.com",
        original_value="Example.COM",
        is_primary=False,
    )


def _alias_projection() -> object:
    return SimpleNamespace(
        resource_id=uuid4(),
        tenant_id=uuid4(),
        canonical_name="resource.example.com",
        display_name="Resource",
        alias_id=uuid4(),
        alias_type="dns_name",
        normalized_value="example.com",
        alias_value="Example.COM",
    )


def test_identity_lookup_queries_are_frozen_data_only() -> None:
    identifier_query = FindResourceByIdentifierQuery(
        tenant_id=uuid4(),
        identifier_type_id=uuid4(),
        namespace=None,
        normalized_value="example.com",
    )
    alias_query = FindResourceByAliasQuery(
        tenant_id=uuid4(),
        alias_type="dns_name",
        normalized_value="example.com",
    )

    assert is_dataclass(identifier_query)
    assert is_dataclass(alias_query)
    assert set(identifier_query.__annotations__) == {
        "tenant_id",
        "identifier_type_id",
        "namespace",
        "normalized_value",
    }
    assert set(alias_query.__annotations__) == {
        "tenant_id",
        "alias_type",
        "normalized_value",
    }
    assert not hasattr(identifier_query, "execute")
    assert not hasattr(alias_query, "execute")
    with pytest.raises(FrozenInstanceError):
        identifier_query.normalized_value = "changed.example.com"
    with pytest.raises(FrozenInstanceError):
        alias_query.alias_type = "changed"


def test_identifier_query_validation_aggregates_before_unit_of_work() -> None:
    factory = FakeUnitOfWorkFactory()
    handler = FindResourceByIdentifierHandler(factory)

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(
            FindResourceByIdentifierQuery(
                tenant_id=uuid4(),
                identifier_type_id=uuid4(),
                namespace=" ",
                normalized_value="",
            )
        )

    assert str(exc_info.value) == "Invalid resource identifier lookup query"
    assert [failure.field for failure in exc_info.value.failures] == [
        "normalized_value",
        "namespace",
    ]
    assert factory.created == []


def test_alias_query_validation_aggregates_before_unit_of_work() -> None:
    factory = FakeUnitOfWorkFactory()
    handler = FindResourceByAliasHandler(factory)

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(
            FindResourceByAliasQuery(
                tenant_id=uuid4(),
                alias_type=" ",
                normalized_value="",
            )
        )

    assert str(exc_info.value) == "Invalid resource alias lookup query"
    assert [failure.field for failure in exc_info.value.failures] == [
        "alias_type",
        "normalized_value",
    ]
    assert factory.created == []


def test_identifier_handler_is_read_only_and_materializes_result() -> None:
    projection = _identifier_projection()
    uow = FakeUnitOfWork(identifier_projection=projection)
    handler = FindResourceByIdentifierHandler(FakeUnitOfWorkFactory(uow))
    query = FindResourceByIdentifierQuery(
        tenant_id=projection.tenant_id,
        identifier_type_id=projection.identifier_type_id,
        namespace=None,
        normalized_value=projection.normalized_value,
    )

    result = handler.handle(query)

    assert result == ResourceIdentifierLookupResult(
        resource=ResourceReadResult(
            id=projection.resource_id,
            tenant_id=projection.tenant_id,
            canonical_name=projection.canonical_name,
            display_name=projection.display_name,
        ),
        identifier_id=projection.identifier_id,
        identifier_type_id=projection.identifier_type_id,
        namespace=projection.namespace,
        normalized_value=projection.normalized_value,
        original_value=projection.original_value,
        is_primary=projection.is_primary,
    )
    assert uow.resource_queries.identifier_calls == [
        {
            "tenant_id": projection.tenant_id,
            "identifier_type_id": projection.identifier_type_id,
            "namespace": None,
            "normalized_value": projection.normalized_value,
        }
    ]
    assert uow.events == ["enter", "resource_queries.find_by_identifier", "exit"]
    assert uow.commits == 0
    assert uow.rollbacks == 0
    with pytest.raises(FrozenInstanceError):
        result.normalized_value = "changed.example.com"


def test_alias_handler_is_read_only_and_materializes_result() -> None:
    projection = _alias_projection()
    uow = FakeUnitOfWork(alias_projection=projection)
    handler = FindResourceByAliasHandler(FakeUnitOfWorkFactory(uow))
    query = FindResourceByAliasQuery(
        tenant_id=projection.tenant_id,
        alias_type=projection.alias_type,
        normalized_value=projection.normalized_value,
    )

    result = handler.handle(query)

    assert result == ResourceAliasLookupResult(
        resource=ResourceReadResult(
            id=projection.resource_id,
            tenant_id=projection.tenant_id,
            canonical_name=projection.canonical_name,
            display_name=projection.display_name,
        ),
        alias_id=projection.alias_id,
        alias_type=projection.alias_type,
        normalized_value=projection.normalized_value,
        alias_value=projection.alias_value,
    )
    assert uow.resource_queries.alias_calls == [
        {
            "tenant_id": projection.tenant_id,
            "alias_type": projection.alias_type,
            "normalized_value": projection.normalized_value,
        }
    ]
    assert uow.events == ["enter", "resource_queries.find_by_alias", "exit"]
    assert uow.commits == 0
    assert uow.rollbacks == 0
    with pytest.raises(FrozenInstanceError):
        result.alias_value = "changed.example.com"


def test_identifier_not_found_raises_stable_application_error() -> None:
    uow = FakeUnitOfWork()
    handler = FindResourceByIdentifierHandler(FakeUnitOfWorkFactory(uow))
    query = FindResourceByIdentifierQuery(
        tenant_id=uuid4(),
        identifier_type_id=uuid4(),
        namespace="dns",
        normalized_value="missing.example.com",
    )

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(query)

    assert str(exc_info.value) == "Resource identifier not found"
    assert exc_info.value.entity_type == "ResourceIdentifier"
    assert exc_info.value.lookup_field == "identifier"
    assert exc_info.value.lookup_value == (
        query.identifier_type_id,
        query.namespace,
        query.normalized_value,
    )
    assert uow.events == ["enter", "resource_queries.find_by_identifier", "exit"]
    assert uow.commits == 0


def test_alias_not_found_raises_stable_application_error() -> None:
    uow = FakeUnitOfWork()
    handler = FindResourceByAliasHandler(FakeUnitOfWorkFactory(uow))
    query = FindResourceByAliasQuery(
        tenant_id=uuid4(),
        alias_type="dns_name",
        normalized_value="missing.example.com",
    )

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(query)

    assert str(exc_info.value) == "Resource alias not found"
    assert exc_info.value.entity_type == "ResourceAlias"
    assert exc_info.value.lookup_field == "alias"
    assert exc_info.value.lookup_value == (query.alias_type, query.normalized_value)
    assert uow.events == ["enter", "resource_queries.find_by_alias", "exit"]
    assert uow.commits == 0
