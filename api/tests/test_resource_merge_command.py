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

from app.application.commands import MergeResourceCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import GetResourceDetailsHandler, MergeResourceHandler
from app.application.queries import GetResourceDetailsQuery
from app.application.results import ResourceMergedResult
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    IdentifierType,
    Label,
    LifecycleStatus,
    RelationshipType,
    Resource,
    ResourceAlias,
    ResourceIdentifier,
    ResourceLabel,
    ResourceMerge,
    ResourceRelationship,
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
        self._events.append(f"resources.get_for_update:{resource_id}")
        return self._resources.get((tenant_id, resource_id))


class FakeResourceMergeRepository:
    def __init__(
        self,
        events: list[str],
        *,
        outgoing: ResourceMerge | object | None = None,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._outgoing = outgoing
        self._fail_on_add = fail_on_add
        self.added: list[ResourceMerge] = []
        self.flushes = 0

    def get_outgoing_merge(
        self,
        tenant_id: UUID,
        source_resource_id: UUID,
    ) -> ResourceMerge | object | None:
        self._events.append("resource_merges.get_outgoing_merge")
        return self._outgoing

    def add(self, merge: ResourceMerge) -> None:
        self._events.append("resource_merges.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(merge)

    def flush(self) -> None:
        self._events.append("resource_merges.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        source_resource_id: UUID,
        target_resource_id: UUID,
        source_exists: bool = True,
        target_exists: bool = True,
        outgoing: ResourceMerge | object | None = None,
        fail_on_add: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self._fail_on_commit = fail_on_commit
        self.source_resource = SimpleNamespace(id=source_resource_id, tenant_id=tenant_id)
        self.target_resource = SimpleNamespace(id=target_resource_id, tenant_id=tenant_id)
        resources: dict[tuple[UUID, UUID], object] = {}
        if source_exists:
            resources[(tenant_id, source_resource_id)] = self.source_resource
        if target_exists:
            resources[(tenant_id, target_resource_id)] = self.target_resource
        self.resources = FakeResourceRepository(self.events, resources)
        self.resource_merges = FakeResourceMergeRepository(
            self.events,
            outgoing=outgoing,
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
    source_resource_id: UUID | None = None,
    target_resource_id: UUID | None = None,
    reason: str | None = "duplicate",
    source: str | None = "manual",
    merged_at: datetime | None = None,
) -> MergeResourceCommand:
    return MergeResourceCommand(
        tenant_id=tenant_id or uuid4(),
        source_resource_id=source_resource_id or uuid4(),
        target_resource_id=target_resource_id or uuid4(),
        reason=reason,
        source=source,
        merged_at=merged_at or _now(),
    )


def _uow_for_command(
    command: MergeResourceCommand,
    *,
    source_exists: bool = True,
    target_exists: bool = True,
    outgoing: ResourceMerge | object | None = None,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        source_resource_id=command.source_resource_id,
        target_resource_id=command.target_resource_id,
        source_exists=source_exists,
        target_exists=target_exists,
        outgoing=outgoing,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def test_merge_resource_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "source_resource_id",
        "target_resource_id",
        "reason",
        "source",
        "merged_at",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.target_resource_id = uuid4()


def test_resource_merged_result_is_immutable_and_entity_free() -> None:
    result = ResourceMergedResult(
        merge_id=uuid4(),
        source_resource_id=uuid4(),
        target_resource_id=uuid4(),
        merged_at=_now(),
        reason="duplicate",
        source="manual",
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceMerge)
    with pytest.raises(FrozenInstanceError):
        result.target_resource_id = uuid4()


@pytest.mark.parametrize(
    ("command", "expected_fields"),
    (
        (_command(merged_at=datetime(2026, 1, 1)), ("merged_at",)),
        (_command(reason=""), ("reason",)),
        (_command(reason="   "), ("reason",)),
        (_command(source=""), ("source",)),
        (_command(source="   "), ("source",)),
    ),
)
def test_pre_uow_validation_failures_do_not_create_unit_of_work(
    command: MergeResourceCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = MergeResourceHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_self_merge_is_rejected_before_unit_of_work() -> None:
    resource_id = uuid4()
    command = _command(
        source_resource_id=resource_id,
        target_resource_id=resource_id,
    )
    handler = MergeResourceHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "target_resource_id",
    )


def test_pre_uow_validation_gathers_deterministic_failures() -> None:
    resource_id = uuid4()
    command = _command(
        source_resource_id=resource_id,
        target_resource_id=resource_id,
        reason=" ",
        source=" ",
        merged_at=datetime(2026, 1, 1),
    )
    handler = MergeResourceHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "target_resource_id",
        "merged_at",
        "reason",
        "source",
    )


def test_locks_resources_in_stable_order_while_preserving_direction() -> None:
    lower_id = UUID("01984000-0000-7000-8000-000000000001")
    higher_id = UUID("01984000-0000-7000-8000-000000000002")
    command = _command(source_resource_id=higher_id, target_resource_id=lower_id)
    uow = _uow_for_command(command)
    handler = MergeResourceHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.source_resource_id == higher_id
    assert result.target_resource_id == lower_id
    merge = uow.resource_merges.added[0]
    assert merge.source_resource_id == higher_id
    assert merge.target_resource_id == lower_id
    assert uow.events == [
        "enter",
        f"resources.get_for_update:{lower_id}",
        f"resources.get_for_update:{higher_id}",
        "resource_merges.get_outgoing_merge",
        "resource_merges.add",
        "commit",
        "exit",
    ]


def test_opposite_direction_requests_same_physical_lock_order() -> None:
    lower_id = UUID("01984000-0000-7000-8000-000000000001")
    higher_id = UUID("01984000-0000-7000-8000-000000000002")
    first_command = _command(source_resource_id=lower_id, target_resource_id=higher_id)
    second_command = _command(source_resource_id=higher_id, target_resource_id=lower_id)
    first_uow = _uow_for_command(first_command)
    second_uow = _uow_for_command(second_command)

    MergeResourceHandler(FakeUnitOfWorkFactory(first_uow)).handle(first_command)
    MergeResourceHandler(FakeUnitOfWorkFactory(second_uow)).handle(second_command)

    first_locks = [
        event for event in first_uow.events if event.startswith("resources.get_for_update")
    ]
    second_locks = [
        event for event in second_uow.events if event.startswith("resources.get_for_update")
    ]
    assert first_locks == [
        f"resources.get_for_update:{lower_id}",
        f"resources.get_for_update:{higher_id}",
    ]
    assert second_locks == first_locks
    assert second_uow.resource_merges.added[0].source_resource_id == higher_id
    assert second_uow.resource_merges.added[0].target_resource_id == lower_id


def test_missing_source_reports_semantic_role_even_when_locked_second() -> None:
    lower_id = UUID("01984000-0000-7000-8000-000000000001")
    higher_id = UUID("01984000-0000-7000-8000-000000000002")
    command = _command(source_resource_id=higher_id, target_resource_id=lower_id)
    uow = _uow_for_command(command, source_exists=False)
    handler = MergeResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "source_resource_id"
    assert exc_info.value.lookup_value == higher_id
    assert uow.events == [
        "enter",
        f"resources.get_for_update:{lower_id}",
        f"resources.get_for_update:{higher_id}",
        "exit",
    ]
    assert uow.resource_merges.added == []
    assert uow.commits == 0


def test_missing_target_reports_semantic_role_even_when_locked_first() -> None:
    lower_id = UUID("01984000-0000-7000-8000-000000000001")
    higher_id = UUID("01984000-0000-7000-8000-000000000002")
    command = _command(source_resource_id=higher_id, target_resource_id=lower_id)
    uow = _uow_for_command(command, target_exists=False)
    handler = MergeResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "target_resource_id"
    assert exc_info.value.lookup_value == lower_id
    assert uow.events == ["enter", f"resources.get_for_update:{lower_id}", "exit"]
    assert uow.resource_merges.added == []
    assert uow.commits == 0


def test_existing_outgoing_merge_is_rejected_before_mutation() -> None:
    command = _command()
    outgoing = SimpleNamespace(source_resource_id=command.source_resource_id)
    uow = _uow_for_command(command, outgoing=outgoing)
    handler = MergeResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceMerge"
    assert exc_info.value.conflict_field == "source_resource_id"
    assert exc_info.value.conflict_value == command.source_resource_id
    assert str(exc_info.value) == "Resource is already merged"
    assert uow.resource_merges.added == []
    assert uow.commits == 0
    assert uow.events[-2:] == [
        "resource_merges.get_outgoing_merge",
        "exit",
    ]


def test_successful_merge_adds_one_edge_and_commits_last() -> None:
    command = _command(reason=None, source=None)
    uow = _uow_for_command(command)
    handler = MergeResourceHandler(FakeUnitOfWorkFactory(uow))
    expected_locks = [
        f"resources.get_for_update:{resource_id}"
        for resource_id in sorted(
            (command.source_resource_id, command.target_resource_id),
            key=str,
        )
    ]

    result = handler.handle(command)

    assert result.merge_id == uow.resource_merges.added[0].id
    assert result.source_resource_id == command.source_resource_id
    assert result.target_resource_id == command.target_resource_id
    assert result.merged_at == command.merged_at
    assert result.reason is None
    assert result.source is None
    assert len(uow.resource_merges.added) == 1
    merge = uow.resource_merges.added[0]
    assert merge.tenant_id == command.tenant_id
    assert merge.source_resource_id == command.source_resource_id
    assert merge.target_resource_id == command.target_resource_id
    assert merge.reason is None
    assert merge.source is None
    assert merge.merged_at == command.merged_at
    assert uow.resource_merges.flushes == 0
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        *expected_locks,
        "resource_merges.get_outgoing_merge",
        "resource_merges.add",
        "commit",
        "exit",
    ]


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = MergeResourceHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.merge_id == succeeding_uow.resource_merges.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = MergeResourceHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_tenant_resources(session: Session, count: int = 3) -> tuple[UUID, list[UUID]]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    resources = [
        _resource(session, tenant.id, _slug(f"resource-{index}"))
        for index in range(count)
    ]
    session.add_all(resources)
    session.flush()
    return tenant.id, [resource.id for resource in resources]


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


def _merge(
    tenant_id: UUID,
    source_resource_id: UUID,
    target_resource_id: UUID,
    *,
    reason: str | None = "duplicate",
    source: str | None = "manual",
    merged_at: datetime | None = None,
) -> ResourceMerge:
    return ResourceMerge(
        tenant_id=tenant_id,
        source_resource_id=source_resource_id,
        target_resource_id=target_resource_id,
        reason=reason,
        source=source,
        merged_at=merged_at or _now(),
    )


def _merge_count(session: Session, tenant_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceMerge)
            .where(ResourceMerge.tenant_id == tenant_id)
        )
        or 0
    )


