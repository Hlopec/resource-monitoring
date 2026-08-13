from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.errors import EntityNotFoundError
from app.application.handlers import (
    GetResourceByCanonicalNameHandler,
    GetResourceDetailsHandler,
)
from app.application.queries import (
    GetResourceByCanonicalNameQuery,
    GetResourceDetailsQuery,
)
from app.application.results import (
    ResourceAliasResult,
    ResourceDetailsResult,
    ResourceIdentifierResult,
    ResourceLabelResult,
    ResourceMergeResult,
    ResourceOwnershipResult,
    ResourceStateResult,
)
from app.application.ports.resource_queries import (
    ResourceAliasProjection,
    ResourceClassificationProjection,
    ResourceDetailsProjection,
    ResourceIdentifierProjection,
    ResourceLabelProjection,
    ResourceMergeProjection,
    ResourceOwnershipProjection,
    ResourceStateProjection,
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


class FakeResourceRepository:
    def __init__(self, events: list[str], resources: dict[tuple[UUID, UUID], object]):
        self._events = events
        self._resources = resources

    def get_by_id(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append("resources.get_by_id")
        return self._resources.get((tenant_id, resource_id))

    def get_by_canonical_name(self, tenant_id: UUID, canonical_name: str) -> object | None:
        self._events.append("resources.get_by_canonical_name")
        return next(
            (
                resource
                for (stored_tenant_id, _), resource in self._resources.items()
                if stored_tenant_id == tenant_id
                and resource.canonical_name == canonical_name
            ),
            None,
        )


class FakeResourceStates:
    def __init__(self, events: list[str], state: object | None):
        self._events = events
        self._state = state

    def get_current(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append("resource_states.get_current")
        return self._state


class FakeResourceIdentifiers:
    def __init__(self, events: list[str], identifiers: tuple[object, ...]):
        self._events = events
        self._identifiers = identifiers

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[object, ...]:
        self._events.append("resource_identifiers.get_current_for_resource")
        return self._identifiers


class FakeResourceOwnerships:
    def __init__(self, events: list[str], ownership: tuple[object, ...]):
        self._events = events
        self._ownership = ownership

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[object, ...]:
        self._events.append("resource_ownerships.get_current_for_resource")
        return self._ownership


class FakeResourceClassifications:
    def __init__(self, events: list[str], classifications: tuple[object, ...]):
        self._events = events
        self._classifications = classifications

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[object, ...]:
        self._events.append("resource_classifications.get_current_for_resource")
        return self._classifications


class FakeResourceLabels:
    def __init__(self, events: list[str], labels: tuple[object, ...]):
        self._events = events
        self._labels = labels

    def get_current_for_resource(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> tuple[object, ...]:
        self._events.append("resource_labels.get_current_for_resource")
        return self._labels


class FakeResourceAliases:
    def __init__(self, events: list[str], aliases: tuple[object, ...]):
        self._events = events
        self._aliases = aliases

    def list_for_resource(self, tenant_id: UUID, resource_id: UUID) -> tuple[object, ...]:
        self._events.append("resource_aliases.list_for_resource")
        return self._aliases


class FakeResourceMerges:
    def __init__(self, events: list[str], outgoing_merge: object | None):
        self._events = events
        self._outgoing_merge = outgoing_merge

    def get_outgoing_merge(self, tenant_id: UUID, resource_id: UUID) -> object | None:
        self._events.append("resource_merges.get_outgoing_merge")
        return self._outgoing_merge


class FakeResourceQueryService:
    def __init__(
        self,
        events: list[str],
        details: dict[tuple[UUID, UUID], ResourceDetailsProjection],
    ) -> None:
        self._events = events
        self._details = details

    def get_resource_details(
        self,
        tenant_id: UUID,
        resource_id: UUID,
    ) -> ResourceDetailsProjection | None:
        self._events.append("resource_queries.get_resource_details")
        return self._details.get((tenant_id, resource_id))


class FakeUnitOfWork:
    def __init__(
        self,
        resources: dict[tuple[UUID, UUID], object],
        details: dict[tuple[UUID, UUID], ResourceDetailsProjection] | None = None,
        *,
        state: object | None = None,
        identifiers: tuple[object, ...] = (),
        ownership: tuple[object, ...] = (),
        classifications: tuple[object, ...] = (),
        labels: tuple[object, ...] = (),
        aliases: tuple[object, ...] = (),
        outgoing_merge: object | None = None,
    ) -> None:
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.exited = False
        self.resources = FakeResourceRepository(self.events, resources)
        self.resource_states = FakeResourceStates(self.events, state)
        self.resource_identifiers = FakeResourceIdentifiers(self.events, identifiers)
        self.resource_ownerships = FakeResourceOwnerships(self.events, ownership)
        self.resource_classifications = FakeResourceClassifications(
            self.events,
            classifications,
        )
        self.resource_labels = FakeResourceLabels(self.events, labels)
        self.resource_aliases = FakeResourceAliases(self.events, aliases)
        self.resource_merges = FakeResourceMerges(self.events, outgoing_merge)
        self.resource_queries = FakeResourceQueryService(
            self.events,
            details or {},
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


def _now(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _resource_projection_source(
    tenant_id: UUID,
    resource_id: UUID,
    *,
    canonical_name: str = "example.com",
) -> object:
    return SimpleNamespace(
        id=resource_id,
        tenant_id=tenant_id,
        resource_type_id=uuid4(),
        canonical_name=canonical_name,
        display_name="Example",
        record_version=3,
        created_at=_now(-30),
        updated_at=_now(-10),
    )


def _details_uow(
    tenant_id: UUID,
    resource_id: UUID,
    *,
    canonical_name: str = "example.com",
) -> FakeUnitOfWork:
    lifecycle_status_id = uuid4()
    criticality_id = uuid4()
    exposure_level_id = uuid4()
    organization_id = uuid4()
    ownership_role_id = uuid4()
    classification_type_id = uuid4()
    classification_value_id = uuid4()
    identifier_type_id = uuid4()
    label_id = uuid4()
    target_resource_id = uuid4()
    resource = _resource_projection_source(
        tenant_id,
        resource_id,
        canonical_name=canonical_name,
    )
    primary_ownership = ResourceOwnershipProjection(
        id=uuid4(),
        organization_id=organization_id,
        ownership_role_id=ownership_role_id,
        is_primary=True,
        confidence_score=Decimal("0.7000"),
        valid_from=_now(-7),
        source="manual",
    )
    details = ResourceDetailsProjection(
        id=resource_id,
        tenant_id=tenant_id,
        organization_id=organization_id,
        resource_type_id=resource.resource_type_id,
        canonical_name=canonical_name,
        display_name=resource.display_name,
        record_version=resource.record_version,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
        state=ResourceStateProjection(
            id=uuid4(),
            lifecycle_status_id=lifecycle_status_id,
            criticality_id=criticality_id,
            exposure_level_id=exposure_level_id,
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-20),
            source="collector",
        ),
        primary_ownership=primary_ownership,
        identifiers=(
            ResourceIdentifierProjection(
                id=uuid4(),
                identifier_type_id=identifier_type_id,
                namespace=None,
                normalized_value="a.example.com",
                original_value="A.EXAMPLE.COM",
                is_primary=True,
                confidence_score=Decimal("0.9500"),
                valid_from=_now(-9),
            ),
            ResourceIdentifierProjection(
                id=uuid4(),
                identifier_type_id=identifier_type_id,
                namespace=None,
                normalized_value="b.example.com",
                original_value="B.EXAMPLE.COM",
                is_primary=False,
                confidence_score=Decimal("0.8000"),
                valid_from=_now(-8),
            ),
        ),
        ownership=(primary_ownership,),
        classifications=(
            ResourceClassificationProjection(
                id=uuid4(),
                classification_type_id=classification_type_id,
                classification_value_id=classification_value_id,
                is_primary=True,
                confidence_score=Decimal("0.8500"),
                valid_from=_now(-6),
                source="manual",
            ),
        ),
        labels=(
            ResourceLabelProjection(
                id=uuid4(),
                label_id=label_id,
                valid_from=_now(-5),
                source="manual",
            ),
        ),
        aliases=(
            ResourceAliasProjection(
                id=uuid4(),
                alias_type="hostname",
                alias_value="B.EXAMPLE.COM",
                normalized_value="b.example.com",
                source="manual",
                first_seen_at=_now(-4),
                last_seen_at=_now(-3),
            ),
        ),
        outgoing_merge=ResourceMergeProjection(
            id=uuid4(),
            source_resource_id=resource_id,
            target_resource_id=target_resource_id,
            reason="duplicate",
            source="manual",
            merged_at=_now(-2),
        ),
    )
    return FakeUnitOfWork(
        {(tenant_id, resource_id): resource},
        details={(tenant_id, resource_id): details},
        state=SimpleNamespace(
            id=uuid4(),
            lifecycle_status_id=lifecycle_status_id,
            criticality_id=criticality_id,
            exposure_level_id=exposure_level_id,
            source_priority=100,
            confidence_score=Decimal("0.9000"),
            valid_from=_now(-20),
            source="collector",
        ),
        identifiers=(
            SimpleNamespace(
                id=uuid4(),
                identifier_type_id=identifier_type_id,
                namespace=None,
                normalized_value="b.example.com",
                original_value="B.EXAMPLE.COM",
                is_primary=False,
                confidence_score=Decimal("0.8000"),
                valid_from=_now(-8),
            ),
            SimpleNamespace(
                id=uuid4(),
                identifier_type_id=identifier_type_id,
                namespace=None,
                normalized_value="a.example.com",
                original_value="A.EXAMPLE.COM",
                is_primary=True,
                confidence_score=Decimal("0.9500"),
                valid_from=_now(-9),
            ),
        ),
        ownership=(
            SimpleNamespace(
                id=uuid4(),
                organization_id=organization_id,
                ownership_role_id=ownership_role_id,
                is_primary=True,
                confidence_score=Decimal("0.7000"),
                valid_from=_now(-7),
                source="manual",
            ),
        ),
        classifications=(
            SimpleNamespace(
                id=uuid4(),
                classification_type_id=classification_type_id,
                classification_value_id=classification_value_id,
                is_primary=True,
                confidence_score=Decimal("0.8500"),
                valid_from=_now(-6),
                source="manual",
            ),
        ),
        labels=(
            SimpleNamespace(
                id=uuid4(),
                label_id=label_id,
                valid_from=_now(-5),
                source="manual",
            ),
        ),
        aliases=(
            SimpleNamespace(
                id=uuid4(),
                alias_type="hostname",
                alias_value="B.EXAMPLE.COM",
                normalized_value="b.example.com",
                source="manual",
                first_seen_at=_now(-4),
                last_seen_at=_now(-3),
            ),
        ),
        outgoing_merge=SimpleNamespace(
            id=uuid4(),
            source_resource_id=resource_id,
            target_resource_id=target_resource_id,
            reason="duplicate",
            source="manual",
            merged_at=_now(-2),
        ),
    )


def test_resource_read_queries_are_immutable_and_transport_neutral() -> None:
    details_query = GetResourceDetailsQuery(uuid4(), uuid4())
    canonical_query = GetResourceByCanonicalNameQuery(uuid4(), "Example.COM")

    for query in (details_query, canonical_query):
        assert is_dataclass(query)
        assert "tenant_id" in {field.name for field in fields(query)}
        assert not hasattr(query, "execute")
        assert not hasattr(query, "commit")
        with pytest.raises(FrozenInstanceError):
            query.tenant_id = uuid4()


def test_resource_details_result_is_immutable_and_uses_tuples() -> None:
    result = ResourceDetailsResult(
        id=uuid4(),
        tenant_id=uuid4(),
        organization_id=None,
        resource_type_id=uuid4(),
        canonical_name="example.com",
        display_name="Example",
        record_version=1,
        created_at=_now(-1),
        updated_at=_now(),
        state=None,
        identifiers=(),
        ownership=(),
        classifications=(),
        labels=(),
        aliases=(),
        outgoing_merge=None,
    )

    assert is_dataclass(result)
    assert isinstance(result.identifiers, tuple)
    assert isinstance(result.ownership, tuple)
    assert isinstance(result.classifications, tuple)
    assert isinstance(result.labels, tuple)
    assert isinstance(result.aliases, tuple)
    assert not isinstance(result, dict)
    with pytest.raises(FrozenInstanceError):
        result.canonical_name = "changed.example.com"


def test_details_handler_materializes_projection_with_one_unit_of_work() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    uow = _details_uow(tenant_id, resource_id)
    factory = FakeUnitOfWorkFactory(uow)
    handler = GetResourceDetailsHandler(factory)

    result = handler.handle(GetResourceDetailsQuery(tenant_id, resource_id))

    assert len(factory.created) == 1
    assert uow.commits == 0
    assert uow.rollbacks == 0
    assert uow.exited is True
    assert uow.events == [
        "enter",
        "resource_queries.get_resource_details",
        "exit",
    ]
    assert result.id == resource_id
    assert result.tenant_id == tenant_id
    assert result.organization_id == result.ownership[0].organization_id
    assert isinstance(result.state, ResourceStateResult)
    assert all(isinstance(item, ResourceIdentifierResult) for item in result.identifiers)
    assert [item.normalized_value for item in result.identifiers] == [
        "a.example.com",
        "b.example.com",
    ]
    assert all(isinstance(item, ResourceOwnershipResult) for item in result.ownership)
    assert all(
        isinstance(item, ResourceLabelResult)
        for item in result.labels
    )
    assert all(isinstance(item, ResourceAliasResult) for item in result.aliases)
    assert isinstance(result.outgoing_merge, ResourceMergeResult)


def test_details_handler_raises_not_found_without_composition_reads() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    uow = FakeUnitOfWork({})
    handler = GetResourceDetailsHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as exc_info:
        handler.handle(GetResourceDetailsQuery(tenant_id, resource_id))

    assert exc_info.value.entity_type == "Resource"
    assert exc_info.value.lookup_field == "resource_id"
    assert exc_info.value.lookup_value == resource_id
    assert uow.commits == 0
    assert uow.events == ["enter", "resource_queries.get_resource_details", "exit"]


def test_details_handler_wrong_tenant_matches_not_found_behavior() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    other_tenant_id = uuid4()
    uow = _details_uow(tenant_id, resource_id)
    handler = GetResourceDetailsHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError):
        handler.handle(GetResourceDetailsQuery(other_tenant_id, resource_id))

    assert uow.commits == 0
    assert uow.events == ["enter", "resource_queries.get_resource_details", "exit"]


def test_canonical_name_handler_uses_contract_lookup_without_normalizing() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    uow = _details_uow(
        tenant_id,
        resource_id,
        canonical_name="Example.COM",
    )
    handler = GetResourceByCanonicalNameHandler(FakeUnitOfWorkFactory(uow))

    result = handler.handle(
        GetResourceByCanonicalNameQuery(tenant_id, "Example.COM"),
    )

    assert result.id == resource_id
    assert uow.commits == 0
    assert uow.events == [
        "enter",
        "resources.get_by_canonical_name",
        "resource_queries.get_resource_details",
        "exit",
    ]


def test_canonical_name_handler_missing_and_wrong_tenant_do_not_leak() -> None:
    tenant_id = uuid4()
    resource_id = uuid4()
    uow = _details_uow(tenant_id, resource_id)
    handler = GetResourceByCanonicalNameHandler(FakeUnitOfWorkFactory(uow))

    with pytest.raises(EntityNotFoundError) as missing:
        handler.handle(GetResourceByCanonicalNameQuery(tenant_id, "missing.example.com"))
    with pytest.raises(EntityNotFoundError) as wrong_tenant:
        handler.handle(GetResourceByCanonicalNameQuery(uuid4(), "example.com"))

    assert missing.value.lookup_field == "canonical_name"
    assert wrong_tenant.value.lookup_field == "canonical_name"
    assert uow.commits == 0


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _catalog_id(session: Session, model_type: type[object], code: str) -> UUID:
    entity_id = session.scalar(select(model_type.id).where(model_type.code == code))
    assert entity_id is not None
    return entity_id


def _seed_resource_details(session: Session) -> tuple[UUID, UUID, str]:
    seed_catalogs(session)
    session.flush()
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    organization = Organization(
        tenant_id=tenant.id,
        canonical_name=_slug("org"),
        display_name="Organization",
        status="active",
    )
    session.add_all([tenant, organization])
    session.flush()
    lifecycle_status_id = _catalog_id(session, LifecycleStatus, "active")
    criticality_id = _catalog_id(session, Criticality, "medium")
    exposure_level_id = _catalog_id(session, ExposureLevel, "public")
    resource = Resource(
        tenant_id=tenant.id,
        resource_type_id=_catalog_id(session, ResourceType, "domain"),
        canonical_name=_slug("resource"),
        display_name="Resource",
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=_now(-30),
        last_seen_at=_now(-1),
    )
    target_resource = Resource(
        tenant_id=tenant.id,
        resource_type_id=resource.resource_type_id,
        canonical_name=_slug("target"),
        display_name="Target",
        lifecycle_status_id=lifecycle_status_id,
        criticality_id=criticality_id,
        exposure_level_id=exposure_level_id,
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=_now(-30),
        last_seen_at=_now(-1),
    )
    label = Label(tenant_id=tenant.id, key=_slug("env"), value="Production")
    session.add_all([resource, target_resource, label])
    session.flush()
    classification_type_id = _catalog_id(session, ClassificationType, "environment")
    session.add_all(
        [
            ResourceState(
                tenant_id=tenant.id,
                resource_id=resource.id,
                lifecycle_status_id=lifecycle_status_id,
                criticality_id=criticality_id,
                exposure_level_id=exposure_level_id,
                source_priority=90,
                confidence_score=Decimal("0.9100"),
                valid_from=_now(-20),
                source="collector",
            ),
            ResourceIdentifier(
                tenant_id=tenant.id,
                resource_id=resource.id,
                identifier_type_id=_catalog_id(session, IdentifierType, "fqdn"),
                namespace=None,
                normalized_value="example.com",
                original_value="Example.COM",
                value_hash="hash-example.com",
                is_primary=True,
                confidence_score=Decimal("0.9500"),
                valid_from=_now(-19),
            ),
            ResourceOwnership(
                tenant_id=tenant.id,
                resource_id=resource.id,
                organization_id=organization.id,
                ownership_role_id=_catalog_id(session, OwnershipRole, "owner"),
                is_primary=True,
                confidence_score=Decimal("0.8500"),
                valid_from=_now(-18),
                source="manual",
            ),
            ResourceClassification(
                tenant_id=tenant.id,
                resource_id=resource.id,
                classification_type_id=classification_type_id,
                classification_value_id=_catalog_id(
                    session,
                    ClassificationValue,
                    "production",
                ),
                is_primary=True,
                confidence_score=Decimal("0.8700"),
                valid_from=_now(-17),
                source="manual",
            ),
            ResourceLabel(
                tenant_id=tenant.id,
                resource_id=resource.id,
                label_id=label.id,
                valid_from=_now(-16),
                source="manual",
            ),
            ResourceAlias(
                tenant_id=tenant.id,
                resource_id=resource.id,
                alias_type="hostname",
                alias_value="Example.COM",
                normalized_value="example.com",
                source="manual",
                first_seen_at=_now(-15),
                last_seen_at=_now(-14),
            ),
            ResourceMerge(
                tenant_id=tenant.id,
                source_resource_id=resource.id,
                target_resource_id=target_resource.id,
                reason="duplicate",
                source="manual",
                merged_at=_now(-13),
            ),
        ]
    )
    session.flush()
    return tenant.id, resource.id, resource.canonical_name


def test_sqlalchemy_unit_of_work_returns_persisted_resource_details(
    migrated_engine: Engine,
) -> None:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        tenant_id, resource_id, canonical_name = _seed_resource_details(setup_session)
        setup_session.commit()

    details_handler = GetResourceDetailsHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal),
    )
    canonical_handler = GetResourceByCanonicalNameHandler(
        lambda: SQLAlchemyUnitOfWork(SessionLocal),
    )

    details = details_handler.handle(GetResourceDetailsQuery(tenant_id, resource_id))
    canonical = canonical_handler.handle(
        GetResourceByCanonicalNameQuery(tenant_id, canonical_name),
    )

    assert details == canonical
    assert details.id == resource_id
    assert details.tenant_id == tenant_id
    assert details.state is not None
    assert details.identifiers[0].normalized_value == "example.com"
    assert details.ownership[0].organization_id == details.organization_id
    assert details.classifications[0].classification_value_id
    assert details.labels[0].label_id
    assert details.aliases[0].normalized_value == "example.com"
    assert details.outgoing_merge is not None
    assert details.outgoing_merge.source_resource_id == resource_id
