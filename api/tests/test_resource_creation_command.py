from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.commands import CreateResourceCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import (
    CreateResourceHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceDetailsHandler,
)
from app.application.queries import (
    GetResourceByCanonicalNameQuery,
    GetResourceDetailsQuery,
)
from app.application.results import ResourceCreatedResult
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Resource,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


class FakeTenantRepository:
    def __init__(self, events: list[str], tenants: set[UUID]) -> None:
        self._events = events
        self._tenants = tenants

    def get_by_id(self, tenant_id: UUID) -> object | None:
        self._events.append("tenants.get_by_id")
        return object() if tenant_id in self._tenants else None


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


class FakeResourceRepository:
    def __init__(
        self,
        events: list[str],
        existing_names: set[tuple[UUID, str]],
        *,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._existing_names = existing_names
        self._fail_on_add = fail_on_add
        self.added: list[Resource] = []
        self.flushes = 0

    def get_by_canonical_name(
        self,
        tenant_id: UUID,
        canonical_name: str,
    ) -> object | None:
        self._events.append("resources.get_by_canonical_name")
        if (tenant_id, canonical_name) in self._existing_names:
            return object()
        return None

    def add(self, resource: Resource) -> None:
        self._events.append("resources.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(resource)

    def flush(self) -> None:
        self._events.append("resources.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_ids: set[UUID],
        resource_type: object,
        lifecycle_status: object,
        criticality: object,
        exposure_level: object,
        existing_names: set[tuple[UUID, str]] = frozenset(),
        fail_on_add: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self._fail_on_commit = fail_on_commit
        self.tenants = FakeTenantRepository(self.events, tenant_ids)
        self.resource_types = FakeCatalogRepository(
            self.events,
            "resource_types.get_by_id",
            {resource_type.id: resource_type},
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
        self.resources = FakeResourceRepository(
            self.events,
            existing_names,
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
    resource_type_id: UUID | None = None,
    lifecycle_status_id: UUID | None = None,
    criticality_id: UUID | None = None,
    exposure_level_id: UUID | None = None,
    canonical_name: str = "example.com",
    display_name: str = "Example",
    source_priority: int = 100,
    confidence_score: Decimal = Decimal("0.9000"),
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> CreateResourceCommand:
    first_seen_at = first_seen_at or _now(-2)
    last_seen_at = last_seen_at or _now(-1)
    return CreateResourceCommand(
        tenant_id=tenant_id or uuid4(),
        resource_type_id=resource_type_id or uuid4(),
        canonical_name=canonical_name,
        display_name=display_name,
        lifecycle_status_id=lifecycle_status_id or uuid4(),
        criticality_id=criticality_id or uuid4(),
        exposure_level_id=exposure_level_id or uuid4(),
        source_priority=source_priority,
        confidence_score=confidence_score,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


def _uow_for_command(
    command: CreateResourceCommand,
    *,
    existing_names: set[tuple[UUID, str]] = frozenset(),
    resource_type_active: bool = True,
    lifecycle_status_active: bool = True,
    criticality_active: bool = True,
    exposure_level_active: bool = True,
    tenant_exists: bool = True,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    resource_type = SimpleNamespace(
        id=command.resource_type_id,
        is_active=resource_type_active,
    )
    lifecycle_status = SimpleNamespace(
        id=command.lifecycle_status_id,
        is_active=lifecycle_status_active,
    )
    criticality = SimpleNamespace(id=command.criticality_id, is_active=criticality_active)
    exposure_level = SimpleNamespace(
        id=command.exposure_level_id,
        is_active=exposure_level_active,
    )
    return FakeUnitOfWork(
        tenant_ids={command.tenant_id} if tenant_exists else set(),
        resource_type=resource_type,
        lifecycle_status=lifecycle_status,
        criticality=criticality,
        exposure_level=exposure_level,
        existing_names=existing_names,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def test_create_resource_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "resource_type_id",
        "canonical_name",
        "display_name",
        "lifecycle_status_id",
        "criticality_id",
        "exposure_level_id",
        "source_priority",
        "confidence_score",
        "first_seen_at",
        "last_seen_at",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.canonical_name = "changed.example.com"


def test_resource_created_result_is_immutable_and_entity_free() -> None:
    result = ResourceCreatedResult(
        resource_id=uuid4(),
        tenant_id=uuid4(),
        canonical_name="example.com",
        record_version=1,
    )

    assert is_dataclass(result)
    assert not isinstance(result, Resource)
    with pytest.raises(FrozenInstanceError):
        result.record_version = 2


@pytest.mark.parametrize(
    ("command", "expected_fields"),
    (
        (_command(canonical_name=""), ("canonical_name",)),
        (_command(canonical_name="   "), ("canonical_name",)),
        (_command(display_name=""), ("display_name",)),
        (_command(source_priority=-1), ("source_priority",)),
        (_command(source_priority=1001), ("source_priority",)),
        (_command(confidence_score=Decimal("-0.0001")), ("confidence_score",)),
        (_command(confidence_score=Decimal("1.0001")), ("confidence_score",)),
        (
            _command(first_seen_at=datetime(2026, 1, 1), last_seen_at=_now()),
            ("first_seen_at",),
        ),
        (
            _command(first_seen_at=_now(), last_seen_at=datetime(2026, 1, 1)),
            ("last_seen_at",),
        ),
        (
            _command(first_seen_at=_now(), last_seen_at=_now(-5)),
            ("last_seen_at",),
        ),
    ),
)
def test_validation_failures_happen_before_unit_of_work_creation(
    command: CreateResourceCommand,
    expected_fields: tuple[str, ...],
) -> None:
    factory = FakeUnitOfWorkFactory(_uow_for_command(_command()))
    handler = CreateResourceHandler(factory)

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields
    assert factory.created == []


def test_validation_gathers_deterministic_input_failures() -> None:
    command = _command(
        canonical_name=" ",
        display_name="",
        source_priority=1001,
        confidence_score=Decimal("-1"),
    )
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(_uow_for_command(_command())))

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "canonical_name",
        "display_name",
        "source_priority",
        "confidence_score",
    )


def test_missing_tenant_raises_entity_not_found_without_mutation() -> None:
    command = _command()
    uow = _uow_for_command(command, tenant_exists=False)
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Tenant"
    assert exc_info.value.lookup_field == "tenant_id"
    assert exc_info.value.lookup_value == command.tenant_id
    assert uow.resources.added == []
    assert uow.commits == 0
    assert uow.events == ["enter", "tenants.get_by_id", "exit"]


@pytest.mark.parametrize(
    ("missing_field", "entity_type", "event_name"),
    (
        ("resource_type_id", "ResourceType", "resource_types.get_by_id"),
        ("lifecycle_status_id", "LifecycleStatus", "lifecycle_statuses.get_by_id"),
        ("criticality_id", "Criticality", "criticalities.get_by_id"),
        ("exposure_level_id", "ExposureLevel", "exposure_levels.get_by_id"),
    ),
)
def test_missing_catalog_raises_entity_not_found_without_mutation(
    missing_field: str,
    entity_type: str,
    event_name: str,
) -> None:
    command = _command()
    uow = _uow_for_command(command)
    catalog = getattr(uow, {
        "resource_type_id": "resource_types",
        "lifecycle_status_id": "lifecycle_statuses",
        "criticality_id": "criticalities",
        "exposure_level_id": "exposure_levels",
    }[missing_field])
    catalog._catalogs.clear()
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == entity_type
    assert exc_info.value.lookup_field == missing_field
    assert event_name in uow.events
    assert "resources.add" not in uow.events
    assert uow.commits == 0


@pytest.mark.parametrize(
    "inactive_flag",
    (
        "resource_type_active",
        "lifecycle_status_active",
        "criticality_active",
        "exposure_level_active",
    ),
)
def test_inactive_catalog_raises_conflict_without_mutation(inactive_flag: str) -> None:
    command = _command()
    uow = _uow_for_command(command, **{inactive_flag: False})
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type in {
        "ResourceType",
        "LifecycleStatus",
        "Criticality",
        "ExposureLevel",
    }
    assert "resources.add" not in uow.events
    assert uow.commits == 0


def test_same_tenant_canonical_conflict_prevents_add_flush_and_commit() -> None:
    command = _command(canonical_name="example.com")
    uow = _uow_for_command(
        command,
        existing_names={(command.tenant_id, command.canonical_name)},
    )
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.conflict_field == "canonical_name"
    assert exc_info.value.conflict_value == command.canonical_name
    assert uow.resources.added == []
    assert uow.resources.flushes == 0
    assert uow.commits == 0


def test_other_tenant_canonical_name_does_not_conflict() -> None:
    command = _command(canonical_name="shared.example.com")
    uow = _uow_for_command(
        command,
        existing_names={(uuid4(), command.canonical_name)},
    )
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.canonical_name == command.canonical_name
    assert len(uow.resources.added) == 1
    assert uow.commits == 1


def test_successful_creation_uses_expected_event_order_and_commit_last() -> None:
    command = _command()
    uow = _uow_for_command(command)
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.resource_id == uow.resources.added[0].id
    assert result.tenant_id == command.tenant_id
    assert result.canonical_name == command.canonical_name
    assert result.record_version == 1
    assert len(uow.resources.added) == 1
    assert uow.resources.flushes == 0
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        "tenants.get_by_id",
        "resource_types.get_by_id",
        "lifecycle_statuses.get_by_id",
        "criticalities.get_by_id",
        "exposure_levels.get_by_id",
        "resources.get_by_canonical_name",
        "resources.add",
        "commit",
        "exit",
    ]


def test_repository_failure_propagates_and_next_execution_uses_fresh_unit() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = CreateResourceHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.resource_id == succeeding_uow.resources.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = CreateResourceHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_tenant_and_catalogs(session: Session) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    return (
        tenant.id,
        _catalog_id(session, ResourceType, "domain"),
        _catalog_id(session, LifecycleStatus, "active"),
        _catalog_id(session, Criticality, "medium"),
        _catalog_id(session, ExposureLevel, "public"),
    )


def _resource_count(engine: Engine, tenant_id: UUID, canonical_name: str) -> int:
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(Resource)
                .where(
                    Resource.tenant_id == tenant_id,
                    Resource.canonical_name == canonical_name,
                )
            )
            or 0
        )


def test_sqlalchemy_resource_creation_persists_and_reads_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        (
            tenant_id,
            resource_type_id,
            lifecycle_status_id,
            criticality_id,
            exposure_level_id,
        ) = _seed_tenant_and_catalogs(setup_session)
        setup_session.commit()

    command = _command(
        tenant_id=tenant_id,
        resource_type_id=resource_type_id,
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        canonical_name=_slug("resource"),
        display_name="Created Resource",
    )
    handler = CreateResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    assert result.tenant_id == tenant_id
    assert result.canonical_name == command.canonical_name
    assert result.record_version == 1
    with SessionLocal() as verification:
        resource = verification.get(Resource, result.resource_id)
        assert resource is not None
        assert resource.tenant_id == command.tenant_id
        assert resource.resource_type_id == command.resource_type_id
        assert resource.canonical_name == command.canonical_name
        assert resource.display_name == command.display_name
        assert resource.lifecycle_status_id == command.lifecycle_status_id
        assert resource.criticality_id == command.criticality_id
        assert resource.exposure_level_id == command.exposure_level_id
        assert resource.source_priority == command.source_priority
        assert resource.confidence_score == command.confidence_score
        assert resource.first_seen_at == command.first_seen_at
        assert resource.last_seen_at == command.last_seen_at
        assert resource.record_version == 1

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, result.resource_id),
    )
    canonical = GetResourceByCanonicalNameHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal),
    ).handle(GetResourceByCanonicalNameQuery(tenant_id, command.canonical_name))
    assert details.id == result.resource_id
    assert details.identifiers == ()
    assert details.state is None
    assert canonical.id == result.resource_id


