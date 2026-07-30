from concurrent.futures import ThreadPoolExecutor
from datetime import UTC

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint

from app.db.base import Base
from app.db.settings import DatabaseSettings
from app.db.time import utc_now
from app.db.uuid import generate_uuid7
from app.models import Tenant


def test_database_settings_build_sqlalchemy_url() -> None:
    settings = DatabaseSettings(
        POSTGRES_HOST="db",
        POSTGRES_PORT=5433,
        POSTGRES_DB="resource_monitoring_test",
        POSTGRES_USER="resource_monitoring",
        POSTGRES_PASSWORD="secret value",
    )

    assert (
        settings.sqlalchemy_url
        == "postgresql+psycopg://resource_monitoring:secret+value@db:5433/resource_monitoring_test"
    )


def test_database_settings_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        DatabaseSettings(
            _env_file=None,
            POSTGRES_HOST="db",
            POSTGRES_PORT=5433,
            POSTGRES_DB="resource_monitoring_test",
            POSTGRES_USER="resource_monitoring",
        )


def test_uuid7_version_and_sort_order() -> None:
    values = [generate_uuid7() for _ in range(64)]

    assert {value.version for value in values} == {7}
    assert values == sorted(values)


def test_uuid7_generation_is_thread_safe() -> None:
    errors: list[Exception] = []

    def generate_batch() -> list[object]:
        try:
            return [generate_uuid7() for _ in range(500)]
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
            return []

    with ThreadPoolExecutor(max_workers=8) as executor:
        batches = list(executor.map(lambda _: generate_batch(), range(8)))

    values = [value for batch in batches for value in batch]

    assert errors == []
    assert len(values) == 4000
    assert len(set(values)) == len(values)
    assert {value.version for value in values} == {7}


def test_model_uuid7_is_available_before_flush() -> None:
    tenant = Tenant(slug="alpha", display_name="Alpha", status="active")

    assert tenant.id.version == 7


def test_utc_now_is_timezone_aware() -> None:
    value = utc_now()

    assert value.tzinfo is UTC


def test_metadata_naming_convention() -> None:
    convention = Base.metadata.naming_convention

    assert convention["pk"] == "pk_%(table_name)s"
    assert convention["fk"] == "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    assert convention["uq"] == "uq_%(table_name)s_%(column_0_name)s"
    assert convention["ck"] == "ck_%(table_name)s_%(constraint_name)s"
    assert convention["ix"] == "ix_%(table_name)s_%(column_0_name)s"


def test_constraint_names_are_deterministic() -> None:
    names = {constraint.name for constraint in Tenant.__table__.constraints}
    index_names = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    fk_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    pk_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, PrimaryKeyConstraint)
    }
    ck_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "uq_tenant_slug" in names
    assert "ix_organization_tenant_id_status" in index_names
    assert "fk_organization_tenant_id_tenant" in fk_names
    assert "pk_tenant" in pk_names
    assert "ck_tenant_slug_normalized" in ck_names
