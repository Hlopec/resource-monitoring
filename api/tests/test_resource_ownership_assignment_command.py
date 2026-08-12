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

from app.application.commands import AssignResourceOwnershipCommand
from app.application.errors import ConflictError, EntityNotFoundError, ValidationError
from app.application.handlers import (
    AssignResourceOwnershipHandler,
    GetResourceDetailsHandler,
)
from app.application.queries import GetResourceDetailsQuery
from app.application.results import ResourceOwnershipAssignedResult
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Organization,
    OwnershipRole,
    Resource,
    ResourceOwnership,
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


class FakeOrganizationRepository:
    def __init__(
        self,
        events: list[str],
        organizations: dict[tuple[UUID, UUID], object],
    ) -> None:
        self._events = events
        self._organizations = organizations

    def get_by_id(self, tenant_id: UUID, organization_id: UUID) -> object | None:
        self._events.append("organizations.get_by_id")
        return self._organizations.get((tenant_id, organization_id))


class FakeOwnershipRoleRepository:
    def __init__(
        self,
        events: list[str],
        ownership_roles: dict[UUID, object],
    ) -> None:
        self._events = events
        self._ownership_roles = ownership_roles

    def get_by_id(self, ownership_role_id: UUID) -> object | None:
        self._events.append("ownership_roles.get_by_id")
        return self._ownership_roles.get(ownership_role_id)


class FakeResourceOwnershipRepository:
    def __init__(
        self,
        events: list[str],
        *,
        current: ResourceOwnership | object | None = None,
        current_primary: ResourceOwnership | object | None = None,
        fail_on_add: bool = False,
    ) -> None:
        self._events = events
        self._current = current
        self._current_primary = current_primary
        self._fail_on_add = fail_on_add
        self.added: list[ResourceOwnership] = []
        self.flushes = 0

    def find_current(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        organization_id: UUID,
        ownership_role_id: UUID,
    ) -> ResourceOwnership | object | None:
        self._events.append("resource_ownerships.find_current")
        return self._current

    def get_current_primary(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        ownership_role_id: UUID,
    ) -> ResourceOwnership | object | None:
        self._events.append("resource_ownerships.get_current_primary")
        return self._current_primary

    def add(self, ownership: ResourceOwnership) -> None:
        self._events.append("resource_ownerships.add")
        if self._fail_on_add:
            raise RuntimeError("add failed")
        self.added.append(ownership)

    def flush(self) -> None:
        self._events.append("resource_ownerships.flush")
        self.flushes += 1


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        resource_id: UUID,
        organization_id: UUID,
        ownership_role: object,
        resource_exists: bool = True,
        organization_exists: bool = True,
        current: ResourceOwnership | object | None = None,
        current_primary: ResourceOwnership | object | None = None,
        fail_on_add: bool = False,
        fail_on_commit: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self._fail_on_commit = fail_on_commit
        self.resource = SimpleNamespace(id=resource_id, tenant_id=tenant_id)
        self.organization = SimpleNamespace(id=organization_id, tenant_id=tenant_id)
        self.resources = FakeResourceRepository(
            self.events,
            {(tenant_id, resource_id): self.resource} if resource_exists else {},
        )
        self.organizations = FakeOrganizationRepository(
            self.events,
            (
                {(tenant_id, organization_id): self.organization}
                if organization_exists
                else {}
            ),
        )
        self.ownership_roles = FakeOwnershipRoleRepository(
            self.events,
            {ownership_role.id: ownership_role},
        )
        self.resource_ownerships = FakeResourceOwnershipRepository(
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
    organization_id: UUID | None = None,
    ownership_role_id: UUID | None = None,
    is_primary: bool = False,
    confidence_score: Decimal = Decimal("0.9000"),
    valid_from: datetime | None = None,
    source: str | None = "manual",
) -> AssignResourceOwnershipCommand:
    return AssignResourceOwnershipCommand(
        tenant_id=tenant_id or uuid4(),
        resource_id=resource_id or uuid4(),
        organization_id=organization_id or uuid4(),
        ownership_role_id=ownership_role_id or uuid4(),
        is_primary=is_primary,
        confidence_score=confidence_score,
        valid_from=valid_from or _now(),
        source=source,
    )


