from datetime import UTC, datetime
from decimal import Decimal

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.settings import get_database_settings
from app.db.seed.catalogs import seed_catalogs
from app.models import (
    Criticality,
    ExposureLevel,
    LifecycleStatus,
    Resource,
    ResourceType,
    Tenant,
)
from tests.conftest import list_user_tables

EXPECTED_TABLES = [
    "alembic_version",
    "classification_type",
    "classification_value",
    "criticality",
    "exposure_level",
    "identifier_type",
    "label",
    "lifecycle_status",
    "organization",
    "ownership_role",
    "relationship_type",
    "resource",
    "resource_alias",
    "resource_classification",
    "resource_identifier",
    "resource_label",
    "resource_merge",
    "resource_ownership",
    "resource_relationship",
    "resource_state",
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
    "label",
    "lifecycle_status",
    "organization",
    "ownership_role",
    "relationship_type",
    "resource",
    "resource_classification",
    "resource_identifier",
    "resource_label",
    "resource_ownership",
    "resource_relationship",
    "resource_state",
    "resource_type",
    "tenant",
]
RESOURCE_STATE_PREVIOUS_REVISION_TABLES = [
    table_name
    for table_name in PREVIOUS_REVISION_TABLES
    if table_name != "resource_state"
]
PREVIOUS_REVISION = "202607300007"
RESOURCE_STATE_PREVIOUS_REVISION = "202607300006"
LABEL_PREVIOUS_REVISION = "202607300005"
CLASSIFICATION_PREVIOUS_REVISION = "202607300004"


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
    command.downgrade(alembic_config, CLASSIFICATION_PREVIOUS_REVISION)
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