def test_sqlalchemy_successful_merge_persists_and_reads_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=2)
        source_id, target_id = resource_ids
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        source_resource_id=source_id,
        target_resource_id=target_id,
        reason="duplicate",
        source="manual",
        merged_at=_now(-5),
    )
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    with SessionLocal() as verification:
        merge = verification.get(ResourceMerge, result.merge_id)
        assert merge is not None
        assert merge.tenant_id == tenant_id
        assert merge.source_resource_id == source_id
        assert merge.target_resource_id == target_id
        assert merge.reason == "duplicate"
        assert merge.source == "manual"
        assert merge.merged_at == command.merged_at
        assert _merge_count(verification, tenant_id) == 1

        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            outgoing = uow.resource_merges.get_outgoing_merge(tenant_id, source_id)
            incoming = uow.resource_merges.list_incoming_merges(tenant_id, target_id)
            assert outgoing is not None
            assert outgoing.id == result.merge_id
            assert [row.id for row in incoming] == [result.merge_id]

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, source_id)
    )
    assert details.outgoing_merge is not None
    assert details.outgoing_merge.id == result.merge_id
    assert details.outgoing_merge.source_resource_id == source_id
    assert details.outgoing_merge.target_resource_id == target_id


def test_sqlalchemy_wrong_tenant_source_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=2)
        _, target_id = resource_ids
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.flush()
        other_source = _resource(setup_session, other_tenant.id, _slug("other-source"))
        setup_session.add(other_source)
        setup_session.commit()
        other_source_id = other_source.id
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=other_source_id,
                target_resource_id=target_id,
            )
        )

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "source_resource_id"
    with SessionLocal() as verification:
        assert _merge_count(verification, tenant_id) == 0


