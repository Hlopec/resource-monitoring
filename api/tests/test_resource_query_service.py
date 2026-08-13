from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.errors import EntityNotFoundError
from app.application.handlers import (
    FindResourceByAliasHandler,
    FindResourceByIdentifierHandler,
    GetResourceDetailsHandler,
    ListResourcesHandler,
    ResolveCanonicalResourceHandler,
)
from app.application.pagination import decode_resource_list_cursor
from app.application.queries import (
    FindResourceByAliasQuery,
    FindResourceByIdentifierQuery,
    GetResourceDetailsQuery,
    ListResourcesQuery,
    ResolveCanonicalResourceQuery,
)
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    IdentifierType,
    ClassificationType,
    ClassificationValue,
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
from app.persistence.sqlalchemy.queries import SQLAlchemyResourceQueryService


def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _uow_factory(SessionLocal: sessionmaker[Session]):
    return lambda: SQLAlchemyUnitOfWork(SessionLocal)


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _now(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


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


def _organization(session: Session, tenant_id: UUID, name: str) -> Organization:
    organization = Organization(
        tenant_id=tenant_id,
        canonical_name=name,
        display_name=name,
        external_key=None,
        status="active",
        archived_at=None,
    )
    session.add(organization)
    session.flush()
    return organization


def _resource(
    session: Session,
    tenant_id: UUID,
    canonical_name: str,
    *,
    created_at: datetime,
    resource_type_code: str = "domain",
    lifecycle_status_code: str = "active",
) -> Resource:
    resource = Resource(
        tenant_id=tenant_id,
        resource_type_id=_catalog_id(session, ResourceType, resource_type_code),
        canonical_name=canonical_name,
        display_name=canonical_name,
        lifecycle_status_id=_catalog_id(
            session,
            LifecycleStatus,
            lifecycle_status_code,
        ),
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


def _seed_resources(
    session: Session,
    tenant_id: UUID,
    count: int,
    *,
    created_at: datetime | None = None,
    prefix: str = "resource",
) -> list[Resource]:
    start = created_at or _now(-count)
    resources = [
        _resource(
            session,
            tenant_id,
            _slug(f"{prefix}-{index}"),
            created_at=start + timedelta(minutes=index),
        )
        for index in range(count)
    ]
    session.flush()
    return resources


def _expected_order(resources: list[Resource]) -> list[UUID]:
    return [
        resource.id
        for resource in sorted(resources, key=lambda row: (row.created_at, row.id))
    ]


def _owner_role_id(session: Session) -> UUID:
    return _catalog_id(session, OwnershipRole, "owner")


def _custodian_role_id(session: Session) -> UUID:
    return _catalog_id(session, OwnershipRole, "custodian")


def _classification_type_id(session: Session, code: str = "environment") -> UUID:
    return _catalog_id(session, ClassificationType, code)


def _classification_value_id(session: Session, code: str) -> UUID:
    entity_id = session.scalar(
        select(ClassificationValue.id).where(ClassificationValue.code == code)
    )
    assert entity_id is not None
    return entity_id


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
    classification_type_id: UUID | None = None,
    classification_value_id: UUID | None = None,
    is_primary: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceClassification:
    classification_type_id = classification_type_id or _classification_type_id(session)
    classification_value_id = classification_value_id or _classification_value_id(
        session,
        "production",
    )
    classification = ResourceClassification(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        classification_type_id=classification_type_id,
        classification_value_id=classification_value_id,
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from or _now(-1),
        valid_to=valid_to,
        source="test",
    )
    session.add(classification)
    session.flush()
    return classification


def _ownership(
    session: Session,
    resource: Resource,
    organization: Organization,
    *,
    ownership_role_id: UUID | None = None,
    is_primary: bool = True,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceOwnership:
    ownership = ResourceOwnership(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        organization_id=organization.id,
        ownership_role_id=ownership_role_id or _owner_role_id(session),
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from or _now(-1),
        valid_to=valid_to,
        source="test",
    )
    session.add(ownership)
    session.flush()
    return ownership


def _identifier_type_id(session: Session, code: str = "fqdn") -> UUID:
    return _catalog_id(session, IdentifierType, code)


def _identifier(
    session: Session,
    resource: Resource,
    *,
    identifier_type_id: UUID | None = None,
    namespace: str | None = None,
    normalized_value: str = "example.com",
    original_value: str = "Example.COM",
    value_hash: str = "hash-example.com",
    is_primary: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceIdentifier:
    identifier = ResourceIdentifier(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        identifier_type_id=identifier_type_id or _identifier_type_id(session),
        namespace=namespace,
        normalized_value=normalized_value,
        original_value=original_value,
        value_hash=value_hash,
        is_primary=is_primary,
        confidence_score=Decimal("0.9000"),
        valid_from=valid_from or _now(-1),
        valid_to=valid_to,
    )
    session.add(identifier)
    session.flush()
    return identifier


def _alias(
    session: Session,
    resource: Resource,
    *,
    alias_type: str = "dns_name",
    normalized_value: str = "example.com",
    alias_value: str = "Example.COM",
) -> ResourceAlias:
    now = _now(-1)
    alias = ResourceAlias(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        alias_type=alias_type,
        alias_value=alias_value,
        normalized_value=normalized_value,
        source="test",
        first_seen_at=now,
        last_seen_at=now,
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


def _state(
    session: Session,
    resource: Resource,
    *,
    lifecycle_status_id: UUID | None = None,
    criticality_id: UUID | None = None,
    exposure_level_id: UUID | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ResourceState:
    state = ResourceState(
        tenant_id=resource.tenant_id,
        resource_id=resource.id,
        lifecycle_status_id=(
            lifecycle_status_id or _catalog_id(session, LifecycleStatus, "active")
        ),
        criticality_id=criticality_id or _catalog_id(session, Criticality, "medium"),
        exposure_level_id=(
            exposure_level_id or _catalog_id(session, ExposureLevel, "public")
        ),
        source_priority=90,
        confidence_score=Decimal("0.9100"),
        valid_from=valid_from or _now(-1),
        valid_to=valid_to,
        source="test",
    )
    session.add(state)
    session.flush()
    return state


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


def test_sqlalchemy_query_service_orders_by_created_at_then_id_with_ties(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    tied_created_at = _now(-10)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resources = _seed_resources(
            setup,
            tenant_id,
            3,
            created_at=tied_created_at,
            prefix="tie",
        )
        setup.commit()

    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        page = uow.resource_queries.list_resources(
            tenant_id,
            resource_type_id=None,
            lifecycle_status_id=None,
            organization_id=None,
            label_id=None,
            classification_type_id=None,
            classification_value_id=None,
            after=None,
            limit=10,
        )

    assert [item.resource_id for item in page.items] == _expected_order(resources)
    assert page.next_position is None


def test_list_resources_keyset_paginates_without_gaps_duplicates_or_offset(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resources = _seed_resources(setup, tenant_id, 23)
        expected_ids = _expected_order(resources)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    cursor = None
    seen_ids: list[UUID] = []
    page_sizes: list[int] = []
    sql_statements: list[str] = []
    while True:
        with _capture_sql(migrated_engine) as statements:
            page = handler.handle(
                ListResourcesQuery(tenant_id=tenant_id, page_size=5, cursor=cursor)
            )
        sql_statements.extend(statements)
        page_sizes.append(len(page.items))
        seen_ids.extend(item.resource_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen_ids == expected_ids
    assert len(seen_ids) == len(set(seen_ids)) == 23
    assert all(size <= 5 for size in page_sizes)
    assert page_sizes == [5, 5, 5, 5, 3]
    assert not any(" OFFSET " in statement.upper() for statement in sql_statements)


def test_page_size_can_change_between_cursor_requests(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resources = _seed_resources(setup, tenant_id, 12)
        expected_ids = _expected_order(resources)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    first_page = handler.handle(ListResourcesQuery(tenant_id=tenant_id, page_size=4))
    second_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            page_size=7,
            cursor=first_page.next_cursor,
        )
    )

    assert [item.resource_id for item in first_page.items] == expected_ids[:4]
    assert [item.resource_id for item in second_page.items] == expected_ids[4:11]


def test_tenant_isolation_and_cross_tenant_cursor_behavior(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    shared_created_at = _now(-10)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        resources_a = _seed_resources(
            setup,
            tenant_a,
            2,
            created_at=shared_created_at,
            prefix="a",
        )
        resources_b = _seed_resources(
            setup,
            tenant_b,
            2,
            created_at=shared_created_at,
            prefix="b",
        )
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    tenant_a_page = handler.handle(ListResourcesQuery(tenant_id=tenant_a, page_size=1))
    tenant_b_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_b,
            page_size=10,
            cursor=tenant_a_page.next_cursor,
        )
    )

    assert {item.resource_id for item in tenant_a_page.items}.issubset(
        {resource.id for resource in resources_a}
    )
    assert {item.resource_id for item in tenant_b_page.items}.issubset(
        {resource.id for resource in resources_b}
    )


def test_exact_filters_combine_with_keyset_pagination(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        matching = [
            _resource(
                setup,
                tenant_id,
                _slug(f"matching-{index}"),
                created_at=_now(-10 + index),
                resource_type_code="ip",
                lifecycle_status_code="inactive",
            )
            for index in range(4)
        ]
        _resource(
            setup,
            tenant_id,
            _slug("wrong-type"),
            created_at=_now(-1),
            resource_type_code="domain",
            lifecycle_status_code="inactive",
        )
        _resource(
            setup,
            tenant_id,
            _slug("wrong-status"),
            created_at=_now(),
            resource_type_code="ip",
            lifecycle_status_code="active",
        )
        resource_type_id = _catalog_id(setup, ResourceType, "ip")
        lifecycle_status_id = _catalog_id(setup, LifecycleStatus, "inactive")
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    first_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
            page_size=2,
        )
    )
    second_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
            page_size=2,
            cursor=first_page.next_cursor,
        )
    )

    expected_ids = _expected_order(matching)
    assert [item.resource_id for item in first_page.items] == expected_ids[:2]
    assert [item.resource_id for item in second_page.items] == expected_ids[2:]
    assert second_page.next_cursor is None


def test_resources_without_current_primary_owner_remain_visible_without_filter(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(
            setup,
            tenant_id,
            _slug("unowned"),
            created_at=_now(-5),
        )
        organization = _organization(setup, tenant_id, _slug("owner"))
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    unfiltered = handler.handle(ListResourcesQuery(tenant_id=tenant_id))
    filtered = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=organization.id)
    )

    assert [item.resource_id for item in unfiltered.items] == [resource.id]
    assert unfiltered.items[0].primary_organization_id is None
    assert unfiltered.items[0].primary_ownership_role_id is None
    assert filtered.items == ()


def test_current_primary_owner_is_projected_and_filtered_exactly(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("owned"), created_at=_now(-5))
        organization = _organization(setup, tenant_id, _slug("owner"))
        ownership = _ownership(setup, resource, organization)
        wrong_organization = _organization(setup, tenant_id, _slug("wrong-owner"))
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    matching_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=organization.id)
    )
    wrong_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=wrong_organization.id)
    )

    assert [item.resource_id for item in matching_page.items] == [resource.id]
    assert matching_page.items[0].primary_organization_id == organization.id
    assert matching_page.items[0].primary_ownership_role_id == ownership.ownership_role_id
    assert wrong_page.items == ()