def _uow_for_command(
    command: AssignResourceOwnershipCommand,
    *,
    ownership_role_active: bool = True,
    resource_exists: bool = True,
    organization_exists: bool = True,
    current: ResourceOwnership | object | None = None,
    current_primary: ResourceOwnership | object | None = None,
    fail_on_add: bool = False,
    fail_on_commit: bool = False,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        organization_id=command.organization_id,
        ownership_role=SimpleNamespace(
            id=command.ownership_role_id,
            is_active=ownership_role_active,
        ),
        resource_exists=resource_exists,
        organization_exists=organization_exists,
        current=current,
        current_primary=current_primary,
        fail_on_add=fail_on_add,
        fail_on_commit=fail_on_commit,
    )


def _current_ownership_for_command(
    command: AssignResourceOwnershipCommand,
    *,
    organization_id: UUID | None = None,
    valid_to: datetime | None = None,
) -> ResourceOwnership:
    return ResourceOwnership(
        tenant_id=command.tenant_id,
        resource_id=command.resource_id,
        organization_id=organization_id or command.organization_id,
        ownership_role_id=command.ownership_role_id,
        is_primary=command.is_primary,
        confidence_score=command.confidence_score,
        valid_from=_now(-10),
        valid_to=valid_to,
        source=command.source,
    )


def test_assign_resource_ownership_command_is_frozen_data_only() -> None:
    command = _command()

    assert is_dataclass(command)
    assert set(command.__annotations__) == {
        "tenant_id",
        "resource_id",
        "organization_id",
        "ownership_role_id",
        "is_primary",
        "confidence_score",
        "valid_from",
        "source",
    }
    assert not hasattr(command, "execute")
    assert not hasattr(command, "save")
    assert not hasattr(command, "commit")
    with pytest.raises(FrozenInstanceError):
        command.organization_id = uuid4()


def test_resource_ownership_assigned_result_is_immutable_and_entity_free() -> None:
    result = ResourceOwnershipAssignedResult(
        resource_id=uuid4(),
        ownership_id=uuid4(),
        organization_id=uuid4(),
        ownership_role_id=uuid4(),
        is_primary=True,
        valid_from=_now(),
        source="manual",
    )

    assert is_dataclass(result)
    assert not isinstance(result, ResourceOwnership)
    with pytest.raises(FrozenInstanceError):
        result.organization_id = uuid4()


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
    command: AssignResourceOwnershipCommand,
    expected_fields: tuple[str, ...],
) -> None:
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == expected_fields


def test_pre_uow_validation_gathers_deterministic_failures() -> None:
    command = _command(
        confidence_score=Decimal("-1"),
        valid_from=datetime(2026, 1, 1),
        source=" ",
    )
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory())

    with pytest.raises(ValidationError) as exc_info:
        handler.handle(command)

    assert tuple(failure.field for failure in exc_info.value.failures) == (
        "confidence_score",
        "valid_from",
        "source",
    )


def test_missing_resource_stops_before_organization_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == command.resource_id
    assert uow.events == ["enter", "resources.get_for_update", "exit"]
    assert uow.resource_ownerships.added == []
    assert uow.commits == 0


def test_wrong_tenant_resource_matches_not_found_behavior() -> None:
    command = _command()
    uow = _uow_for_command(command, resource_exists=False)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Resource"
    assert "organizations.get_by_id" not in uow.events
    assert "resource_ownerships.find_current" not in uow.events
    assert uow.commits == 0


def test_missing_organization_stops_before_role_lookup() -> None:
    command = _command()
    uow = _uow_for_command(command, organization_exists=False)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Organization"
    assert exc_info.value.lookup_field == "organization_id"
    assert exc_info.value.lookup_value == command.organization_id
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "organizations.get_by_id",
        "exit",
    ]
    assert uow.resource_ownerships.added == []
    assert uow.commits == 0


def test_wrong_tenant_organization_matches_not_found_behavior() -> None:
    command = _command()
    uow = _uow_for_command(command, organization_exists=False)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "Organization"
    assert "ownership_roles.get_by_id" not in uow.events
    assert "resource_ownerships.add" not in uow.events
    assert uow.commits == 0


