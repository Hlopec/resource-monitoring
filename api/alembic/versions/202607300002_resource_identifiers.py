"""resource identifiers

Revision ID: 202607300002
Revises: 202607300001
Create Date: 2026-07-30 00:02:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300002"
down_revision: str | None = "202607300001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _managed_catalog_table(table_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("code <> ''", name=op.f(f"ck_{table_name}_code_not_empty")),
        sa.CheckConstraint(
            "code = lower(code)", name=op.f(f"ck_{table_name}_code_normalized")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table_name}")),
        sa.UniqueConstraint("code", name=op.f(f"uq_{table_name}_code")),
    )


def upgrade() -> None:
    _managed_catalog_table("lifecycle_status")
    _managed_catalog_table("criticality")
    _managed_catalog_table("exposure_level")

    op.create_table(
        "resource",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("lifecycle_status_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("criticality_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exposure_level_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "canonical_name <> ''", name=op.f("ck_resource_canonical_name_not_empty")
        ),
        sa.CheckConstraint(
            "display_name <> ''", name=op.f("ck_resource_display_name_not_empty")
        ),
        sa.CheckConstraint(
            "source_priority >= 0 AND source_priority <= 1000",
            name=op.f("ck_resource_source_priority_range"),
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name=op.f("ck_resource_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "record_version > 0", name=op.f("ck_resource_record_version_positive")
        ),
        sa.CheckConstraint(
            "first_seen_at <= last_seen_at", name=op.f("ck_resource_seen_at_order")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_resource_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_type_id"],
            ["resource_type.id"],
            name=op.f("fk_resource_resource_type_id_resource_type"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lifecycle_status_id"],
            ["lifecycle_status.id"],
            name=op.f("fk_resource_lifecycle_status_id_lifecycle_status"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["criticality_id"],
            ["criticality.id"],
            name=op.f("fk_resource_criticality_id_criticality"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exposure_level_id"],
            ["exposure_level.id"],
            name=op.f("fk_resource_exposure_level_id_exposure_level"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_resource_tenant_id_id"),
    )
    op.create_index(
        "ix_resource_tenant_id_resource_type_id",
        "resource",
        ["tenant_id", "resource_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_tenant_id_lifecycle_status_id",
        "resource",
        ["tenant_id", "lifecycle_status_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_tenant_id_criticality_id",
        "resource",
        ["tenant_id", "criticality_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_tenant_id_exposure_level_id",
        "resource",
        ["tenant_id", "exposure_level_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_tenant_id_canonical_name",
        "resource",
        ["tenant_id", "canonical_name"],
        unique=False,
    )
    op.create_index(
        "ix_resource_tenant_id_last_seen_at",
        "resource",
        ["tenant_id", "last_seen_at"],
        unique=False,
    )

    op.create_table(
        "resource_identifier",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identifier_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace", sa.String(), nullable=True),
        sa.Column("normalized_value", sa.String(), nullable=False),
        sa.Column("original_value", sa.String(), nullable=False),
        sa.Column("value_hash", sa.String(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "namespace IS NULL OR namespace <> ''",
            name=op.f("ck_resource_identifier_namespace_not_empty"),
        ),
        sa.CheckConstraint(
            "normalized_value <> ''",
            name=op.f("ck_resource_identifier_normalized_value_not_empty"),
        ),
        sa.CheckConstraint(
            "original_value <> ''",
            name=op.f("ck_resource_identifier_original_value_not_empty"),
        ),
        sa.CheckConstraint(
            "value_hash <> ''", name=op.f("ck_resource_identifier_value_hash_not_empty")
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name=op.f("ck_resource_identifier_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_resource_identifier_valid_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_identifier_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["identifier_type_id"],
            ["identifier_type.id"],
            name=op.f("fk_resource_identifier_identifier_type_id_identifier_type"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_identifier")),
    )
    op.create_index(
        "ix_resource_identifier_tenant_id_resource_id",
        "resource_identifier",
        ["tenant_id", "resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_res_ident_tenant_type_hash",
        "resource_identifier",
        ["tenant_id", "identifier_type_id", "value_hash"],
        unique=False,
    )
    op.create_index(
        "ix_res_ident_tenant_type_normalized",
        "resource_identifier",
        ["tenant_id", "identifier_type_id", "normalized_value"],
        unique=False,
    )
    op.create_index(
        "ix_resource_identifier_tenant_id_valid_to",
        "resource_identifier",
        ["tenant_id", "valid_to"],
        unique=False,
    )
    op.create_index(
        "uq_resource_identifier_current_value",
        "resource_identifier",
        [
            "tenant_id",
            "identifier_type_id",
            sa.text("COALESCE(namespace, '')"),
            "normalized_value",
        ],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "uq_resource_identifier_current_primary",
        "resource_identifier",
        ["resource_id", "identifier_type_id"],
        unique=True,
        postgresql_where=sa.text("is_primary = true AND valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_resource_identifier_current_primary", table_name="resource_identifier")
    op.drop_index("uq_resource_identifier_current_value", table_name="resource_identifier")
    op.drop_index("ix_resource_identifier_tenant_id_valid_to", table_name="resource_identifier")
    op.drop_index(
        "ix_res_ident_tenant_type_normalized",
        table_name="resource_identifier",
    )
    op.drop_index(
        "ix_res_ident_tenant_type_hash",
        table_name="resource_identifier",
    )
    op.drop_index("ix_resource_identifier_tenant_id_resource_id", table_name="resource_identifier")
    op.drop_table("resource_identifier")
    op.drop_index("ix_resource_tenant_id_last_seen_at", table_name="resource")
    op.drop_index("ix_resource_tenant_id_canonical_name", table_name="resource")
    op.drop_index("ix_resource_tenant_id_exposure_level_id", table_name="resource")
    op.drop_index("ix_resource_tenant_id_criticality_id", table_name="resource")
    op.drop_index("ix_resource_tenant_id_lifecycle_status_id", table_name="resource")
    op.drop_index("ix_resource_tenant_id_resource_type_id", table_name="resource")
    op.drop_table("resource")
    op.drop_table("exposure_level")
    op.drop_table("criticality")
    op.drop_table("lifecycle_status")