def test_historical_and_current_non_primary_ownership_are_ignored(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(
            setup,
            tenant_id,
            _slug("historical-nonprimary"),
            created_at=_now(-5),
        )
        historical_org = _organization(setup, tenant_id, _slug("historical"))
        non_primary_org = _organization(setup, tenant_id, _slug("non-primary"))
        current_org = _organization(setup, tenant_id, _slug("current"))
        _ownership(
            setup,
            resource,
            historical_org,
            valid_from=_now(-30),
            valid_to=_now(-20),
        )
        _ownership(setup, resource, non_primary_org, is_primary=False)
        current = _ownership(setup, resource, current_org, valid_from=_now(-10))
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    page = handler.handle(ListResourcesQuery(tenant_id=tenant_id))
    historical_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=historical_org.id)
    )
    non_primary_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=non_primary_org.id)
    )
    current_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=current_org.id)
    )

    assert [item.resource_id for item in page.items] == [resource.id]
    assert page.items[0].primary_organization_id == current_org.id
    assert page.items[0].primary_ownership_role_id == current.ownership_role_id
    assert historical_page.items == ()
    assert non_primary_page.items == ()
    assert [item.resource_id for item in current_page.items] == [resource.id]


def test_historical_primary_replacement_uses_only_current_owner(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("replacement"), created_at=_now(-5))
        org_a = _organization(setup, tenant_id, _slug("org-a"))
        org_b = _organization(setup, tenant_id, _slug("org-b"))
        _ownership(
            setup,
            resource,
            org_a,
            valid_from=_now(-30),
            valid_to=_now(-20),
        )
        _ownership(setup, resource, org_b, valid_from=_now(-20))
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    old_owner_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=org_a.id)
    )
    current_owner_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=org_b.id)
    )

    assert old_owner_page.items == ()
    assert [item.resource_id for item in current_owner_page.items] == [resource.id]
    assert current_owner_page.items[0].primary_organization_id == org_b.id


