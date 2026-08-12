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

from app.application.commands import AssignResourceAliasCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import AssignResourceAliasHandler, GetResourceDetailsHandler
from app.application.queries import GetResourceDetailsQuery
from app.application.results import ResourceAliasAssignedResult
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Resource,
    ResourceAlias,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork
from app.persistence.sqlalchemy.repositories import SQLAlchemyResourceAliasRepository


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


class FakeResourceAliasRepository:
    def __init__(
        self,
        events: list[str],
        *,
        existing_resource: object | None = None,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._existing_resource = existing_resource
        self._fail_on_add = fail_on_add
        self.added: list[ResourceAlias] = []
        self.flushes = 0

    def find_resource_by_alias(
        self,
        tenant_id: UUID,
        alias_type: str,
        normalized_value: str,
    ) -> object | None:
        self._events.append("resource_aliases.find_resource_by_alias")
        return self._existing_resource

    def add(self, alias: ResourceAlias) -> None:
        self._events.append("resource_aliases.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(alias)

    def flush(self) -> None:
        self._events.append("resource_aliases.flush")
        self.flushes += 1


class FakeResourceMergeRepository:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.added: list[object] = []

    def add(self, merge: object) -> None:
        self._events.append("resource_merges.add")
        self.added.append(merge)


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        resource_id: UUID,
        resource_exists: bool = True,
        existing_alias_resource_id: UUID | None = None,
        fail_on_add: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self._fail_on_commit = fail_on_commit
        self.resource = SimpleNamespace(id=resource_id, tenant_id=tenant_id)
        self.existing_alias_resource = (
            SimpleNamespace(id=existing_alias_resource_id, tenant_id=tenant_id)
            if existing_alias_resource_id is not None
            else None
        )
        self.resources = FakeResourceRepository(
            self.events,
            {(tenant_id, resource_id): self.resource} if resource_exists else {},
        )
        self.resource_aliases = FakeResourceAliasRepository(
            self.events,
            existing_resource=self.existing_alias_resource,
            fail_on_add=fail_on_add,
        )
        self.resource_merges = FakeResourceMergeRepository(self.events)

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
    alias_type: str = "hostname",
    alias_value: str = "Example.COM",
    normalized_value: str = "example.com",
    source: str | None = "manual",
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> AssignResourceAliasCommand:
    first_seen_at = first_seen_at or _now(-10)
    last_seen_at = last_seen_at or _now(-5)
    return AssignResourceAliasCommand(
        tenant_id=tenant_id or uuid4(),
        resource_id=resource_id or uuid4(),
        alias_type=alias_type,
        alias_value=alias_value,
        normalized_value=normalized_value,
        source=source,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


def _uow_for_command(
    command: AssignResourceAliasCommand,
    *,
    resource_exists: bool = True,
    existing_alias_resource_id: UUID | None = None,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        resource_exists=resource_exists,
        existing_alias_resource_id=existing_alias_resource_id,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def test_assign_resource_alias_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "resource_id",
        "alias_type",
        "alias_value",
        "normalized_value",
        "source",
        "first_seen_at",
        "last_seen_at",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.alias_value = "changed"


def test_resource_alias_assigned_result_is_immutable_and_entity_free() -> None:
    result = ResourceAliasAssignedResult(
        alias_id=uuid4(),
        resource_id=uuid4(),
        alias_type="hostname",
        alias_value="Example.COM",
        normalized_value="example.com",
        first_seen_at=_now(-10),
        last_seen_at=_now(-5),
        source="manual",
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceAlias)
    with pytest.raises(FrozenInstanceError):
        result.alias_value = "changed"


@pytest.mark.parametrize(
    ("command", "expected_fields"),
    (
        (_command(alias_type=""), ("alias_type",)),
        (_command(alias_type="   "), ("alias_type",)),
        (_command(alias_value=""), ("alias_value",)),
        (_command(alias_value="   "), ("alias_value",)),
        (_command(normalized_value=""), ("normalized_value",)),
        (_command(normalized_value="   "), ("normalized_value",)),
        (_command(source=""), ("source",)),
        (_command(source="   "), ("source",)),
        (_command(first_seen_at=datetime(2026, 1, 1)), ("first_seen_at",)),
        (_command(last_seen_at=datetime(2026, 1, 1)), ("last_seen_at",)),
        (
            _command(first_seen_at=_now(5), last_seen_at=_now(-5)),
            ("last_seen_at",),
        ),
    ),
)
def test_pre_uow_validation_failures_do_not_create_unit_of_work(
    command: AssignResourceAliasCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = AssignResourceAliasHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_pre_uow_validation_gathers_deterministic_failures() -> None:
    command = _command(
        alias_type=" ",
        alias_value=" ",
        normalized_value=" ",
        source=" ",
        first_seen_at=datetime(2026, 1, 1),
        last_seen_at=datetime(2025, 1, 1),
    )
    handler = AssignResourceAliasHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "alias_type",
        "alias_value",
        "normalized_value",
        "source",
        "first_seen_at",
        "last_seen_at",
    )


def test_missing_resource_stops_before_alias_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceAliasHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == command.resource_id
    assert uow.events == ["enter", "resources.get_for_update", "exit"]
    assert uow.resource_aliases.added == []
    assert uow.commits == 0


def test_successful_assignment_adds_one_alias_and_commits_last() -> None:
    command = _command(
        alias_type="dns_name",
        alias_value=" Example.COM ",
        normalized_value="example.com",
        source=None,
    )
    uow = _uow_for_command(command)
    handler = AssignResourceAliasHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.alias_id == uow.resource_aliases.added[0].id
    assert result.resource_id == command.resource_id
    assert result.alias_type == "dns_name"
    assert result.alias_value == " Example.COM "
    assert result.normalized_value == "example.com"
    assert result.first_seen_at == command.first_seen_at
    assert result.last_seen_at == command.last_seen_at
    assert result.source is None
    assert len(uow.resource_aliases.added) == 1
    alias = uow.resource_aliases.added[0]
    assert alias.tenant_id == command.tenant_id
    assert alias.resource_id == command.resource_id
    assert alias.alias_type == command.alias_type
    assert alias.alias_value == command.alias_value
    assert alias.normalized_value == command.normalized_value
    assert alias.source is None
    assert alias.first_seen_at == command.first_seen_at
    assert alias.last_seen_at == command.last_seen_at
    assert uow.resource_aliases.flushes == 0
    assert uow.resource_merges.added == []
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "resource_aliases.find_resource_by_alias",
        "resource_aliases.add",
        "commit",
        "exit",
    ]


def test_same_resource_duplicate_is_rejected_before_mutation() -> None:
    command = _command()
    uow = _uow_for_command(command, existing_alias_resource_id=command.resource_id)
    handler = AssignResourceAliasHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceAlias"
    assert exc_info.value.conflict_field == "alias"
    assert exc_info.value.conflict_value == command.normalized_value
    assert str(exc_info.value) == "Resource alias is already assigned"
    assert uow.resource_aliases.added == []
    assert uow.resource_merges.added == []
    assert uow.commits == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "resource_aliases.find_resource_by_alias",
        "exit",
    ]


def test_different_resource_collision_is_rejected_before_mutation() -> None:
    command = _command()
    other_resource_id = uuid4()
    uow = _uow_for_command(command, existing_alias_resource_id=other_resource_id)
    handler = AssignResourceAliasHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceAlias"
    assert exc_info.value.conflict_field == "alias"
    assert exc_info.value.conflict_value == command.normalized_value
    assert str(exc_info.value) == (
        "Resource alias is already assigned to another Resource"
    )
    assert uow.resource_aliases.added == []
    assert uow.resource_merges.added == []
    assert uow.commits == 0


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = AssignResourceAliasHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.alias_id == succeeding_uow.resource_aliases.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = AssignResourceAliasHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_tenant_resources(session: Session) -> tuple[UUID, UUID, UUID]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    resource = _resource(session, tenant.id, _slug("resource"))
    other_resource = _resource(session, tenant.id, _slug("other"))
    session.add_all([resource, other_resource])
    session.flush()
    return tenant.id, resource.id, other_resource.id


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


def _alias_count(session: Session, tenant_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceAlias)
            .where(ResourceAlias.tenant_id == tenant_id)
        )
        or 0
    )