def test_missing_ownership_role_stops_before_ownership_reads() -> None:
    command = _command()
    uow = _uow_for_command(command)
    uow.ownership_roles._ownership_roles.clear()
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "OwnershipRole"
    assert exc_info.value.lookup_field == "ownership_role_id"
    assert "resource_ownerships.find_current" not in uow.events
    assert uow.resource_ownerships.added == []
    assert uow.commits == 0


def test_inactive_ownership_role_stops_before_ownership_mutation() -> None:
    command = _command()
    uow = _uow_for_command(command, ownership_role_active=False)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "OwnershipRole"
    assert exc_info.value.conflict_field == "ownership_role_id"
    assert "resource_ownerships.find_current" not in uow.events
    assert uow.resource_ownerships.added == []
    assert uow.commits == 0


def test_successful_non_primary_assignment_adds_one_ownership_and_commits_last() -> None:
    command = _command(is_primary=False, source=None)
    uow = _uow_for_command(command)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.resource_id == command.resource_id
    assert result.ownership_id == uow.resource_ownerships.added[0].id
    assert result.organization_id == command.organization_id
    assert result.ownership_role_id == command.ownership_role_id
    assert result.is_primary is False
    assert result.valid_from == command.valid_from
    assert result.source is None
    assert len(uow.resource_ownerships.added) == 1
    ownership = uow.resource_ownerships.added[0]
    assert ownership.tenant_id == command.tenant_id
    assert ownership.resource_id == command.resource_id
    assert ownership.organization_id == command.organization_id
    assert ownership.ownership_role_id == command.ownership_role_id
    assert ownership.is_primary is False
    assert ownership.confidence_score == command.confidence_score
    assert ownership.valid_from == command.valid_from
    assert ownership.valid_to is None
    assert ownership.source is None
    assert uow.resource_ownerships.flushes == 0
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "organizations.get_by_id",
        "ownership_roles.get_by_id",
        "resource_ownerships.find_current",
        "resource_ownerships.add",
        "commit",
        "exit",
    ]


def test_successful_first_primary_assignment_checks_current_primary() -> None:
    command = _command(is_primary=True, source="manual")
    uow = _uow_for_command(command)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(command)

    assert result.is_primary is True
    assert len(uow.resource_ownerships.added) == 1
    assert uow.resource_ownerships.added[0].is_primary is True
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "organizations.get_by_id",
        "ownership_roles.get_by_id",
        "resource_ownerships.find_current",
        "resource_ownerships.get_current_primary",
        "resource_ownerships.add",
        "commit",
        "exit",
    ]


def test_duplicate_current_ownership_is_rejected_before_mutation() -> None:
    command = _command()
    current = _current_ownership_for_command(command)
    uow = _uow_for_command(command, current=current)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceOwnership"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.conflict_value == command.organization_id
    assert uow.resource_ownerships.added == []
    assert uow.commits == 0
    assert uow.events == [
        "enter",
        "resources.get_for_update",
        "organizations.get_by_id",
        "ownership_roles.get_by_id",
        "resource_ownerships.find_current",
        "exit",
    ]


def test_existing_current_primary_is_rejected_before_mutation() -> None:
    command = _command(is_primary=True)
    current_primary = _current_ownership_for_command(command, organization_id=uuid4())
    uow = _uow_for_command(command, current_primary=current_primary)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(command)

    assert exc_info.value.entity_type == "ResourceOwnership"
    assert exc_info.value.conflict_field == "current_primary"
    assert exc_info.value.conflict_value == command.ownership_role_id
    assert uow.resource_ownerships.added == []
    assert uow.commits == 0
    assert "resource_ownerships.add" not in uow.events


def test_add_failure_propagates_and_next_execution_uses_fresh_uow() -> None:
    command = _command()
    failing_uow = _uow_for_command(command, fail_on_add=True)
    succeeding_uow = _uow_for_command(command)
    factory = FakeUnitOfWorkFactory(failing_uow, succeeding_uow)
    handler = AssignResourceOwnershipHandler(factory)

    with pytest.raises(RuntimeError, match="add failed"):
        handler.handle(command)
    result = handler.handle(command)

    assert failing_uow.commits == 0
    assert failing_uow.rollbacks == 0
    assert failing_uow.exited is True
    assert succeeding_uow.commits == 1
    assert result.ownership_id == succeeding_uow.resource_ownerships.added[0].id
    assert factory.created == [failing_uow, succeeding_uow]


