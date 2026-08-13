from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.handlers import (
    FindResourceByAliasHandler,
    FindResourceByIdentifierHandler,
    ListResourcesHandler,
    ResolveCanonicalResourceHandler,
)
from app.application.queries import (
    FindResourceByAliasQuery,
    FindResourceByIdentifierQuery,
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
    Resource,
    ResourceAlias,
    ResourceClassification,
    ResourceIdentifier,
    ResourceLabel,
    ResourceMerge,
    ResourceOwnership,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _uow_factory(SessionLocal: sessionmaker[Session]):
    return lambda: SQLAlchemyUnitOfWork(SessionLocal)


def _now(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


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


def _seed_tenant(session: Session, prefix: str) -> UUID:
    seed_catalogs(session)
    tenant = Tenant(slug=_slug(prefix), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    return tenant.id


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


def _resource(
    session: Session,
    tenant_id: UUID,
    name: str,
    *,
    created_at: datetime,
    resource_type_code: str = "ip",
    lifecycle_status_code: str = "inactive",
) -> Resource:
    resource = Resource(
        tenant_id=tenant_id,
        resource_type_id=_catalog_id(session, ResourceType, resource_type_code),
        canonical_name=_slug(name),
        display_name=name,
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, lifecycle_status_code),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        first_seen_at=created_at,
        last_seen_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(resource)
    session.flush()
    return resource


def _ownership(
    session: Session,
    resource: Resource,
    organization: Organization,
    *,
    is_primary: bool = True,
    ownership_role_id: UUID | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceOwnership:
    ownership = ResourceOwnership(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        organization_id=organization.id,
        ownership_role_id=ownership_role_id or _catalog_id(session, OwnershipRole, "owner"),
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from or _now(-1),
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
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceLabel:
    assignment = ResourceLabel(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        label_id=label.id,
        valid_from=valid_from or _now(-1),
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
    value_code: str,
    is_primary: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceClassification:
    classification_type_id = _catalog_id(session, ClassificationType, "environment")
    classification = ResourceClassification(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        classification_type_id=classification_type_id,
        classification_value_id=_classification_value_id(session, value_code),
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from or _now(-1),
        valid_to=valid_to,
        source="test",
    )
    session.add(classification)
    session.flush()
    return classification


def _identifier(
    session: Session,
    resource: Resource,
    normalized_value: str,
    *,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceIdentifier:
    identifier = ResourceIdentifier(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        identifier_type_id=_catalog_id(session, IdentifierType, "fqdn"),
        namespace="dns",
        normalized_value=normalized_value,
        original_value=normalized_value.upper(),
        value_hash=f"hash-{normalized_value}",
        is_primary=False,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from or _now(-1),
        valid_to=valid_to,
    )
    session.add(identifier)
    session.flush()
    return identifier


def _alias(session: Session, resource: Resource, normalized_value: str) -> ResourceAlias:
    alias = ResourceAlias(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        alias_type="dns_name",
        alias_value=normalized_value.upper(),
        normalized_value=normalized_value,
        source="test",
        first_seen_at=_now(-2),
        last_seen_at=_now(-1),
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
        merged_at=_now(),
    )
    session.add(merge)
    session.flush()
    return merge


def _expected_order(resources: list[Resource]) -> list[UUID]:
    return [
        resource.id
        for resource in sorted(resources, key=lambda row: (row.created_at, row.id))
    ]


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


def test_stage_03_2_query_surface_integrates_filters_pagination_and_identity(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        organization = _organization(setup, tenant_a, "owner")
        wrong_organization = _organization(setup, tenant_a, "wrong-owner")
        tenant_b_organization = _organization(setup, tenant_b, "tenant-b-owner")
        label = _label(setup, tenant_a, "stage", "03-2")
        wrong_label = _label(setup, tenant_a, "stage", "other")
        tenant_b_label = _label(setup, tenant_b, "stage", "03-2")
        classification_type_id = _catalog_id(setup, ClassificationType, "environment")
        production_id = _classification_value_id(setup, "production")
        identifier_type_id = _catalog_id(setup, IdentifierType, "fqdn")
        resource_type_id = _catalog_id(setup, ResourceType, "ip")
        lifecycle_status_id = _catalog_id(setup, LifecycleStatus, "inactive")
        start = _now(-60)

        matching: list[Resource] = []
        for index in range(8):
            resource = _resource(
                setup,
                tenant_a,
                f"match-{index}",
                created_at=start + timedelta(minutes=index * 2),
            )
            _ownership(setup, resource, organization)
            _ownership(
                setup,
                resource,
                wrong_organization,
                ownership_role_id=_catalog_id(setup, OwnershipRole, "custodian"),
                is_primary=True,
            )
            _label_assignment(setup, resource, label)
            _classification(setup, resource, value_code="production", is_primary=False)
            _identifier(setup, resource, f"match-{index}.example.com")
            _alias(setup, resource, f"match-{index}.alias.example.com")
            matching.append(resource)

        historical_noise = _resource(
            setup,
            tenant_a,
            "historical-noise",
            created_at=start + timedelta(minutes=17),
        )
        _ownership(
            setup,
            historical_noise,
            organization,
            valid_from=_now(-50),
            valid_to=_now(-40),
        )
        _label_assignment(
            setup,
            historical_noise,
            label,
            valid_from=_now(-50),
            valid_to=_now(-40),
        )
        _classification(
            setup,
            historical_noise,
            value_code="production",
            valid_from=_now(-50),
            valid_to=_now(-40),
        )
        _identifier(
            setup,
            historical_noise,
            "historical.example.com",
            valid_from=_now(-50),
            valid_to=_now(-40),
        )

        wrong_type = _resource(
            setup,
            tenant_a,
            "wrong-type",
            created_at=start + timedelta(minutes=3),
            resource_type_code="domain",
        )
        wrong_lifecycle = _resource(
            setup,
            tenant_a,
            "wrong-lifecycle",
            created_at=start + timedelta(minutes=5),
            lifecycle_status_code="active",
        )
        wrong_owner = _resource(
            setup,
            tenant_a,
            "wrong-owner",
            created_at=start + timedelta(minutes=7),
        )
        wrong_label_resource = _resource(
            setup,
            tenant_a,
            "wrong-label",
            created_at=start + timedelta(minutes=9),
        )
        wrong_classification = _resource(
            setup,
            tenant_a,
            "wrong-classification",
            created_at=start + timedelta(minutes=11),
        )
        for resource in (wrong_type, wrong_lifecycle):
            _ownership(setup, resource, organization)
            _label_assignment(setup, resource, label)
            _classification(setup, resource, value_code="production")
        _ownership(setup, wrong_owner, wrong_organization)
        _label_assignment(setup, wrong_owner, label)
        _classification(setup, wrong_owner, value_code="production")
        _ownership(setup, wrong_label_resource, organization)
        _label_assignment(setup, wrong_label_resource, wrong_label)
        _classification(setup, wrong_label_resource, value_code="production")
        _ownership(setup, wrong_classification, organization)
        _label_assignment(setup, wrong_classification, label)
        _classification(setup, wrong_classification, value_code="staging")

        tenant_b_resource = _resource(
            setup,
            tenant_b,
            "tenant-b-overlap",
            created_at=start,
        )
        _ownership(setup, tenant_b_resource, tenant_b_organization)
        _label_assignment(setup, tenant_b_resource, tenant_b_label)
        _classification(setup, tenant_b_resource, value_code="production")
        _identifier(setup, tenant_b_resource, "match-0.example.com")
        _alias(setup, tenant_b_resource, "match-0.alias.example.com")

        canonical_target = _resource(
            setup,
            tenant_a,
            "canonical-target",
            created_at=start + timedelta(minutes=30),
        )
        _merge(setup, matching[0], canonical_target)
        expected_ids = _expected_order(matching)
        listed_identifier = "match-0.example.com"
        listed_alias = "match-0.alias.example.com"
        setup.commit()

    list_handler = ListResourcesHandler(_uow_factory(SessionLocal))
    identifier_handler = FindResourceByIdentifierHandler(_uow_factory(SessionLocal))
    alias_handler = FindResourceByAliasHandler(_uow_factory(SessionLocal))
    canonical_handler = ResolveCanonicalResourceHandler(_uow_factory(SessionLocal))

    cursor = None
    actual_ids: list[UUID] = []
    page_sizes: list[int] = []
    list_select_count = 0
    while True:
        with _capture_sql(migrated_engine) as statements:
            page = list_handler.handle(
                ListResourcesQuery(
                    tenant_id=tenant_a,
                    resource_type_id=resource_type_id,
                    lifecycle_status_id=lifecycle_status_id,
                    organization_id=organization.id,
                    label_id=label.id,
                    classification_type_id=classification_type_id,
                    classification_value_id=production_id,
                    page_size=3,
                    cursor=cursor,
                )
            )
        selects = [
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
        ]
        assert len(selects) == 1
        assert "OFFSET" not in selects[0].upper()
        assert "COUNT" not in selects[0].upper()
        assert "DISTINCT" not in selects[0].upper()
        list_select_count += len(selects)
        page_sizes.append(len(page.items))
        actual_ids.extend(item.resource_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert actual_ids == expected_ids
    assert len(actual_ids) == len(set(actual_ids)) == 8
    assert page_sizes == [3, 3, 2]
    assert list_select_count == 3

    with _capture_sql(migrated_engine) as identifier_statements:
        identifier_result = identifier_handler.handle(
            FindResourceByIdentifierQuery(
                tenant_id=tenant_a,
                identifier_type_id=identifier_type_id,
                namespace="dns",
                normalized_value=listed_identifier,
            )
        )
    with _capture_sql(migrated_engine) as alias_statements:
        alias_result = alias_handler.handle(
            FindResourceByAliasQuery(
                tenant_id=tenant_a,
                alias_type="dns_name",
                normalized_value=listed_alias,
            )
        )
    canonical_result = canonical_handler.handle(
        ResolveCanonicalResourceQuery(
            tenant_id=tenant_a,
            resource_id=identifier_result.resource.id,
        )
    )

    identifier_selects = [
        statement
        for statement in identifier_statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    alias_selects = [
        statement
        for statement in alias_statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(identifier_selects) == 1
    assert len(alias_selects) == 1
    assert identifier_result.resource.id == matching[0].id
    assert alias_result.resource.id == matching[0].id
    assert canonical_result.requested_resource_id == matching[0].id
    assert canonical_result.canonical_resource_id != matching[0].id
    assert identifier_result.resource.canonical_name
    assert alias_result.resource.canonical_name
