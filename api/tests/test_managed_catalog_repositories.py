from __future__ import annotations

import inspect
from collections.abc import Callable
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.ports.catalogs import (
    ClassificationValueRepository,
    ManagedCatalogRepository,
)
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    ClassificationType,
    ClassificationValue,
    Criticality,
    ExposureLevel,
    IdentifierType,
    LifecycleStatus,
    OwnershipRole,
    RelationshipType,
    ResourceType,
)
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork, UnitOfWorkNotActiveError
from app.persistence.sqlalchemy.repositories import (
    SQLAlchemyClassificationValueRepository,
    SQLAlchemyManagedCatalogRepository,
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


def _session_factory(engine: Engine) -> sessionmaker[TrackingSession]:
    return sessionmaker(
        bind=engine,
        class_=TrackingSession,
        expire_on_commit=False,
    )


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _accepts_managed_catalog_repository(
    repository: ManagedCatalogRepository[ResourceType],
) -> ManagedCatalogRepository[ResourceType]:
    return repository


def _accepts_classification_value_repository(
    repository: ClassificationValueRepository,
) -> ClassificationValueRepository:
    return repository


def _resource_type(code: str, *, is_active: bool = True) -> ResourceType:
    return ResourceType(
        code=code,
        display_name=code.title(),
        category="test",
        schema_version=1,
        is_active=is_active,
    )


def _identifier_type(code: str, *, is_active: bool = True) -> IdentifierType:
    return IdentifierType(
        code=code,
        display_name=code.title(),
        normalization_strategy="lowercase",
        uniqueness_scope="tenant",
        is_case_sensitive=False,
        is_active=is_active,
    )


def _relationship_type(code: str, *, is_active: bool = True) -> RelationshipType:
    return RelationshipType(
        code=code,
        display_name=code.title(),
        is_directional=True,
        is_transitive=False,
        is_active=is_active,
    )


def _ownership_role(code: str, *, is_active: bool = True) -> OwnershipRole:
    return OwnershipRole(
        code=code,
        display_name=code.title(),
        is_active=is_active,
    )


def _classification_type(code: str, *, is_active: bool = True) -> ClassificationType:
    return ClassificationType(
        code=code,
        display_name=code.title(),
        is_active=is_active,
    )


def _lifecycle_status(code: str, *, is_active: bool = True) -> LifecycleStatus:
    return LifecycleStatus(
        code=code,
        display_name=code.title(),
        is_active=is_active,
    )


def _criticality(code: str, *, is_active: bool = True) -> Criticality:
    return Criticality(
        code=code,
        display_name=code.title(),
        is_active=is_active,
    )


def _exposure_level(code: str, *, is_active: bool = True) -> ExposureLevel:
    return ExposureLevel(
        code=code,
        display_name=code.title(),
        is_active=is_active,
    )


ManagedCatalogModel = (
    type[ResourceType]
    | type[IdentifierType]
    | type[RelationshipType]
    | type[OwnershipRole]
    | type[ClassificationType]
    | type[LifecycleStatus]
    | type[Criticality]
    | type[ExposureLevel]
)
ManagedCatalogFactory = Callable[
    [str],
    (
        ResourceType
        | IdentifierType
        | RelationshipType
        | OwnershipRole
        | ClassificationType
        | LifecycleStatus
        | Criticality
        | ExposureLevel
    ),
]


MANAGED_CATALOG_CASES: tuple[
    tuple[str, ManagedCatalogModel, str, str, ManagedCatalogFactory],
    ...,
] = (
    ("resource_types", ResourceType, "domain", "rt", _resource_type),
    ("identifier_types", IdentifierType, "fqdn", "it", _identifier_type),
    ("relationship_types", RelationshipType, "depends_on", "rel", _relationship_type),
    ("ownership_roles", OwnershipRole, "owner", "own", _ownership_role),
    ("classification_types", ClassificationType, "environment", "ct", _classification_type),
    ("lifecycle_statuses", LifecycleStatus, "active", "ls", _lifecycle_status),
    ("criticalities", Criticality, "medium", "crit", _criticality),
    ("exposure_levels", ExposureLevel, "public", "exp", _exposure_level),
)

CATALOG_PROPERTY_NAMES = tuple(name for name, *_ in MANAGED_CATALOG_CASES) + (
    "classification_values",
)

FORBIDDEN_READ_ONLY_METHODS = {
    "add",
    "delete",
    "remove",
    "update",
    "create",
    "save",
    "flush",
    "commit",
    "rollback",
    "filter",
    "query",
    "execute",
}


@pytest.mark.parametrize(
    ("_property_name", "model_type", "seed_code", "prefix", "factory"),
    MANAGED_CATALOG_CASES,
)
def test_managed_catalog_repository_contract_and_seeded_lookups(
    db_session: Session,
    _property_name: str,
    model_type: ManagedCatalogModel,
    seed_code: str,
    prefix: str,
    factory: ManagedCatalogFactory,
) -> None:
    seed_catalogs(db_session)
    db_session.flush()
    repository = SQLAlchemyManagedCatalogRepository(db_session, model_type)

    seeded = db_session.scalar(select(model_type).where(model_type.code == seed_code))
    assert seeded is not None
    assert repository.session is db_session
    if model_type is ResourceType:
        assert _accepts_managed_catalog_repository(repository) is repository

    assert repository.get_by_id(seeded.id) is seeded
    assert repository.get_by_code(seed_code) is seeded
    assert repository.get_by_id(uuid4()) is None
    assert repository.get_by_code(f"missing-{prefix}") is None

    active_code = _code(f"{prefix}-active")
    inactive_code = _code(f"{prefix}-inactive")
    active = factory(active_code)
    inactive = factory(inactive_code)
    inactive.is_active = False
    db_session.add_all([active, inactive])
    db_session.flush()

    rows = repository.list_active()
    codes = [row.code for row in rows]
    assert active_code in codes
    assert inactive_code not in codes
    assert codes == sorted(codes)
    assert not _catalog_methods(repository) & FORBIDDEN_READ_ONLY_METHODS


def test_managed_catalog_repository_rejects_models_without_required_shape(
    db_session: Session,
) -> None:
    with pytest.raises(TypeError, match="required mapped attribute"):
        SQLAlchemyManagedCatalogRepository(db_session, object)


def test_unit_of_work_catalog_properties_use_seeded_global_catalogs(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SessionLocal() as setup_session:
        seed_catalogs(setup_session)
        setup_session.commit()

    with SQLAlchemyUnitOfWork(SessionLocal) as uow:
        for property_name, _model_type, seed_code, _prefix, _factory in (
            MANAGED_CATALOG_CASES
        ):
            repository = getattr(uow, property_name)
            assert repository.get_by_code(seed_code) is not None
            assert repository.session is uow.session
            assert repository.session is uow.tenants.session
            assert repository.session is uow.organizations.session
            assert repository.session is uow.resources.session

        environment = uow.classification_types.get_by_code("environment")
        assert environment is not None
        production = uow.classification_values.get_by_type_and_code(
            environment.id,
            "production",
        )
        assert production is not None
        assert uow.classification_values.session is uow.session


def test_classification_value_repository_uses_type_scope_and_active_listing(
    db_session: Session,
) -> None:
    seed_catalogs(db_session)
    db_session.flush()
    repository = SQLAlchemyClassificationValueRepository(db_session)

    environment = db_session.scalar(
        select(ClassificationType).where(ClassificationType.code == "environment")
    )
    assert environment is not None
    production = db_session.scalar(
        select(ClassificationValue).where(
            ClassificationValue.classification_type_id == environment.id,
            ClassificationValue.code == "production",
        )
    )
    assert production is not None

    other_type = _classification_type(_code("other-type"))
    only_other_value = ClassificationValue(
        classification_type=other_type,
        code=_code("shared"),
        display_name="Other Only",
    )
    inactive_value = ClassificationValue(
        classification_type=environment,
        code=_code("inactive-value"),
        display_name="Inactive",
        is_active=False,
    )
    db_session.add_all([other_type, only_other_value, inactive_value])
    db_session.flush()

    assert _accepts_classification_value_repository(repository) is repository
    assert repository.session is db_session
    assert repository.get_by_id(production.id) is production
    assert repository.get_by_id(uuid4()) is None
    assert (
        repository.get_by_type_and_code(environment.id, only_other_value.code) is None
    )
    assert repository.get_by_type_and_code(environment.id, production.code) is production
    assert repository.get_by_type_and_code(uuid4(), production.code) is None

    rows = repository.list_active_for_type(environment.id)
    codes = [row.code for row in rows]
    assert "production" in codes
    assert inactive_value.code not in codes
    assert only_other_value.code not in codes
    assert codes == sorted(codes)
    assert not _catalog_methods(repository) & FORBIDDEN_READ_ONLY_METHODS


@pytest.mark.parametrize("property_name", CATALOG_PROPERTY_NAMES)
def test_catalog_repositories_follow_unit_of_work_lifecycle(
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


def test_catalog_repositories_are_distinct_per_unit_of_work(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)

    with SQLAlchemyUnitOfWork(SessionLocal) as first:
        with SQLAlchemyUnitOfWork(SessionLocal) as second:
            assert first.resource_types is not second.resource_types
            assert first.classification_values is not second.classification_values
            assert first.resource_types.session is not second.resource_types.session

        assert first.resource_types.get_by_code("domain") is None


def test_closing_one_unit_of_work_does_not_close_another_catalog_session(
    migrated_engine: Engine,
) -> None:
    SessionLocal = _session_factory(migrated_engine)
    first = SQLAlchemyUnitOfWork(SessionLocal)
    second = SQLAlchemyUnitOfWork(SessionLocal)
    first.__enter__()
    second.__enter__()
    try:
        second_session = second.resource_types.session
        first.__exit__(None, None, None)

        assert second_session.closes == 0
        assert second.resource_types.session is second_session
    finally:
        second.__exit__(None, None, None)


def _catalog_methods(repository: object) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(repository, inspect.ismethod)
        if not name.startswith("_")
    }