def test_commit_failure_propagates_without_second_commit() -> None:
    command = _command()
    uow = _uow_for_command(command, fail_on_commit=True)
    handler = AssignResourceOwnershipHandler(FakeUnitOfWorkFactory(uow))

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


def _seed_resource_and_organization(session: Session) -> tuple[UUID, UUID, UUID, UUID]:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    organization = Organization(
        tenant_id=tenant.id,
        canonical_name=_slug("organization"),
        display_name="Organization",
        status="active",
    )
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
    session.add_all([organization, resource])
    session.flush()
    return (
        tenant.id,
        resource.id,
        organization.id,
        _catalog_id(session, OwnershipRole, "owner"),
    )


def _add_organization(session: Session, tenant_id: UUID) -> UUID:
    organization = Organization(
        tenant_id=tenant_id,
        canonical_name=_slug("organization"),
        display_name="Organization",
        status="active",
    )
    session.add(organization)
    session.flush()
    return organization.id


def _ownership_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceOwnership)
            .where(
                ResourceOwnership.tenant_id == tenant_id,
                ResourceOwnership.resource_id == resource_id,
            )
        )
        or 0
    )


def _current_ownership_count(session: Session, tenant_id: UUID, resource_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ResourceOwnership)
            .where(
                ResourceOwnership.tenant_id == tenant_id,
                ResourceOwnership.resource_id == resource_id,
                ResourceOwnership.valid_to.is_(None),
            )
        )
        or 0
    )


def test_sqlalchemy_assignment_persists_and_reads_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, organization_id, ownership_role_id = (
            _seed_resource_and_organization(setup_session)
        )
        setup_session.commit()
    command = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        is_primary=True,
        confidence_score=Decimal("0.8000"),
        valid_from=_now(-5),
        source="manual",
    )
    handler = AssignResourceOwnershipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    assert result.resource_id == resource_id
    with SessionLocal() as verification:
        ownership = verification.get(ResourceOwnership, result.ownership_id)
        assert ownership is not None
        assert ownership.tenant_id == tenant_id
        assert ownership.resource_id == resource_id
        assert ownership.organization_id == organization_id
        assert ownership.ownership_role_id == ownership_role_id
        assert ownership.is_primary is True
        assert ownership.confidence_score == Decimal("0.8000")
        assert ownership.valid_from == command.valid_from
        assert ownership.valid_to is None
        assert ownership.source == "manual"
        assert _current_ownership_count(verification, tenant_id, resource_id) == 1

    details = GetResourceDetailsHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, resource_id)
    )
    assert len(details.ownership) == 1
    assert details.ownership[0].id == result.ownership_id
    assert details.ownership[0].organization_id == organization_id


def test_sqlalchemy_wrong_tenant_organization_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, _, ownership_role_id = (
            _seed_resource_and_organization(setup_session)
        )
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.flush()
        other_organization_id = _add_organization(setup_session, other_tenant.id)
        setup_session.commit()
    handler = AssignResourceOwnershipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                organization_id=other_organization_id,
                ownership_role_id=ownership_role_id,
            )
        )

    assert exc_info.value.entity_type == "Organization"
    with SessionLocal() as verification:
        assert _ownership_count(verification, tenant_id, resource_id) == 0


def test_sqlalchemy_duplicate_current_ownership_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, organization_id, ownership_role_id = (
            _seed_resource_and_organization(setup_session)
        )
        setup_session.commit()
    handler = AssignResourceOwnershipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    first = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        valid_from=_now(-10),
    )
    first_result = handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                organization_id=organization_id,
                ownership_role_id=ownership_role_id,
                valid_from=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceOwnership"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.__cause__ is None
    with SessionLocal() as verification:
        assert verification.get(ResourceOwnership, first_result.ownership_id) is not None
        assert _ownership_count(verification, tenant_id, resource_id) == 1