def test_multiple_ownership_rows_do_not_duplicate_resource(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("multi-owner"), created_at=_now(-5))
        historical_owner = _organization(setup, tenant_id, _slug("historical-owner"))
        owner_org = _organization(setup, tenant_id, _slug("owner"))
        non_primary_org = _organization(setup, tenant_id, _slug("non-primary"))
        custodian_org = _organization(setup, tenant_id, _slug("custodian"))
        owner_role_id = _owner_role_id(setup)
        _ownership(
            setup,
            resource,
            historical_owner,
            valid_from=_now(-40),
            valid_to=_now(-30),
        )
        _ownership(setup, resource, owner_org, valid_from=_now(-20))
        _ownership(setup, resource, non_primary_org, is_primary=False)
        _ownership(
            setup,
            resource,
            custodian_org,
            ownership_role_id=_custodian_role_id(setup),
            is_primary=True,
        )
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    page = handler.handle(ListResourcesQuery(tenant_id=tenant_id, page_size=10))

    assert [item.resource_id for item in page.items] == [resource.id]
    assert page.items[0].primary_organization_id == owner_org.id
    assert page.items[0].primary_ownership_role_id == owner_role_id


def test_organization_filter_composes_with_type_and_lifecycle_status(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        organization = _organization(setup, tenant_id, _slug("filter-org"))
        wrong_organization = _organization(setup, tenant_id, _slug("wrong-org"))
        matching = _resource(
            setup,
            tenant_id,
            _slug("all-match"),
            created_at=_now(-10),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        wrong_type = _resource(
            setup,
            tenant_id,
            _slug("wrong-type-org"),
            created_at=_now(-9),
            resource_type_code="domain",
            lifecycle_status_code="inactive",
        )
        wrong_status = _resource(
            setup,
            tenant_id,
            _slug("wrong-status-org"),
            created_at=_now(-8),
            resource_type_code="ip",
            lifecycle_status_code="active",
        )
        wrong_org_resource = _resource(
            setup,
            tenant_id,
            _slug("wrong-org"),
            created_at=_now(-7),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        _ownership(setup, matching, organization)
        _ownership(setup, wrong_type, organization)
        _ownership(setup, wrong_status, organization)
        _ownership(setup, wrong_org_resource, wrong_organization)
        resource_type_id = _catalog_id(setup, ResourceType, "ip")
        lifecycle_status_id = _catalog_id(setup, LifecycleStatus, "inactive")
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    org_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=organization.id)
    )
    type_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            organization_id=organization.id,
            resource_type_id=resource_type_id,
        )
    )
    lifecycle_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            organization_id=organization.id,
            lifecycle_status_id=lifecycle_status_id,
        )
    )
    combined_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            organization_id=organization.id,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
        )
    )

    assert [item.resource_id for item in org_page.items] == _expected_order(
        [matching, wrong_type, wrong_status]
    )
    assert [item.resource_id for item in type_page.items] == _expected_order(
        [matching, wrong_status]
    )
    assert [item.resource_id for item in lifecycle_page.items] == _expected_order(
        [matching, wrong_type]
    )
    assert [item.resource_id for item in combined_page.items] == [matching.id]


def test_keyset_pagination_with_organization_filter_skips_nonmatches(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        org_a = _organization(setup, tenant_id, _slug("org-a"))
        org_b = _organization(setup, tenant_id, _slug("org-b"))
        resources: list[Resource] = []
        org_a_resources: list[Resource] = []
        start = _now(-20)
        for index in range(7):
            resource = _resource(
                setup,
                tenant_id,
                _slug(f"interleaved-{index}"),
                created_at=start + timedelta(minutes=index),
            )
            resources.append(resource)
            if index % 2 == 0:
                _ownership(setup, resource, org_a)
                org_a_resources.append(resource)
            else:
                _ownership(setup, resource, org_b)
        expected_ids = _expected_order(org_a_resources)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    first_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, organization_id=org_a.id, page_size=2)
    )
    second_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            organization_id=org_a.id,
            page_size=2,
            cursor=first_page.next_cursor,
        )
    )

    assert _expected_order(resources) != expected_ids
    assert [item.resource_id for item in first_page.items] == expected_ids[:2]
    assert [item.resource_id for item in second_page.items] == expected_ids[2:]
    assert second_page.next_cursor is None


def test_organization_filter_is_tenant_scoped(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        org_a = _organization(setup, tenant_a, _slug("org-a"))
        org_b = _organization(setup, tenant_b, _slug("org-b"))
        resource_a = _resource(setup, tenant_a, _slug("resource-a"), created_at=_now(-5))
        resource_b = _resource(setup, tenant_b, _slug("resource-b"), created_at=_now(-5))
        _ownership(setup, resource_a, org_a)
        _ownership(setup, resource_b, org_b)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    wrong_tenant_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_b, organization_id=org_a.id)
    )
    tenant_b_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_b, organization_id=org_b.id)
    )

    assert wrong_tenant_page.items == ()
    assert [item.resource_id for item in tenant_b_page.items] == [resource_b.id]