def test_sqlalchemy_same_canonical_name_across_tenants_is_allowed(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        refs_a = _seed_tenant_and_catalogs(setup_session)
        refs_b = _seed_tenant_and_catalogs(setup_session)
        setup_session.commit()
    canonical_name = _slug("shared")
    handler = CreateResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(
        _command(
            tenant_id=refs_a[0],
            resource_type_id=refs_a[1],
            lifecycle_status_id=refs_a[2],
            criticality_id=refs_a[3],
            exposure_level_id=refs_a[4],
            canonical_name=canonical_name,
        )
    )
    second = handler.handle(
        _command(
            tenant_id=refs_b[0],
            resource_type_id=refs_b[1],
            lifecycle_status_id=refs_b[2],
            criticality_id=refs_b[3],
            exposure_level_id=refs_b[4],
            canonical_name=canonical_name,
        )
    )

    assert first.resource_id != second.resource_id
    assert _resource_count(migrated_engine, refs_a[0], canonical_name) == 1
    assert _resource_count(migrated_engine, refs_b[0], canonical_name) == 1


def test_sqlalchemy_same_tenant_duplicate_is_rejected_by_precheck(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        refs = _seed_tenant_and_catalogs(setup_session)
        setup_session.commit()
    canonical_name = _slug("duplicate")
    command = _command(
        tenant_id=refs[0],
        resource_type_id=refs[1],
        lifecycle_status_id=refs[2],
        criticality_id=refs[3],
        exposure_level_id=refs[4],
        canonical_name=canonical_name,
    )
    handler = CreateResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    handler.handle(command)

    with pytest.raises(ConflictError):
        handler.handle(command)

    assert _resource_count(migrated_engine, refs[0], canonical_name) == 1


def test_sqlalchemy_validation_failure_leaves_no_partial_resource_and_fresh_uow_works(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        refs = _seed_tenant_and_catalogs(setup_session)
        setup_session.commit()
    handler = CreateResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    bad_name = _slug("bad")

    with pytest.raises(EntityNotFoundError):
        handler.handle(
            _command(
                tenant_id=refs[0],
                resource_type_id=uuid4(),
                lifecycle_status_id=refs[2],
                criticality_id=refs[3],
                exposure_level_id=refs[4],
                canonical_name=bad_name,
            )
        )

    assert _resource_count(migrated_engine, refs[0], bad_name) == 0
    good = handler.handle(
        _command(
            tenant_id=refs[0],
            resource_type_id=refs[1],
            lifecycle_status_id=refs[2],
            criticality_id=refs[3],
            exposure_level_id=refs[4],
            canonical_name=_slug("good"),
        )
    )
    assert good.resource_id is not None
