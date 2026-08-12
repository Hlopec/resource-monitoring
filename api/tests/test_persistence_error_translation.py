from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.application.errors import ConcurrentModificationError, ConflictError
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Resource,
    ResourceAlias,
    ResourceState,
    ResourceType,
    Tenant,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork
from app.persistence.sqlalchemy.errors import (
    CONSTRAINT_TRANSLATORS,
    UNIQUE_VIOLATION,
    translate_sqlalchemy_error,
)


def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _catalog_id(session: Session, model_type: type[object], code: str) -> UUID:
    entity_id = session.scalar(select(model_type.id).where(model_type.code == code))
    assert entity_id is not None
    return entity_id


def _seed_resource(session: Session, canonical_name: str | None = None) -> tuple[UUID, UUID]:
    seed_catalogs(session)
    session.flush()
    tenant = Tenant(slug=_slug("tenant"), display_name="Tenant", status="active")
    session.add(tenant)
    session.flush()
    resource = _resource(session, tenant.id, canonical_name or _slug("resource"))
    session.add(resource)
    session.flush()
    return tenant.id, resource.id


def _resource(session: Session, tenant_id: UUID, canonical_name: str) -> Resource:
    now = datetime.now(UTC)
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


def _state(session: Session, tenant_id: UUID, resource_id: UUID) -> ResourceState:
    return ResourceState(
        tenant_id=tenant_id,
        resource_id=resource_id,
        lifecycle_status_id=_catalog_id(session, LifecycleStatus, "active"),
        criticality_id=_catalog_id(session, Criticality, "medium"),
        exposure_level_id=_catalog_id(session, ExposureLevel, "public"),
        source_priority=100,
        confidence_score=Decimal("0.9000"),
        valid_from=datetime.now(UTC),
        source="test",
    )


def _alias(
    tenant_id: UUID,
    resource_id: UUID,
    *,
    alias_type: str = "dns_name",
    normalized_value: str = "example.com",
) -> ResourceAlias:
    now = datetime.now(UTC)
    return ResourceAlias(
        tenant_id=tenant_id,
        resource_id=resource_id,
        alias_type=alias_type,
        alias_value=normalized_value,
        normalized_value=normalized_value,
        first_seen_at=now,
        last_seen_at=now,
        source="test",
    )


def _tenant(slug: str) -> Tenant:
    return Tenant(slug=slug, display_name=slug.title(), status="active")


def test_translator_exports_explicit_constraint_mapping() -> None:
    assert UNIQUE_VIOLATION == "23505"
    assert "uq_resource_state_current" in CONSTRAINT_TRANSLATORS
    assert "uq_resource_alias_tenant_alias_type_normalized_value" in CONSTRAINT_TRANSLATORS


def test_resource_state_current_conflict_translates_and_rolls_back(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id, resource_id = _seed_resource(setup)
        setup.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            first = _state(uow.session, tenant_id, resource_id)
            second = _state(uow.session, tenant_id, resource_id)
            uow.resource_states.add(first)
            uow.resource_states.add(second)
            uow.commit()

    error = exc_info.value
    assert str(error) == "Resource state conflicts with an existing current state"
    assert error.entity_type == "ResourceState"
    assert error.conflict_field == "current"
    assert error.conflict_value is None
    assert error.constraint == "uq_resource_state_current"
    assert isinstance(error.__cause__, IntegrityError)

    with SessionLocal() as verification:
        states = list(
            verification.scalars(
                select(ResourceState).where(
                    ResourceState.tenant_id == tenant_id,
                    ResourceState.resource_id == resource_id,
                )
            )
        )
        assert states == []

    with SQLAlchemyUnitOfWork(SessionLocal) as fresh:
        fresh.resource_states.add(_state(fresh.session, tenant_id, resource_id))
        fresh.commit()


def test_resource_alias_unique_conflict_translates_and_preserves_cause(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id, first_resource_id = _seed_resource(setup, _slug("first"))
        second = _resource(setup, tenant_id, _slug("second"))
        setup.add(second)
        setup.flush()
        second_resource_id = second.id
        setup.commit()

    with pytest.raises(ConflictError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            uow.resource_aliases.add(_alias(tenant_id, first_resource_id))
            uow.resource_aliases.add(_alias(tenant_id, second_resource_id))
            uow.commit()

    error = exc_info.value
    assert str(error) == "Resource alias already resolves to a resource"
    assert error.entity_type == "ResourceAlias"
    assert error.conflict_field == "alias"
    assert error.constraint == "uq_resource_alias_tenant_alias_type_normalized_value"
    assert isinstance(error.__cause__, IntegrityError)

    with SessionLocal() as verification:
        aliases = list(
            verification.scalars(
                select(ResourceAlias).where(ResourceAlias.tenant_id == tenant_id)
            )
        )
        assert aliases == []

    with SQLAlchemyUnitOfWork(SessionLocal) as fresh:
        fresh.resource_aliases.add(_alias(tenant_id, first_resource_id))
        fresh.commit()


def test_resource_optimistic_concurrency_translates_stale_data_error(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    with SessionLocal() as setup:
        tenant_id, resource_id = _seed_resource(setup)
        setup.commit()

    first = SQLAlchemyUnitOfWork(SessionLocal)
    second = SQLAlchemyUnitOfWork(SessionLocal)
    with first:
        with second:
            first_resource = first.resources.get_by_id(tenant_id, resource_id)
            second_resource = second.resources.get_by_id(tenant_id, resource_id)
            assert first_resource is not None
            assert second_resource is not None

            first_resource.display_name = "Updated first"
            first.commit()

            second_resource.display_name = "Updated second"
            with pytest.raises(ConcurrentModificationError) as exc_info:
                second.commit()

    error = exc_info.value
    assert str(error) == "Resource was modified concurrently"
    assert error.entity_type == "Resource"
    assert error.conflict_field == "record_version"
    assert error.constraint is None
    assert isinstance(error.__cause__, StaleDataError)

    with SQLAlchemyUnitOfWork(SessionLocal) as fresh:
        resource = fresh.resources.get_by_id(tenant_id, resource_id)
        assert resource is not None
        resource.display_name = "Updated fresh"
        fresh.commit()


def test_unmapped_integrity_error_propagates_original_exception(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    slug = _slug("duplicate-tenant")
    with SessionLocal() as setup:
        setup.add(_tenant(slug))
        setup.commit()

    with pytest.raises(IntegrityError) as exc_info:
        with SQLAlchemyUnitOfWork(SessionLocal) as uow:
            uow.tenants.add(_tenant(slug))
            uow.commit()

    assert translate_sqlalchemy_error(exc_info.value) is exc_info.value
    assert not isinstance(exc_info.value, ConflictError)

    replacement_slug = _slug("fresh-tenant")
    with SQLAlchemyUnitOfWork(SessionLocal) as fresh:
        fresh.tenants.add(_tenant(replacement_slug))
        fresh.commit()

    with SessionLocal() as verification:
        assert (
            verification.scalar(select(Tenant).where(Tenant.slug == replacement_slug))
            is not None
        )
