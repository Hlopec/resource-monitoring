from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.db.settings import get_database_settings
from tests.conftest import list_user_tables

EXPECTED_TABLES = [
    "alembic_version",
    "classification_type",
    "classification_value",
    "identifier_type",
    "organization",
    "ownership_role",
    "relationship_type",
    "resource_type",
    "tenant",
]


def test_upgrade_empty_database_to_head(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        assert list_user_tables(engine) == EXPECTED_TABLES
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_downgrade_head_to_empty_database(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        assert list_user_tables(engine) == ["alembic_version"]
        with engine.connect() as connection:
            version_rows = connection.execute(
                text("SELECT count(*) FROM alembic_version")
            ).scalar_one()
        assert version_rows == 0
    finally:
        engine.dispose()
