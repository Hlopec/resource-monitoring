from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.errors import ConflictError, EntityNotFoundError
from app.application.handlers import ResolveCanonicalResourceHandler
from app.application.handlers.resources import MAX_RESOURCE_MERGE_DEPTH
from app.application.queries import ResolveCanonicalResourceQuery
from app.application.results import (
    CanonicalResourceResolvedResult,
    ResourceReadResult,
)
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Resource,
    ResourceMerge,
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

    def get_by_id(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append(f"resources.get_by_id:{resource_id}")
        return self._resources.get((tenant_id, resource_id))

    def get_for_update(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append(f"resources.get_for_update:{resource_id}")
        return self._resources.get((tenant_id, resource_id))


class FakeResourceMergeRepository:
    def __init__(
        self,
        events: list[str],
        edges: dict[tuple[UUID, UUID], UUID],
    ) -> None:
        self._events = events
        self._edges = edges
        self.added: list[object] = []

    def get_outgoing_merge(
        self,
        tenant_id: UUID,
        source_resource_id: UUID,
    ) -> object | None:
        self._events.append(f"resource_merges.get_outgoing_merge:{source_resource_id}")
        target_resource_id = self._edges.get((tenant_id, source_resource_id))
        if target_resource_id is None:
            return None
        return SimpleNamespace(
            source_resource_id=source_resource_id,
            target_resource_id=target_resource_id,
        )

    def list_incoming_merges(
        self,
        tenant_id: UUID,
        target_resource_id: UUID,
    ) -> tuple[object, ...]:
        self._events.append(f"resource_merges.list_incoming_merges:{target_resource_id}")
        return ()

    def add(self, merge: object) -> None:
        self._events.append("resource_merges.add")
        self.added.append(merge)


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        resources: dict[UUID, object],
        edges: dict[UUID, UUID],
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self.resources = FakeResourceRepository(
            self.events,
            {(tenant_id, resource_id): resource for resource_id, resource in resources.items()},
        )
        self.resource_merges = FakeResourceMergeRepository(
            self.events,
            {(tenant_id, source_id): target_id for source_id, target_id in edges.items()},
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


def _resource(resource_id: UUID | None = None, *, tenant_id: UUID | None = None) -> object:
    resource_id = resource_id or uuid4()
    return SimpleNamespace(
        id=resource_id,
        tenant_id=tenant_id or uuid4(),
        canonical_name=f"resource-{resource_id}.example.com",
        display_name=f"Resource {resource_id}",
    )


def _query(
    *,
    tenant_id: UUID | None = None,
    resource_id: UUID | None = None,
) -> ResolveCanonicalResourceQuery:
    return ResolveCanonicalResourceQuery(
        tenant_id=tenant_id or uuid4(),
        resource_id=resource_id or uuid4(),
    )


def _uow(
    *,
    tenant_id: UUID,
    resources: dict[UUID, object],
    edges: dict[UUID, UUID] | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        tenant_id=tenant_id,
        resources=resources,
        edges=edges or {},
    )


def test_resolve_canonical_resource_query_is_frozen_data_only() -> None:
    query = _query()

    assert is_dataclass(query)
    assert set(query.__annotations__) == {"tenant_id", "resource_id"}
    assert not hasattr(query, "execute")
    assert not hasattr(query, "save")
    assert not hasattr(query, "commit")
    with pytest.raises(FrozenInstanceError):
        query.resource_id = uuid4()


def test_canonical_resource_resolved_result_is_immutable_and_entity_free() -> None:
    canonical = ResourceReadResult(
        id=uuid4(),
        tenant_id=uuid4(),
        canonical_name="canonical.example.com",
        display_name="Canonical",
    )
    result = CanonicalResourceResolvedResult(
        requested_resource_id=uuid4(),
        canonical_resource_id=canonical.id,
        immediate_target_resource_id=None,
        merge_depth=0,
        is_canonical=True,
        canonical_resource=canonical,
    )

    assert is_dataclass(result)
    assert not isinstance(result.canonical_resource, Resource)
    with pytest.raises(FrozenInstanceError):
        result.merge_depth = 1
    with pytest.raises(FrozenInstanceError):
        result.canonical_resource.display_name = "changed"


def test_missing_requested_resource_stops_before_merge_lookup() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    uow = _uow(tenant_id=tenant_id, resources={})
    handler = ResolveCanonicalResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(_query(tenant_id=tenant_id, resource_id=resource_id))

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == resource_id
    assert uow.events == ["enter", f"resources.get_by_id:{resource_id}", "exit"]
    assert uow.commits == 0


def test_unmerged_resource_resolves_to_itself_without_commit_or_locks() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    resource = _resource(resource_id, tenant_id=tenant_id)
    uow = _uow(tenant_id=tenant_id, resources={resource_id: resource})
    handler = ResolveCanonicalResourceHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(_query(tenant_id=tenant_id, resource_id=resource_id))

    assert result.requested_resource_id == resource_id
    assert result.canonical_resource_id == resource_id
    assert result.immediate_target_resource_id is None
    assert result.merge_depth == 0
    assert result.is_canonical is True
    assert result.canonical_resource.id == resource_id
    assert result.canonical_resource.canonical_name == resource.canonical_name
    assert uow.events == [
        "enter",
        f"resources.get_by_id:{resource_id}",
        f"resource_merges.get_outgoing_merge:{resource_id}",
        f"resources.get_by_id:{resource_id}",
        "exit",
    ]
    assert not any("get_for_update" in event for event in uow.events)
    assert "commit" not in uow.events
    assert uow.resource_merges.added == []


def test_multi_hop_resolution_tracks_immediate_and_terminal_targets() -> None:
    tenant_id = uuid4()
    first_id = UUID("01984000-0000-7000-8000-000000000001")
    second_id = UUID("01984000-0000-7000-8000-000000000002")
    third_id = UUID("01984000-0000-7000-8000-000000000003")
    resources = {
        first_id: _resource(first_id, tenant_id=tenant_id),
        second_id: _resource(second_id, tenant_id=tenant_id),
        third_id: _resource(third_id, tenant_id=tenant_id),
    }
    uow = _uow(
        tenant_id=tenant_id,
        resources=resources,
        edges={first_id: second_id, second_id: third_id},
    )
    handler = ResolveCanonicalResourceHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))

    assert result.requested_resource_id == first_id
    assert result.immediate_target_resource_id == second_id
    assert result.canonical_resource_id == third_id
    assert result.merge_depth == 2
    assert result.is_canonical is False
    assert result.canonical_resource.id == third_id
    assert uow.events == [
        "enter",
        f"resources.get_by_id:{first_id}",
        f"resource_merges.get_outgoing_merge:{first_id}",
        f"resource_merges.get_outgoing_merge:{second_id}",
        f"resource_merges.get_outgoing_merge:{third_id}",
        f"resources.get_by_id:{third_id}",
        "exit",
    ]


def test_incoming_branches_follow_only_outgoing_edges() -> None:
    tenant_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    canonical_id = uuid4()
    resources = {
        first_id: _resource(first_id, tenant_id=tenant_id),
        second_id: _resource(second_id, tenant_id=tenant_id),
        canonical_id: _resource(canonical_id, tenant_id=tenant_id),
    }
    first_uow = _uow(
        tenant_id=tenant_id,
        resources=resources,
        edges={first_id: canonical_id, second_id: canonical_id},
    )
    second_uow = _uow(
        tenant_id=tenant_id,
        resources=resources,
        edges={first_id: canonical_id, second_id: canonical_id},
    )
    canonical_uow = _uow(
        tenant_id=tenant_id,
        resources=resources,
        edges={first_id: canonical_id, second_id: canonical_id},
    )
    handler = ResolveCanonicalResourceHandler(
        FakeUnitOfWorkFactory(first_uow, second_uow, canonical_uow)
    )

    first = handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))
    second = handler.handle(_query(tenant_id=tenant_id, resource_id=second_id))
    canonical = handler.handle(_query(tenant_id=tenant_id, resource_id=canonical_id))

    assert first.canonical_resource_id == canonical_id
    assert second.canonical_resource_id == canonical_id
    assert canonical.canonical_resource_id == canonical_id
    assert canonical.merge_depth == 0
    for uow in (first_uow, second_uow, canonical_uow):
        assert not any("list_incoming_merges" in event for event in uow.events)


