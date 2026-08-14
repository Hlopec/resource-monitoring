from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.commands import (
    AssignResourceAliasCommand,
    AssignResourceClassificationCommand,
    AssignResourceIdentifierCommand,
    AssignResourceLabelCommand,
    AssignResourceOwnershipCommand,
    AssignResourceRelationshipCommand,
    CreateResourceCommand,
    MergeResourceCommand,
    TransitionResourceStateCommand,
)
from app.application.errors import EntityNotFoundError
from app.application.handlers import (
    AssignResourceAliasHandler,
    AssignResourceClassificationHandler,
    AssignResourceIdentifierHandler,
    AssignResourceLabelHandler,
    AssignResourceOwnershipHandler,
    AssignResourceRelationshipHandler,
    CreateResourceHandler,
    FindResourceByAliasHandler,
    FindResourceByIdentifierHandler,
    GetResourceDetailsHandler,
    GetResourceHistoryHandler,
    GetResourceRelationshipsHandler,
    ListResourcesHandler,
    MergeResourceHandler,
    ResolveCanonicalResourceHandler,
    TransitionResourceStateHandler,
)
from app.application.queries import (
    FindResourceByAliasQuery,
    FindResourceByIdentifierQuery,
    GetResourceDetailsQuery,
    GetResourceHistoryQuery,
    GetResourceRelationshipsQuery,
    ListResourcesQuery,
    ResolveCanonicalResourceQuery,
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
    ResourceAlias,
    ResourceIdentifier,
    ResourceLabel,
    ResourceMerge,
    ResourceRelationship,
    ResourceState,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork

SessionFactory = Callable[[], Session]


class CountingFailingCommitUnitOfWork(SQLAlchemyUnitOfWork):
    commit_attempts = 0

    def commit(self) -> None:
        type(self).commit_attempts += 1
        raise RuntimeError("forced commit failure")


def _now(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _uow_factory(SessionLocal: SessionFactory) -> Callable[[], SQLAlchemyUnitOfWork]:
    return lambda: SQLAlchemyUnitOfWork(SessionLocal)


def _catalog_id(session: Session, model_type: type[object], code: str) -> UUID:
    entity_id = session.scalar(select(model_type.id).where(model_type.code == code))
    assert entity_id is not None
    return entity_id


def _classification_value_id(
    session: Session,
    classification_type_id: UUID,
    code: str,
) -> UUID:
    entity_id = session.scalar(
        select(ClassificationValue.id).where(
            ClassificationValue.classification_type_id == classification_type_id,
            ClassificationValue.code == code,
        )
    )
    assert entity_id is not None
    return entity_id


def _seed_tenant(session: Session, *, prefix: str = "tenant") -> UUID:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug(prefix), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    return tenant.id


def _seed_organization(session: Session, tenant_id: UUID) -> UUID:
    organization = Organization(
        tenant_id=tenant_id,
        canonical_name=_slug("org"),
        display_name="Organization",
        external_key=None,
        status="active",
    )
    session.add(organization)
    session.flush()
    return organization.id


def _seed_label(session: Session, tenant_id: UUID) -> UUID:
    label = Label(
        tenant_id=tenant_id,
        key=_slug("key"),
        value=_slug("value"),
        display_name="Label",
        description=None,
        color="#336699",
        is_active=True,
    )
    session.add(label)
    session.flush()
    return label.id


def _seed_base_resource(
    session: Session,
    tenant_id: UUID,
    canonical_name: str | None = None,
) -> UUID:
    seed_catalogs(session)
    resource = Resource(
        tenant_id=tenant_id,
        resource_type_id=_catalog_id(session, ResourceType, "domain"),
        canonical_name=canonical_name or _slug("resource"),
        display_name="Resource",
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=_now(-30),
        last_seen_at=_now(-20),
    )
    session.add(resource)
    session.flush()
    return resource.id


def _create_resource(
    handler: CreateResourceHandler,
    session: Session,
    tenant_id: UUID,
    canonical_name: str | None = None,
) -> UUID:
    result = handler.handle(
        CreateResourceCommand(
            tenant_id=tenant_id,
            resource_type_id=_catalog_id(session, ResourceType, "domain"),
            canonical_name=canonical_name or _slug("resource"),
            display_name="Resource",
            lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
            criticality_id=_catalog_id(session, Criticality, "medium"),
            exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            first_seen_at=_now(-30),
            last_seen_at=_now(-20),
        )
    )
    return result.resource_id


def _assign_representative_facts(
    *,
    SessionLocal: SessionFactory,
    tenant_id: UUID,
    resource_id: UUID,
    organization_id: UUID,
    label_id: UUID,
    session: Session,
    suffix: str,
) -> None:
    factory = _uow_factory(SessionLocal)
    classification_type_id = _catalog_id(session, ClassificationType, "environment")
    AssignResourceAliasHandler(factory).handle(
        AssignResourceAliasCommand(
            tenant_id=tenant_id,
            resource_id=resource_id,
            alias_type="dns_name",
            alias_value=f"{suffix}.example.com",
            normalized_value=f"{suffix}.example.com",
            source="manual",
            first_seen_at=_now(-10),
            last_seen_at=_now(-5),
        )
    )
    AssignResourceIdentifierHandler(factory).handle(
        AssignResourceIdentifierCommand(
            tenant_id=tenant_id,
            resource_id=resource_id,
            identifier_type_id=_catalog_id(session, IdentifierType, "fqdn"),
            original_value=f"{suffix}.example.com",
            normalized_value=f"{suffix}.example.com",
            value_hash=f"sha256:{suffix}",
            namespace="dns",
            is_primary=True,
            confidence_score=Decimal("0.9500"),
            valid_from=_now(-9),
        )
    )
    AssignResourceOwnershipHandler(factory).handle(
        AssignResourceOwnershipCommand(
            tenant_id=tenant_id,
            resource_id=resource_id,
            organization_id=organization_id,
            ownership_role_id=_catalog_id(session, OwnershipRole, "owner"),
            is_primary=True,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-8),
            source="manual",
        )
    )
    AssignResourceClassificationHandler(factory).handle(
        AssignResourceClassificationCommand(
            tenant_id=tenant_id,
            resource_id=resource_id,
            classification_type_id=classification_type_id,
            classification_value_id=_classification_value_id(
                session,
                classification_type_id,
                "production",
            ),
            is_primary=True,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-7),
            source="manual",
        )
    )
    AssignResourceLabelHandler(factory).handle(
        AssignResourceLabelCommand(
            tenant_id=tenant_id,
            resource_id=resource_id,
            label_id=label_id,
            valid_from=_now(-6),
            source="manual",
        )
    )