def test_label_filter_matches_current_assignments_without_duplicates(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        label_x = _label(setup, tenant_id, "environment", _slug("prod"))
        label_y = _label(setup, tenant_id, "owner", _slug("platform"))
        wrong_label = _label(setup, tenant_id, "environment", _slug("stage"))
        historical_only = _resource(
            setup,
            tenant_id,
            _slug("historical-label"),
            created_at=_now(-10),
        )
        matching = _resource(setup, tenant_id, _slug("label-match"), created_at=_now(-9))
        wrong = _resource(setup, tenant_id, _slug("wrong-label"), created_at=_now(-8))
        no_labels = _resource(setup, tenant_id, _slug("no-label"), created_at=_now(-7))
        _label_assignment(
            setup,
            historical_only,
            label_x,
            valid_from=_now(-30),
            valid_to=_now(-20),
        )
        _label_assignment(setup, matching, label_x)
        _label_assignment(setup, matching, label_y)
        _label_assignment(setup, wrong, wrong_label)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    filtered = handler.handle(ListResourcesQuery(tenant_id=tenant_id, label_id=label_x.id))
    unfiltered = handler.handle(ListResourcesQuery(tenant_id=tenant_id))

    assert [item.resource_id for item in filtered.items] == [matching.id]
    assert len(filtered.items) == len({item.resource_id for item in filtered.items})
    assert no_labels.id in {item.resource_id for item in unfiltered.items}


def test_label_filter_is_tenant_scoped_and_composes_with_other_filters(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        label_a = _label(setup, tenant_a, "team", _slug("a"))
        label_b = _label(setup, tenant_b, "team", _slug("b"))
        org = _organization(setup, tenant_b, _slug("org"))
        wrong_org = _organization(setup, tenant_b, _slug("wrong-org"))
        match = _resource(
            setup,
            tenant_b,
            _slug("label-all-match"),
            created_at=_now(-10),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        wrong_type = _resource(
            setup,
            tenant_b,
            _slug("label-wrong-type"),
            created_at=_now(-9),
            resource_type_code="domain",
            lifecycle_status_code="inactive",
        )
        wrong_status = _resource(
            setup,
            tenant_b,
            _slug("label-wrong-status"),
            created_at=_now(-8),
            resource_type_code="ip",
            lifecycle_status_code="active",
        )
        wrong_owner = _resource(
            setup,
            tenant_b,
            _slug("label-wrong-owner"),
            created_at=_now(-7),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        _label_assignment(setup, match, label_b)
        _label_assignment(setup, wrong_type, label_b)
        _label_assignment(setup, wrong_status, label_b)
        _label_assignment(setup, wrong_owner, label_b)
        _ownership(setup, match, org)
        _ownership(setup, wrong_type, org)
        _ownership(setup, wrong_status, org)
        _ownership(setup, wrong_owner, wrong_org)
        resource_type_id = _catalog_id(setup, ResourceType, "ip")
        lifecycle_status_id = _catalog_id(setup, LifecycleStatus, "inactive")
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    cross_tenant = handler.handle(ListResourcesQuery(tenant_id=tenant_b, label_id=label_a.id))
    composed = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_b,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
            organization_id=org.id,
            label_id=label_b.id,
        )
    )

    assert cross_tenant.items == ()
    assert [item.resource_id for item in composed.items] == [match.id]


def test_label_filter_keyset_pagination_skips_nonmatches(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        label = _label(setup, tenant_id, "segment", _slug("x"))
        matches: list[Resource] = []
        start = _now(-20)
        for index in range(7):
            resource = _resource(
                setup,
                tenant_id,
                _slug(f"label-page-{index}"),
                created_at=start + timedelta(minutes=index),
            )
            if index % 2 == 0:
                _label_assignment(setup, resource, label)
                matches.append(resource)
        expected_ids = _expected_order(matches)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    first_page = handler.handle(
        ListResourcesQuery(tenant_id=tenant_id, label_id=label.id, page_size=2)
    )
    second_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            label_id=label.id,
            page_size=2,
            cursor=first_page.next_cursor,
        )
    )

    assert [item.resource_id for item in first_page.items] == expected_ids[:2]
    assert [item.resource_id for item in second_page.items] == expected_ids[2:]
    assert second_page.next_cursor is None


def test_classification_filter_matches_current_type_and_value_semantics(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        classification_type_id = _classification_type_id(setup)
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        historical_only = _resource(
            setup,
            tenant_id,
            _slug("historical-class"),
            created_at=_now(-10),
        )
        current_non_primary = _resource(
            setup,
            tenant_id,
            _slug("current-non-primary"),
            created_at=_now(-9),
        )
        current_staging = _resource(
            setup,
            tenant_id,
            _slug("current-staging"),
            created_at=_now(-8),
        )
        no_classification = _resource(
            setup,
            tenant_id,
            _slug("no-classification"),
            created_at=_now(-7),
        )
        _classification(
            setup,
            historical_only,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            valid_from=_now(-30),
            valid_to=_now(-20),
        )
        _classification(
            setup,
            current_non_primary,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            is_primary=False,
        )
        _classification(
            setup,
            current_staging,
            classification_type_id=classification_type_id,
            classification_value_id=staging_id,
        )
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    type_only = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            classification_type_id=classification_type_id,
        )
    )
    type_and_value = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
    )
    unfiltered = handler.handle(ListResourcesQuery(tenant_id=tenant_id))

    assert [item.resource_id for item in type_only.items] == _expected_order(
        [current_non_primary, current_staging]
    )
    assert [item.resource_id for item in type_and_value.items] == [
        current_non_primary.id
    ]
    assert no_classification.id in {item.resource_id for item in unfiltered.items}


def test_classification_historical_replacement_and_multiple_rows_do_not_duplicate(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        classification_type_id = _classification_type_id(setup)
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        resource = _resource(
            setup,
            tenant_id,
            _slug("classification-replacement"),
            created_at=_now(-10),
        )
        _classification(
            setup,
            resource,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            valid_from=_now(-30),
            valid_to=_now(-20),
        )
        _classification(
            setup,
            resource,
            classification_type_id=classification_type_id,
            classification_value_id=staging_id,
            valid_from=_now(-20),
        )
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    old_value = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
    )
    current_value = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            classification_type_id=classification_type_id,
            classification_value_id=staging_id,
        )
    )
    type_only = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            classification_type_id=classification_type_id,
        )
    )

    assert old_value.items == ()
    assert [item.resource_id for item in current_value.items] == [resource.id]
    assert [item.resource_id for item in type_only.items] == [resource.id]


def test_classification_filter_tenant_scope_pagination_and_composition(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        classification_type_id = _classification_type_id(setup)
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        tenant_a_resource = _resource(
            setup,
            tenant_a,
            _slug("classification-tenant-a"),
            created_at=_now(-12),
        )
        _classification(
            setup,
            tenant_a_resource,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
        org = _organization(setup, tenant_b, _slug("classification-org"))
        wrong_org = _organization(setup, tenant_b, _slug("classification-wrong-org"))
        matches: list[Resource] = []
        start = _now(-10)
        for index in range(7):
            resource = _resource(
                setup,
                tenant_b,
                _slug(f"classification-page-{index}"),
                created_at=start + timedelta(minutes=index),
                resource_type_code="ip",
                lifecycle_status_code="inactive",
            )
            if index % 2 == 0:
                _classification(
                    setup,
                    resource,
                    classification_type_id=classification_type_id,
                    classification_value_id=production_id,
                )
                _ownership(setup, resource, org)
                matches.append(resource)
            else:
                _classification(
                    setup,
                    resource,
                    classification_type_id=classification_type_id,
                    classification_value_id=staging_id,
                )
                _ownership(setup, resource, wrong_org)
        expected_ids = _expected_order(matches)
        resource_type_id = _catalog_id(setup, ResourceType, "ip")
        lifecycle_status_id = _catalog_id(setup, LifecycleStatus, "inactive")
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    tenant_a_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_a,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
    )
    first_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_b,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
            organization_id=org.id,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            page_size=2,
        )
    )
    second_page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_b,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
            organization_id=org.id,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            page_size=2,
            cursor=first_page.next_cursor,
        )
    )

    assert [item.resource_id for item in tenant_a_page.items] == [tenant_a_resource.id]
    assert [item.resource_id for item in first_page.items] == expected_ids[:2]
    assert [item.resource_id for item in second_page.items] == expected_ids[2:]
    assert second_page.next_cursor is None