def test_label_constraints_and_indexes(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            constraints = dict(
                connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'label'::regclass"
                    )
                ).all()
            )
            index_defs = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, pg_get_indexdef(i.indexrelid) "
                        "FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE i.indrelid = 'label'::regclass"
                    )
                ).all()
            )

        assert constraints["pk_label"] == "PRIMARY KEY (id)"
        assert (
            constraints["fk_label_tenant_id_tenant"]
            == "FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE RESTRICT"
        )
        assert constraints["uq_label_tenant_id_id"] == "UNIQUE (tenant_id, id)"
        assert (
            constraints["uq_label_tenant_id_key_value"]
            == "UNIQUE (tenant_id, key, value)"
        )
        assert constraints["ck_label_key_not_empty"] == "CHECK ((btrim((key)::text) <> ''::text))"
        assert constraints["ck_label_key_lowercase"] == "CHECK (((key)::text = lower((key)::text)))"
        assert constraints["ck_label_key_trimmed"] == "CHECK (((key)::text = btrim((key)::text)))"
        assert (
            constraints["ck_label_value_not_empty"]
            == "CHECK ((btrim((value)::text) <> ''::text))"
        )
        assert (
            constraints["ck_label_value_trimmed"]
            == "CHECK (((value)::text = btrim((value)::text)))"
        )
        assert (
            constraints["ck_label_display_name_not_empty"]
            == "CHECK (((display_name IS NULL) OR "
            "(btrim((display_name)::text) <> ''::text)))"
        )
        assert (
            constraints["ck_label_description_not_empty"]
            == "CHECK (((description IS NULL) OR "
            "(btrim((description)::text) <> ''::text)))"
        )
        assert (
            constraints["ck_label_color_not_empty"]
            == "CHECK (((color IS NULL) OR (btrim((color)::text) <> ''::text)))"
        )
        assert (
            constraints["ck_label_color_hex_format"]
            == "CHECK (((color IS NULL) OR "
            "((color)::text ~ '^#[0-9A-Fa-f]{6}$'::text)))"
        )

        active_index = " ".join(index_defs["ix_label_tenant_id_is_active"].split())
        assert "CREATE INDEX ix_label_tenant_id_is_active" in active_index
        assert "(tenant_id, is_active)" in active_index
        assert "UNIQUE INDEX" not in active_index
        assert " WHERE " not in active_index
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_label_constraints_and_indexes(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            constraints = dict(
                connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'resource_label'::regclass"
                    )
                ).all()
            )
            index_defs = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, pg_get_indexdef(i.indexrelid) "
                        "FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE i.indrelid = 'resource_label'::regclass"
                    )
                ).all()
            )

        assert constraints["pk_resource_label"] == "PRIMARY KEY (id)"
        assert (
            constraints["fk_resource_label_resource_id_resource"]
            == "FOREIGN KEY (tenant_id, resource_id) "
            "REFERENCES resource(tenant_id, id) ON DELETE RESTRICT"
        )
        assert (
            constraints["fk_resource_label_label_id_label"]
            == "FOREIGN KEY (tenant_id, label_id) "
            "REFERENCES label(tenant_id, id) ON DELETE RESTRICT"
        )
        assert (
            constraints["ck_resource_label_valid_time_order"]
            == "CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))"
        )
        assert (
            constraints["ck_resource_label_source_not_empty"]
            == "CHECK (((source IS NULL) OR (btrim((source)::text) <> ''::text)))"
        )

        current = " ".join(index_defs["uq_resource_label_current"].split())
        assert "UNIQUE INDEX uq_resource_label_current" in current
        assert "(tenant_id, resource_id, label_id)" in current
        assert "WHERE (valid_to IS NULL)" in current

        expected_non_unique = {
            "ix_resource_label_tenant_resource_label": (
                "tenant_id",
                "resource_id",
                "label_id",
            ),
            "ix_resource_label_tenant_label_id": ("tenant_id", "label_id"),
            "ix_resource_label_tenant_valid_to": ("tenant_id", "valid_to"),
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


def test_resource_labels_adjacent_downgrade_removes_label_tables(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, LABEL_PREVIOUS_REVISION)
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            label_table = connection.execute(
                text("SELECT to_regclass('public.label')")
            ).scalar_one()
            resource_label_table = connection.execute(
                text("SELECT to_regclass('public.resource_label')")
            ).scalar_one()
        assert label_table is None
        assert resource_label_table is None
        assert "label" not in list_user_tables(engine)
        assert "resource_label" not in list_user_tables(engine)
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_state_constraints_and_indexes(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            constraints = dict(
                connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'resource_state'::regclass"
                    )
                ).all()
            )
            index_defs = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, pg_get_indexdef(i.indexrelid) "
                        "FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE i.indrelid = 'resource_state'::regclass"
                    )
                ).all()
            )

        assert constraints["pk_resource_state"] == "PRIMARY KEY (id)"
        assert (
            constraints["fk_resource_state_resource_id_resource"]
            == "FOREIGN KEY (tenant_id, resource_id) "
            "REFERENCES resource(tenant_id, id) ON DELETE RESTRICT"
        )
        assert (
            constraints["fk_resource_state_lifecycle_status"]
            == "FOREIGN KEY (lifecycle_status_id) "
            "REFERENCES lifecycle_status(id) ON DELETE RESTRICT"
        )
        assert (
            constraints["fk_resource_state_criticality"]
            == "FOREIGN KEY (criticality_id) "
            "REFERENCES criticality(id) ON DELETE RESTRICT"
        )
        assert (
            constraints["fk_resource_state_exposure_level"]
            == "FOREIGN KEY (exposure_level_id) "
            "REFERENCES exposure_level(id) ON DELETE RESTRICT"
        )
        assert (
            constraints["ck_resource_state_source_priority_non_negative"]
            == "CHECK ((source_priority >= 0))"
        )
        assert (
            constraints["ck_resource_state_confidence_score_range"]
            == "CHECK (((confidence_score >= 0.0000) AND "
            "(confidence_score <= 1.0000)))"
        )
        assert (
            constraints["ck_resource_state_valid_time_order"]
            == "CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))"
        )
        assert (
            constraints["ck_resource_state_source_not_empty"]
            == "CHECK (((source IS NULL) OR (btrim(source) <> ''::text)))"
        )

        current = " ".join(index_defs["uq_resource_state_current"].split())
        assert "UNIQUE INDEX uq_resource_state_current" in current
        assert "(tenant_id, resource_id)" in current
        assert "WHERE (valid_to IS NULL)" in current

        expected_non_unique = {
            "ix_resource_state_tenant_resource_valid_from": (
                "tenant_id",
                "resource_id",
                "valid_from",
            ),
            "ix_resource_state_tenant_lifecycle_status": (
                "tenant_id",
                "lifecycle_status_id",
            ),
            "ix_resource_state_tenant_criticality": ("tenant_id", "criticality_id"),
            "ix_resource_state_tenant_exposure_level": (
                "tenant_id",
                "exposure_level_id",
            ),
            "ix_resource_state_tenant_valid_to": ("tenant_id", "valid_to"),
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


def test_resource_state_adjacent_downgrade_removes_table(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, RESOURCE_STATE_PREVIOUS_REVISION)
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            resource_state_table = connection.execute(
                text("SELECT to_regclass('public.resource_state')")
            ).scalar_one()
        assert resource_state_table is None
        assert list_user_tables(engine) == RESOURCE_STATE_PREVIOUS_REVISION_TABLES
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_state_backfills_existing_resources(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, RESOURCE_STATE_PREVIOUS_REVISION)
    engine = create_engine(get_database_settings().sqlalchemy_url)
    tenant_id = None
    resource_id = None
    lifecycle_status_id = None
    criticality_id = None
    exposure_level_id = None
    first_seen_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    created_at = datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)
    try:
        with Session(engine) as session:
            seed_catalogs(session)
            tenant = Tenant(slug="tenant-a", display_name="Tenant A", status="active")
            session.add(tenant)
            session.flush()
            resource_type_id = session.scalar(
                text("SELECT id FROM resource_type WHERE code = 'domain'")
            )
            lifecycle_status_id = session.scalar(
                text("SELECT id FROM lifecycle_status WHERE code = 'active'")
            )
            criticality_id = session.scalar(
                text("SELECT id FROM criticality WHERE code = 'high'")
            )
            exposure_level_id = session.scalar(
                text("SELECT id FROM exposure_level WHERE code = 'public'")
            )
            assert resource_type_id is not None
            assert lifecycle_status_id is not None
            assert criticality_id is not None
            assert exposure_level_id is not None
            resource = Resource(
                tenant_id=tenant.id,
                resource_type_id=resource_type_id,
                canonical_name="backfill.example.com",
                display_name="backfill.example.com",
                lifecycle_status_id=lifecycle_status_id,
                criticality_id=criticality_id,
                exposure_level_id=exposure_level_id,
                source_priority=321,
                confidence_score=Decimal("0.8765"),
                first_seen_at=first_seen_at,
                last_seen_at=first_seen_at,
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(resource)
            session.commit()
            tenant_id = tenant.id
            resource_id = resource.id

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT tenant_id, resource_id, lifecycle_status_id, "
                    "criticality_id, exposure_level_id, source_priority, "
                    "confidence_score, valid_from, valid_to, source, created_at "
                    "FROM resource_state"
                )
            ).mappings().one()

        assert row["tenant_id"] == tenant_id
        assert row["resource_id"] == resource_id
        assert row["lifecycle_status_id"] == lifecycle_status_id
        assert row["criticality_id"] == criticality_id
        assert row["exposure_level_id"] == exposure_level_id
        assert row["source_priority"] == 321
        assert row["confidence_score"] == Decimal("0.8765")
        assert row["valid_from"] == first_seen_at
        assert row["valid_to"] is None
        assert row["source"] == "migration_backfill"
        assert row["created_at"] == created_at

        command.downgrade(alembic_config, RESOURCE_STATE_PREVIOUS_REVISION)
        with engine.connect() as connection:
            resource_row = connection.execute(
                text(
                    "SELECT lifecycle_status_id, criticality_id, exposure_level_id, "
                    "source_priority, confidence_score, first_seen_at, last_seen_at "
                    "FROM resource WHERE id = :resource_id"
                ),
                {"resource_id": resource_id},
            ).mappings().one()
            resource_state_table = connection.execute(
                text("SELECT to_regclass('public.resource_state')")
            ).scalar_one()
        assert resource_state_table is None
        assert resource_row["lifecycle_status_id"] == lifecycle_status_id
        assert resource_row["criticality_id"] == criticality_id
        assert resource_row["exposure_level_id"] == exposure_level_id
        assert resource_row["source_priority"] == 321
        assert resource_row["confidence_score"] == Decimal("0.8765")
        assert resource_row["first_seen_at"] == first_seen_at
        assert resource_row["last_seen_at"] == first_seen_at
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_alias_columns_constraints_and_indexes(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            columns = {
                row["column_name"]: row
                for row in connection.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'resource_alias'"
                    )
                ).mappings()
            }
            constraints = dict(
                connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'resource_alias'::regclass"
                    )
                ).all()
            )
            index_defs = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, pg_get_indexdef(i.indexrelid) "
                        "FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE i.indrelid = 'resource_alias'::regclass"
                    )
                ).all()
            )

        expected_columns = {
            "id": ("uuid", "NO"),
            "tenant_id": ("uuid", "NO"),
            "resource_id": ("uuid", "NO"),
            "alias_type": ("character varying", "NO"),
            "alias_value": ("character varying", "NO"),
            "normalized_value": ("character varying", "NO"),
            "source": ("text", "YES"),
            "first_seen_at": ("timestamp with time zone", "NO"),
            "last_seen_at": ("timestamp with time zone", "NO"),
            "created_at": ("timestamp with time zone", "NO"),
            "updated_at": ("timestamp with time zone", "NO"),
        }
        for column_name, (data_type, nullable) in expected_columns.items():
            assert columns[column_name]["data_type"] == data_type
            assert columns[column_name]["is_nullable"] == nullable

        assert constraints["pk_resource_alias"] == "PRIMARY KEY (id)"
        assert (
            constraints["fk_resource_alias_resource_id_resource"]
            == "FOREIGN KEY (tenant_id, resource_id) "
            "REFERENCES resource(tenant_id, id) ON DELETE RESTRICT"
        )
        assert (
            constraints["uq_resource_alias_tenant_alias_type_normalized_value"]
            == "UNIQUE (tenant_id, alias_type, normalized_value)"
        )
        assert (
            constraints["ck_resource_alias_alias_type_not_empty"]
            == "CHECK ((btrim((alias_type)::text) <> ''::text))"
        )
        assert (
            constraints["ck_resource_alias_alias_value_not_empty"]
            == "CHECK ((btrim((alias_value)::text) <> ''::text))"
        )
        assert (
            constraints["ck_resource_alias_normalized_value_not_empty"]
            == "CHECK ((btrim((normalized_value)::text) <> ''::text))"
        )
        assert (
            constraints["ck_resource_alias_source_not_empty"]
            == "CHECK (((source IS NULL) OR (btrim(source) <> ''::text)))"
        )
        assert (
            constraints["ck_resource_alias_seen_at_order"]
            == "CHECK ((last_seen_at >= first_seen_at))"
        )

        expected_non_unique = {
            "ix_resource_alias_tenant_resource_id": ("tenant_id", "resource_id"),
            "ix_resource_alias_tenant_alias_type": ("tenant_id", "alias_type"),
            "ix_resource_alias_tenant_last_seen_at": ("tenant_id", "last_seen_at"),
        }
        for index_name, columns_tuple in expected_non_unique.items():
            indexdef = " ".join(index_defs[index_name].split())
            assert f"CREATE INDEX {index_name}" in indexdef
            assert f"({', '.join(columns_tuple)})" in indexdef
            assert "UNIQUE INDEX" not in indexdef
            assert " WHERE " not in indexdef
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_merge_columns_constraints_indexes_and_trigger(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            columns = {
                row["column_name"]: row
                for row in connection.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'resource_merge'"
                    )
                ).mappings()
            }
            constraints = dict(
                connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'resource_merge'::regclass"
                    )
                ).all()
            )
            index_defs = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, pg_get_indexdef(i.indexrelid) "
                        "FROM pg_index i "
                        "JOIN pg_class c ON c.oid = i.indexrelid "
                        "WHERE i.indrelid = 'resource_merge'::regclass"
                    )
                ).all()
            )
            trigger_def = connection.execute(
                text(
                    "SELECT pg_get_triggerdef(oid) "
                    "FROM pg_trigger "
                    "WHERE tgrelid = 'resource_merge'::regclass "
                    "AND tgname = 'trg_resource_merge_prevent_cycle'"
                )
            ).scalar_one()
            function_exists = connection.execute(
                text(
                    "SELECT count(*) FROM pg_proc "
                    "WHERE proname = 'prevent_resource_merge_cycle'"
                )
            ).scalar_one()

        expected_columns = {
            "id": ("uuid", "NO"),
            "tenant_id": ("uuid", "NO"),
            "source_resource_id": ("uuid", "NO"),
            "target_resource_id": ("uuid", "NO"),
            "reason": ("text", "YES"),
            "source": ("text", "YES"),
            "merged_at": ("timestamp with time zone", "NO"),
            "created_at": ("timestamp with time zone", "NO"),
        }
        for column_name, (data_type, nullable) in expected_columns.items():
            assert columns[column_name]["data_type"] == data_type
            assert columns[column_name]["is_nullable"] == nullable

        assert constraints["pk_resource_merge"] == "PRIMARY KEY (id)"
        assert (
            constraints["fk_resource_merge_source_resource_id_resource"]
            == "FOREIGN KEY (tenant_id, source_resource_id) "
            "REFERENCES resource(tenant_id, id) ON DELETE RESTRICT"
        )
        assert (
            constraints["fk_resource_merge_target_resource_id_resource"]
            == "FOREIGN KEY (tenant_id, target_resource_id) "
            "REFERENCES resource(tenant_id, id) ON DELETE RESTRICT"
        )
        assert (
            constraints["uq_resource_merge_tenant_source_resource_id"]
            == "UNIQUE (tenant_id, source_resource_id)"
        )
        assert (
            constraints["ck_resource_merge_source_resource_not_target_resource"]
            == "CHECK ((source_resource_id <> target_resource_id))"
        )
        assert (
            constraints["ck_resource_merge_reason_not_empty"]
            == "CHECK (((reason IS NULL) OR (btrim(reason) <> ''::text)))"
        )
        assert (
            constraints["ck_resource_merge_source_not_empty"]
            == "CHECK (((source IS NULL) OR (btrim(source) <> ''::text)))"
        )

        target_history = " ".join(
            index_defs["ix_resource_merge_tenant_target_merged_at"].split()
        )
        assert "CREATE INDEX ix_resource_merge_tenant_target_merged_at" in target_history
        assert "(tenant_id, target_resource_id, merged_at)" in target_history
        assert "UNIQUE INDEX" not in target_history
        assert " WHERE " not in target_history

        merged_at = " ".join(index_defs["ix_resource_merge_tenant_merged_at"].split())
        assert "CREATE INDEX ix_resource_merge_tenant_merged_at" in merged_at
        assert "(tenant_id, merged_at)" in merged_at
        assert "UNIQUE INDEX" not in merged_at
        assert " WHERE " not in merged_at
        assert "ix_resource_merge_tenant_target_resource_id" not in index_defs

        normalized_trigger = " ".join(trigger_def.split())
        assert function_exists == 1
        assert "TRIGGER trg_resource_merge_prevent_cycle" in normalized_trigger
        assert (
            "BEFORE INSERT OR UPDATE OF tenant_id, "
            "source_resource_id, target_resource_id"
        ) in normalized_trigger
        assert "ON public.resource_merge" in normalized_trigger
        assert "EXECUTE FUNCTION prevent_resource_merge_cycle()" in normalized_trigger
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_resource_merge_alias_adjacent_downgrade_removes_tables_and_trigger(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_REVISION)
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        with engine.connect() as connection:
            resource_alias_table = connection.execute(
                text("SELECT to_regclass('public.resource_alias')")
            ).scalar_one()
            resource_merge_table = connection.execute(
                text("SELECT to_regclass('public.resource_merge')")
            ).scalar_one()
            trigger_count = connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname = 'trg_resource_merge_prevent_cycle'"
                )
            ).scalar_one()
            function_count = connection.execute(
                text(
                    "SELECT count(*) FROM pg_proc "
                    "WHERE proname = 'prevent_resource_merge_cycle'"
                )
            ).scalar_one()
        assert resource_alias_table is None
        assert resource_merge_table is None
        assert trigger_count == 0
        assert function_count == 0
        assert list_user_tables(engine) == PREVIOUS_REVISION_TABLES
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_upgrade_downgrade_upgrade_cycle_succeeds(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_REVISION)
    command.upgrade(alembic_config, "head")
    engine = create_engine(get_database_settings().sqlalchemy_url)
    try:
        assert list_user_tables(engine) == EXPECTED_TABLES
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


def test_alembic_check_has_no_pending_operations(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    try:
        command.check(alembic_config)
    finally:
        command.downgrade(alembic_config, "base")
