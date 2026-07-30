from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.db.settings import get_database_settings
from tests.conftest import list_user_tables

EXPECTED_TABLES = [
    "alembic_version",
    "classification_type",
    "classification_value",
    "criticality",
    "exposure_level",
    "identifier_type",
    "lifecycle_status",
    "organization",
    "ownership_role",
    "relationship_type",
    "resource",
    "resource_classification",
    "resource_identifier",
    "resource_ownership",
    "resource_relationship",
    "resource_type",
    "tenant",
]
PREVIOUS_REVISION_TABLES = [
    "alembic_version",
    "classification_type",
    "classification_value",
    "criticality",
    "exposure_level",
    "identifier_type",
    "lifecycle_status",
    "organization",
    "ownership_role",
    "relationship_type",
    "resource",
    "resource_identifier",
    "resource_ownership",
    "resource_relationship",
    "resource_type",
    "tenant",
]
PREVIOUS_REVISION = "202607300004"


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


def test_upgrade_previous_revision_to_new_head(alembic_config: Config) -> None:
    command.upgrade(alembic_config, PREVIOUS_REVISION)
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        assert list_user_tables(engine) == EXPECTED_TABLES
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_downgrade_new_head_to_previous_revision(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_REVISION)
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        assert list_user_tables(engine) == PREVIOUS_REVISION_TABLES
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_current_primary_identifier_index_is_tenant_first(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            indexdef = connection.execute(
                text(
                    "SELECT pg_get_indexdef(indexrelid) "
                    "FROM pg_index "
                    "WHERE indexrelid = "
                    "'uq_resource_identifier_current_primary'::regclass"
                )
            ).scalar_one()

        normalized = " ".join(indexdef.split())
        assert "UNIQUE INDEX uq_resource_identifier_current_primary" in normalized
        assert "(tenant_id, resource_id, identifier_type_id)" in normalized
        assert "WHERE ((is_primary = true) AND (valid_to IS NULL))" in normalized
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_ownership_indexes_are_tenant_first(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            current_index = connection.execute(
                text(
                    "SELECT pg_get_indexdef(indexrelid) "
                    "FROM pg_index "
                    "WHERE indexrelid = 'uq_resource_ownership_current'::regclass"
                )
            ).scalar_one()
            primary_index = connection.execute(
                text(
                    "SELECT pg_get_indexdef(indexrelid) "
                    "FROM pg_index "
                    "WHERE indexrelid = "
                    "'uq_resource_ownership_current_primary'::regclass"
                )
            ).scalar_one()
            access_index = connection.execute(
                text(
                    "SELECT pg_get_indexdef(indexrelid) "
                    "FROM pg_index "
                    "WHERE indexrelid = "
                    "'ix_resource_ownership_tenant_resource_role'::regclass"
                )
            ).scalar_one()

        current_normalized = " ".join(current_index.split())
        primary_normalized = " ".join(primary_index.split())
        access_normalized = " ".join(access_index.split())
        assert "UNIQUE INDEX uq_resource_ownership_current" in current_normalized
        assert (
            "(tenant_id, resource_id, organization_id, ownership_role_id)"
            in current_normalized
        )
        assert "WHERE (valid_to IS NULL)" in current_normalized
        assert (
            "UNIQUE INDEX uq_resource_ownership_current_primary"
            in primary_normalized
        )
        assert "(tenant_id, resource_id, ownership_role_id)" in primary_normalized
        assert "WHERE ((is_primary = true) AND (valid_to IS NULL))" in primary_normalized
        assert (
            "CREATE INDEX ix_resource_ownership_tenant_resource_role"
            in access_normalized
        )
        assert "(tenant_id, resource_id, ownership_role_id)" in access_normalized
        assert "UNIQUE INDEX" not in access_normalized
        assert " WHERE " not in access_normalized
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_relationship_indexes_are_tenant_first(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            index_defs = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, pg_get_indexdef(i.indexrelid) "
                        "FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE i.indrelid = 'resource_relationship'::regclass"
                    )
                ).all()
            )

        current = " ".join(index_defs["uq_resource_relationship_current"].split())
        assert "UNIQUE INDEX uq_resource_relationship_current" in current
        assert (
            "(tenant_id, source_resource_id, target_resource_id, relationship_type_id)"
            in current
        )
        assert "WHERE (valid_to IS NULL)" in current

        expected_non_unique = {
            "ix_resource_relationship_tenant_id_source_resource_id": (
                "tenant_id",
                "source_resource_id",
            ),
            "ix_resource_relationship_tenant_id_target_resource_id": (
                "tenant_id",
                "target_resource_id",
            ),
            "ix_resource_relationship_tenant_id_relationship_type_id": (
                "tenant_id",
                "relationship_type_id",
            ),
            "ix_resource_relationship_tenant_source_type": (
                "tenant_id",
                "source_resource_id",
                "relationship_type_id",
            ),
            "ix_resource_relationship_tenant_target_type": (
                "tenant_id",
                "target_resource_id",
                "relationship_type_id",
            ),
            "ix_resource_relationship_tenant_id_valid_to": ("tenant_id", "valid_to"),
        }
        for index_name, columns in expected_non_unique.items():
            indexdef = " ".join(index_defs[index_name].split())
            assert f"CREATE INDEX {index_name}" in indexdef
            assert f"({', '.join(columns)})" in indexdef
            assert "UNIQUE INDEX" not in indexdef
            assert " WHERE " not in indexdef
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_classification_constraints_and_indexes(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            constraints = dict(
                connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'resource_classification'::regclass"
                    )
                ).all()
            )
            catalog_constraints = dict(
                connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'classification_value'::regclass"
                    )
                ).all()
            )
            index_defs = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, pg_get_indexdef(i.indexrelid) "
                        "FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE i.indrelid = 'resource_classification'::regclass"
                    )
                ).all()
            )

        assert constraints["pk_resource_classification"] == "PRIMARY KEY (id)"
        assert (
            constraints["fk_resource_classification_resource_id_resource"]
            == "FOREIGN KEY (tenant_id, resource_id) "
            "REFERENCES resource(tenant_id, id) ON DELETE RESTRICT"
        )
        assert (
            constraints["fk_resource_classification_type"]
            == "FOREIGN KEY (classification_type_id) "
            "REFERENCES classification_type(id) ON DELETE RESTRICT"
        )
        assert (
            constraints["fk_resource_classification_type_value"]
            == "FOREIGN KEY (classification_type_id, classification_value_id) "
            "REFERENCES classification_value(classification_type_id, id) "
            "ON DELETE RESTRICT"
        )
        assert (
            constraints["ck_resource_classification_confidence_score_range"]
            == "CHECK (((confidence_score >= 0.0000) AND "
            "(confidence_score <= 1.0000)))"
        )
        assert (
            constraints["ck_resource_classification_valid_time_order"]
            == "CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))"
        )
        assert (
            constraints["ck_resource_classification_source_not_empty"]
            == "CHECK (((source IS NULL) OR (btrim((source)::text) <> ''::text)))"
        )
        assert (
            catalog_constraints["uq_classification_value_classification_type_id_id"]
            == "UNIQUE (classification_type_id, id)"
        )

        current_value = " ".join(
            index_defs["uq_resource_classification_current_value"].split()
        )
        assert "UNIQUE INDEX uq_resource_classification_current_value" in current_value
        assert "(tenant_id, resource_id, classification_value_id)" in current_value
        assert "WHERE (valid_to IS NULL)" in current_value

        current_primary = " ".join(
            index_defs["uq_resource_classification_current_primary_type"].split()
        )
        assert (
            "UNIQUE INDEX uq_resource_classification_current_primary_type"
            in current_primary
        )
        assert "(tenant_id, resource_id, classification_type_id)" in current_primary
        assert "WHERE ((is_primary = true) AND (valid_to IS NULL))" in current_primary

        expected_non_unique = {
            "ix_resource_classification_tenant_resource_value": (
                "tenant_id",
                "resource_id",
                "classification_value_id",
            ),
            "ix_resource_classification_tenant_resource_type": (
                "tenant_id",
                "resource_id",
                "classification_type_id",
            ),
            "ix_resource_classification_tenant_value": (
                "tenant_id",
                "classification_value_id",
            ),
            "ix_resource_classification_tenant_type_value": (
                "tenant_id",
                "classification_type_id",
                "classification_value_id",
            ),
            "ix_resource_classification_tenant_valid_to": ("tenant_id", "valid_to"),
        }
        for index_name, columns in expected_non_unique.items():
            indexdef = " ".join(index_defs[index_name].split())
            assert f"CREATE INDEX {index_name}" in indexdef
            assert f"({', '.join(columns)})" in indexdef
            assert "UNIQUE INDEX" not in indexdef
            assert " WHERE " not in indexdef
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_classification_adjacent_downgrade_removes_supporting_constraint(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_REVISION)
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            resource_classification_table = connection.execute(
                text("SELECT to_regclass('public.resource_classification')")
            ).scalar_one()
            supporting_constraint = connection.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = "
                    "'uq_classification_value_classification_type_id_id'"
                )
            ).scalar_one()
        assert resource_classification_table is None
        assert supporting_constraint == 0
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
