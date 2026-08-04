from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.application.ports.temporal import (
    ResourceClassificationRepository,
    ResourceIdentifierRepository,
    ResourceLabelRepository,
    ResourceOwnershipRepository,
    ResourceRelationshipRepository,
    ResourceStateRepository,
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
    RelationshipType,
    Resource,
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceOwnership,
    ResourceRelationship,
    ResourceState,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import (
    SQLAlchemyUnitOfWork,
    UnitOfWorkNotActiveError,
)
from app.persistence.sqlalchemy.repositories import (
    SQLAlchemyResourceClassificationRepository,
    SQLAlchemyResourceIdentifierRepository,
    SQLAlchemyResourceLabelRepository,
    SQLAlchemyResourceOwnershipRepository,
    SQLAlchemyResourceRelationshipRepository,
    SQLAlchemyResourceStateRepository,
)


class TrackingSession(Session):
    commits = 0
    rollbacks = 0
    closes = 0

    def commit(self) -> None:
        self.commits += 1
        super().commit()

    def rollback(self) -> None:
        self.rollbacks += 1
        super().rollback()

    def close(self) -> None:
        self.closes += 1
        super().close()


@dataclass(frozen=True)
class TemporalRefs:
    tenant_id: UUID
    other_tenant_id: UUID
    resource_id: UUID
    other_resource_id: UUID
    target_resource_id: UUID
    other_tenant_resource_id: UUID
    organization_id: UUID
    other_organization_id: UUID
    identifier_type_id: UUID
    ownership_role_id: UUID
    relationship_type_id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    other_classification_value_id: UUID
    label_id: UUID
    other_label_id: UUID
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID


def _session_factory(engine: Engine) -> sessionmaker[TrackingSession]:
    return sessionmaker(
        bind=engine,
        class_=TrackingSession,
        expire_on_commit=False,
    )


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _now(offset_seconds: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


def _seed_refs(session: Session) -> TemporalRefs:
    seed_catalogs(session)
    session.flush()
    tenant = Tenant(slug=_slug("tenant-a"), display_name="Tenant A", status="active")
    other_tenant = Tenant(
        slug=_slug("tenant-b"),
        display_name="Tenant B",
        status="active",
    )
    session.add_all([tenant, other_tenant])
    session.flush()

    organization = Organization(
        tenant_id=tenant.id,
        canonical_name=_slug("platform"),
        display_name="Platform",
        status="active",
    )
    other_organization = Organization(
        tenant_id=other_tenant.id,
        canonical_name=_slug("other-platform"),
        display_name="Other Platform",
        status="active",
    )
    session.add_all([organization, other_organization])
    session.flush()

    resource_type_id = _catalog_id(session, ResourceType, "domain")
    lifecycle_status_id = _catalog_id(session, LifecycleStatus, "active")
    criticality_id = _catalog_id(session, Criticality, "medium")
    exposure_level_id = _catalog_id(session, ExposureLevel, "public")
    resource = _resource(
        tenant.id,
        resource_type_id,
        lifecycle_status_id,
        criticality_id,
        exposure_level_id,
        _slug("resource"),
    )
    target_resource = _resource(
        tenant.id,
        resource_type_id,
        lifecycle_status_id,
        criticality_id,
        exposure_level_id,
        _slug("target"),
    )
    other_resource = _resource(
        tenant.id,
        resource_type_id,
        lifecycle_status_id,
        criticality_id,
        exposure_level_id,
        _slug("other-resource"),
    )
    other_tenant_resource = _resource(
        other_tenant.id,
        resource_type_id,
        lifecycle_status_id,
        criticality_id,
        exposure_level_id,
        _slug("other-tenant-resource"),
    )
    label = Label(tenant_id=tenant.id, key=_slug("key"), value="Production")
    other_label = Label(tenant_id=tenant.id, key=_slug("other-key"), value="Security")
    session.add_all(
        [
            resource,
            target_resource,
            other_resource,
            other_tenant_resource,
            label,
            other_label,
        ]
    )
    session.flush()

    classification_type_id = _catalog_id(session, ClassificationType, "environment")
    production_value_id = _catalog_id(session, ClassificationValue, "production")
    staging_value_id = _catalog_id(session, ClassificationValue, "staging")

    return TemporalRefs(
        tenant_id=tenant.id,
        other_tenant_id=other_tenant.id,
        resource_id=resource.id,
        other_resource_id=other_resource.id,
        target_resource_id=target_resource.id,
        other_tenant_resource_id=other_tenant_resource.id,
        organization_id=organization.id,
        other_organization_id=other_organization.id,
        identifier_type_id=_catalog_id(session, IdentifierType, "fqdn"),
        ownership_role_id=_catalog_id(session, OwnershipRole, "owner"),
        relationship_type_id=_catalog_id(session, RelationshipType, "depends_on"),
        classification_type_id=classification_type_id,
        classification_value_id=production_value_id,
        other_classification_value_id=staging_value_id,
        label_id=label.id,
        other_label_id=other_label.id,
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
    )


def _catalog_id(session: Session, model_type: type[object], code: str) -> UUID:
    entity_id = session.scalar(select(model_type.id).where(model_type.code == code))
    assert entity_id is not None
    return entity_id


def _resource(
    tenant_id: UUID,
    resource_type_id: UUID,
    lifecycle_status_id: UUID,
    criticality_id: UUID,
    exposure_level_id: UUID,
    canonical_name: str,
) -> Resource:
    now = _now()
    return Resource(
        tenant_id=tenant_id,
        resource_type_id=resource_type_id,
        canonical_name=canonical_name,
        display_name=canonical_name,
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=now,
        last_seen_at=now,
    )


def _identifier(
    refs: TemporalRefs,
    *,
    value: str = "example.com",
    namespace: str | None = None,
    is_primary: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceIdentifier:
    return ResourceIdentifier(
        tenant_id=refs.tenant_id,
        resource_id=refs.resource_id,
        identifier_type_id=refs.identifier_type_id,
        namespace=namespace,
        normalized_value=value,
        original_value=value,
        value_hash=f"hash-{value}",
        is_primary=is_primary,
        confidence_score=Decimal("0.9500"),
        valid_from=valid_from or _now(-60),
        valid_to=valid_to,
    )


def _ownership(
    refs: TemporalRefs,
    *,
    organization_id: UUID | None = None,
    is_primary: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceOwnership:
    return ResourceOwnership(
        tenant_id=refs.tenant_id,
        resource_id=refs.resource_id,
        organization_id=organization_id or refs.organization_id,
        ownership_role_id=refs.ownership_role_id,
        is_primary=is_primary,
        confidence_score=Decimal("0.9500"),
        valid_from=valid_from or _now(-60),
        valid_to=valid_to,
        source="manual",
    )


def _relationship(
    refs: TemporalRefs,
    *,
    target_resource_id: UUID | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceRelationship:
    return ResourceRelationship(
        tenant_id=refs.tenant_id,
        source_resource_id=refs.resource_id,
        target_resource_id=target_resource_id or refs.target_resource_id,
        relationship_type_id=refs.relationship_type_id,
        confidence_score=Decimal("0.9500"),
        valid_from=valid_from or _now(-60),
        valid_to=valid_to,
        source="manual",
    )


def _classification(
    refs: TemporalRefs,
    *,
    classification_value_id: UUID | None = None,
    is_primary: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceClassification:
    return ResourceClassification(
        tenant_id=refs.tenant_id,
        resource_id=refs.resource_id,
        classification_type_id=refs.classification_type_id,
        classification_value_id=classification_value_id or refs.classification_value_id,
        is_primary=is_primary,
        confidence_score=Decimal("0.9500"),
        valid_from=valid_from or _now(-60),
        valid_to=valid_to,
        source="manual",
    )


def _label_assignment(
    refs: TemporalRefs,
    *,
    label_id: UUID | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceLabel:
    return ResourceLabel(
        tenant_id=refs.tenant_id,
        resource_id=refs.resource_id,
        label_id=label_id or refs.label_id,
        valid_from=valid_from or _now(-60),
        valid_to=valid_to,
        source="manual",
    )


def _state(
    refs: TemporalRefs,
    *,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceState:
    return ResourceState(
        tenant_id=refs.tenant_id,
        resource_id=refs.resource_id,
        lifecycle_status_id=refs.lifecycle_status_id,
        criticality_id=refs.criticality_id,
        exposure_level_id=refs.exposure_level_id,
        source_priority=100,
        confidence_score=Decimal("0.9500"),
        valid_from=valid_from or _now(-60),
        valid_to=valid_to,
        source="manual",
    )


def _count_by_id(session: Session, model_type: type[object], entity_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(model_type).where(model_type.id == entity_id)
        )
        or 0
    )


def _method_names(repository: object) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(repository, inspect.ismethod)
        if not name.startswith("_")
    }


def _accepts_identifier_repository(
    repository: ResourceIdentifierRepository,
) -> ResourceIdentifierRepository:
    return repository


def _accepts_ownership_repository(
    repository: ResourceOwnershipRepository,
) -> ResourceOwnershipRepository:
    return repository


def _accepts_relationship_repository(
    repository: ResourceRelationshipRepository,
) -> ResourceRelationshipRepository:
    return repository


def _accepts_classification_repository(
    repository: ResourceClassificationRepository,
) -> ResourceClassificationRepository:
    return repository


def _accepts_label_repository(
    repository: ResourceLabelRepository,
) -> ResourceLabelRepository:
    return repository


def _accepts_state_repository(
    repository: ResourceStateRepository,
) -> ResourceStateRepository:
    return repository


def test_temporal_repositories_satisfy_protocols_and_use_injected_session(
    db_session: Session,
) -> None:
    repositories = (
        (
            SQLAlchemyResourceIdentifierRepository(db_session),
            _accepts_identifier_repository,
        ),
        (
            SQLAlchemyResourceOwnershipRepository(db_session),
            _accepts_ownership_repository,
        ),
        (
            SQLAlchemyResourceRelationshipRepository(db_session),
            _accepts_relationship_repository,
        ),
        (
            SQLAlchemyResourceClassificationRepository(db_session),
            _accepts_classification_repository,
        ),
        (SQLAlchemyResourceLabelRepository(db_session), _accepts_label_repository),
        (SQLAlchemyResourceStateRepository(db_session), _accepts_state_repository),
    )

    for repository, accepts in repositories:
        assert accepts(repository) is repository
        assert repository.session is db_session
        assert repository.__class__.__module__.startswith("app.persistence.sqlalchemy")
        assert {"commit", "rollback", "delete"}.isdisjoint(_method_names(repository))


def test_identifier_current_reads_are_tenant_scoped_and_ordered(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    historical = _identifier(
        refs,
        value="old.example.com",
        valid_from=_now(-120),
        valid_to=_now(-90),
    )
    first = _identifier(refs, value="b.example.com", valid_from=_now(-30))
    second = _identifier(refs, value="a.example.com", valid_from=_now(-20))
    other_resource = _identifier(refs, value="other.example.com")
    other_resource.resource_id = refs.other_resource_id
    db_session.add_all([historical, first, second, other_resource])
    db_session.flush()
    repository = SQLAlchemyResourceIdentifierRepository(db_session)

    rows = repository.get_current_for_resource(refs.tenant_id, refs.resource_id)

    assert [row.normalized_value for row in rows] == ["a.example.com", "b.example.com"]
    assert repository.get_current_for_resource(refs.other_tenant_id, refs.resource_id) == []
    assert (
        repository.find_current_by_value(
            refs.tenant_id,
            refs.identifier_type_id,
            "a.example.com",
        )
        is second
    )
    assert (
        repository.find_current_by_value(
            refs.tenant_id,
            refs.identifier_type_id,
            "missing.example.com",
        )
        is None
    )
    assert repository.find_current_by_value(refs.other_tenant_id, refs.identifier_type_id, "a.example.com") is None
    assert (
        repository.find_current_by_value(
            refs.tenant_id,
            uuid4(),
            "a.example.com",
        )
        is None
    )


def test_ownership_current_reads_are_tenant_scoped_and_primary_aware(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    historical = _ownership(refs, valid_from=_now(-120), valid_to=_now(-90))
    current = _ownership(refs, is_primary=True, valid_from=_now(-30))
    db_session.add_all([historical, current])
    db_session.flush()
    repository = SQLAlchemyResourceOwnershipRepository(db_session)

    assert repository.get_current_for_resource(refs.tenant_id, refs.resource_id) == [
        current
    ]
    assert repository.get_current_for_resource(refs.other_tenant_id, refs.resource_id) == []
    assert (
        repository.get_current_primary(
            refs.tenant_id,
            refs.resource_id,
            refs.ownership_role_id,
        )
        is current
    )
    assert (
        repository.get_current_primary(
            refs.tenant_id,
            refs.other_resource_id,
            refs.ownership_role_id,
        )
        is None
    )


def test_relationship_current_reads_preserve_incoming_and_outgoing_semantics(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    historical = _relationship(refs, valid_from=_now(-120), valid_to=_now(-90))
    outgoing = _relationship(refs, valid_from=_now(-30))
    incoming = ResourceRelationship(
        tenant_id=refs.tenant_id,
        source_resource_id=refs.other_resource_id,
        target_resource_id=refs.resource_id,
        relationship_type_id=refs.relationship_type_id,
        confidence_score=Decimal("0.9500"),
        valid_from=_now(-20),
        source="manual",
    )
    db_session.add_all([historical, outgoing, incoming])
    db_session.flush()
    repository = SQLAlchemyResourceRelationshipRepository(db_session)

    assert repository.list_current_outgoing(refs.tenant_id, refs.resource_id) == [
        outgoing
    ]
    assert repository.list_current_incoming(refs.tenant_id, refs.resource_id) == [
        incoming
    ]
    assert repository.list_current_outgoing(refs.other_tenant_id, refs.resource_id) == []
    assert repository.list_current_incoming(refs.other_tenant_id, refs.resource_id) == []


def test_classification_current_reads_are_tenant_scoped_and_primary_aware(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    historical = _classification(refs, valid_from=_now(-120), valid_to=_now(-90))
    current = _classification(refs, is_primary=True, valid_from=_now(-30))
    db_session.add_all([historical, current])
    db_session.flush()
    repository = SQLAlchemyResourceClassificationRepository(db_session)

    assert repository.get_current_for_resource(refs.tenant_id, refs.resource_id) == [
        current
    ]
    assert repository.get_current_for_resource(refs.other_tenant_id, refs.resource_id) == []
    assert (
        repository.get_current_primary(
            refs.tenant_id,
            refs.resource_id,
            refs.classification_type_id,
        )
        is current
    )
    assert (
        repository.get_current_primary(
            refs.tenant_id,
            refs.other_resource_id,
            refs.classification_type_id,
        )
        is None
    )


def test_label_current_reads_are_tenant_scoped_and_ordered(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    historical = _label_assignment(refs, valid_from=_now(-120), valid_to=_now(-90))
    second = _label_assignment(refs, label_id=refs.other_label_id, valid_from=_now(-30))
    first = _label_assignment(refs, label_id=refs.label_id, valid_from=_now(-20))
    db_session.add_all([historical, second, first])
    db_session.flush()
    repository = SQLAlchemyResourceLabelRepository(db_session)

    assert repository.get_current_for_resource(refs.tenant_id, refs.resource_id) == [
        first,
        second,
    ]
    assert repository.get_current_for_resource(refs.other_tenant_id, refs.resource_id) == []


def test_state_current_and_history_reads_are_tenant_scoped_and_ordered(
    db_session: Session,
) -> None:
    refs = _seed_refs(db_session)
    historical = _state(refs, valid_from=_now(-120), valid_to=_now(-90))
    current = _state(refs, valid_from=_now(-30))
    other_resource = _state(refs)
    other_resource.resource_id = refs.other_resource_id
    db_session.add_all([historical, current, other_resource])
    db_session.flush()
    repository = SQLAlchemyResourceStateRepository(db_session)

    assert repository.get_current(refs.tenant_id, refs.resource_id) is current
    assert repository.get_current(refs.other_tenant_id, refs.resource_id) is None
    assert repository.get_current(refs.tenant_id, refs.other_tenant_resource_id) is None
    assert repository.list_history(refs.tenant_id, refs.resource_id) == [
        historical,
        current,
    ]
    assert repository.list_history(refs.other_tenant_id, refs.resource_id) == []
    assert historical.valid_to is not None


@pytest.mark.parametrize(
    ("property_name", "model_type", "factory"),
    (
        ("resource_identifiers", ResourceIdentifier, _identifier),
        ("resource_ownerships", ResourceOwnership, _ownership),
        ("resource_relationships", ResourceRelationship, _relationship),
        ("resource_classifications", ResourceClassification, _classification),
        ("resource_labels", ResourceLabel, _label_assignment),
        ("resource_states", ResourceState, _state),
    ),
)
def test_temporal_add_commit_and_rollback(
    migrated_engine: Engine,
    property_name: str,
    model_type: type[object],
    factory: object,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    committed = factory(refs)
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        getattr(uow, property_name).add(committed)
        uow.commit()

    rolled_back = factory(refs)
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        getattr(uow, property_name).add(rolled_back)

    with SessionLocal() as verification:
        assert _count_by_id(verification, model_type, committed.id) == 1
        assert _count_by_id(verification, model_type, rolled_back.id) == 0


def test_explicit_temporal_flush_does_not_commit(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    identifier = _identifier(refs, value="flush.example.com")
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_identifiers.add(identifier)
        uow.resource_identifiers.flush()
        session = uow.resource_identifiers.session
        assert session.commits == 0
        assert identifier.created_at is not None

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceIdentifier, identifier.id) == 0


def test_temporal_constraint_failure_rolls_back_multi_repository_unit_of_work(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    identifier = _identifier(refs, value="atomic.example.com")
    ownership = _ownership(refs, is_primary=True)
    state = _state(refs)

    with pytest.raises(IntegrityError):
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            uow.resource_identifiers.add(identifier)
            uow.resource_ownerships.add(ownership)
            uow.resource_states.add(state)
            uow.resource_states.add(_state(refs))
            uow.commit()

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceIdentifier, identifier.id) == 0
        assert _count_by_id(verification, ResourceOwnership, ownership.id) == 0
        assert _count_by_id(verification, ResourceState, state.id) == 0

    replacement = _identifier(refs, value="after-failure.example.com")
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_identifiers.add(replacement)
        uow.commit()

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceIdentifier, replacement.id) == 1


def test_multi_repository_temporal_commit_and_rollback_are_atomic(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup_session:
        refs = _seed_refs(setup_session)
        setup_session.commit()

    committed_identifier = _identifier(refs, value="commit.example.com")
    committed_ownership = _ownership(refs, is_primary=True)
    committed_state = _state(refs)
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_identifiers.add(committed_identifier)
        uow.resource_ownerships.add(committed_ownership)
        uow.resource_states.add(committed_state)
        uow.commit()

    rollback_identifier = _identifier(refs, value="rollback.example.com")
    rollback_ownership = _ownership(refs)
    rollback_state = _state(refs)
    rollback_state.resource_id = refs.other_resource_id
    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        uow.resource_identifiers.add(rollback_identifier)
        uow.resource_ownerships.add(rollback_ownership)
        uow.resource_states.add(rollback_state)

    with SessionLocal() as verification:
        assert _count_by_id(verification, ResourceIdentifier, committed_identifier.id) == 1
        assert _count_by_id(verification, ResourceOwnership, committed_ownership.id) == 1
        assert _count_by_id(verification, ResourceState, committed_state.id) == 1
        assert _count_by_id(verification, ResourceIdentifier, rollback_identifier.id) == 0
        assert _count_by_id(verification, ResourceOwnership, rollback_ownership.id) == 0
        assert _count_by_id(verification, ResourceState, rollback_state.id) == 0


@pytest.mark.parametrize(
    "property_name",
    (
        "resource_identifiers",
        "resource_ownerships",
        "resource_relationships",
        "resource_classifications",
        "resource_labels",
        "resource_states",
    ),
)
def test_temporal_repositories_follow_unit_of_work_lifecycle(
    migrated_engine: Engine,
    property_name: str,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    uow = SQLAlchemyUnitOfWork(SessionLocal)

    with pytest.raises(UnitOfWorkNotActiveError):
        getattr(uow, property_name)

    with uow:
        repository = getattr(uow, property_name)
        assert repository.session is uow.session
        uow.commit()
        with pytest.raises(UnitOfWorkNotActiveError):
            getattr(uow, property_name)

    with pytest.raises(UnitOfWorkNotActiveError):
        getattr(uow, property_name)

    rollback_uow = SQLAlchemyUnitOfWork(SessionLocal)
    with rollback_uow:
        getattr(rollback_uow, property_name)
        rollback_uow.rollback()
        with pytest.raises(UnitOfWorkNotActiveError):
            getattr(rollback_uow, property_name)


def test_temporal_repositories_share_unit_of_work_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        expected = uow.session
        for property_name in (
            "resource_identifiers",
            "resource_ownerships",
            "resource_relationships",
            "resource_classifications",
            "resource_labels",
            "resource_states",
        ):
            assert getattr(uow, property_name).session is expected

        assert uow.tenants.session is expected
        assert uow.organizations.session is expected
        assert uow.resources.session is expected
        assert uow.resource_types.session is expected
        assert uow.lifecycle_statuses.session is expected


def test_temporal_repositories_are_distinct_per_unit_of_work(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as first:
        with SQLAlchemyUnitOfWork(SessionLocal) as second:
            assert first.resource_identifiers is not second.resource_identifiers
            assert first.resource_states is not second.resource_states
            assert first.resource_identifiers.session is not second.resource_identifiers.session


def test_closing_one_unit_of_work_does_not_close_another_temporal_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    first = SQLAlchemyUnitOfWork(SessionLocal)
    second = SQLAlchemyUnitOfWork(SessionLocal)
    first.__enter__()
    second.__enter__()
    try:
        second_session = second.resource_states.session
        first.__exit__(None, None, None)

        assert second_session.closes == 0
        assert second.resource_states.session is second_session
    finally:
        second.__exit__(None, None, None)