def _alias(
    tenant_id: UUID,
    resource_id: UUID,
    *,
    alias_type: str = "hostname",
    alias_value: str = "Example.COM",
    normalized_value: str = "example.com",
    source: str | None = "manual",
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> ResourceAlias:
    first_seen_at = first_seen_at or _now(-30)
    last_seen_at = last_seen_at or _now(-20)
    return ResourceAlias(
        tenant_id=tenant_id,
        resource_id=resource_id,
        alias_type=alias_type,
        alias_value=alias_value,
        normalized_value=normalized_value,
        source=source,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


def test_sqlalchemy_assignment_persists_and_reads_back_alias(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, _ = _seed_tenant_resources(setup_session)
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        alias_type="dns_name",
        alias_value=" Example.COM ",
        normalized_value="example.com",
        source="manual",
        first_seen_at=_now(-10),
        last_seen_at=_now(-5),
    )
    handler = AssignResourceAliasHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    with SessionLocal() as verification:
        alias = verification.get(ResourceAlias, result.alias_id)
        assert alias is not None
        assert alias.tenant_id == tenant_id
        assert alias.resource_id == resource_id
        assert alias.alias_type == "dns_name"
        assert alias.alias_value == " Example.COM "
        assert alias.normalized_value == "example.com"
        assert alias.source == "manual"
        assert alias.first_seen_at == command.first_seen_at
        assert alias.last_seen_at == command.last_seen_at
        assert _alias_count(verification, tenant_id) == 1

        resolved = SQLAlchemyResourceAliasRepository(
            verification
        ).find_resource_by_alias(tenant_id, "dns_name", "example.com")
        assert resolved is not None
        assert resolved.id == resource_id

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, resource_id)
    )
    assert len(details.aliases) == 1
    assert details.aliases[0].id == result.alias_id
    assert details.aliases[0].alias_type == "dns_name"
    assert details.aliases[0].alias_value == " Example.COM "
    assert details.aliases[0].normalized_value == "example.com"
    assert details.aliases[0].source == "manual"


