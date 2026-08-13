from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.errors import EntityNotFoundError
from app.application.handlers import (
    GetResourceDetailsHandler,
    GetResourceHistoryHandler,
    ResolveCanonicalResourceHandler,
)
from app.application.ports.resource_queries import (
    ResourceClassificationHistoryProjection,
    ResourceHistoryProjection,
    ResourceIdentifierHistoryProjection,
    ResourceLabelHistoryProjection,
    ResourceOwnershipHistoryProjection,
    ResourceStateHistoryProjection,
)
from app.application.queries import (
    GetResourceDetailsQuery,
    GetResourceHistoryQuery,
    ResolveCanonicalResourceQuery,
)
from app.application.results import (
    ResourceClassificationHistoryResult,
    ResourceHistoryResult,
    ResourceIdentifierHistoryResult,
    ResourceLabelHistoryResult,
    ResourceOwnershipHistoryResult,
    ResourceStateHistoryResult,
)
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    ClassificationType,
    ClassificationValue,
    Criticality,
    ExposureLevel,
    IdentifierType,
    Label,
    LifecycleStatus,
    Organization,
    OwnershipRole,
    Resource,
    ResourceAlias,
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceMerge,
    ResourceOwnership,
    ResourceState,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


HISTORY_SELECT_COUNT = 6


