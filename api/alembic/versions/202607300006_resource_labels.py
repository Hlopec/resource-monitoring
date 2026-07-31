"""resource labels

Revision ID: 202607300006
Revises: 202607300005
Create Date: 2026-07-31 00:07:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300006"
down_revision: str | None = "202607300005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "label",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("btrim(key) <> ''", name=op.f("ck_label_key_not_empty")),
        sa.CheckConstraint("key = lower(key)", name=op.f("ck_label_key_lowercase")),
        sa.CheckConstraint("key = btrim(key)", name=op.f("ck_label_key_trimmed")),
        sa.CheckConstraint("btrim(value) <> ''", name=op.f("ck_label_value_not_empty")),
        sa.CheckConstraint("value = btrim(value)", name=op.f("ck_label_value_trimmed")),
        sa.CheckConstraint(
            "display_name IS NULL OR btrim(display_name) <> ''",
            name=op.f("ck_label_display_name_not_empty"),
        ),
        sa.CheckConstraint(
            "description IS NULL OR btrim(description) <> ''",
            name=op.f("ck_label_description_not_empty"),
        ),
        sa.CheckConstraint(
            "color IS NULL OR btrim(color) <> ''",
            name=op.f("ck_label_color_not_empty"),
        ),
        sa.CheckConstraint(
            "color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'",
            name=op.f("ck_label_color_hex_format"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_label_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_label")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_label_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "key",
            "value",
            name="uq_label_tenant_id_key_value",
        ),
    )
    op.create_index(
        "ix_label_tenant_id_is_active",
        "label",
        ["tenant_id", "is_active"],
        unique=False,
    )
    op.create_table(
        "resource_label",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_resource_label_valid_time_order"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR btrim(source) <> ''",
            name=op.f("ck_resource_label_source_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_label_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "label_id"],
            ["label.tenant_id", "label.id"],
            name="fk_resource_label_label_id_label",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_label")),
    )
    op.create_index(
        "ix_resource_label_tenant_resource_label",
        "resource_label",
        ["tenant_id", "resource_id", "label_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_label_tenant_label_id",
        "resource_label",
        ["tenant_id", "label_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_label_tenant_valid_to",
        "resource_label",
        ["tenant_id", "valid_to"],
        unique=False,
    )
    op.create_index(
        "uq_resource_label_current",
        "resource_label",
        ["tenant_id", "resource_id", "label_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_resource_label_current", table_name="resource_label")
    op.drop_index("ix_resource_label_tenant_valid_to", table_name="resource_label")
    op.drop_index("ix_resource_label_tenant_label_id", table_name="resource_label")
    op.drop_index(
        "ix_resource_label_tenant_resource_label",
        table_name="resource_label",
    )
    op.drop_table("resource_label")
    op.drop_index("ix_label_tenant_id_is_active", table_name="label")
    op.drop_table("label")