def test_sqlalchemy_wrong_tenant_target_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=2)
        source_id, _ = resource_ids
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.flush()
        other_target = _resource(setup_session, other_tenant.id, _slug("other-target"))
        setup_session.add(other_target)
        setup_session.commit()
        other_target_id = other_target.id
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=source_id,
                target_resource_id=other_target_id,
            )
        )

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "target_resource_id"
    with SessionLocal() as verification:
        assert _merge_count(verification, tenant_id) == 0


def test_sqlalchemy_existing_outgoing_source_merge_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        source_id, first_target_id, second_target_id = resource_ids
        setup_session.add(_merge(tenant_id, source_id, first_target_id))
        setup_session.commit()
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=source_id,
                target_resource_id=second_target_id,
            )
        )

    assert exc_info.value.entity_type == "ResourceMerge"
    assert exc_info.value.conflict_field == "source_resource_id"
    with SessionLocal() as verification:
        assert _merge_count(verification, tenant_id) == 1
        existing = verification.scalar(
            select(ResourceMerge).where(
                ResourceMerge.tenant_id == tenant_id,
                ResourceMerge.source_resource_id == source_id,
            )
        )
        assert existing is not None
        assert existing.target_resource_id == first_target_id


def test_sqlalchemy_target_already_merged_onward_allows_immediate_target_chain(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        source_id, target_id, terminal_id = resource_ids
        setup_session.add(_merge(tenant_id, target_id, terminal_id, merged_at=_now(-20)))
        setup_session.commit()
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_id,
            target_resource_id=target_id,
            merged_at=_now(-10),
        )
    )

    with SessionLocal() as verification:
        edges = list(
            verification.scalars(
                select(ResourceMerge)
                .where(ResourceMerge.tenant_id == tenant_id)
                .order_by(ResourceMerge.source_resource_id)
            )
        )
        assert {(edge.source_resource_id, edge.target_resource_id) for edge in edges} == {
            (source_id, target_id),
            (target_id, terminal_id),
        }
        assert verification.get(ResourceMerge, result.merge_id).target_resource_id == target_id