def _count_rows(session: Session, model_type: type[object], tenant_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(model_type)
            .where(model_type.tenant_id == tenant_id)
        )
        or 0
    )


def test_resource_facts_compose_into_resource_details(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        organization_id = _seed_organization(setup, tenant_id)
        label_id = _seed_label(setup, tenant_id)
        setup.commit()
    with SessionLocal() as catalog_session:
        create_handler = CreateResourceHandler(_uow_factory(SessionLocal))
        resource_id = _create_resource(
            create_handler,
            catalog_session,
            tenant_id,
            _slug("details-resource"),
        )
        _assign_representative_facts(
            SessionLocal=SessionLocal,
            tenant_id=tenant_id,
            resource_id=resource_id,
            organization_id=organization_id,
            label_id=label_id,
            session=catalog_session,
            suffix="details",
        )
    details = GetResourceDetailsHandler(_uow_factory(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource_id)
    )

    assert details.id == resource_id
    assert details.organization_id == organization_id
    assert len(details.aliases) == 1
    assert len(details.identifiers) == 1
    assert len(details.ownership) == 1
    assert len(details.classifications) == 1
    assert len(details.labels) == 1
    assert details.outgoing_merge is None
    assert details.aliases[0].normalized_value == "details.example.com"
    assert details.identifiers[0].namespace == "dns"

    with SessionLocal() as verification:
        assert _count_rows(verification, Resource, tenant_id) == 1
        assert _count_rows(verification, ResourceAlias, tenant_id) == 1
        assert _count_rows(verification, ResourceIdentifier, tenant_id) == 1
        assert _count_rows(verification, ResourceLabel, tenant_id) == 1


def test_state_transition_updates_current_details_and_preserves_history(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource_id = _seed_base_resource(setup, tenant_id)
        setup.add(
            ResourceState(
                tenant_id=tenant_id,
                resource_id=resource_id,
                lifecycle_status_id=_catalog_id(setup, LifecycleStatus, "active"),
                criticality_id=_catalog_id(setup, Criticality, "medium"),
                exposure_level_id=_catalog_id(setup, ExposureLevel, "public"),
                source_priority=100,
                confidence_score=Decimal("0.9000"),
                valid_from=_now(-10),
                valid_to=None,
                source="seed",
            )
        )
        setup.commit()
    with SessionLocal() as catalog_session:
        TransitionResourceStateHandler(_uow_factory(SessionLocal)).handle(
            TransitionResourceStateCommand(
                tenant_id=tenant_id,
                resource_id=resource_id,
                lifecycle_status_id=_catalog_id(
                    catalog_session,
                    LifecycleStatus,
                    "inactive",
                ),
                criticality_id=_catalog_id(catalog_session, Criticality, "high"),
                exposure_level_id=_catalog_id(
                    catalog_session,
                    ExposureLevel,
                    "internal",
                ),
                source_priority=200,
                confidence_score=Decimal("0.8000"),
                transitioned_at=_now(),
                source="manual",
            )
        )
    details = GetResourceDetailsHandler(_uow_factory(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource_id)
    )

    assert details.state is not None
    assert details.state.source == "manual"
    assert details.state.source_priority == 200
    with SessionLocal() as verification:
        states = list(
            verification.scalars(
                select(ResourceState)
                .where(
                    ResourceState.tenant_id == tenant_id,
                    ResourceState.resource_id == resource_id,
                )
                .order_by(ResourceState.valid_from)
            )
        )
        assert len(states) == 2
        assert sum(state.valid_to is None for state in states) == 1


def test_relationship_assignment_preserves_direction_and_details_contract(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        source_id = _seed_base_resource(setup, tenant_id, _slug("source"))
        target_id = _seed_base_resource(setup, tenant_id, _slug("target"))
        setup.commit()
    with SessionLocal() as catalog_session:
        relationship_type_id = _catalog_id(
            catalog_session,
            RelationshipType,
            "depends_on",
        )
    AssignResourceRelationshipHandler(_uow_factory(SessionLocal)).handle(
        AssignResourceRelationshipCommand(
            tenant_id=tenant_id,
            source_resource_id=source_id,
            relationship_type_id=relationship_type_id,
            target_resource_id=target_id,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(),
            source="manual",
        )
    )

    source_details = GetResourceDetailsHandler(_uow_factory(SessionLocal)).handle(
        GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=source_id)
    )
    with SessionLocal() as verification:
        relationships = list(
            verification.scalars(
                select(ResourceRelationship).where(
                    ResourceRelationship.tenant_id == tenant_id
                )
            )
        )
        reverse = verification.scalar(
            select(ResourceRelationship).where(
                ResourceRelationship.tenant_id == tenant_id,
                ResourceRelationship.source_resource_id == target_id,
                ResourceRelationship.target_resource_id == source_id,
            )
        )
    assert [
        (row.source_resource_id, row.target_resource_id) for row in relationships
    ] == [(source_id, target_id)]
    assert reverse is None
    assert source_details.outgoing_merge is None


def test_merge_chain_resolves_canonical_without_rewriting_lineage(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        first_id = _seed_base_resource(setup, tenant_id, _slug("first"))
        second_id = _seed_base_resource(setup, tenant_id, _slug("second"))
        third_id = _seed_base_resource(setup, tenant_id, _slug("third"))
        setup.commit()
    merge_handler = MergeResourceHandler(_uow_factory(SessionLocal))
    merge_handler.handle(
        MergeResourceCommand(
            tenant_id=tenant_id,
            source_resource_id=second_id,
            target_resource_id=third_id,
            reason="duplicate",
            source="manual",
            merged_at=_now(-2),
        )
    )
    merge_handler.handle(
        MergeResourceCommand(
            tenant_id=tenant_id,
            source_resource_id=first_id,
            target_resource_id=second_id,
            reason="duplicate",
            source="manual",
            merged_at=_now(-1),
        )
    )
    resolver = ResolveCanonicalResourceHandler(_uow_factory(SessionLocal))

    first = resolver.handle(ResolveCanonicalResourceQuery(tenant_id, first_id))
    second = resolver.handle(ResolveCanonicalResourceQuery(tenant_id, second_id))
    third = resolver.handle(ResolveCanonicalResourceQuery(tenant_id, third_id))

    assert (
        first.immediate_target_resource_id,
        first.canonical_resource_id,
        first.merge_depth,
    ) == (
        second_id,
        third_id,
        2,
    )
    assert (
        second.immediate_target_resource_id,
        second.canonical_resource_id,
        second.merge_depth,
    ) == (
        third_id,
        third_id,
        1,
    )
    assert (
        third.immediate_target_resource_id,
        third.canonical_resource_id,
        third.merge_depth,
    ) == (
        None,
        third_id,
        0,
    )
    with SessionLocal() as verification:
        edges = {
            (merge.source_resource_id, merge.target_resource_id)
            for merge in verification.scalars(
                select(ResourceMerge).where(ResourceMerge.tenant_id == tenant_id)
            )
        }
    assert edges == {(first_id, second_id), (second_id, third_id)}
    assert (first_id, third_id) not in edges


def test_merge_remains_lineage_only_and_keeps_source_facts(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        organization_id = _seed_organization(setup, tenant_id)
        label_id = _seed_label(setup, tenant_id)
        source_id = _seed_base_resource(setup, tenant_id, _slug("source"))
        target_id = _seed_base_resource(setup, tenant_id, _slug("target"))
        setup.commit()
    with SessionLocal() as catalog_session:
        _assign_representative_facts(
            SessionLocal=SessionLocal,
            tenant_id=tenant_id,
            resource_id=source_id,
            organization_id=organization_id,
            label_id=label_id,
            session=catalog_session,
            suffix="lineage-only",
        )
    MergeResourceHandler(_uow_factory(SessionLocal)).handle(
        MergeResourceCommand(
            tenant_id=tenant_id,
            source_resource_id=source_id,
            target_resource_id=target_id,
            reason="duplicate",
            source="manual",
            merged_at=_now(),
        )
    )

    with SessionLocal() as verification:
        assert verification.scalar(
            select(ResourceAlias.resource_id).where(ResourceAlias.tenant_id == tenant_id)
        ) == source_id
        assert verification.scalar(
            select(ResourceIdentifier.resource_id).where(
                ResourceIdentifier.tenant_id == tenant_id
            )
        ) == source_id
        assert verification.scalar(
            select(ResourceLabel.resource_id).where(ResourceLabel.tenant_id == tenant_id)
        ) == source_id


def test_cross_tenant_composed_operations_do_not_leak_resource_existence(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, prefix="tenant-a")
        tenant_b = _seed_tenant(setup, prefix="tenant-b")
        resource_a = _seed_base_resource(setup, tenant_a, _slug("a"))
        resource_b = _seed_base_resource(setup, tenant_b, _slug("b"))
        label_b = _seed_label(setup, tenant_b)
        setup.commit()

    with pytest.raises(EntityNotFoundError):
        GetResourceDetailsHandler(_uow_factory(SessionLocal)).handle(
            GetResourceDetailsQuery(tenant_id=tenant_a, resource_id=resource_b)
        )
    with pytest.raises(EntityNotFoundError):
        AssignResourceLabelHandler(_uow_factory(SessionLocal)).handle(
            AssignResourceLabelCommand(
                tenant_id=tenant_a,
                resource_id=resource_b,
                label_id=label_b,
                valid_from=_now(),
                source="manual",
            )
        )
    with pytest.raises(EntityNotFoundError):
        MergeResourceHandler(_uow_factory(SessionLocal)).handle(
            MergeResourceCommand(
                tenant_id=tenant_a,
                source_resource_id=resource_a,
                target_resource_id=resource_b,
                reason="duplicate",
                source="manual",
                merged_at=_now(),
            )
        )
    with pytest.raises(EntityNotFoundError):
        ResolveCanonicalResourceHandler(_uow_factory(SessionLocal)).handle(
            ResolveCanonicalResourceQuery(tenant_id=tenant_a, resource_id=resource_b)
        )


def test_block_03_read_models_remain_tenant_scoped_and_separate(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, prefix="tenant-a")
        tenant_b = _seed_tenant(setup, prefix="tenant-b")
        organization_a = _seed_organization(setup, tenant_a)
        organization_b = _seed_organization(setup, tenant_b)
        label_a = _seed_label(setup, tenant_a)
        label_b = _seed_label(setup, tenant_b)
        resource_a = _seed_base_resource(setup, tenant_a, _slug("tenant-a-resource"))
        canonical_a = _seed_base_resource(setup, tenant_a, _slug("tenant-a-canonical"))
        outgoing_target = _seed_base_resource(setup, tenant_a, _slug("outgoing"))
        incoming_source = _seed_base_resource(setup, tenant_a, _slug("incoming"))
        canonical_target = _seed_base_resource(
            setup,
            tenant_a,
            _slug("canonical-target"),
        )
        resource_b = _seed_base_resource(setup, tenant_b, _slug("tenant-b-resource"))
        tenant_b_target = _seed_base_resource(setup, tenant_b, _slug("tenant-b-target"))
        old_state = ResourceState(
            tenant_id=tenant_a,
            resource_id=resource_a,
            lifecycle_status_id=_catalog_id(setup, LifecycleStatus, "active"),
            criticality_id=_catalog_id(setup, Criticality, "medium"),
            exposure_level_id=_catalog_id(setup, ExposureLevel, "public"),
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-20),
            valid_to=_now(-10),
            source="seed",
        )
        current_state = ResourceState(
            tenant_id=tenant_a,
            resource_id=resource_a,
            lifecycle_status_id=_catalog_id(setup, LifecycleStatus, "inactive"),
            criticality_id=_catalog_id(setup, Criticality, "high"),
            exposure_level_id=_catalog_id(setup, ExposureLevel, "internal"),
            source_priority=200,
            confidence_score=Decimal("0.8000"),
            valid_from=_now(-10),
            valid_to=None,
            source="seed",
        )
        setup.add_all([old_state, current_state])
        setup.commit()

    factory = _uow_factory(SessionLocal)
    with SessionLocal() as catalog_session:
        relationship_type_id = _catalog_id(
            catalog_session,
            RelationshipType,
            "depends_on",
        )
        identifier_type_id = _catalog_id(catalog_session, IdentifierType, "fqdn")
        classification_type_id = _catalog_id(
            catalog_session,
            ClassificationType,
            "environment",
        )
        production_id = _classification_value_id(
            catalog_session,
            classification_type_id,
            "production",
        )
        _assign_representative_facts(
            SessionLocal=SessionLocal,
            tenant_id=tenant_a,
            resource_id=resource_a,
            organization_id=organization_a,
            label_id=label_a,
            session=catalog_session,
            suffix="closeout",
        )
        _assign_representative_facts(
            SessionLocal=SessionLocal,
            tenant_id=tenant_b,
            resource_id=resource_b,
            organization_id=organization_b,
            label_id=label_b,
            session=catalog_session,
            suffix="closeout",
        )

    relationship_handler = AssignResourceRelationshipHandler(factory)
    relationship_handler.handle(
        AssignResourceRelationshipCommand(
            tenant_id=tenant_a,
            source_resource_id=resource_a,
            relationship_type_id=relationship_type_id,
            target_resource_id=outgoing_target,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-4),
            source="manual",
        )
    )
    relationship_handler.handle(
        AssignResourceRelationshipCommand(
            tenant_id=tenant_a,
            source_resource_id=incoming_source,
            relationship_type_id=relationship_type_id,
            target_resource_id=resource_a,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-3),
            source="manual",
        )
    )
    relationship_handler.handle(
        AssignResourceRelationshipCommand(
            tenant_id=tenant_a,
            source_resource_id=canonical_a,
            relationship_type_id=relationship_type_id,
            target_resource_id=canonical_target,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-2),
            source="manual",
        )
    )
    relationship_handler.handle(
        AssignResourceRelationshipCommand(
            tenant_id=tenant_b,
            source_resource_id=resource_b,
            relationship_type_id=relationship_type_id,
            target_resource_id=tenant_b_target,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-1),
            source="manual",
        )
    )
    MergeResourceHandler(factory).handle(
        MergeResourceCommand(
            tenant_id=tenant_a,
            source_resource_id=resource_a,
            target_resource_id=canonical_a,
            reason="duplicate",
            source="manual",
            merged_at=_now(),
        )
    )

    page = ListResourcesHandler(factory).handle(
        ListResourcesQuery(
            tenant_id=tenant_a,
            organization_id=organization_a,
            label_id=label_a,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            page_size=10,
        )
    )
    identifier = FindResourceByIdentifierHandler(factory).handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_a,
            identifier_type_id=identifier_type_id,
            namespace="dns",
            normalized_value="closeout.example.com",
        )
    )
    alias = FindResourceByAliasHandler(factory).handle(
        FindResourceByAliasQuery(
            tenant_id=tenant_a,
            alias_type="dns_name",
            normalized_value="closeout.example.com",
        )
    )
    details = GetResourceDetailsHandler(factory).handle(
        GetResourceDetailsQuery(tenant_id=tenant_a, resource_id=resource_a)
    )
    history = GetResourceHistoryHandler(factory).handle(
        GetResourceHistoryQuery(tenant_id=tenant_a, resource_id=resource_a)
    )
    relationships = GetResourceRelationshipsHandler(factory).handle(
        GetResourceRelationshipsQuery(tenant_id=tenant_a, resource_id=resource_a)
    )
    canonical = ResolveCanonicalResourceHandler(factory).handle(
        ResolveCanonicalResourceQuery(tenant_id=tenant_a, resource_id=resource_a)
    )

    assert [item.resource_id for item in page.items] == [resource_a]
    assert identifier.resource.id == resource_a
    assert alias.resource.id == resource_a
    assert details.id == resource_a
    assert details.outgoing_merge is not None
    assert details.outgoing_merge.target_resource_id == canonical_a
    assert not hasattr(details, "relationships")
    assert [state.id for state in history.states] == [old_state.id, current_state.id]
    assert history.states[0].valid_to == old_state.valid_to
    assert history.states[1].valid_to is None
    assert not hasattr(history, "relationships")
    assert not hasattr(history, "outgoing_merge")
    assert {
        (relationship.source_resource_id, relationship.target_resource_id)
        for relationship in relationships.relationships
    } == {
        (resource_a, outgoing_target),
        (incoming_source, resource_a),
    }
    assert {relationship.direction for relationship in relationships.relationships} == {
        "incoming",
        "outgoing",
    }
    assert all(
        resource_b
        not in (relationship.source_resource_id, relationship.target_resource_id)
        for relationship in relationships.relationships
    )
    assert canonical.canonical_resource_id == canonical_a

    tenant_b_identifier = FindResourceByIdentifierHandler(factory).handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_b,
            identifier_type_id=identifier_type_id,
            namespace="dns",
            normalized_value="closeout.example.com",
        )
    )
    assert tenant_b_identifier.resource.id == resource_b
    with pytest.raises(EntityNotFoundError):
        GetResourceDetailsHandler(factory).handle(
            GetResourceDetailsQuery(tenant_id=tenant_a, resource_id=resource_b)
        )
    with pytest.raises(EntityNotFoundError):
        GetResourceHistoryHandler(factory).handle(
            GetResourceHistoryQuery(tenant_id=tenant_a, resource_id=resource_b)
        )
    with pytest.raises(EntityNotFoundError):
        GetResourceRelationshipsHandler(factory).handle(
            GetResourceRelationshipsQuery(tenant_id=tenant_a, resource_id=resource_b)
        )
    with pytest.raises(EntityNotFoundError):
        ResolveCanonicalResourceHandler(factory).handle(
            ResolveCanonicalResourceQuery(tenant_id=tenant_a, resource_id=resource_b)
        )


