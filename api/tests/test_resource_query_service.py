from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.handlers import ListResourcesHandler
from app.application.pagination import decode_resource_list_cursor
from app.application.queries import ListResourcesQuery
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