def test_all_resource_list_filters_compose_with_and_semantics(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        label = _label(setup, tenant_id, "tier", _slug("critical"))
        wrong_label = _label(setup, tenant_id, "tier", _slug("standard"))
        classification_type_id = _classification_type_id(setup)
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        org = _organization(setup, tenant_id, _slug("full-org"))
        wrong_org = _organization(setup, tenant_id, _slug("full-wrong-org"))
        match = _resource(
            setup,
            tenant_id,
            _slug("full-match"),
            created_at=_now(-10),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        wrong_type = _resource(
            setup,
            tenant_id,
            _slug("full-wrong-type"),
            created_at=_now(-9),
            resource_type_code="domain",
            lifecycle_status_code="inactive",
        )
        wrong_lifecycle = _resource(
            setup,
            tenant_id,
            _slug("full-wrong-lifecycle"),
            created_at=_now(-8),
            resource_type_code="ip",
            lifecycle_status_code="active",
        )
        wrong_org_resource = _resource(
            setup,
            tenant_id,
            _slug("full-wrong-org"),
            created_at=_now(-7),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        wrong_label_resource = _resource(
            setup,
            tenant_id,
            _slug("full-wrong-label"),
            created_at=_now(-6),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        wrong_classification_value = _resource(
            setup,
            tenant_id,
            _slug("full-wrong-classification-value"),
            created_at=_now(-5),
            resource_type_code="ip",
            lifecycle_status_code="inactive",
        )
        for resource in (
            match,
            wrong_type,
            wrong_lifecycle,
        ):
            _ownership(setup, resource, org)
            _label_assignment(setup, resource, label)
            _classification(
                setup,
                resource,
                classification_type_id=classification_type_id,
                classification_value_id=production_id,
            )
        _ownership(setup, wrong_org_resource, wrong_org)
        _label_assignment(setup, wrong_org_resource, label)
        _classification(
            setup,
            wrong_org_resource,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
        _ownership(setup, wrong_label_resource, org)
        _label_assignment(setup, wrong_label_resource, wrong_label)
        _classification(
            setup,
            wrong_label_resource,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
        _ownership(setup, wrong_classification_value, org)
        _label_assignment(setup, wrong_classification_value, label)
        _classification(
            setup,
            wrong_classification_value,
            classification_type_id=classification_type_id,
            classification_value_id=staging_id,
        )
        resource_type_id = _catalog_id(setup, ResourceType, "ip")
        lifecycle_status_id = _catalog_id(setup, LifecycleStatus, "inactive")
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    page = handler.handle(
        ListResourcesQuery(
            tenant_id=tenant_id,
            resource_type_id=resource_type_id,
            lifecycle_status_id=lifecycle_status_id,
            organization_id=org.id,
            label_id=label.id,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
    )

    assert [item.resource_id for item in page.items] == [match.id]


def test_label_and_classification_filter_sql_shape(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        label = _label(setup, tenant_id, "shape", _slug("label"))
        classification_type_id = _classification_type_id(setup)
        production_id = _classification_value_id(setup, "production")
        resource = _resource(setup, tenant_id, _slug("shape-resource"), created_at=_now(-5))
        _label_assignment(setup, resource, label)
        _classification(
            setup,
            resource,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
        )
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        page = handler.handle(
            ListResourcesQuery(
                tenant_id=tenant_id,
                label_id=label.id,
                classification_type_id=classification_type_id,
                classification_value_id=production_id,
            )
        )

    select_statements = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(select_statements) == 1
    sql = select_statements[0].upper()
    assert "EXISTS" in sql
    assert "RESOURCE_LABEL" in sql
    assert "RESOURCE_CLASSIFICATION" in sql
    assert "LABEL_ID" in sql
    assert "CLASSIFICATION_TYPE_ID" in sql
    assert "CLASSIFICATION_VALUE_ID" in sql
    assert "VALID_TO IS NULL" in sql
    assert "OFFSET" not in sql
    assert "COUNT" not in sql
    assert "DISTINCT" not in sql
    assert [item.resource_id for item in page.items] == [resource.id]


def test_classification_type_only_sql_omits_value_predicate(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        classification_type_id = _classification_type_id(setup)
        resource = _resource(
            setup,
            tenant_id,
            _slug("type-only-shape"),
            created_at=_now(-5),
        )
        _classification(setup, resource, classification_type_id=classification_type_id)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        page = handler.handle(
            ListResourcesQuery(
                tenant_id=tenant_id,
                classification_type_id=classification_type_id,
            )
        )

    sql = "\n".join(
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ).upper()
    assert "RESOURCE_CLASSIFICATION" in sql
    assert "CLASSIFICATION_TYPE_ID" in sql
    assert "CLASSIFICATION_VALUE_ID =" not in sql
    assert "OFFSET" not in sql
    assert "COUNT" not in sql
    assert "DISTINCT" not in sql
    assert [item.resource_id for item in page.items] == [resource.id]


def test_identifier_lookup_matches_exact_current_identifier(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("identifier"), created_at=_now(-5))
        identifier = _identifier(
            setup,
            resource,
            namespace="dns",
            normalized_value="CaseSensitive-Key",
            original_value="Example.COM",
            is_primary=False,
        )
        setup.commit()
    handler = FindResourceByIdentifierHandler(_uow_factory(SessionLocal))

    result = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier.identifier_type_id,
            namespace="dns",
            normalized_value="CaseSensitive-Key",
        )
    )

    assert result.resource.id == resource.id
    assert result.resource.tenant_id == tenant_id
    assert result.identifier_id == identifier.id
    assert result.namespace == "dns"
    assert result.normalized_value == "CaseSensitive-Key"
    assert result.original_value == "Example.COM"
    assert result.is_primary is False


def test_identifier_lookup_uses_normalized_value_not_original_value(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("original"), created_at=_now(-5))
        identifier = _identifier(
            setup,
            resource,
            normalized_value="example.com",
            original_value="Example.COM",
        )
        setup.commit()
    handler = FindResourceByIdentifierHandler(_uow_factory(SessionLocal))

    matching = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier.identifier_type_id,
            namespace=None,
            normalized_value="example.com",
        )
    )

    assert matching.resource.id == resource.id
    with pytest.raises(EntityNotFoundError):
        handler.handle(
            FindResourceByIdentifierQuery(
                tenant_id=tenant_id,
                identifier_type_id=identifier.identifier_type_id,
                namespace=None,
                normalized_value="Example.COM",
            )
        )


def test_identifier_lookup_namespace_semantics_are_exact(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        identifier_type_id = _identifier_type_id(setup)
        null_resource = _resource(setup, tenant_id, _slug("null-ns"), created_at=_now(-5))
        dns_resource = _resource(setup, tenant_id, _slug("dns-ns"), created_at=_now(-4))
        cloud_resource = _resource(setup, tenant_id, _slug("cloud-ns"), created_at=_now(-3))
        null_identifier = _identifier(
            setup,
            null_resource,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value="shared.example.com",
            value_hash="hash-null",
        )
        dns_identifier = _identifier(
            setup,
            dns_resource,
            identifier_type_id=identifier_type_id,
            namespace="dns",
            normalized_value="shared.example.com",
            value_hash="hash-dns",
        )
        cloud_identifier = _identifier(
            setup,
            cloud_resource,
            identifier_type_id=identifier_type_id,
            namespace="cloud",
            normalized_value="shared.example.com",
            value_hash="hash-cloud",
        )
        setup.commit()
    handler = FindResourceByIdentifierHandler(_uow_factory(SessionLocal))

    null_result = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value="shared.example.com",
        )
    )
    dns_result = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier_type_id,
            namespace="dns",
            normalized_value="shared.example.com",
        )
    )
    cloud_result = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier_type_id,
            namespace="cloud",
            normalized_value="shared.example.com",
        )
    )

    assert null_result.identifier_id == null_identifier.id
    assert dns_result.identifier_id == dns_identifier.id
    assert cloud_result.identifier_id == cloud_identifier.id


