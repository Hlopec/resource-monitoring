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

from app.application.commands import AssignResourceRelationshipCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import AssignResourceRelationshipHandler
from app.application.results import ResourceRelationshipAssignedResult
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    RelationshipType,
    Resource,
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


class FakeRelationshipTypeRepository:
    def __init__(self, events: list[str], relationship_types: dict[UUID, object]) -> None:
        self._events = events
        self._relationship_types = relationship_types

    def get_by_id(self, relationship_type_id: UUID) -> object | None:
        self._events.append("relationship_types.get_by_id")
        return self._relationship_types.get(relationship_type_id)


class FakeResourceRelationshipRepository:
    def __init__(
        self,
        events: list[str],
        *,
        current: ResourceRelationship | object | None = None,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._current = current
        self._fail_on_add = fail_on_add
        self.added: list[ResourceRelationship] = []
        self.flushes = 0

    def find_current(
        self,
        tenant_id: UUID,
        source_resource_id: UUID,
        relationship_type_id: UUID,
        target_resource_id: UUID,
    ) -> ResourceRelationship | object | None:
        self._events.append("resource_relationships.find_current")
        return self._current

    def add(self, relationship: ResourceRelationship) -> None:
        self._events.append("resource_relationships.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(relationship)

    def flush(self) -> None:
        self._events.append("resource_relationships.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        source_resource_id: UUID,
        target_resource_id: UUID,
        relationship_type_id: UUID,
        source_exists: bool = True,
        target_exists: bool = True,
        relationship_type_exists: bool = True,
        relationship_type_active: bool = True,
        current: ResourceRelationship | object | None = None,
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
        self.relationship_type = SimpleNamespace(
            id=relationship_type_id,
            is_active=relationship_type_active,
            source_type_constraint=None,
            target_type_constraint=None,
        )
        self.relationship_types = FakeRelationshipTypeRepository(
            self.events,
            (
                {relationship_type_id: self.relationship_type}
                if relationship_type_exists
                else {}
            ),
        )
        self.resource_relationships = FakeResourceRelationshipRepository(
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
    source_resource_id: UUID | None = None,
    target_resource_id: UUID | None = None,
    relationship_type_id: UUID | None = None,
    confidence_score: Decimal = Decimal("0.9000"),
    valid_from: datetime | None = None,
    source: str | None = "manual",
) -> AssignResourceRelationshipCommand:
    return AssignResourceRelationshipCommand(
        tenant_id=tenant_id or uuid4(),
        source_resource_id=source_resource_id or uuid4(),
        relationship_type_id=relationship_type_id or uuid4(),
        target_resource_id=target_resource_id or uuid4(),
        confidence_score=confidence_score,
        valid_from=valid_from or _now(),
        source=source,
    )


def _uow_for_command(
    command: AssignResourceRelationshipCommand,
    *,
    source_exists: bool = True,
    target_exists: bool = True,
    relationship_type_exists: bool = True,
    relationship_type_active: bool = True,
    current: ResourceRelationship | object | None = None,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        source_resource_id=command.source_resource_id,
        target_resource_id=command.target_resource_id,
        relationship_type_id=command.relationship_type_id,
        source_exists=source_exists,
        target_exists=target_exists,
        relationship_type_exists=relationship_type_exists,
        relationship_type_active=relationship_type_active,
        current=current,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def _current_relationship_for_command(
    command: AssignResourceRelationshipCommand,
    *,
    valid_to: datetime | None = None,
) -> ResourceRelationship:
    return ResourceRelationship(
        tenant_id=command.tenant_id,
        source_resource_id=command.source_resource_id,
        target_resource_id=command.target_resource_id,
        relationship_type_id=command.relationship_type_id,
        confidence_score=command.confidence_score,
        valid_from=_now(-10),
        valid_to=valid_to,
        source=command.source,
    )


def test_assign_resource_relationship_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "source_resource_id",
        "relationship_type_id",
        "target_resource_id",
        "confidence_score",
        "valid_from",
        "source",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.target_resource_id = uuid4()


def test_resource_relationship_assigned_result_is_immutable_and_entity_free() -> None:
    result = ResourceRelationshipAssignedResult(
        relationship_id=uuid4(),
        source_resource_id=uuid4(),
        relationship_type_id=uuid4(),
        target_resource_id=uuid4(),
        valid_from=_now(),
        source="manual",
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceRelationship)
    with pytest.raises(FrozenInstanceError):
        result.target_resource_id = uuid4()


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
    command: AssignResourceRelationshipCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_self_reference_is_rejected_before_unit_of_work() -> None:
    resource_id = uuid4()
    command = _command(source_resource_id=resource_id, target_resource_id=resource_id)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory())

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
        confidence_score=Decimal("1.0001"),
        valid_from=datetime(2026, 1, 1),
        source=" ",
    )
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "target_resource_id",
        "confidence_score",
        "valid_from",
        "source",
    )


def test_locks_resources_in_stable_order_while_preserving_direction() -> None:
    lower_id = UUID("01984000-0000-7000-8000-000000000001")
    higher_id = UUID("01984000-0000-7000-8000-000000000002")
    command = _command(source_resource_id=higher_id, target_resource_id=lower_id)
    uow = _uow_for_command(command)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.source_resource_id == higher_id
    assert result.target_resource_id == lower_id
    relationship = uow.resource_relationships.added[0]
    assert relationship.source_resource_id == higher_id
    assert relationship.target_resource_id == lower_id
    assert uow.events[:3] == [
        "enter",
        f"resources.get_for_update:{lower_id}",
        f"resources.get_for_update:{higher_id}",
    ]


def test_missing_source_is_reported_by_semantic_role_even_when_locked_second() -> None:
    lower_id = UUID("01984000-0000-7000-8000-000000000001")
    higher_id = UUID("01984000-0000-7000-8000-000000000002")
    command = _command(source_resource_id=higher_id, target_resource_id=lower_id)
    uow = _uow_for_command(command, source_exists=False)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))

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
    assert "relationship_types.get_by_id" not in uow.events
    assert uow.resource_relationships.added == []
    assert uow.commits == 0


