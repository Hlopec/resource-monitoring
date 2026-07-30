"""resource ownership

Revision ID: 202607300003
Revises: 202607300002
Create Date: 2026-07-31 00:04:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300003"
down_revision: str | None = "202607300002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_ownership",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ownership_role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name=op.f("ck_resource_ownership_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_resource_ownership_valid_time_order"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR btrim(source) <> ''",
            name=op.f("ck_resource_ownership_source_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_ownership_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id"],
            ["organization.tenant_id", "organization.id"],
            name="fk_resource_ownership_organization_id_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ownership_role_id"],
            ["ownership_role.id"],
            name=op.f("fk_resource_ownership_ownership_role_id_ownership_role"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_ownership")),
    )
    op.create_index(
        "ix_resource_ownership_tenant_id_resource_id",
        "resource_ownership",
        ["tenant_id", "resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_ownership_tenant_id_organization_id",
        "resource_ownership",
        ["tenant_id", "organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_ownership_tenant_id_ownership_role_id",
        "resource_ownership",
        ["tenant_id", "ownership_role_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_ownership_tenant_id_valid_to",
        "resource_ownership",
        ["tenant_id", "valid_to"],
        unique=False,
    )
    op.create_index(
        "uq_resource_ownership_current",
        "resource_ownership",
        ["tenant_id", "resource_id", "organization_id", "ownership_role_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "uq_resource_ownership_current_primary",
        "resource_ownership",
        ["tenant_id", "resource_id", "ownership_role_id"],
        unique=True,
        postgresql_where=sa.text("is_primary = true AND valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_resource_ownership_current_primary", table_name="resource_ownership")
    op.drop_index("uq_resource_ownership_current", table_name="resource_ownership")
    op.drop_index("ix_resource_ownership_tenant_id_valid_to", table_name="resource_ownership")
    op.drop_index(
        "ix_resource_ownership_tenant_id_ownership_role_id",
        table_name="resource_ownership",
    )
    op.drop_index(
        "ix_resource_ownership_tenant_id_organization_id",
        table_name="resource_ownership",
    )
    op.drop_index("ix_resource_ownership_tenant_id_resource_id", table_name="resource_ownership")
    op.drop_table("resource_ownership")