def test_historical_identifier_is_ignored_and_current_reuse_matches(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        identifier_type_id = _identifier_type_id(setup)
        resource_a = _resource(setup, tenant_id, _slug("old-id"), created_at=_now(-10))
        resource_b = _resource(setup, tenant_id, _slug("new-id"), created_at=_now(-9))
        _identifier(
            setup,
            resource_a,
            identifier_type_id=identifier_type_id,
            normalized_value="reused.example.com",
            value_hash="hash-old",
            valid_from=_now(-30),
            valid_to=_now(-20),
        )
        current = _identifier(
            setup,
            resource_b,
            identifier_type_id=identifier_type_id,
            normalized_value="reused.example.com",
            value_hash="hash-new",
            valid_from=_now(-20),
        )
        setup.commit()
    handler = FindResourceByIdentifierHandler(_uow_factory(SessionLocal))

    result = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_id,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value="reused.example.com",
        )
    )

    assert result.resource.id == resource_b.id
    assert result.identifier_id == current.id


def test_identifier_lookup_is_tenant_scoped(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        identifier_type_id = _identifier_type_id(setup)
        resource_a = _resource(setup, tenant_a, _slug("tenant-a-id"), created_at=_now(-5))
        resource_b = _resource(setup, tenant_b, _slug("tenant-b-id"), created_at=_now(-5))
        _identifier(
            setup,
            resource_a,
            identifier_type_id=identifier_type_id,
            normalized_value="shared.example.com",
            value_hash="hash-a",
        )
        _identifier(
            setup,
            resource_b,
            identifier_type_id=identifier_type_id,
            normalized_value="shared.example.com",
            value_hash="hash-b",
        )
        setup.commit()
    handler = FindResourceByIdentifierHandler(_uow_factory(SessionLocal))

    result_a = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_a,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value="shared.example.com",
        )
    )
    result_b = handler.handle(
        FindResourceByIdentifierQuery(
            tenant_id=tenant_b,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value="shared.example.com",
        )
    )

    assert result_a.resource.id == resource_a.id
    assert result_b.resource.id == resource_b.id


def test_alias_lookup_matches_exact_alias_key_and_value_boundary(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("alias"), created_at=_now(-5))
        alias = _alias(
            setup,
            resource,
            alias_type="dns_name",
            normalized_value="CaseSensitive-Key",
            alias_value="Example.COM",
        )
        _alias(
            setup,
            resource,
            alias_type="display_name",
            normalized_value="CaseSensitive-Key",
            alias_value="Example.COM",
        )
        setup.commit()
    handler = FindResourceByAliasHandler(_uow_factory(SessionLocal))

    result = handler.handle(
        FindResourceByAliasQuery(
            tenant_id=tenant_id,
            alias_type="dns_name",
            normalized_value="CaseSensitive-Key",
        )
    )

    assert result.resource.id == resource.id
    assert result.alias_id == alias.id
    assert result.alias_type == "dns_name"
    assert result.normalized_value == "CaseSensitive-Key"
    assert result.alias_value == "Example.COM"
    with pytest.raises(EntityNotFoundError):
        handler.handle(
            FindResourceByAliasQuery(
                tenant_id=tenant_id,
                alias_type="dns_name",
                normalized_value="Example.COM",
            )
        )


