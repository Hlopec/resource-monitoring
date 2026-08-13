from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.errors import EntityNotFoundError
from app.application.handlers import (
    GetResourceDetailsHandler,
    GetResourceHistoryHandler,
    GetResourceRelationshipsHandler,
    ResolveCanonicalResourceHandler,
)
from app.application.ports.resource_queries import (
    ResourceRelationshipProjection,
    ResourceRelationshipsProjection,
)
from app.application.queries import (
    GetResourceDetailsQuery,
    GetResourceHistoryQuery,
    GetResourceRelationshipsQuery,
    ResolveCanonicalResourceQuery,
)
from app.application.results import (
    ResourceRelationshipResult,
    ResourceRelationshipsResult,
)
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    RelationshipType,
    Resource,
    ResourceMerge,
    ResourceRelationship,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


RELATIONSHIP_SELECT_COUNT = 2


class FakeResourceQueryService:
    def __init__(
        self,
        events: list[str],
        projections: dict[tuple[UUID, UUID], ResourceRelationshipsProjection],
    ) -> None:
        self._events = events
        self._projections = projections

    def get_resource_relationships(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceRelationshipsProjection | None:
        self._events.append("resource_queries.get_resource_relationships")
        return self._projections.get((tenant_id, resource_id))


class FakeUnitOfWork:
    def __init__(
        self,
        projections: dict[tuple[UUID, UUID], ResourceRelationshipsProjection],
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


def _now(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _at(day: int, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 2, day, hour, minute, second, tzinfo=UTC)


def _catalog_id(session: Session, model_type: type[object], code: str) -> UUID:
    entity_id = session.scalar(select(model_type.id).where(model_type.code == code))
    assert entity_id is not None
    return entity_id


def _seed_tenant(session: Session, prefix: str = "tenant") -> UUID:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug(prefix), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    return tenant.id


def _resource(session: Session, tenant_id: UUID, name: str) -> Resource:
    timestamp = _now(-10)
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


def _relationship_type_id(session: Session, code: str = "depends_on") -> UUID:
    entity_id = session.scalar(
        select(RelationshipType.id).where(RelationshipType.code == code)
    )
    assert entity_id is not None
    return entity_id


def _extra_relationship_type_id(session: Session, code: str = "supports") -> UUID:
    relationship_type = RelationshipType(
        code=_slug(code),
        display_name="Supports",
        inverse_code=None,
        source_type_constraint=None,
        target_type_constraint=None,
        is_active=True,
    )
    session.add(relationship_type)
    session.flush()
    return relationship_type.id


def _relationship(
    session: Session,
    source: Resource,
    target: Resource,
    *,
    relationship_type_id: UUID | None = None,
    confidence_score: Decimal = Decimal("0.9000"),
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceRelationship:
    relationship = ResourceRelationship(
        tenant_id=source.tenant_id,
        source_resource_id=source.id,
        target_resource_id=target.id,
        relationship_type_id=relationship_type_id or _relationship_type_id(session),
        confidence_score=confidence_score,
        valid_from=valid_from or _now(-5),
        valid_to=valid_to,
        source="test",
    )
    session.add(relationship)
    session.flush()
    return relationship


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


def _sample_relationships_projection(
    tenant_id: UUID,
    resource_id: UUID,
) -> ResourceRelationshipsProjection:
    return ResourceRelationshipsProjection(
        resource_id=resource_id,
        tenant_id=tenant_id,
        relationships=(
            ResourceRelationshipProjection(
                id=uuid4(),
                relationship_type_id=uuid4(),
                source_resource_id=resource_id,
                target_resource_id=uuid4(),
                direction="outgoing",
                confidence_score=Decimal("0.9000"),
                valid_from=_at(1),
                source="test",
                created_at=_at(1, 0),
            ),
        ),
    )


def test_resource_relationship_contracts_are_immutable_and_tuple_based() -> None:
    query = GetResourceRelationshipsQuery(uuid4(), uuid4())
    projection = _sample_relationships_projection(query.tenant_id, query.resource_id)
    handler = GetResourceRelationshipsHandler(
        FakeUnitOfWorkFactory(
            FakeUnitOfWork({(query.tenant_id, query.resource_id): projection})
        )
    )

    result = handler.handle(query)

    assert is_dataclass(query)
    assert {field.name for field in fields(query)} == {"tenant_id", "resource_id"}
    assert is_dataclass(result)
    assert isinstance(result, ResourceRelationshipsResult)
    assert isinstance(result.relationships, tuple)
    assert isinstance(result.relationships[0], ResourceRelationshipResult)
    with pytest.raises(FrozenInstanceError):
        query.resource_id = uuid4()
    with pytest.raises(FrozenInstanceError):
        result.resource_id = uuid4()
    with pytest.raises(FrozenInstanceError):
        result.relationships[0].direction = "incoming"


def test_relationship_handler_uses_one_read_only_query_service_call() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    projection = _sample_relationships_projection(tenant_id, resource_id)
    uow = FakeUnitOfWork({(tenant_id, resource_id): projection})
    factory = FakeUnitOfWorkFactory(uow)
    handler = GetResourceRelationshipsHandler(factory)

    result = handler.handle(GetResourceRelationshipsQuery(tenant_id, resource_id))

    assert result.resource_id == resource_id
    assert len(factory.created) == 1
    assert uow.exited is True
    assert uow.commits == 0
    assert uow.rollbacks == 0
    assert uow.events == [
        "enter",
        "resource_queries.get_resource_relationships",
        "exit",
    ]


def test_relationship_handler_missing_resource_raises_resource_not_found() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    uow = FakeUnitOfWork({})
    handler = GetResourceRelationshipsHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(GetResourceRelationshipsQuery(tenant_id, resource_id))

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == resource_id
    assert uow.commits == 0
    assert uow.events == [
        "enter",
        "resource_queries.get_resource_relationships",
        "exit",
    ]


def test_resource_relationships_return_current_incoming_and_outgoing_rows(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "resource-a")
        outbound_target = _resource(setup, tenant_id, "resource-b")
        inbound_source = _resource(setup, tenant_id, "resource-c")
        transitive_target = _resource(setup, tenant_id, "resource-d")
        tenant_b_id = _seed_tenant(setup, "tenant-b")
        tenant_b_source = _resource(setup, tenant_b_id, "tenant-b-source")
        tenant_b_target = _resource(setup, tenant_b_id, "tenant-b-target")
        t1 = _at(1, 10, 0, 1)
        t2 = _at(1, 10, 0, 2)
        t3 = _at(1, 10, 0, 3)
        historical = _relationship(
            setup,
            resource,
            outbound_target,
            valid_from=_at(1, 9),
            valid_to=_at(1, 9, 30),
        )
        outgoing = _relationship(
            setup,
            resource,
            outbound_target,
            valid_from=t1,
        )
        incoming = _relationship(
            setup,
            inbound_source,
            resource,
            valid_from=t2,
        )
        same_keys_type = _extra_relationship_type_id(setup)
        tied = _relationship(
            setup,
            resource,
            outbound_target,
            relationship_type_id=same_keys_type,
            valid_from=t1,
        )
        transitive = _relationship(
            setup,
            outbound_target,
            transitive_target,
            valid_from=t3,
        )
        tenant_b_relationship = _relationship(
            setup,
            tenant_b_source,
            tenant_b_target,
            valid_from=t3,
        )
        setup.commit()

    handler = GetResourceRelationshipsHandler(_uow_factory(SessionLocal))
    with _capture_sql(migrated_engine) as statements:
        result = handler.handle(
            GetResourceRelationshipsQuery(
                tenant_id=tenant_id,
                resource_id=resource.id,
            )
        )

    selects = _selects(statements)
    sql = "\n".join(selects).upper()
    assert len(selects) == RELATIONSHIP_SELECT_COUNT
    assert "RESOURCE_RELATIONSHIP" in sql
    assert "SOURCE_RESOURCE_ID" in sql
    assert "TARGET_RESOURCE_ID" in sql
    assert "TENANT_ID" in sql
    assert "VALID_TO IS NULL" in sql
    assert "OFFSET" not in sql
    assert "COUNT" not in sql
    assert "DISTINCT" not in sql
    assert "WITH RECURSIVE" not in sql
    assert "RESOURCE_MERGE" not in sql
    assert "LIMIT" not in sql

    assert result.resource_id == resource.id
    assert result.tenant_id == tenant_id
    assert [item.id for item in result.relationships] == [
        outgoing.id,
        tied.id,
        incoming.id,
    ]
    assert [item.direction for item in result.relationships] == [
        "outgoing",
        "outgoing",
        "incoming",
    ]
    assert result.relationships[0].source_resource_id == resource.id
    assert result.relationships[0].target_resource_id == outbound_target.id
    assert result.relationships[-1].source_resource_id == inbound_source.id
    assert result.relationships[-1].target_resource_id == resource.id
    assert historical.id not in {item.id for item in result.relationships}
    assert transitive.id not in {item.id for item in result.relationships}
    assert tenant_b_relationship.id not in {item.id for item in result.relationships}
    assert result.relationships[0].valid_from == t1
    assert result.relationships[0].confidence_score == Decimal("0.9000")
    assert result.relationships[0].source == "test"
    assert result.relationships[0].created_at


def test_resource_relationships_empty_for_resource_without_current_relationships(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "isolated")
        setup.commit()

    handler = GetResourceRelationshipsHandler(_uow_factory(SessionLocal))
    with _capture_sql(migrated_engine) as statements:
        result = handler.handle(GetResourceRelationshipsQuery(tenant_id, resource.id))

    assert result.relationships == ()
    assert len(_selects(statements)) == RELATIONSHIP_SELECT_COUNT


def test_resource_relationships_wrong_tenant_matches_missing_and_stops_after_core_query(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "tenant-owned")
        wrong_tenant_id = _seed_tenant(setup, "wrong-tenant")
        setup.commit()

    handler = GetResourceRelationshipsHandler(_uow_factory(SessionLocal))
    with _capture_sql(migrated_engine) as statements:
        with pytest.raises(EntityNotFoundError) as exc_info:
            handler.handle(
                GetResourceRelationshipsQuery(wrong_tenant_id, resource.id)
            )

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == resource.id
    selects = _selects(statements)
    assert len(selects) == 1
    assert "RESOURCE_RELATIONSHIP" not in selects[0].upper()


def test_resource_relationships_missing_resource_stops_after_core_query(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        setup.commit()

    handler = GetResourceRelationshipsHandler(_uow_factory(SessionLocal))
    with _capture_sql(migrated_engine) as statements:
        with pytest.raises(EntityNotFoundError):
            handler.handle(GetResourceRelationshipsQuery(tenant_id, uuid4()))

    assert len(_selects(statements)) == 1


def test_resource_relationship_query_count_is_independent_of_relationship_count(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "dense")
        for index in range(20):
            related = _resource(setup, tenant_id, f"related-{index}")
            if index % 2 == 0:
                _relationship(setup, resource, related, valid_from=_at(2, 10, index))
            else:
                _relationship(setup, related, resource, valid_from=_at(2, 10, index))
        setup.commit()

    handler = GetResourceRelationshipsHandler(_uow_factory(SessionLocal))
    with _capture_sql(migrated_engine) as statements:
        result = handler.handle(GetResourceRelationshipsQuery(tenant_id, resource.id))

    assert len(result.relationships) == 20
    assert len(_selects(statements)) == RELATIONSHIP_SELECT_COUNT


def test_resource_relationships_do_not_merge_canonical_relationship_sets(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        source_resource = _resource(setup, tenant_id, "source")
        canonical_resource = _resource(setup, tenant_id, "canonical")
        source_target = _resource(setup, tenant_id, "source-target")
        canonical_target = _resource(setup, tenant_id, "canonical-target")
        source_relationship = _relationship(setup, source_resource, source_target)
        canonical_relationship = _relationship(
            setup,
            canonical_resource,
            canonical_target,
        )
        _merge(setup, source_resource, canonical_resource)
        setup.commit()

    relationship_handler = GetResourceRelationshipsHandler(_uow_factory(SessionLocal))
    canonical_handler = ResolveCanonicalResourceHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        relationships = relationship_handler.handle(
            GetResourceRelationshipsQuery(tenant_id, source_resource.id)
        )

    assert len(_selects(statements)) == RELATIONSHIP_SELECT_COUNT
    assert [item.id for item in relationships.relationships] == [source_relationship.id]
    assert relationships.relationships[0].source_resource_id == source_resource.id
    assert canonical_relationship.id not in {
        item.id for item in relationships.relationships
    }
    canonical = canonical_handler.handle(
        ResolveCanonicalResourceQuery(tenant_id, source_resource.id)
    )
    assert canonical.canonical_resource_id == canonical_resource.id


def test_resource_details_and_history_do_not_include_relationship_read_model(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, "details")
        target = _resource(setup, tenant_id, "target")
        _relationship(setup, resource, target)
        setup.commit()

    details = GetResourceDetailsHandler(_uow_factory(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id, resource.id)
    )
    history = GetResourceHistoryHandler(_uow_factory(SessionLocal)).handle(
        GetResourceHistoryQuery(tenant_id, resource.id)
    )

    assert not hasattr(details, "relationships")
    assert not hasattr(history, "relationships")