def test_defensive_cycle_detection_stops_finite_traversal() -> None:
    tenant_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    third_id = uuid4()
    resources = {
        first_id: _resource(first_id, tenant_id=tenant_id),
        second_id: _resource(second_id, tenant_id=tenant_id),
        third_id: _resource(third_id, tenant_id=tenant_id),
    }
    uow = _uow(
        tenant_id=tenant_id,
        resources=resources,
        edges={first_id: second_id, second_id: third_id, third_id: first_id},
    )
    handler = ResolveCanonicalResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))

    assert str(exc_info.value) == "Resource merge lineage contains a cycle"
    assert exc_info.value.entity_type == "ResourceMerge"
    assert exc_info.value.conflict_field == "lineage"
    assert uow.events.count(f"resource_merges.get_outgoing_merge:{first_id}") == 1
    assert "commit" not in uow.events
    assert uow.exited is True


def test_direct_fake_cycle_is_detected() -> None:
    tenant_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    resources = {
        first_id: _resource(first_id, tenant_id=tenant_id),
        second_id: _resource(second_id, tenant_id=tenant_id),
    }
    uow = _uow(
        tenant_id=tenant_id,
        resources=resources,
        edges={first_id: second_id, second_id: first_id},
    )
    handler = ResolveCanonicalResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError):
        handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))

    assert "commit" not in uow.events
    assert uow.exited is True