def test_missing_target_is_reported_by_semantic_role_even_when_locked_first() -> None:
    lower_id = UUID("01984000-0000-7000-8000-000000000001")
    higher_id = UUID("01984000-0000-7000-8000-000000000002")
    command = _command(source_resource_id=higher_id, target_resource_id=lower_id)
    uow = _uow_for_command(command, target_exists=False)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "target_resource_id"
    assert exc_info.value.lookup_value == lower_id
    assert uow.events == ["enter", f"resources.get_for_update:{lower_id}", "exit"]
    assert uow.resource_relationships.added == []
    assert uow.commits == 0


def test_missing_relationship_type_stops_before_assignment_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, relationship_type_exists=False)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "RelationshipType"
    assert exc_info.value.lookup_field == "relationship_type_id"
    assert exc_info.value.lookup_value == command.relationship_type_id
    assert "resource_relationships.find_current" not in uow.events
    assert uow.resource_relationships.added == []
    assert uow.commits == 0


def test_inactive_relationship_type_stops_before_assignment_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, relationship_type_active=False)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "RelationshipType"
    assert exc_info.value.conflict_field == "relationship_type_id"
    assert exc_info.value.conflict_value == command.relationship_type_id
    assert "resource_relationships.find_current" not in uow.events
    assert uow.resource_relationships.added == []
    assert uow.commits == 0