def test_alias_lookup_is_tenant_scoped(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        resource_a = _resource(setup, tenant_a, _slug("alias-a"), created_at=_now(-5))
        resource_b = _resource(setup, tenant_b, _slug("alias-b"), created_at=_now(-5))
        _alias(setup, resource_a, normalized_value="shared.example.com")
        _alias(setup, resource_b, normalized_value="shared.example.com")
        setup.commit()
    handler = FindResourceByAliasHandler(_uow_factory(SessionLocal))

    result_a = handler.handle(
        FindResourceByAliasQuery(
            tenant_id=tenant_a,
            alias_type="dns_name",
            normalized_value="shared.example.com",
        )
    )
    result_b = handler.handle(
        FindResourceByAliasQuery(
            tenant_id=tenant_b,
            alias_type="dns_name",
            normalized_value="shared.example.com",
        )
    )

    assert result_a.resource.id == resource_a.id
    assert result_b.resource.id == resource_b.id


def test_identity_lookup_returns_matched_resource_not_canonical_target(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        source = _resource(setup, tenant_id, _slug("merged-source"), created_at=_now(-5))
        target = _resource(setup, tenant_id, _slug("merged-target"), created_at=_now(-4))
        _alias(setup, source, normalized_value="merged.example.com")
        _merge(setup, source, target)
        setup.commit()
    alias_handler = FindResourceByAliasHandler(_uow_factory(SessionLocal))
    canonical_handler = ResolveCanonicalResourceHandler(_uow_factory(SessionLocal))

    alias_result = alias_handler.handle(
        FindResourceByAliasQuery(
            tenant_id=tenant_id,
            alias_type="dns_name",
            normalized_value="merged.example.com",
        )
    )
    canonical_result = canonical_handler.handle(
        ResolveCanonicalResourceQuery(tenant_id=tenant_id, resource_id=source.id)
    )

    assert alias_result.resource.id == source.id
    assert canonical_result.canonical_resource_id == target.id


def test_exact_identity_lookups_are_single_projection_queries_and_read_only(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("shape"), created_at=_now(-5))
        identifier = _identifier(setup, resource, normalized_value="shape.example.com")
        alias = _alias(setup, resource, normalized_value="shape.example.com")
        setup.commit()
    identifier_handler = FindResourceByIdentifierHandler(_uow_factory(SessionLocal))
    alias_handler = FindResourceByAliasHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as identifier_statements:
        identifier_result = identifier_handler.handle(
            FindResourceByIdentifierQuery(
                tenant_id=tenant_id,
                identifier_type_id=identifier.identifier_type_id,
                namespace=None,
                normalized_value="shape.example.com",
            )
        )
    with _capture_sql(migrated_engine) as alias_statements:
        alias_result = alias_handler.handle(
            FindResourceByAliasQuery(
                tenant_id=tenant_id,
                alias_type=alias.alias_type,
                normalized_value="shape.example.com",
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
    combined_sql = "\n".join(identifier_selects + alias_selects).upper()
    assert "RESOURCE_IDENTIFIER" in combined_sql
    assert "RESOURCE_ALIAS" in combined_sql
    assert "JOIN RESOURCE" in combined_sql
    assert "VALID_TO IS NULL" in combined_sql
    assert "OFFSET" not in combined_sql
    assert "ILIKE" not in combined_sql
    assert "LIKE" not in combined_sql
    assert "TO_TSVECTOR" not in combined_sql
    assert "TSQUERY" not in combined_sql
    assert identifier_result.resource.id == resource.id
    assert alias_result.resource.id == resource.id
    with SessionLocal() as verification:
        unchanged = verification.get(Resource, resource.id)
        assert unchanged is not None
        assert unchanged.record_version == resource.record_version
        assert unchanged.updated_at == resource.updated_at


def test_resource_details_returns_current_facts_with_fixed_projection_queries(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        other_tenant_id = _seed_tenant(setup, "other-tenant")
        resource = _resource(setup, tenant_id, _slug("details"), created_at=_now(-30))
        target = _resource(setup, tenant_id, _slug("target"), created_at=_now(-29))
        other_resource = _resource(
            setup,
            other_tenant_id,
            _slug("other-resource"),
            created_at=_now(-30),
        )
        organization = _organization(setup, tenant_id, _slug("owner"))
        custodian = _organization(setup, tenant_id, _slug("custodian"))
        other_organization = _organization(
            setup,
            other_tenant_id,
            _slug("other-owner"),
        )
        labels = [
            _label(setup, tenant_id, "env", "prod"),
            _label(setup, tenant_id, "team", "alpha"),
            _label(setup, tenant_id, "tier", "one"),
        ]
        historical_label = _label(setup, tenant_id, "old", "label")
        other_label = _label(setup, other_tenant_id, "env", "prod")
        classification_type_id = _classification_type_id(setup)
        production_id = _classification_value_id(setup, "production")
        staging_id = _classification_value_id(setup, "staging")
        identifier_type_id = _identifier_type_id(setup)
        historical_window = {"valid_from": _now(-40), "valid_to": _now(-20)}

        _state(setup, resource, **historical_window)
        current_state = _state(setup, resource, valid_from=_now(-10))
        _ownership(setup, resource, organization, **historical_window)
        owner = _ownership(setup, resource, organization, is_primary=True)
        _ownership(
            setup,
            resource,
            custodian,
            ownership_role_id=_custodian_role_id(setup),
            is_primary=True,
        )
        _label_assignment(setup, resource, historical_label, **historical_window)
        for label in labels:
            _label_assignment(setup, resource, label)
        _classification(
            setup,
            resource,
            classification_value_id=production_id,
            **historical_window,
        )
        current_primary_classification = _classification(
            setup,
            resource,
            classification_type_id=classification_type_id,
            classification_value_id=production_id,
            is_primary=True,
        )
        current_non_primary_classification = _classification(
            setup,
            resource,
            classification_type_id=classification_type_id,
            classification_value_id=staging_id,
            is_primary=False,
        )
        _identifier(
            setup,
            resource,
            normalized_value="old.example.com",
            original_value="OLD.EXAMPLE.COM",
            value_hash="hash-old.example.com",
            **historical_window,
        )
        _identifier(
            setup,
            resource,
            identifier_type_id=identifier_type_id,
            namespace=None,
            normalized_value="a.example.com",
            original_value="A.EXAMPLE.COM",
            value_hash="hash-a.example.com",
            is_primary=True,
        )
        _identifier(
            setup,
            resource,
            identifier_type_id=identifier_type_id,
            namespace="dns",
            normalized_value="b.example.com",
            original_value="B.EXAMPLE.COM",
            value_hash="hash-b.example.com",
        )
        _identifier(
            setup,
            resource,
            identifier_type_id=identifier_type_id,
            namespace="dns",
            normalized_value="c.example.com",
            original_value="C.EXAMPLE.COM",
            value_hash="hash-c.example.com",
        )
        _alias(
            setup,
            resource,
            alias_type="dns_name",
            normalized_value="b.example.com",
            alias_value="B.EXAMPLE.COM",
        )
        _alias(
            setup,
            resource,
            alias_type="dns_name",
            normalized_value="a.example.com",
            alias_value="A.EXAMPLE.COM",
        )
        _alias(
            setup,
            resource,
            alias_type="hostname",
            normalized_value="host.example.com",
            alias_value="HOST.EXAMPLE.COM",
        )
        _merge(setup, resource, target)

        _state(setup, other_resource)
        _ownership(setup, other_resource, other_organization)
        _label_assignment(setup, other_resource, other_label)
        _classification(setup, other_resource, classification_value_id=production_id)
        _identifier(
            setup,
            other_resource,
            normalized_value="a.example.com",
            value_hash="other-hash-a.example.com",
        )
        _alias(setup, other_resource, normalized_value="other.example.com")
        setup.commit()

    handler = GetResourceDetailsHandler(_uow_factory(SessionLocal))
    canonical_handler = ResolveCanonicalResourceHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        result = handler.handle(
            GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource.id)
        )

    selects = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 6
    sql = "\n".join(selects).upper()
    assert "RESOURCE_STATE" in sql
    assert "RESOURCE_OWNERSHIP" in sql
    assert "RESOURCE_LABEL" in sql
    assert "RESOURCE_CLASSIFICATION" in sql
    assert "RESOURCE_IDENTIFIER" in sql
    assert "RESOURCE_ALIAS" in sql
    assert "RESOURCE_MERGE" in sql
    assert sql.count("VALID_TO IS NULL") >= 5
    assert "OFFSET" not in sql
    assert "COUNT" not in sql
    assert "DISTINCT" not in sql
    assert "RESOURCE_LABEL" not in selects[0].upper()
    assert "RESOURCE_CLASSIFICATION" not in selects[0].upper()
    assert "RESOURCE_IDENTIFIER" not in selects[0].upper()
    assert "RESOURCE_ALIAS" not in selects[0].upper()

    assert result.id == resource.id
    assert result.organization_id == owner.organization_id
    assert result.state is not None
    assert result.state.id == current_state.id
    assert [item.label_id for item in result.labels] == [label.id for label in labels]
    assert [item.classification_value_id for item in result.classifications] == [
        production_id,
        staging_id,
    ]
    assert {
        item.id for item in result.classifications
    } == {
        current_primary_classification.id,
        current_non_primary_classification.id,
    }
    assert [item.normalized_value for item in result.identifiers] == [
        "a.example.com",
        "b.example.com",
        "c.example.com",
    ]
    assert [item.namespace for item in result.identifiers] == [None, "dns", "dns"]
    assert [item.normalized_value for item in result.aliases] == [
        "a.example.com",
        "b.example.com",
        "host.example.com",
    ]
    assert result.outgoing_merge is not None
    assert result.outgoing_merge.target_resource_id == target.id
    canonical = canonical_handler.handle(
        ResolveCanonicalResourceQuery(tenant_id=tenant_id, resource_id=resource.id)
    )
    assert canonical.canonical_resource_id == target.id
    assert result.id != canonical.canonical_resource_id
    assert len({item.id for item in result.labels}) == 3
    assert len({item.id for item in result.classifications}) == 2
    assert len({item.id for item in result.identifiers}) == 3
    assert len({item.id for item in result.aliases}) == 3
    assert result.canonical_name
    assert result.labels[0].label_id
    assert result.identifiers[0].normalized_value


def test_resource_details_accepts_resources_without_optional_facts(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        resource = _resource(setup, tenant_id, _slug("empty"), created_at=_now(-5))
        setup.commit()
    handler = GetResourceDetailsHandler(_uow_factory(SessionLocal))

    result = handler.handle(
        GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource.id)
    )

    assert result.id == resource.id
    assert result.organization_id is None
    assert result.state is None
    assert result.identifiers == ()
    assert result.ownership == ()
    assert result.classifications == ()
    assert result.labels == ()
    assert result.aliases == ()
    assert result.outgoing_merge is None


def test_resource_details_query_count_is_independent_of_collection_size(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        organization = _organization(setup, tenant_id, _slug("owner"))
        labels = [
            _label(setup, tenant_id, f"k{index}", f"v{index}")
            for index in range(10)
        ]
        resource = _resource(setup, tenant_id, _slug("dense"), created_at=_now(-5))
        _state(setup, resource)
        _ownership(setup, resource, organization)
        for index, label in enumerate(labels):
            _label_assignment(setup, resource, label)
            _identifier(
                setup,
                resource,
                namespace=f"ns-{index}",
                normalized_value=f"{index}.example.com",
                original_value=f"{index}.EXAMPLE.COM",
                value_hash=f"hash-{index}.example.com",
            )
            _alias(
                setup,
                resource,
                alias_type="dns_name",
                normalized_value=f"{index}.alias.example.com",
                alias_value=f"{index}.ALIAS.EXAMPLE.COM",
            )
        _classification(
            setup,
            resource,
            classification_value_id=_classification_value_id(setup, "production"),
            is_primary=True,
        )
        _classification(
            setup,
            resource,
            classification_value_id=_classification_value_id(setup, "staging"),
            is_primary=False,
        )
        setup.commit()
    handler = GetResourceDetailsHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        result = handler.handle(
            GetResourceDetailsQuery(tenant_id=tenant_id, resource_id=resource.id)
        )

    selects = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 6
    assert len(result.labels) == 10
    assert len(result.identifiers) == 10
    assert len(result.aliases) == 10
    assert len(result.classifications) == 2


def test_resource_details_wrong_tenant_matches_missing_resource(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_a = _seed_tenant(setup, "tenant-a")
        tenant_b = _seed_tenant(setup, "tenant-b")
        resource_b = _resource(setup, tenant_b, _slug("tenant-b"), created_at=_now(-5))
        setup.commit()
    handler = GetResourceDetailsHandler(_uow_factory(SessionLocal))

    with pytest.raises(EntityNotFoundError) as wrong_tenant:
        handler.handle(
            GetResourceDetailsQuery(tenant_id=tenant_a, resource_id=resource_b.id)
        )
    with pytest.raises(EntityNotFoundError) as missing:
        handler.handle(GetResourceDetailsQuery(tenant_id=tenant_a, resource_id=uuid4()))

    assert wrong_tenant.value.entity_type == missing.value.entity_type == "Resource"
    assert wrong_tenant.value.lookup_field == missing.value.lookup_field == "resource_id"
    assert wrong_tenant.value.lookup_value == resource_b.id


def test_empty_page_is_tuple_with_no_next_cursor(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    page = handler.handle(ListResourcesQuery(tenant_id=tenant_id))

    assert page.items == ()
    assert page.next_cursor is None


def test_list_query_is_single_projection_query_and_read_only(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        _seed_resources(setup, tenant_id, 3)
        before_count = setup.scalar(
            select(Resource).where(Resource.tenant_id == tenant_id)
        )
        assert before_count is not None
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))

    with _capture_sql(migrated_engine) as statements:
        page = handler.handle(ListResourcesQuery(tenant_id=tenant_id, page_size=2))

    select_statements = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(select_statements) == 1
    sql = select_statements[0].upper()
    assert "JOIN" in sql
    assert "RESOURCE_OWNERSHIP" in sql
    assert "VALID_TO IS NULL" in sql
    assert "IS_PRIMARY IS TRUE" in sql or "IS_PRIMARY = TRUE" in sql
    assert "ORDER BY" in sql
    assert "CREATED_AT" in sql
    assert "RESOURCE.ID" in sql or ".ID" in sql
    assert "LIMIT" in sql
    assert "OFFSET" not in sql
    assert "DISTINCT" not in sql
    assert "COUNT" not in sql
    assert page.next_cursor is not None
    with SessionLocal() as verification:
        assert len(
            list(
                verification.scalars(
                    select(Resource).where(Resource.tenant_id == tenant_id)
                )
            )
        ) == 3


def test_continuation_query_contains_keyset_predicate(migrated_engine: Engine) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id = _seed_tenant(setup)
        _seed_resources(setup, tenant_id, 4)
        setup.commit()
    handler = ListResourcesHandler(_uow_factory(SessionLocal))
    first_page = handler.handle(ListResourcesQuery(tenant_id=tenant_id, page_size=2))
    assert first_page.next_cursor is not None
    assert decode_resource_list_cursor(first_page.next_cursor) is not None

    with _capture_sql(migrated_engine) as statements:
        handler.handle(
            ListResourcesQuery(
                tenant_id=tenant_id,
                page_size=2,
                cursor=first_page.next_cursor,
            )
        )

    sql = "\n".join(statements).upper()
    assert "OFFSET" not in sql
    assert "CREATED_AT >" in sql
    assert "CREATED_AT =" in sql
    assert "ID >" in sql


def test_sqlalchemy_resource_query_service_is_protocol_compatible() -> None:
    assert hasattr(SQLAlchemyResourceQueryService, "list_resources")