def test_maximum_depth_allows_64_edges_and_rejects_65th_edge() -> None:
    tenant_id = uuid4()
    node_ids = [uuid4() for _ in range(MAX_RESOURCE_MERGE_DEPTH + 2)]
    resources = {
        node_id: _resource(node_id, tenant_id=tenant_id) for node_id in node_ids
    }
    allowed_edges = {
        node_ids[index]: node_ids[index + 1]
        for index in range(MAX_RESOURCE_MERGE_DEPTH)
    }
    too_deep_edges = {
        node_ids[index]: node_ids[index + 1]
        for index in range(MAX_RESOURCE_MERGE_DEPTH + 1)
    }
    allowed_uow = _uow(tenant_id=tenant_id, resources=resources, edges=allowed_edges)
    too_deep_uow = _uow(tenant_id=tenant_id, resources=resources, edges=too_deep_edges)
    handler = ResolveCanonicalResourceHandler(
        FakeUnitOfWorkFactory(allowed_uow, too_deep_uow)
    )

    allowed = handler.handle(_query(tenant_id=tenant_id, resource_id=node_ids[0]))
    with pytest.raises(ConflictError) as exc_info:
        handler.handle(_query(tenant_id=tenant_id, resource_id=node_ids[0]))

    assert allowed.merge_depth == MAX_RESOURCE_MERGE_DEPTH
    assert allowed.canonical_resource_id == node_ids[MAX_RESOURCE_MERGE_DEPTH]
    assert str(exc_info.value) == "Resource merge lineage exceeds maximum depth"
    assert exc_info.value.conflict_field == "merge_depth"
    assert exc_info.value.conflict_value == MAX_RESOURCE_MERGE_DEPTH
    assert "commit" not in too_deep_uow.events


def test_broken_terminal_resource_raises_invariant_conflict() -> None:
    tenant_id = uuid4()
    first_id = uuid4()
    missing_target_id = uuid4()
    resources = {first_id: _resource(first_id, tenant_id=tenant_id)}
    uow = _uow(
        tenant_id=tenant_id,
        resources=resources,
        edges={first_id: missing_target_id},
    )
    handler = ResolveCanonicalResourceHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(ConflictError) as exc_info:
        handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))

    assert str(exc_info.value) == "Resource merge lineage target is missing"
    assert exc_info.value.entity_type == "ResourceMerge"
    assert exc_info.value.conflict_field == "target_resource_id"
    assert exc_info.value.conflict_value == missing_target_id
    assert "commit" not in uow.events


def test_each_invocation_uses_fresh_uow_and_local_visited_state() -> None:
    tenant_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    resources = {
        first_id: _resource(first_id, tenant_id=tenant_id),
        second_id: _resource(second_id, tenant_id=tenant_id),
    }
    first_uow = _uow(tenant_id=tenant_id, resources=resources, edges={first_id: second_id})
    second_uow = _uow(tenant_id=tenant_id, resources=resources, edges={first_id: second_id})
    factory = FakeUnitOfWorkFactory(first_uow, second_uow)
    handler = ResolveCanonicalResourceHandler(factory)

    first = handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))
    second = handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))

    assert first.canonical_resource_id == second_id
    assert second.canonical_resource_id == second_id
    assert factory.created == [first_uow, second_uow]


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
        _db_resource(session, tenant.id, _slug(f"resource-{index}"))
        for index in range(count)
    ]
    session.add_all(resources)
    session.flush()
    return tenant.id, [resource.id for resource in resources]


