"""resource relationship

Revision ID: 202607300004
Revises: 202607300003
Create Date: 2026-07-31 00:05:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300004"
down_revision: str | None = "202607300003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_relationship",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "source_resource_id <> target_resource_id",
            name=op.f("ck_resource_relationship_source_resource_not_target_resource"),
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name=op.f("ck_resource_relationship_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_resource_relationship_valid_time_order"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR btrim(source) <> ''",
            name=op.f("ck_resource_relationship_source_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_relationship_source_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_relationship_target_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_type_id"],
            ["relationship_type.id"],
            name=op.f("fk_resource_relationship_relationship_type_id_relationship_type"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_relationship")),
    )
    op.create_index(
        "ix_resource_relationship_tenant_id_source_resource_id",
        "resource_relationship",
        ["tenant_id", "source_resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_relationship_tenant_id_target_resource_id",
        "resource_relationship",
        ["tenant_id", "target_resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_relationship_tenant_id_relationship_type_id",
        "resource_relationship",
        ["tenant_id", "relationship_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_relationship_tenant_source_type",
        "resource_relationship",
        ["tenant_id", "source_resource_id", "relationship_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_relationship_tenant_target_type",
        "resource_relationship",
        ["tenant_id", "target_resource_id", "relationship_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_relationship_tenant_id_valid_to",
        "resource_relationship",
        ["tenant_id", "valid_to"],
        unique=False,
    )
    op.create_index(
        "uq_resource_relationship_current",
        "resource_relationship",
        ["tenant_id", "source_resource_id", "target_resource_id", "relationship_type_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_resource_relationship_current", table_name="resource_relationship")
    op.drop_index("ix_resource_relationship_tenant_id_valid_to", table_name="resource_relationship")
    op.drop_index(
        "ix_resource_relationship_tenant_target_type",
        table_name="resource_relationship",
    )
    op.drop_index(
        "ix_resource_relationship_tenant_source_type",
        table_name="resource_relationship",
    )
    op.drop_index(
        "ix_resource_relationship_tenant_id_relationship_type_id",
        table_name="resource_relationship",
    )
    op.drop_index(
        "ix_resource_relationship_tenant_id_target_resource_id",
        table_name="resource_relationship",
    )
    op.drop_index(
        "ix_resource_relationship_tenant_id_source_resource_id",
        table_name="resource_relationship",
    )
    op.drop_table("resource_relationship")