class FakeResourceQueryService:
    def __init__(
        self,
        events: list[str],
        projections: dict[tuple[UUID, UUID], ResourceHistoryProjection],
    ) -> None:
        self._events = events
        self._projections = projections

    def get_resource_history(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceHistoryProjection | None:
        self._events.append("resource_queries.get_resource_history")
        return self._projections.get((tenant_id, resource_id))


class FakeUnitOfWork:
    def __init__(
        self,
        projections: dict[tuple[UUID, UUID], ResourceHistoryProjection],
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self.resource_queries = FakeResourceQueryService(self.events, projections)

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
        self.commits += 1
        self.events.append("commit")

    def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append("rollback")


class FakeUnitOfWorkFactory:
    def __init__(self, uow: FakeUnitOfWork) -> None:
        self._uow = uow
        self.created: list[FakeUnitOfWork] = []

    def __call__(self) -> FakeUnitOfWork:
        self.created.append(self._uow)
        return self._uow


def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _uow_factory(SessionLocal: sessionmaker[Session]):
    return lambda: SQLAlchemyUnitOfWork(SessionLocal)


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _at(day: int, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, second, tzinfo=UTC)


def _now(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _catalog_id(session: Session, model_type: type[object], code: str) -> UUID:
    entity_id = session.scalar(select(model_type.id).where(model_type.code == code))
    assert entity_id is not None
    return entity_id


def _classification_value_id(session: Session, code: str) -> UUID:
    entity_id = session.scalar(
        select(ClassificationValue.id).where(ClassificationValue.code == code)
    )
    assert entity_id is not None
    return entity_id


def _seed_tenant(session: Session, prefix: str = "tenant") -> UUID:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug(prefix), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    return tenant.id


def _resource(
    session: Session,
    tenant_id: UUID,
    name: str,
    *,
    created_at: datetime | None = None,
) -> Resource:
    timestamp = created_at or _now(-10)
    resource = Resource(
        tenant_id=tenant_id,
        resource_type_id=_catalog_id(session, ResourceType, "domain"),
        canonical_name=_slug(name),
        display_name=name,
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=timestamp,
        last_seen_at=timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(resource)
    session.flush()
    return resource


def _organization(session: Session, tenant_id: UUID, name: str) -> Organization:
    organization = Organization(
        tenant_id=tenant_id,
        canonical_name=_slug(name),
        display_name=name,
        external_key=None,
        status="active",
        archived_at=None,
    )
    session.add(organization)
    session.flush()
    return organization


def _label(session: Session, tenant_id: UUID, key: str, value: str) -> Label:
    label = Label(
        tenant_id=tenant_id,
        key=key,
        value=value,
        display_name=f"{key}:{value}",
        description=None,
        color=None,
        is_active=True,
    )
    session.add(label)
    session.flush()
    return label


def _state(
    session: Session,
    resource: Resource,
    *,
    valid_from: datetime,
    valid_to: datetime | None,
) -> ResourceState:
    state = ResourceState(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=90,
        confidence_score=Decimal("0.9100"),
        valid_from=valid_from,
        valid_to=valid_to,
        source="test",
    )
    session.add(state)
    session.flush()
    return state


def _ownership(
    session: Session,
    resource: Resource,
    organization: Organization,
    *,
    ownership_role_id: UUID | None = None,
    is_primary: bool = True,
    valid_from: datetime,
    valid_to: datetime | None,
) -> ResourceOwnership:
    ownership = ResourceOwnership(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        organization_id=organization.id,
        ownership_role_id=(
            ownership_role_id or _catalog_id(session, OwnershipRole, "owner")
        ),
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from,
        valid_to=valid_to,
        source="test",
    )
    session.add(ownership)
    session.flush()
    return ownership


def _label_assignment(
    session: Session,
    resource: Resource,
    label: Label,
    *,
    valid_from: datetime,
    valid_to: datetime | None,
) -> ResourceLabel:
    assignment = ResourceLabel(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        label_id=label.id,
        valid_from=valid_from,
        valid_to=valid_to,
        source="test",
    )
    session.add(assignment)
    session.flush()
    return assignment


def _classification(
    session: Session,
    resource: Resource,
    *,
    classification_value_id: UUID,
    is_primary: bool,
    valid_from: datetime,
    valid_to: datetime | None,
) -> ResourceClassification:
    classification = ResourceClassification(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        classification_type_id=_catalog_id(session, ClassificationType, "environment"),
        classification_value_id=classification_value_id,
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from,
        valid_to=valid_to,
        source="test",
    )
    session.add(classification)
    session.flush()
    return classification


def _identifier(
    session: Session,
    resource: Resource,
    *,
    namespace: str | None,
    normalized_value: str,
    is_primary: bool,
    valid_from: datetime,
    valid_to: datetime | None,
) -> ResourceIdentifier:
    identifier = ResourceIdentifier(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        identifier_type_id=_catalog_id(session, IdentifierType, "fqdn"),
        namespace=namespace,
        normalized_value=normalized_value,
        original_value=normalized_value.upper(),
        value_hash=f"hash-{normalized_value}",
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from,
        valid_to=valid_to,
    )
    session.add(identifier)
    session.flush()
    return identifier


def _alias(session: Session, resource: Resource) -> ResourceAlias:
    alias = ResourceAlias(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        alias_type="dns_name",
        alias_value="Alias.EXAMPLE.COM",
        normalized_value="alias.example.com",
        source="test",
        first_seen_at=_now(-5),
        last_seen_at=_now(-4),
    )
    session.add(alias)
    session.flush()
    return alias


def _merge(session: Session, source: Resource, target: Resource) -> ResourceMerge:
    merge = ResourceMerge(
        tenant_id=source.tenant_id,
        source_resource_id=source.id,
        target_resource_id=target.id,
        reason="duplicate",
        source="test",
        merged_at=_now(-1),
    )
    session.add(merge)
    session.flush()
    return merge


@contextmanager
def _capture_sql(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def before_cursor_execute(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def _selects(statements: list[str]) -> list[str]:
    return [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]


def _sample_history_projection(
    tenant_id: UUID,
    resource_id: UUID,
) -> ResourceHistoryProjection:
    return ResourceHistoryProjection(
        id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=uuid4(),
        canonical_name="resource.example.com",
        display_name="Resource",
        states=(
            ResourceStateHistoryProjection(
                id=uuid4(),
                lifecycle_status_id=uuid4(),
                criticality_id=uuid4(),
                exposure_level_id=uuid4(),
                source_priority=90,
                confidence_score=Decimal("0.9100"),
                valid_from=_at(1),
                valid_to=_at(2),
                source="test",
            ),
        ),
        ownership=(
            ResourceOwnershipHistoryProjection(
                id=uuid4(),
                organization_id=uuid4(),
                ownership_role_id=uuid4(),
                is_primary=True,
                confidence_score=Decimal("0.9000"),
                valid_from=_at(1),
                valid_to=None,
                source="test",
            ),
        ),
        labels=(
            ResourceLabelHistoryProjection(
                id=uuid4(),
                label_id=uuid4(),
                valid_from=_at(1),
                valid_to=None,
                source="test",
            ),
        ),
        classifications=(
            ResourceClassificationHistoryProjection(
                id=uuid4(),
                classification_type_id=uuid4(),
                classification_value_id=uuid4(),
                is_primary=False,
                confidence_score=Decimal("0.9000"),
                valid_from=_at(1),
                valid_to=None,
                source="test",
            ),
        ),
        identifiers=(
            ResourceIdentifierHistoryProjection(
                id=uuid4(),
                identifier_type_id=uuid4(),
                namespace=None,
                normalized_value="resource.example.com",
                original_value="RESOURCE.EXAMPLE.COM",
                is_primary=True,
                confidence_score=Decimal("0.9000"),
                valid_from=_at(1),
                valid_to=None,
            ),
        ),
    )


def test_resource_history_contracts_are_immutable_and_tuple_based() -> None:
    query = GetResourceHistoryQuery(uuid4(), uuid4())
    projection = _sample_history_projection(query.tenant_id, query.resource_id)
    handler = GetResourceHistoryHandler(
        FakeUnitOfWorkFactory(
            FakeUnitOfWork({(query.tenant_id, query.resource_id): projection})
        )
    )

    result = handler.handle(query)

    assert is_dataclass(query)
    assert {field.name for field in fields(query)} == {"tenant_id", "resource_id"}
    assert is_dataclass(result)
    assert isinstance(result, ResourceHistoryResult)
    assert isinstance(result.states, tuple)
    assert isinstance(result.ownership, tuple)
    assert isinstance(result.labels, tuple)
    assert isinstance(result.classifications, tuple)
    assert isinstance(result.identifiers, tuple)
    assert isinstance(result.states[0], ResourceStateHistoryResult)
    assert isinstance(result.ownership[0], ResourceOwnershipHistoryResult)
    assert isinstance(result.labels[0], ResourceLabelHistoryResult)
    assert isinstance(result.classifications[0], ResourceClassificationHistoryResult)
    assert isinstance(result.identifiers[0], ResourceIdentifierHistoryResult)
    with pytest.raises(FrozenInstanceError):
        query.resource_id = uuid4()
    with pytest.raises(FrozenInstanceError):
        result.canonical_name = "changed.example.com"
    with pytest.raises(FrozenInstanceError):
        result.states[0].valid_to = None


def test_history_handler_uses_one_read_only_query_service_call() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    projection = _sample_history_projection(tenant_id, resource_id)
    uow = FakeUnitOfWork({(tenant_id, resource_id): projection})
    factory = FakeUnitOfWorkFactory(uow)
    handler = GetResourceHistoryHandler(factory)

    result = handler.handle(GetResourceHistoryQuery(tenant_id, resource_id))

    assert result.id == resource_id
    assert len(factory.created) == 1
    assert uow.exited is True
    assert uow.commits == 0
    assert uow.rollbacks == 0
    assert uow.events == ["enter", "resource_queries.get_resource_history", "exit"]


def test_history_handler_missing_resource_raises_resource_not_found() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    uow = FakeUnitOfWork({})
    handler = GetResourceHistoryHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(GetResourceHistoryQuery(tenant_id, resource_id))

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == resource_id
    assert uow.commits == 0
    assert uow.events == ["enter", "resource_queries.get_resource_history", "exit"]


def test_resource_history_returns_temporal_rows_with_exact_intervals_and_ordering(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "history", created_at=_at(1, 9))
        target = _resource(setup, tenant_id, "target", created_at=_at(1, 9, 1))
        owner = _organization(setup, tenant_id, "owner")
        custodian = _organization(setup, tenant_id, "custodian")
        labels = [
            _label(setup, tenant_id, "alpha", "one"),
            _label(setup, tenant_id, "beta", "two"),
        ]
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        t1 = _at(1, 10, 0, 1)
        t2 = _at(2, 10, 0, 2)
        t3 = _at(3, 10, 0, 3)
        equal = _at(4, 10, 0, 4)

        state_1 = _state(setup, resource, valid_from=t1, valid_to=t2)
        state_2 = _state(setup, resource, valid_from=t2, valid_to=t3)
        state_current = _state(setup, resource, valid_from=t3, valid_to=None)
        owner_old = _ownership(
            setup,
            resource,
            owner,
            valid_from=t1,
            valid_to=t2,
        )
        owner_current = _ownership(
            setup,
            resource,
            owner,
            valid_from=t2,
            valid_to=None,
        )
        custodian_old = _ownership(
            setup,
            resource,
            custodian,
            ownership_role_id=_catalog_id(setup, OwnershipRole, "custodian"),
            is_primary=False,
            valid_from=equal,
            valid_to=_at(5),
        )
        label_old = _label_assignment(
            setup,
            resource,
            labels[1],
            valid_from=t1,
            valid_to=t2,
        )
        label_current = _label_assignment(
            setup,
            resource,
            labels[0],
            valid_from=t2,
            valid_to=None,
        )
        classification_old = _classification(
            setup,
            resource,
            classification_value_id=production_id,
            is_primary=True,
            valid_from=t1,
            valid_to=t2,
        )
        classification_current = _classification(
            setup,
            resource,
            classification_value_id=staging_id,
            is_primary=False,
            valid_from=t2,
            valid_to=None,
        )
        identifier_old = _identifier(
            setup,
            resource,
            namespace=None,
            normalized_value="old.example.com",
            is_primary=True,
            valid_from=t1,
            valid_to=t2,
        )
        identifier_current = _identifier(
            setup,
            resource,
            namespace="dns",
            normalized_value="current.example.com",
            is_primary=True,
            valid_from=t2,
            valid_to=None,
        )
        _alias(setup, resource)
        _merge(setup, resource, target)
        setup.commit()

    history_handler = GetResourceHistoryHandler(_uow_factory(SessionLocal))
    canonical_handler = ResolveCanonicalResourceHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        result = history_handler.handle(
            GetResourceHistoryQuery(tenant_id=tenant_id, resource_id=resource.id)
        )

    selects = _selects(statements)
    sql = "\n".join(selects).upper()
    assert len(selects) == HISTORY_SELECT_COUNT
    assert "RESOURCE_STATE" in sql
    assert "RESOURCE_OWNERSHIP" in sql
    assert "RESOURCE_LABEL" in sql
    assert "RESOURCE_CLASSIFICATION" in sql
    assert "RESOURCE_IDENTIFIER" in sql
    assert "RESOURCE_ALIAS" not in sql
    assert "RESOURCE_MERGE" not in sql
    assert "OFFSET" not in sql
    assert "COUNT" not in sql
    assert "DISTINCT" not in sql
    assert "VALID_TO IS NULL" not in sql
    assert "NULLS LAST" in sql
    assert "RESOURCE_STATE" not in selects[0].upper()
    assert "RESOURCE_OWNERSHIP" not in selects[0].upper()
    assert "RESOURCE_LABEL" not in selects[0].upper()
    assert "RESOURCE_CLASSIFICATION" not in selects[0].upper()
    assert "RESOURCE_IDENTIFIER" not in selects[0].upper()

    assert result.id == resource.id
    assert result.tenant_id == tenant_id
    assert [item.id for item in result.states] == [
        state_1.id,
        state_2.id,
        state_current.id,
    ]
    assert result.states[0].valid_from == t1
    assert result.states[0].valid_to == t2
    assert result.states[-1].valid_to is None
    assert [item.id for item in result.ownership] == [
        owner_old.id,
        owner_current.id,
        custodian_old.id,
    ]
    assert {item.id for item in result.labels} == {label_old.id, label_current.id}
    assert [item.valid_from for item in result.labels] == [t1, t2]
    assert {item.id for item in result.classifications} == {
        classification_old.id,
        classification_current.id,
    }
    assert {item.id for item in result.identifiers} == {
        identifier_old.id,
        identifier_current.id,
    }
    assert result.identifiers[0].normalized_value == "old.example.com"
    assert result.identifiers[-1].valid_to is None
    assert result.states[0].lifecycle_status_id
    assert result.ownership[0].organization_id
    assert result.labels[0].label_id
    assert result.classifications[0].classification_value_id
    assert result.identifiers[0].original_value

    canonical = canonical_handler.handle(
        ResolveCanonicalResourceQuery(tenant_id=tenant_id, resource_id=resource.id)
    )
    assert canonical.canonical_resource_id == target.id
    assert result.id != canonical.canonical_resource_id


def test_resource_history_empty_for_resource_without_temporal_facts(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "empty", created_at=_at(1))
        setup.commit()
    handler = GetResourceHistoryHandler(_uow_factory(SessionLocal))

    result = handler.handle(
        GetResourceHistoryQuery(tenant_id=tenant_id, resource_id=resource.id)
    )

    assert result.id == resource.id
    assert result.states == ()
    assert result.ownership == ()
    assert result.labels == ()
    assert result.classifications == ()
    assert result.identifiers == ()


def test_resource_history_wrong_tenant_matches_missing_and_stops_after_core_query(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        resource_b = _resource(setup, tenant_b, "tenant-b", created_at=_at(1))
        setup.commit()
    handler = GetResourceHistoryHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as wrong_tenant_statements:
        with pytest.raises(EntityNotFoundError) as wrong_tenant:
            handler.handle(
                GetResourceHistoryQuery(tenant_id=tenant_a, resource_id=resource_b.id)
            )
    with _capture_sql(migrated_engine) as missing_statements:
        with pytest.raises(EntityNotFoundError) as missing:
            handler.handle(
                GetResourceHistoryQuery(tenant_id=tenant_a, resource_id=uuid4())
            )

    assert wrong_tenant.value.entity_type == missing.value.entity_type == "Resource"
    assert wrong_tenant.value.lookup_field == missing.value.lookup_field == "resource_id"
    assert len(_selects(wrong_tenant_statements)) == 1
    assert len(_selects(missing_statements)) == 1


def test_resource_history_query_count_is_independent_of_history_size(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "dense", created_at=_at(1))
        organization = _organization(setup, tenant_id, "owner")
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        labels = [_label(setup, tenant_id, f"k{index}", f"v{index}") for index in range(10)]
        for index in range(10):
            valid_from = _at(1, 10, index, 0)
            valid_to = _at(1, 10, index + 1, 0)
            _state(setup, resource, valid_from=valid_from, valid_to=valid_to)
            _ownership(
                setup,
                resource,
                organization,
                valid_from=valid_from,
                valid_to=valid_to,
            )
            _label_assignment(
                setup,
                resource,
                labels[index],
                valid_from=valid_from,
                valid_to=valid_to,
            )
            _classification(
                setup,
                resource,
                classification_value_id=production_id if index % 2 == 0 else staging_id,
                is_primary=index % 2 == 0,
                valid_from=valid_from,
                valid_to=valid_to,
            )
            _identifier(
                setup,
                resource,
                namespace=f"ns-{index}",
                normalized_value=f"history-{index}.example.com",
                is_primary=index == 0,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        _state(setup, resource, valid_from=_at(2), valid_to=None)
        setup.commit()
    handler = GetResourceHistoryHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        result = handler.handle(
            GetResourceHistoryQuery(tenant_id=tenant_id, resource_id=resource.id)
        )

    assert len(_selects(statements)) == HISTORY_SELECT_COUNT
    assert len(result.states) == 11
    assert len(result.ownership) == 10
    assert len(result.labels) == 10
    assert len(result.classifications) == 10
    assert len(result.identifiers) == 10


def test_resource_details_remain_current_only_after_history_query_is_added(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "details-current", created_at=_at(1))
        organization = _organization(setup, tenant_id, "owner")
        old_label = _label(setup, tenant_id, "old", "label")
        current_label = _label(setup, tenant_id, "current", "label")
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        t1 = _at(1)
        t2 = _at(2)
        _state(setup, resource, valid_from=t1, valid_to=t2)
        _state(setup, resource, valid_from=t2, valid_to=None)
        _ownership(setup, resource, organization, valid_from=t1, valid_to=t2)
        current_owner = _ownership(
            setup,
            resource,
            organization,
            valid_from=t2,
            valid_to=None,
        )
        _label_assignment(setup, resource, old_label, valid_from=t1, valid_to=t2)
        current_label_assignment = _label_assignment(
            setup,
            resource,
            current_label,
            valid_from=t2,
            valid_to=None,
        )
        _classification(
            setup,
            resource,
            classification_value_id=production_id,
            is_primary=True,
            valid_from=t1,
            valid_to=t2,
        )
        current_classification = _classification(
            setup,
            resource,
            classification_value_id=staging_id,
            is_primary=False,
            valid_from=t2,
            valid_to=None,
        )
        _identifier(
            setup,
            resource,
            namespace=None,
            normalized_value="old.example.com",
            is_primary=True,
            valid_from=t1,
            valid_to=t2,
        )
        current_identifier = _identifier(
            setup,
            resource,
            namespace=None,
            normalized_value="current.example.com",
            is_primary=True,
            valid_from=t2,
            valid_to=None,
        )
        setup.commit()
    details_handler = GetResourceDetailsHandler(_uow_factory(SessionLocal))
    history_handler = GetResourceHistoryHandler(_uow_factory(SessionLocal))

    details = details_handler.handle(
        GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource.id)
    )
    history = history_handler.handle(
        GetResourceHistoryQuery(tenant_id=tenant_id, resource_id=resource.id)
    )

    assert [item.id for item in details.ownership] == [current_owner.id]
    assert [item.id for item in details.labels] == [current_label_assignment.id]
    assert [item.id for item in details.classifications] == [
        current_classification.id
    ]
    assert [item.id for item in details.identifiers] == [current_identifier.id]
    assert len(history.ownership) == 2
    assert len(history.labels) == 2
    assert len(history.classifications) == 2
    assert len(history.identifiers) == 2