def _db_resource(session: Session, tenant_id: UUID, canonical_name: str) -> Resource:
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
    merged_at: datetime | None = None,
) -> ResourceMerge:
    return ResourceMerge(
        tenant_id=tenant_id,
        source_resource_id=source_resource_id,
        target_resource_id=target_resource_id,
        reason="duplicate",
        source="manual",
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


def test_sqlalchemy_unmerged_resource_resolves_to_self_and_does_not_mutate(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=1)
        resource_id = resource_ids[0]
        resource = setup_session.get(Resource, resource_id)
        assert resource is not None
        version = resource.record_version
        setup_session.commit()
    handler = ResolveCanonicalResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(_query(tenant_id=tenant_id, resource_id=resource_id))

    assert result.requested_resource_id == resource_id
    assert result.canonical_resource_id == resource_id
    assert result.immediate_target_resource_id is None
    assert result.merge_depth == 0
    assert result.is_canonical is True
    assert result.canonical_resource.id == resource_id
    with SessionLocal() as verification:
        assert _merge_count(verification, tenant_id) == 0
        resource = verification.get(Resource, resource_id)
        assert resource is not None
        assert resource.record_version == version


def test_sqlalchemy_one_hop_resolution(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=2)
        source_id, target_id = resource_ids
        setup_session.add(_merge(tenant_id, source_id, target_id))
        target = setup_session.get(Resource, target_id)
        assert target is not None
        target_name = target.canonical_name
        setup_session.commit()
    handler = ResolveCanonicalResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(_query(tenant_id=tenant_id, resource_id=source_id))

    assert result.requested_resource_id == source_id
    assert result.immediate_target_resource_id == target_id
    assert result.canonical_resource_id == target_id
    assert result.merge_depth == 1
    assert result.is_canonical is False
    assert result.canonical_resource.id == target_id
    assert result.canonical_resource.canonical_name == target_name


def test_sqlalchemy_multi_hop_resolution_for_each_node(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        first_id, second_id, third_id = resource_ids
        setup_session.add(_merge(tenant_id, first_id, second_id, merged_at=_now(-20)))
        setup_session.add(_merge(tenant_id, second_id, third_id, merged_at=_now(-10)))
        setup_session.commit()
    handler = ResolveCanonicalResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))
    second = handler.handle(_query(tenant_id=tenant_id, resource_id=second_id))
    third = handler.handle(_query(tenant_id=tenant_id, resource_id=third_id))

    assert first.immediate_target_resource_id == second_id
    assert first.canonical_resource_id == third_id
    assert first.merge_depth == 2
    assert first.is_canonical is False
    assert second.immediate_target_resource_id == third_id
    assert second.canonical_resource_id == third_id
    assert second.merge_depth == 1
    assert third.immediate_target_resource_id is None
    assert third.canonical_resource_id == third_id
    assert third.merge_depth == 0
    assert third.is_canonical is True


def test_sqlalchemy_multiple_incoming_branches_resolve_to_same_terminal(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        first_id, second_id, terminal_id = resource_ids
        setup_session.add(_merge(tenant_id, first_id, terminal_id))
        setup_session.add(_merge(tenant_id, second_id, terminal_id))
        setup_session.commit()
    handler = ResolveCanonicalResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    first = handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))
    second = handler.handle(_query(tenant_id=tenant_id, resource_id=second_id))
    terminal = handler.handle(_query(tenant_id=tenant_id, resource_id=terminal_id))

    assert first.canonical_resource_id == terminal_id
    assert second.canonical_resource_id == terminal_id
    assert terminal.canonical_resource_id == terminal_id
    assert terminal.is_canonical is True


def test_sqlalchemy_wrong_tenant_requested_resource_is_not_found(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, _ = _seed_tenant_resources(setup_session, count=1)
        other_tenant = Tenant(
            slug=_slug("other"),
            display_name="Other",
            status="active",
        )
        setup_session.add(other_tenant)
        setup_session.flush()
        other_resource = _db_resource(setup_session, other_tenant.id, _slug("other"))
        setup_session.add(other_resource)
        setup_session.commit()
        other_resource_id = other_resource.id
    handler = ResolveCanonicalResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(_query(tenant_id=tenant_id, resource_id=other_resource_id))

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"


def test_sqlalchemy_read_only_query_does_not_rewrite_lineage(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_ids = _seed_tenant_resources(setup_session, count=3)
        first_id, second_id, third_id = resource_ids
        first_merge = _merge(tenant_id, first_id, second_id, merged_at=_now(-20))
        second_merge = _merge(tenant_id, second_id, third_id, merged_at=_now(-10))
        setup_session.add_all([first_merge, second_merge])
        setup_session.commit()
        first_merge_id = first_merge.id
        second_merge_id = second_merge.id
    handler = ResolveCanonicalResourceHandler(lambda: SQLAlchemyUnitOfWork(SessionLocal))

    result = handler.handle(_query(tenant_id=tenant_id, resource_id=first_id))

    assert result.canonical_resource_id == third_id
    with SessionLocal() as verification:
        edges = list(
            verification.scalars(
                select(ResourceMerge)
                .where(ResourceMerge.tenant_id == tenant_id)
                .order_by(ResourceMerge.source_resource_id)
            )
        )
        assert {edge.id for edge in edges} == {first_merge_id, second_merge_id}
        assert {(edge.source_resource_id, edge.target_resource_id) for edge in edges} == {
            (first_id, second_id),
            (second_id, third_id),
        }