def test_successful_assignment_adds_one_relationship_and_commits_last() -> None:
    command = _command(source=None)
    uow = _uow_for_command(command)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))
    expected_locks = [
        f"resources.get_for_update:{resource_id}"
        for resource_id in sorted(
            (command.source_resource_id, command.target_resource_id),
            key=str,
        )
    ]

    result = handler.handle(command)

    assert result.relationship_id == uow.resource_relationships.added[0].id
    assert result.source_resource_id == command.source_resource_id
    assert result.relationship_type_id == command.relationship_type_id
    assert result.target_resource_id == command.target_resource_id
    assert result.valid_from == command.valid_from
    assert result.source is None
    assert len(uow.resource_relationships.added) == 1
    relationship = uow.resource_relationships.added[0]
    assert relationship.tenant_id == command.tenant_id
    assert relationship.source_resource_id == command.source_resource_id
    assert relationship.target_resource_id == command.target_resource_id
    assert relationship.relationship_type_id == command.relationship_type_id
    assert relationship.confidence_score == command.confidence_score
    assert relationship.valid_from == command.valid_from
    assert relationship.valid_to is None
    assert relationship.source is None
    assert uow.resource_relationships.flushes == 0
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        *expected_locks,
        "relationship_types.get_by_id",
        "resource_relationships.find_current",
        "resource_relationships.add",
        "commit",
        "exit",
    ]


def test_duplicate_current_relationship_is_rejected_before_mutation() -> None:
    command = _command()
    current = _current_relationship_for_command(command)
    uow = _uow_for_command(command, current=current)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceRelationship"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.conflict_value == command.relationship_type_id
    assert uow.resource_relationships.added == []
    assert uow.commits == 0
    assert uow.events[-3:] == [
        "relationship_types.get_by_id",
        "resource_relationships.find_current",
        "exit",
    ]


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = AssignResourceRelationshipHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.relationship_id == succeeding_uow.resource_relationships.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = AssignResourceRelationshipHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_tenant_resources_relationship_type(
    session: Session,
) -> tuple[UUID, UUID, UUID, UUID]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    source_resource = _resource(session, tenant.id, _slug("source"))
    target_resource = _resource(session, tenant.id, _slug("target"))
    relationship_type_id = _catalog_id(session, RelationshipType, "depends_on")
    session.add_all([source_resource, target_resource])
    session.flush()
    return tenant.id, source_resource.id, target_resource.id, relationship_type_id


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


def _relationship_count(
    session: Session,
    tenant_id: UUID,
    source_resource_id: UUID | None = None,
) -> int:
    statement = select(func.count()).select_from(ResourceRelationship).where(
        ResourceRelationship.tenant_id == tenant_id,
    )
    if source_resource_id is not None:
        statement = statement.where(
            ResourceRelationship.source_resource_id == source_resource_id,
        )
    return session.scalar(statement) or 0


def _second_relationship_type(session: Session) -> RelationshipType:
    relationship_type = RelationshipType(
        code=_slug("supports"),
        display_name="Supports",
        inverse_code=None,
        source_type_constraint=None,
        target_type_constraint=None,
        is_directional=True,
        is_transitive=False,
        is_system=False,
        is_active=True,
    )
    session.add(relationship_type)
    session.flush()
    return relationship_type


def test_sqlalchemy_assignment_persists_directed_relationship(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        source_resource_id=source_resource_id,
        target_resource_id=target_resource_id,
        relationship_type_id=relationship_type_id,
        valid_from=_now(-5),
        source="manual",
    )
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    assert result.source_resource_id == source_resource_id
    assert result.target_resource_id == target_resource_id
    with SessionLocal() as verification:
        relationship = verification.get(ResourceRelationship, result.relationship_id)
        assert relationship is not None
        assert relationship.tenant_id == tenant_id
        assert relationship.source_resource_id == source_resource_id
        assert relationship.target_resource_id == target_resource_id
        assert relationship.relationship_type_id == relationship_type_id
        assert relationship.confidence_score == command.confidence_score
        assert relationship.valid_from == command.valid_from
        assert relationship.valid_to is None
        assert relationship.source == "manual"
        assert _relationship_count(verification, tenant_id, source_resource_id) == 1


