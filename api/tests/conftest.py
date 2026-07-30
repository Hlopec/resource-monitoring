from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from urllib.parse import quote_plus

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.settings import get_database_settings


def _maintenance_url() -> str:
    user = quote_plus(os.environ.get("POSTGRES_USER", "resource_monitoring"))
    password = quote_plus(os.environ.get("POSTGRES_PASSWORD", "local-development-only"))
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/postgres"


@pytest.fixture(scope="session", autouse=True)
def isolated_database() -> Generator[None, None, None]:
    database_name = os.environ.get("POSTGRES_DB", "resource_monitoring_test")
    assert database_name.endswith("_test")

    with psycopg.connect(_maintenance_url(), autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (database_name,),
        )
        connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        connection.execute(f'CREATE DATABASE "{database_name}"')

    get_database_settings.cache_clear()
    yield

    with psycopg.connect(_maintenance_url(), autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (database_name,),
        )
        connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


@pytest.fixture()
def alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


@pytest.fixture()
def migrated_engine(alembic_config: Config) -> Generator[Engine, None, None]:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


@pytest.fixture()
def db_session(migrated_engine: Engine) -> Generator[Session, None, None]:
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with SessionLocal() as session:
        yield session
        session.rollback()


def list_user_tables(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
            ).scalars()
        )
