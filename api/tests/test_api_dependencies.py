from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.composition import (
    get_assign_resource_alias_handler,
    get_assign_resource_classification_handler,
    get_assign_resource_identifier_handler,
    get_assign_resource_label_handler,
    get_assign_resource_ownership_handler,
    get_assign_resource_relationship_handler,
    get_create_resource_handler,
    get_find_resource_by_alias_handler,
    get_find_resource_by_identifier_handler,
    get_get_resource_by_canonical_name_handler,
    get_get_resource_by_id_handler,
    get_get_resource_details_handler,
    get_get_resource_history_handler,
    get_get_resource_relationships_handler,
    get_list_resources_handler,
    get_merge_resource_handler,
    get_resolve_canonical_resource_handler,
    get_transition_resource_state_handler,
    get_unit_of_work_factory,
)
from app.application.handlers import (
    AssignResourceAliasHandler,
    AssignResourceClassificationHandler,
    AssignResourceIdentifierHandler,
    AssignResourceLabelHandler,
    AssignResourceOwnershipHandler,
    AssignResourceRelationshipHandler,
    CreateResourceHandler,
    FindResourceByAliasHandler,
    FindResourceByIdentifierHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
    GetResourceHistoryHandler,
    GetResourceRelationshipsHandler,
    ListResourcesHandler,
    MergeResourceHandler,
    ResolveCanonicalResourceHandler,
    TransitionResourceStateHandler,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


class FakeUnitOfWorkFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        raise AssertionError("Provider resolution must not open a Unit of Work")


HandlerProvider = Callable[[FakeUnitOfWorkFactory], object]

PROVIDER_INVENTORY: tuple[tuple[HandlerProvider, type], ...] = (
    (get_list_resources_handler, ListResourcesHandler),
    (get_get_resource_by_id_handler, GetResourceByIdHandler),
    (get_get_resource_details_handler, GetResourceDetailsHandler),
    (get_get_resource_history_handler, GetResourceHistoryHandler),
    (get_get_resource_relationships_handler, GetResourceRelationshipsHandler),
    (get_get_resource_by_canonical_name_handler, GetResourceByCanonicalNameHandler),
    (get_find_resource_by_identifier_handler, FindResourceByIdentifierHandler),
    (get_find_resource_by_alias_handler, FindResourceByAliasHandler),
    (get_resolve_canonical_resource_handler, ResolveCanonicalResourceHandler),
    (get_create_resource_handler, CreateResourceHandler),
    (get_transition_resource_state_handler, TransitionResourceStateHandler),
    (get_assign_resource_identifier_handler, AssignResourceIdentifierHandler),
    (get_assign_resource_ownership_handler, AssignResourceOwnershipHandler),
    (get_assign_resource_classification_handler, AssignResourceClassificationHandler),
    (get_assign_resource_label_handler, AssignResourceLabelHandler),
    (get_assign_resource_relationship_handler, AssignResourceRelationshipHandler),
    (get_assign_resource_alias_handler, AssignResourceAliasHandler),
    (get_merge_resource_handler, MergeResourceHandler),
)


def _handler_factory(handler: object) -> object:
    return getattr(handler, "_uow_factory")


def test_unit_of_work_factory_dependency_returns_factory_without_instantiation() -> None:
    factory = get_unit_of_work_factory()

    assert factory is SQLAlchemyUnitOfWork
    assert inspect.isclass(factory)


def test_representative_read_provider_uses_supplied_factory_without_db_access() -> None:
    fake_factory = FakeUnitOfWorkFactory()

    handler = get_list_resources_handler(fake_factory)

    assert isinstance(handler, ListResourcesHandler)
    assert _handler_factory(handler) is fake_factory
    assert fake_factory.calls == 0


def test_representative_write_provider_uses_supplied_factory_without_db_access() -> None:
    fake_factory = FakeUnitOfWorkFactory()

    handler = get_create_resource_handler(fake_factory)

    assert isinstance(handler, CreateResourceHandler)
    assert _handler_factory(handler) is fake_factory
    assert fake_factory.calls == 0


@pytest.mark.parametrize(("provider", "handler_type"), PROVIDER_INVENTORY)
def test_full_provider_inventory_is_explicit_fresh_and_uses_supplied_factory(
    provider: HandlerProvider,
    handler_type: type,
) -> None:
    fake_factory = FakeUnitOfWorkFactory()

    first = provider(fake_factory)
    second = provider(fake_factory)

    assert isinstance(first, handler_type)
    assert isinstance(second, handler_type)
    assert first is not second
    assert _handler_factory(first) is fake_factory
    assert _handler_factory(second) is fake_factory
    assert fake_factory.calls == 0


def test_fastapi_dependency_override_can_replace_unit_of_work_factory() -> None:
    fake_factory = FakeUnitOfWorkFactory()
    test_app = FastAPI()

    @test_app.get("/handler-check")
    def handler_check(
        handler: ListResourcesHandler = Depends(get_list_resources_handler),
    ) -> dict[str, Any]:
        return {
            "handler_type": type(handler).__name__,
            "uses_override": _handler_factory(handler) is fake_factory,
        }

    test_app.dependency_overrides[get_unit_of_work_factory] = lambda: fake_factory

    response = TestClient(test_app).get("/handler-check")

    assert response.status_code == 200
    assert response.json() == {
        "handler_type": "ListResourcesHandler",
        "uses_override": True,
    }
    assert fake_factory.calls == 0


def test_fastapi_dependency_override_can_replace_explicit_handler_provider() -> None:
    fake_factory = FakeUnitOfWorkFactory()
    replacement_handler = ListResourcesHandler(fake_factory)
    test_app = FastAPI()

    @test_app.get("/handler-override")
    def handler_override(
        handler: ListResourcesHandler = Depends(get_list_resources_handler),
    ) -> dict[str, Any]:
        return {
            "same_handler": handler is replacement_handler,
            "uses_fake_factory": _handler_factory(handler) is fake_factory,
        }

    test_app.dependency_overrides[get_list_resources_handler] = (
        lambda: replacement_handler
    )

    response = TestClient(test_app).get("/handler-override")

    assert response.status_code == 200
    assert response.json() == {
        "same_handler": True,
        "uses_fake_factory": True,
    }
    assert fake_factory.calls == 0