def test_sqlalchemy_wrong_tenant_source_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
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
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=other_source_id,
                target_resource_id=target_resource_id,
                relationship_type_id=relationship_type_id,
            )
        )

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "source_resource_id"
    with SessionLocal() as verification:
        assert _relationship_count(verification, tenant_id) == 0


def test_sqlalchemy_wrong_tenant_target_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
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
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=source_resource_id,
                target_resource_id=other_target_id,
                relationship_type_id=relationship_type_id,
            )
        )

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "target_resource_id"
    with SessionLocal() as verification:
        assert _relationship_count(verification, tenant_id) == 0


def test_sqlalchemy_inactive_relationship_type_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        relationship_type = setup_session.get(RelationshipType, relationship_type_id)
        assert relationship_type is not None
        relationship_type.is_active = False
        setup_session.commit()
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=source_resource_id,
                target_resource_id=target_resource_id,
                relationship_type_id=relationship_type_id,
            )
        )

    assert exc_info.value.entity_type == "RelationshipType"
    assert exc_info.value.conflict_field == "relationship_type_id"
    with SessionLocal() as verification:
        assert _relationship_count(verification, tenant_id) == 0


def test_sqlalchemy_duplicate_current_relationship_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        setup_session.commit()
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    first = _command(
        tenant_id=tenant_id,
        source_resource_id=source_resource_id,
        target_resource_id=target_resource_id,
        relationship_type_id=relationship_type_id,
        valid_from=_now(-10),
    )
    first_result = handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                source_resource_id=source_resource_id,
                target_resource_id=target_resource_id,
                relationship_type_id=relationship_type_id,
                valid_from=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceRelationship"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.__cause__ is None
    with SessionLocal() as verification:
        assert (
            verification.get(ResourceRelationship, first_result.relationship_id)
            is not None
        )
        assert _relationship_count(verification, tenant_id) == 1


def test_sqlalchemy_reverse_relationship_is_allowed_as_distinct_directed_edge(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        setup_session.commit()
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    outgoing = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_resource_id,
            target_resource_id=target_resource_id,
            relationship_type_id=relationship_type_id,
            valid_from=_now(-10),
        )
    )
    incoming = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=target_resource_id,
            target_resource_id=source_resource_id,
            relationship_type_id=relationship_type_id,
            valid_from=_now(-5),
        )
    )

    with SessionLocal() as verification:
        relationships = list(
            verification.scalars(
                select(ResourceRelationship)
                .where(ResourceRelationship.tenant_id == tenant_id)
                .order_by(ResourceRelationship.source_resource_id)
            )
        )
        assert {row.id for row in relationships} == {
            outgoing.relationship_id,
            incoming.relationship_id,
        }
        assert {
            (row.source_resource_id, row.target_resource_id) for row in relationships
        } == {
            (source_resource_id, target_resource_id),
            (target_resource_id, source_resource_id),
        }


def test_sqlalchemy_different_relationship_types_are_allowed_for_same_endpoints(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, first_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        second_type = _second_relationship_type(setup_session)
        setup_session.commit()
        second_type_id = second_type.id
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_resource_id,
            target_resource_id=target_resource_id,
            relationship_type_id=first_type_id,
            valid_from=_now(-10),
        )
    )
    second = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_resource_id,
            target_resource_id=target_resource_id,
            relationship_type_id=second_type_id,
            valid_from=_now(-5),
        )
    )

    with SessionLocal() as verification:
        relationships = list(
            verification.scalars(
                select(ResourceRelationship).where(
                    ResourceRelationship.tenant_id == tenant_id,
                    ResourceRelationship.source_resource_id == source_resource_id,
                    ResourceRelationship.target_resource_id == target_resource_id,
                    ResourceRelationship.valid_to.is_(None),
                )
            )
        )
        assert {row.id for row in relationships} == {
            first.relationship_id,
            second.relationship_id,
        }
        assert {row.relationship_type_id for row in relationships} == {
            first_type_id,
            second_type_id,
        }


