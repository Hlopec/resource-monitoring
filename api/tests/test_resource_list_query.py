from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.application.errors import ValidationError
from app.application.handlers import ListResourcesHandler
from app.application.pagination import (
    ResourceListCursor,
    decode_resource_list_cursor,
    encode_resource_list_cursor,
)
from app.application.queries import (
    DEFAULT_RESOURCE_PAGE_SIZE,
    ListResourcesQuery,
    MAX_RESOURCE_PAGE_SIZE,
    MIN_RESOURCE_PAGE_SIZE,
)
from app.application.results import ResourcePageResult, ResourceSummaryResult


class FakeResourceQueryService:
    def __init__(
        self,
        events: list[str],
        items: tuple[object, ...] = (),
        next_position: ResourceListCursor | None = None,
    ) -> None:
        self._events = events
        self._items = items
        self._next_position = next_position
        self.calls: list[dict[str, object]] = []

    def list_resources(
        self,
        tenant_id: UUID,
        *,
        resource_type_id: UUID | None,
        lifecycle_status_id: UUID | None,
        organization_id: UUID | None,
        after: ResourceListCursor | None,
        limit: int,
    ) -> object:
        self._events.append("resource_queries.list_resources")
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "resource_type_id": resource_type_id,
                "lifecycle_status_id": lifecycle_status_id,
                "organization_id": organization_id,
                "after": after,
                "limit": limit,
            }
        )
        return SimpleNamespace(items=self._items, next_position=self._next_position)


class FakeUnitOfWork:
    def __init__(
        self,
        items: tuple[object, ...] = (),
        next_position: ResourceListCursor | None = None,
    ) -> None:
        self.events: list[str] = []
        self.resource_queries = FakeResourceQueryService(
            self.events,
            items,
            next_position,
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


def _summary(
    *,
    resource_id: UUID | None = None,
    tenant_id: UUID | None = None,
    created_at: datetime | None = None,
) -> object:
    resource_id = resource_id or uuid4()
    tenant_id = tenant_id or uuid4()
    now = created_at or datetime.now(UTC)
    return SimpleNamespace(
        resource_id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=uuid4(),
        lifecycle_status_id=uuid4(),
        canonical_name=f"resource-{resource_id}.example.com",
        display_name="Resource",
        primary_organization_id=uuid4(),
        primary_ownership_role_id=uuid4(),
        record_version=1,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )


def _cursor_payload(**overrides: object) -> str:
    payload = {
        "v": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "id": str(uuid4()),
    }
    payload.update(overrides)
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode(
        "ascii"
    ).rstrip("=")


def test_list_resources_query_is_frozen_data_only() -> None:
    query = ListResourcesQuery(tenant_id=uuid4())

    assert is_dataclass(query)
    assert set(query.__annotations__) == {
        "tenant_id",
        "resource_type_id",
        "lifecycle_status_id",
        "organization_id",
        "page_size",
        "cursor",
    }
    assert query.page_size == DEFAULT_RESOURCE_PAGE_SIZE
    assert MIN_RESOURCE_PAGE_SIZE == 1
    assert MAX_RESOURCE_PAGE_SIZE == 200
    assert not hasattr(query, "execute")
    assert not hasattr(query, "save")
    assert not hasattr(query, "commit")
    with pytest.raises(FrozenInstanceError):
        query.page_size = 10


def test_cursor_codec_round_trips_opaque_url_safe_position() -> None:
    position = ResourceListCursor(
        created_at=datetime(2026, 8, 13, 12, 30, tzinfo=UTC),
        resource_id=uuid4(),
    )

    encoded = encode_resource_list_cursor(position)
    decoded = decode_resource_list_cursor(encoded)

    assert decoded == position
    assert "{" not in encoded
    assert "/" not in encoded
    assert "+" not in encoded


@pytest.mark.parametrize(
    "cursor",
    (
        "not base64!",
        base64.urlsafe_b64encode(b"{not-json").decode("ascii"),
        _cursor_payload(v=2),
        _cursor_payload(created_at=None),
        _cursor_payload(created_at="not-a-datetime"),
        _cursor_payload(created_at="2026-08-13T12:30:00"),
        _cursor_payload(id="not-a-uuid"),
        base64.urlsafe_b64encode(json.dumps(["not", "object"]).encode()).decode(),
        _cursor_payload(extra="field"),
    ),
)
def test_cursor_decode_failures_are_validation_errors(cursor: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        decode_resource_list_cursor(cursor)

    assert str(exc_info.value) == "Invalid resource list cursor"
    assert exc_info.value.failures[0].field == "cursor"


def test_invalid_page_size_fails_before_unit_of_work_creation() -> None:
    factory = FakeUnitOfWorkFactory()
    handler = ListResourcesHandler(factory)

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(ListResourcesQuery(tenant_id=uuid4(), page_size=0))

    assert exc_info.value.failures[0].field == "page_size"
    assert factory.created == []


def test_page_size_above_maximum_fails_before_unit_of_work_creation() -> None:
    factory = FakeUnitOfWorkFactory()
    handler = ListResourcesHandler(factory)

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(
            ListResourcesQuery(tenant_id=uuid4(), page_size=MAX_RESOURCE_PAGE_SIZE + 1)
        )

    assert exc_info.value.failures[0].field == "page_size"
    assert factory.created == []


def test_list_resources_handler_is_read_only_and_materializes_page() -> None:
    tenant_id = uuid4()
    item = _summary(tenant_id=tenant_id)
    next_position = ResourceListCursor(item.created_at, item.resource_id)
    uow = FakeUnitOfWork(items=(item,), next_position=next_position)
    handler = ListResourcesHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(ListResourcesQuery(tenant_id=tenant_id, page_size=1))

    assert result == ResourcePageResult(
        items=(
            ResourceSummaryResult(
                resource_id=item.resource_id,
                tenant_id=tenant_id,
                resource_type_id=item.resource_type_id,
                lifecycle_status_id=item.lifecycle_status_id,
                canonical_name=item.canonical_name,
                display_name=item.display_name,
                primary_organization_id=item.primary_organization_id,
                primary_ownership_role_id=item.primary_ownership_role_id,
                record_version=item.record_version,
                first_seen_at=item.first_seen_at,
                last_seen_at=item.last_seen_at,
                created_at=item.created_at,
                updated_at=item.updated_at,
            ),
        ),
        next_cursor=encode_resource_list_cursor(next_position),
        page_size=1,
    )
    assert uow.events == ["enter", "resource_queries.list_resources", "exit"]
    assert uow.commits == 0
    assert uow.rollbacks == 0
    assert isinstance(result.items, tuple)
    with pytest.raises(FrozenInstanceError):
        result.page_size = 2
    with pytest.raises(FrozenInstanceError):
        result.items[0].canonical_name = "changed.example.com"


def test_handler_passes_decoded_cursor_and_all_filters_to_query_service() -> None:
    tenant_id = uuid4()
    resource_type_id = uuid4()
    lifecycle_status_id = uuid4()
    organization_id = uuid4()
    position = ResourceListCursor(datetime.now(UTC), uuid4())
    cursor = encode_resource_list_cursor(position)
    uow = FakeUnitOfWork()
    handler = ListResourcesHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
            organization_id=organization_id,
            page_size=25,
            cursor=cursor,
        )
    )

    assert result.items == ()
    assert uow.resource_queries.calls == [
        {
            "tenant_id": tenant_id,
            "resource_type_id": resource_type_id,
            "lifecycle_status_id": lifecycle_status_id,
            "organization_id": organization_id,
            "after": position,
            "limit": 25,
        }
    ]