def test_sqlalchemy_direct_cycle_rejected_by_database_and_transaction_recovers(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        first_id, second_id, third_id = resource_ids
        setup_session.add(_merge(tenant_id, first_id, second_id))
        setup_session.commit()
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(IntegrityError):
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=second_id,
                target_resource_id=first_id,
            )
        )

    with SessionLocal() as verification:
        assert _merge_count(verification, tenant_id) == 1

    result = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=third_id,
            target_resource_id=first_id,
        )
    )
    with SessionLocal() as verification:
        assert verification.get(ResourceMerge, result.merge_id) is not None


def test_sqlalchemy_deeper_cycle_rejected_by_database_and_rolls_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=4)
        first_id, second_id, third_id, fourth_id = resource_ids
        setup_session.add(_merge(tenant_id, first_id, second_id))
        setup_session.add(_merge(tenant_id, second_id, third_id))
        setup_session.commit()
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(IntegrityError):
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=third_id,
                target_resource_id=first_id,
            )
        )

    with SessionLocal() as verification:
        assert _merge_count(verification, tenant_id) == 2

    result = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=fourth_id,
            target_resource_id=first_id,
        )
    )
    with SessionLocal() as verification:
        assert verification.get(ResourceMerge, result.merge_id) is not None


def test_sqlalchemy_duplicate_source_conflict_translates_and_rolls_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        source_id, first_target_id, second_target_id = resource_ids
        setup_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            uow.resource_merges.add(_merge(tenant_id, source_id, first_target_id))
            uow.resource_merges.add(_merge(tenant_id, source_id, second_target_id))
            uow.commit()

    error = exc_info.value
    assert str(error) == "Resource merge already exists for the source resource"
    assert error.entity_type == "ResourceMerge"
    assert error.conflict_field == "source_resource_id"
    assert error.constraint == "uq_resource_merge_tenant_source_resource_id"
    assert isinstance(error.__cause__, IntegrityError)
    with SessionLocal() as verification:
        assert _merge_count(verification, tenant_id) == 0

    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_id,
            target_resource_id=first_target_id,
        )
    )