def test_sqlalchemy_wrong_tenant_resource_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, _, _ = _seed_tenant_resources(setup_session)
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.flush()
        other_resource = _resource(setup_session, other_tenant.id, _slug("other"))
        setup_session.add(other_resource)
        setup_session.commit()
        other_resource_id = other_resource.id
    handler = AssignResourceAliasHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(_command(tenant_id=tenant_id, resource_id=other_resource_id))

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    with SessionLocal() as verification:
        assert _alias_count(verification, tenant_id) == 0


def test_sqlalchemy_same_resource_duplicate_does_not_update_existing_alias(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, _ = _seed_tenant_resources(setup_session)
        existing = _alias(
            tenant_id,
            resource_id,
            alias_value="Example.COM",
            source="original",
            first_seen_at=_now(-30),
            last_seen_at=_now(-20),
        )
        setup_session.add(existing)
        setup_session.commit()
        existing_id = existing.id
        original_alias_value = existing.alias_value
        original_source = existing.source
        original_first_seen_at = existing.first_seen_at
        original_last_seen_at = existing.last_seen_at
    handler = AssignResourceAliasHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                alias_value="Different.COM",
                normalized_value="example.com",
                source="changed",
                first_seen_at=_now(-10),
                last_seen_at=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceAlias"
    assert str(exc_info.value) == "Resource alias is already assigned"
    with SessionLocal() as verification:
        existing_after = verification.get(ResourceAlias, existing_id)
        assert existing_after is not None
        assert existing_after.alias_value == original_alias_value
        assert existing_after.source == original_source
        assert existing_after.first_seen_at == original_first_seen_at
        assert existing_after.last_seen_at == original_last_seen_at
        assert _alias_count(verification, tenant_id) == 1


def test_sqlalchemy_different_resource_collision_does_not_transfer_alias(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, other_resource_id = _seed_tenant_resources(setup_session)
        existing = _alias(tenant_id, other_resource_id)
        setup_session.add(existing)
        setup_session.commit()
        existing_id = existing.id
    handler = AssignResourceAliasHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                normalized_value="example.com",
            )
        )

    assert exc_info.value.entity_type == "ResourceAlias"
    assert str(exc_info.value) == (
        "Resource alias is already assigned to another Resource"
    )
    with SessionLocal() as verification:
        existing_after = verification.get(ResourceAlias, existing_id)
        assert existing_after is not None
        assert existing_after.resource_id == other_resource_id
        assert _alias_count(verification, tenant_id) == 1


def test_sqlalchemy_same_normalized_value_with_different_alias_type_is_allowed(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, _ = _seed_tenant_resources(setup_session)
        setup_session.commit()
    handler = AssignResourceAliasHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            alias_type="hostname",
            normalized_value="example.com",
        )
    )
    second = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            alias_type="dns_name",
            normalized_value="example.com",
        )
    )

    with SessionLocal() as verification:
        aliases = list(
            verification.scalars(
                select(ResourceAlias).where(ResourceAlias.tenant_id == tenant_id)
            )
        )
        assert {alias.id for alias in aliases} == {first.alias_id, second.alias_id}
        assert {alias.alias_type for alias in aliases} == {"hostname", "dns_name"}


def test_sqlalchemy_same_alias_identity_in_different_tenants_is_allowed(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, _ = _seed_tenant_resources(setup_session)
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.flush()
        other_resource = _resource(setup_session, other_tenant.id, _slug("other"))
        setup_session.add(other_resource)
        setup_session.commit()
        other_tenant_id = other_tenant.id
        other_resource_id = other_resource.id
    handler = AssignResourceAliasHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(_command(tenant_id=tenant_id, resource_id=resource_id))
    second = handler.handle(
        _command(tenant_id=other_tenant_id, resource_id=other_resource_id)
    )

    with SessionLocal() as verification:
        assert verification.get(ResourceAlias, first.alias_id) is not None
        assert verification.get(ResourceAlias, second.alias_id) is not None


def test_sqlalchemy_unique_alias_conflict_translates_and_rolls_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, other_resource_id = _seed_tenant_resources(setup_session)
        setup_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            first = _alias(tenant_id, resource_id)
            second = _alias(tenant_id, other_resource_id)
            uow.resource_aliases.add(first)
            uow.resource_aliases.add(second)
            uow.commit()

    error = exc_info.value
    assert str(error) == "Resource alias already resolves to a resource"
    assert error.entity_type == "ResourceAlias"
    assert error.conflict_field == "alias"
    assert error.constraint == "uq_resource_alias_tenant_alias_type_normalized_value"
    assert isinstance(error.__cause__, IntegrityError)
    with SessionLocal() as verification:
        assert _alias_count(verification, tenant_id) == 0

    handler = AssignResourceAliasHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    handler.handle(_command(tenant_id=tenant_id, resource_id=resource_id))