def test_representative_commit_failures_are_atomic_and_uow_recovers(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        first_resource_id = _seed_base_resource(setup, tenant_id, _slug("first"))
        second_resource_id = _seed_base_resource(setup, tenant_id, _slug("second"))
        third_resource_id = _seed_base_resource(setup, tenant_id, _slug("third"))
        label_id = _seed_label(setup, tenant_id)
        existing_label = ResourceLabel(
            tenant_id=tenant_id,
            resource_id=first_resource_id,
            label_id=label_id,
            valid_from=_now(-5),
            valid_to=None,
            source="setup",
        )
        existing_merge = ResourceMerge(
            tenant_id=tenant_id,
            source_resource_id=first_resource_id,
            target_resource_id=second_resource_id,
            reason="setup",
            source="setup",
            merged_at=_now(-5),
        )
        setup.add_all([existing_label, existing_merge])
        setup.commit()

    CountingFailingCommitUnitOfWork.commit_attempts = 0
    failing_factory = lambda: CountingFailingCommitUnitOfWork(SessionLocal)
    with pytest.raises(RuntimeError, match="forced commit failure"):
        AssignResourceLabelHandler(failing_factory).handle(
            AssignResourceLabelCommand(
                tenant_id=tenant_id,
                resource_id=second_resource_id,
                label_id=label_id,
                valid_from=_now(),
                source="manual",
            )
        )
    with pytest.raises(RuntimeError, match="forced commit failure"):
        MergeResourceHandler(failing_factory).handle(
            MergeResourceCommand(
                tenant_id=tenant_id,
                source_resource_id=second_resource_id,
                target_resource_id=third_resource_id,
                reason="duplicate",
                source="manual",
                merged_at=_now(),
            )
        )

    assert CountingFailingCommitUnitOfWork.commit_attempts == 2
    with SessionLocal() as verification:
        assert _count_rows(verification, ResourceLabel, tenant_id) == 1
        assert _count_rows(verification, ResourceMerge, tenant_id) == 1

    with SessionLocal() as setup:
        fresh_label = _seed_label(setup, tenant_id)
        setup.commit()
    AssignResourceLabelHandler(_uow_factory(SessionLocal)).handle(
        AssignResourceLabelCommand(
            tenant_id=tenant_id,
            resource_id=second_resource_id,
            label_id=fresh_label,
            valid_from=_now(),
            source="fresh",
        )
    )
    with SessionLocal() as verification:
        assert _count_rows(verification, ResourceLabel, tenant_id) == 2