def test_sqlalchemy_merge_is_lineage_only_and_does_not_move_dependent_facts(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        source_id, target_id, related_id = resource_ids
        alias = ResourceAlias(
            tenant_id=tenant_id,
            resource_id=source_id,
            alias_type="hostname",
            alias_value="source.example.com",
            normalized_value="source.example.com",
            first_seen_at=_now(-20),
            last_seen_at=_now(-10),
            source="manual",
        )
        identifier = ResourceIdentifier(
            tenant_id=tenant_id,
            resource_id=source_id,
            identifier_type_id=_catalog_id(setup_session, IdentifierType, "fqdn"),
            namespace=None,
            normalized_value="source.example.com",
            original_value="source.example.com",
            value_hash="hash-source",
            is_primary=True,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-20),
        )
        label = Label(tenant_id=tenant_id, key=_slug("label"), value="Source")
        setup_session.add(label)
        setup_session.flush()
        resource_label = ResourceLabel(
            tenant_id=tenant_id,
            resource_id=source_id,
            label_id=label.id,
            valid_from=_now(-20),
            source="manual",
        )
        relationship = ResourceRelationship(
            tenant_id=tenant_id,
            source_resource_id=source_id,
            target_resource_id=related_id,
            relationship_type_id=_catalog_id(setup_session, RelationshipType, "depends_on"),
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-20),
            source="manual",
        )
        setup_session.add_all([alias, identifier, resource_label, relationship])
        source_resource = setup_session.get(Resource, source_id)
        target_resource = setup_session.get(Resource, target_id)
        assert source_resource is not None
        assert target_resource is not None
        source_snapshot = (
            source_resource.canonical_name,
            source_resource.display_name,
            source_resource.record_version,
            source_resource.lifecycle_status_id,
            source_resource.criticality_id,
            source_resource.exposure_level_id,
            source_resource.source_priority,
            source_resource.confidence_score,
        )
        target_snapshot = (
            target_resource.canonical_name,
            target_resource.display_name,
            target_resource.record_version,
            target_resource.lifecycle_status_id,
            target_resource.criticality_id,
            target_resource.exposure_level_id,
            target_resource.source_priority,
            target_resource.confidence_score,
        )
        setup_session.commit()
        alias_id = alias.id
        identifier_id = identifier.id
        resource_label_id = resource_label.id
        relationship_id = relationship.id
    handler = MergeResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_id,
            target_resource_id=target_id,
        )
    )

    with SessionLocal() as verification:
        assert verification.get(ResourceAlias, alias_id).resource_id == source_id
        assert verification.get(ResourceIdentifier, identifier_id).resource_id == source_id
        assert verification.get(ResourceLabel, resource_label_id).resource_id == source_id
        assert (
            verification.get(ResourceRelationship, relationship_id).source_resource_id
            == source_id
        )
        source_after = verification.get(Resource, source_id)
        target_after = verification.get(Resource, target_id)
        assert source_after is not None
        assert target_after is not None
        assert (
            source_after.canonical_name,
            source_after.display_name,
            source_after.record_version,
            source_after.lifecycle_status_id,
            source_after.criticality_id,
            source_after.exposure_level_id,
            source_after.source_priority,
            source_after.confidence_score,
        ) == source_snapshot
        assert (
            target_after.canonical_name,
            target_after.display_name,
            target_after.record_version,
            target_after.lifecycle_status_id,
            target_after.criticality_id,
            target_after.exposure_level_id,
            target_after.source_priority,
            target_after.confidence_score,
        ) == target_snapshot