def test_sqlalchemy_historical_relationship_is_preserved_when_assigning_new_current(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        historical = ResourceRelationship(
            tenant_id=tenant_id,
            source_resource_id=source_resource_id,
            target_resource_id=target_resource_id,
            relationship_type_id=relationship_type_id,
            confidence_score=Decimal("0.8000"),
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
        source_resource_id=source_resource_id,
        target_resource_id=target_resource_id,
        relationship_type_id=relationship_type_id,
        valid_from=_now(-5),
    )
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    with SessionLocal() as verification:
        history = list(
            verification.scalars(
                select(ResourceRelationship)
                .where(
                    ResourceRelationship.tenant_id == tenant_id,
                    ResourceRelationship.source_resource_id == source_resource_id,
                    ResourceRelationship.target_resource_id == target_resource_id,
                )
                .order_by(ResourceRelationship.valid_from, ResourceRelationship.id)
            )
        )
        assert [row.id for row in history] == [historical_id, result.relationship_id]
        assert history[0].valid_from == historical_valid_from
        assert history[0].valid_to == historical_valid_to
        assert history[0].source == "legacy"
        assert history[1].valid_to is None
        assert history[1].relationship_type_id == relationship_type_id


def test_sqlalchemy_unrelated_current_relationship_is_preserved(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        third_resource = _resource(setup_session, tenant_id, _slug("third"))
        setup_session.add(third_resource)
        setup_session.flush()
        unrelated = ResourceRelationship(
            tenant_id=tenant_id,
            source_resource_id=source_resource_id,
            target_resource_id=third_resource.id,
            relationship_type_id=relationship_type_id,
            confidence_score=Decimal("0.8000"),
            valid_from=_now(-30),
            source="manual",
        )
        setup_session.add(unrelated)
        setup_session.commit()
        unrelated_id = unrelated.id
    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_resource_id,
            target_resource_id=target_resource_id,
            relationship_type_id=relationship_type_id,
            valid_from=_now(-5),
        )
    )

    with SessionLocal() as verification:
        current = list(
            verification.scalars(
                select(ResourceRelationship)
                .where(
                    ResourceRelationship.tenant_id == tenant_id,
                    ResourceRelationship.source_resource_id == source_resource_id,
                    ResourceRelationship.valid_to.is_(None),
                )
                .order_by(ResourceRelationship.target_resource_id)
            )
        )
        assert {row.id for row in current} == {unrelated_id, result.relationship_id}


def test_sqlalchemy_unique_current_relationship_conflict_translates_and_rolls_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, source_resource_id, target_resource_id, relationship_type_id = (
            _seed_tenant_resources_relationship_type(setup_session)
        )
        setup_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            first = ResourceRelationship(
                tenant_id=tenant_id,
                source_resource_id=source_resource_id,
                target_resource_id=target_resource_id,
                relationship_type_id=relationship_type_id,
                confidence_score=Decimal("0.9000"),
                valid_from=_now(-10),
                source="manual",
            )
            second = ResourceRelationship(
                tenant_id=tenant_id,
                source_resource_id=source_resource_id,
                target_resource_id=target_resource_id,
                relationship_type_id=relationship_type_id,
                confidence_score=Decimal("0.8000"),
                valid_from=_now(-5),
                source="manual",
            )
            uow.resource_relationships.add(first)
            uow.resource_relationships.add(second)
            uow.commit()

    error = exc_info.value
    assert str(error) == (
        "Resource relationship conflicts with an existing current relationship"
    )
    assert error.entity_type == "ResourceRelationship"
    assert error.conflict_field == "current"
    assert error.constraint == "uq_resource_relationship_current"
    assert isinstance(error.__cause__, IntegrityError)

    with SessionLocal() as verification:
        assert _relationship_count(verification, tenant_id) == 0

    handler = AssignResourceRelationshipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    handler.handle(
        _command(
            tenant_id=tenant_id,
            source_resource_id=source_resource_id,
            target_resource_id=target_resource_id,
            relationship_type_id=relationship_type_id,
            valid_from=_now(),
        )
    )
