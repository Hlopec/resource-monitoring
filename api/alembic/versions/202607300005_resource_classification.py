"""resource classification

Revision ID: 202607300005
Revises: 202607300004
Create Date: 2026-07-31 00:06:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300005"
down_revision: str | None = "202607300004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_classification_value_classification_type_id_id",
        "classification_value",
        ["classification_type_id", "id"],
    )
    op.create_table(
        "resource_classification",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classification_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classification_value_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name=op.f("ck_resource_classification_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_resource_classification_valid_time_order"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR btrim(source) <> ''",
            name=op.f("ck_resource_classification_source_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_classification_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["classification_type_id"],
            ["classification_type.id"],
            name="fk_resource_classification_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["classification_type_id", "classification_value_id"],
            ["classification_value.classification_type_id", "classification_value.id"],
            name="fk_resource_classification_type_value",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_classification")),
    )
    op.create_index(
        "ix_resource_classification_tenant_resource_value",
        "resource_classification",
        ["tenant_id", "resource_id", "classification_value_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_classification_tenant_resource_type",
        "resource_classification",
        ["tenant_id", "resource_id", "classification_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_classification_tenant_value",
        "resource_classification",
        ["tenant_id", "classification_value_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_classification_tenant_type_value",
        "resource_classification",
        ["tenant_id", "classification_type_id", "classification_value_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_classification_tenant_valid_to",
        "resource_classification",
        ["tenant_id", "valid_to"],
        unique=False,
    )
    op.create_index(
        "uq_resource_classification_current_value",
        "resource_classification",
        ["tenant_id", "resource_id", "classification_value_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "uq_resource_classification_current_primary_type",
        "resource_classification",
        ["tenant_id", "resource_id", "classification_type_id"],
        unique=True,
        postgresql_where=sa.text("is_primary = true AND valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_resource_classification_current_primary_type",
        table_name="resource_classification",
    )
    op.drop_index(
        "uq_resource_classification_current_value",
        table_name="resource_classification",
    )
    op.drop_index(
        "ix_resource_classification_tenant_valid_to",
        table_name="resource_classification",
    )
    op.drop_index(
        "ix_resource_classification_tenant_type_value",
        table_name="resource_classification",
    )
    op.drop_index(
        "ix_resource_classification_tenant_value",
        table_name="resource_classification",
    )
    op.drop_index(
        "ix_resource_classification_tenant_resource_type",
        table_name="resource_classification",
    )
    op.drop_index(
        "ix_resource_classification_tenant_resource_value",
        table_name="resource_classification",
    )
    op.drop_table("resource_classification")
    op.drop_constraint(
        "uq_classification_value_classification_type_id_id",
        "classification_value",
        type_="unique",
    )