def test_sqlalchemy_current_primary_conflict_is_rejected_before_insert(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, organization_id, ownership_role_id = (
            _seed_resource_and_organization(setup_session)
        )
        other_organization_id = _add_organization(setup_session, tenant_id)
        setup_session.commit()
    handler = AssignResourceOwnershipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    first = _command(
        tenant_id=tenant_id,
        resource_id=resource_id,
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        is_primary=True,
        valid_from=_now(-10),
    )
    handler.handle(first)

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(
            _command(
                tenant_id=tenant_id,
                resource_id=resource_id,
                organization_id=other_organization_id,
                ownership_role_id=ownership_role_id,
                is_primary=True,
                valid_from=_now(-5),
            )
        )

    assert exc_info.value.entity_type == "ResourceOwnership"
    assert exc_info.value.conflict_field == "current_primary"
    assert exc_info.value.__cause__ is None
    with SessionLocal() as verification:
        ownerships = list(
            verification.scalars(
                select(ResourceOwnership)
                .where(
                    ResourceOwnership.tenant_id == tenant_id,
                    ResourceOwnership.resource_id == resource_id,
                )
                .order_by(ResourceOwnership.valid_from, ResourceOwnership.id)
            )
        )
        assert len(ownerships) == 1
        assert ownerships[0].organization_id == organization_id
        assert ownerships[0].valid_to is None


def test_sqlalchemy_historical_ownership_is_preserved_when_assigning_new_current(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, organization_id, ownership_role_id = (
            _seed_resource_and_organization(setup_session)
        )
        historical = ResourceOwnership(
            tenant_id=tenant_id,
            resource_id=resource_id,
            organization_id=organization_id,
            ownership_role_id=ownership_role_id,
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
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        valid_from=_now(-5),
    )
    handler = AssignResourceOwnershipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(command)

    with SessionLocal() as verification:
        history = list(
            verification.scalars(
                select(ResourceOwnership)
                .where(
                    ResourceOwnership.tenant_id == tenant_id,
                    ResourceOwnership.resource_id == resource_id,
                )
                .order_by(ResourceOwnership.valid_from, ResourceOwnership.id)
            )
        )
        assert [row.id for row in history] == [historical_id, result.ownership_id]
        assert history[0].valid_from == historical_valid_from
        assert history[0].valid_to == historical_valid_to
        assert history[0].source == "legacy"
        assert history[1].valid_to is None
        assert history[1].organization_id == organization_id


def test_sqlalchemy_persistence_boundary_translates_unchecked_ownership_conflict(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, organization_id, ownership_role_id = (
            _seed_resource_and_organization(setup_session)
        )
        setup_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            resource = uow.resources.get_for_update(tenant_id, resource_id)
            assert resource is not None
            first = ResourceOwnership(
                tenant_id=tenant_id,
                resource_id=resource_id,
                organization_id=organization_id,
                ownership_role_id=ownership_role_id,
                is_primary=False,
                confidence_score=Decimal("0.9000"),
                valid_from=_now(-10),
                source="manual",
            )
            second = ResourceOwnership(
                tenant_id=tenant_id,
                resource_id=resource_id,
                organization_id=organization_id,
                ownership_role_id=ownership_role_id,
                is_primary=False,
                confidence_score=Decimal("0.8000"),
                valid_from=_now(-5),
                source="manual",
            )
            uow.resource_ownerships.add(first)
            uow.resource_ownerships.add(second)
            uow.commit()

    assert exc_info.value.entity_type == "ResourceOwnership"
    assert exc_info.value.conflict_field == "current"
    assert exc_info.value.constraint == "uq_resource_ownership_current"
    assert isinstance(exc_info.value.__cause__, IntegrityError)
    with SessionLocal() as verification:
        assert _ownership_count(verification, tenant_id, resource_id) == 0

    handler = AssignResourceOwnershipHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))
    fresh_result = handler.handle(
        _command(
            tenant_id=tenant_id,
            resource_id=resource_id,
            organization_id=organization_id,
            ownership_role_id=ownership_role_id,
            valid_from=_now(),
        )
    )
    assert fresh_result.ownership_id is not None
