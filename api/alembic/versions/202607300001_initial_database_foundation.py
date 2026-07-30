"""initial database foundation

Revision ID: 202607300001
Revises:
Create Date: 2026-07-30 00:01:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classification_type",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "code <> ''", name=op.f("ck_classification_type_code_not_empty")
        ),
        sa.CheckConstraint(
            "code = lower(code)", name=op.f("ck_classification_type_code_normalized")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classification_type")),
        sa.UniqueConstraint("code", name=op.f("uq_classification_type_code")),
    )
    op.create_table(
        "identifier_type",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("normalization_strategy", sa.String(), nullable=False),
        sa.Column("uniqueness_scope", sa.String(), nullable=False),
        sa.Column("is_case_sensitive", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("code <> ''", name=op.f("ck_identifier_type_code_not_empty")),
        sa.CheckConstraint(
            "code = lower(code)", name=op.f("ck_identifier_type_code_normalized")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identifier_type")),
        sa.UniqueConstraint("code", name=op.f("uq_identifier_type_code")),
    )
    op.create_table(
        "ownership_role",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("code <> ''", name=op.f("ck_ownership_role_code_not_empty")),
        sa.CheckConstraint(
            "code = lower(code)", name=op.f("ck_ownership_role_code_normalized")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ownership_role")),
        sa.UniqueConstraint("code", name=op.f("uq_ownership_role_code")),
    )
    op.create_table(
        "relationship_type",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("inverse_code", sa.String(), nullable=True),
        sa.Column("source_type_constraint", sa.String(), nullable=True),
        sa.Column("target_type_constraint", sa.String(), nullable=True),
        sa.Column("is_directional", sa.Boolean(), nullable=False),
        sa.Column("is_transitive", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("code <> ''", name=op.f("ck_relationship_type_code_not_empty")),
        sa.CheckConstraint(
            "code = lower(code)", name=op.f("ck_relationship_type_code_normalized")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationship_type")),
        sa.UniqueConstraint("code", name=op.f("uq_relationship_type_code")),
    )
    op.create_table(
        "resource_type",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("parent_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("code <> ''", name=op.f("ck_resource_type_code_not_empty")),
        sa.CheckConstraint(
            "code = lower(code)", name=op.f("ck_resource_type_code_normalized")
        ),
        sa.ForeignKeyConstraint(
            ["parent_type_id"],
            ["resource_type.id"],
            name=op.f("fk_resource_type_parent_type_id_resource_type"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_type")),
        sa.UniqueConstraint("code", name=op.f("uq_resource_type_code")),
    )
    op.create_table(
        "tenant",
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("slug <> ''", name=op.f("ck_tenant_slug_not_empty")),
        sa.CheckConstraint("slug = lower(slug)", name=op.f("ck_tenant_slug_normalized")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenant_slug")),
    )
    op.create_table(
        "classification_value",
        sa.Column("classification_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("code <> ''", name=op.f("ck_classification_value_code_not_empty")),
        sa.CheckConstraint(
            "code = lower(code)", name=op.f("ck_classification_value_code_normalized")
        ),
        sa.ForeignKeyConstraint(
            ["classification_type_id"],
            ["classification_type.id"],
            name=op.f("fk_classification_value_classification_type_id_classification_type"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classification_value")),
        sa.UniqueConstraint(
            "classification_type_id",
            "code",
            name="uq_classification_value_classification_type_id_code",
        ),
    )
    op.create_table(
        "organization",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("external_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "canonical_name <> ''", name=op.f("ck_organization_canonical_name_not_empty")
        ),
        sa.CheckConstraint(
            "parent_organization_id IS NULL OR parent_organization_id <> id",
            name=op.f("ck_organization_parent_organization_not_self"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_organization_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_organization_id"],
            ["organization.tenant_id", "organization.id"],
            name="fk_organization_parent_organization_id_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_organization_tenant_id_id"),
    )
    op.create_index(
        "uq_organization_tenant_id_external_key_not_null",
        "organization",
        ["tenant_id", "external_key"],
        unique=True,
        postgresql_where=sa.text("external_key IS NOT NULL"),
    )
    op.create_index(
        "ix_organization_tenant_id_canonical_name",
        "organization",
        ["tenant_id", "canonical_name"],
        unique=False,
    )
    op.create_index(
        "ix_organization_tenant_id_status",
        "organization",
        ["tenant_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_organization_tenant_id_external_key_not_null",
        table_name="organization",
        postgresql_where=sa.text("external_key IS NOT NULL"),
    )
    op.drop_index("ix_organization_tenant_id_status", table_name="organization")
    op.drop_index("ix_organization_tenant_id_canonical_name", table_name="organization")
    op.drop_table("organization")
    op.drop_table("classification_value")
    op.drop_table("tenant")
    op.drop_table("resource_type")
    op.drop_table("relationship_type")
    op.drop_table("ownership_role")
    op.drop_table("identifier_type")
    op.drop_table("classification_type")
