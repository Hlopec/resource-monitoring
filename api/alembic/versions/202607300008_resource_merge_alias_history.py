"""resource merge and alias history

Revision ID: 202607300008
Revises: 202607300007
Create Date: 2026-07-31 00:09:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300008"
down_revision: str | None = "202607300007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_alias",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias_type", sa.String(), nullable=False),
        sa.Column("alias_value", sa.String(), nullable=False),
        sa.Column("normalized_value", sa.String(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "btrim(alias_type) <> ''",
            name=op.f("ck_resource_alias_alias_type_not_empty"),
        ),
        sa.CheckConstraint(
            "btrim(alias_value) <> ''",
            name=op.f("ck_resource_alias_alias_value_not_empty"),
        ),
        sa.CheckConstraint(
            "btrim(normalized_value) <> ''",
            name=op.f("ck_resource_alias_normalized_value_not_empty"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR btrim(source) <> ''",
            name=op.f("ck_resource_alias_source_not_empty"),
        ),
        sa.CheckConstraint(
            "last_seen_at >= first_seen_at",
            name=op.f("ck_resource_alias_seen_at_order"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_alias_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_alias")),
        sa.UniqueConstraint(
            "tenant_id",
            "alias_type",
            "normalized_value",
            name="uq_resource_alias_tenant_alias_type_normalized_value",
        ),
    )
    op.create_index(
        "ix_resource_alias_tenant_resource_id",
        "resource_alias",
        ["tenant_id", "resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_alias_tenant_alias_type",
        "resource_alias",
        ["tenant_id", "alias_type"],
        unique=False,
    )
    op.create_index(
        "ix_resource_alias_tenant_last_seen_at",
        "resource_alias",
        ["tenant_id", "last_seen_at"],
        unique=False,
    )

    op.create_table(
        "resource_merge",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "source_resource_id <> target_resource_id",
            name=op.f("ck_resource_merge_source_resource_not_target_resource"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR btrim(reason) <> ''",
            name=op.f("ck_resource_merge_reason_not_empty"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR btrim(source) <> ''",
            name=op.f("ck_resource_merge_source_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_merge_source_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_merge_target_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_merge")),
        sa.UniqueConstraint(
            "tenant_id",
            "source_resource_id",
            name="uq_resource_merge_tenant_source_resource_id",
        ),
    )
    op.create_index(
        "ix_resource_merge_tenant_target_merged_at",
        "resource_merge",
        ["tenant_id", "target_resource_id", "merged_at"],
        unique=False,
    )
    op.create_index(
        "ix_resource_merge_tenant_merged_at",
        "resource_merge",
        ["tenant_id", "merged_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION prevent_resource_merge_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_resource_id = NEW.target_resource_id THEN
                RAISE EXCEPTION
                    'resource_merge cycle detected: self-merge rejected'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'trg_resource_merge_prevent_cycle';
            END IF;

            IF EXISTS (
                WITH RECURSIVE lineage(resource_id, path, depth) AS (
                    SELECT
                        NEW.target_resource_id,
                        ARRAY[NEW.target_resource_id]::uuid[],
                        1
                    UNION ALL
                    SELECT
                        resource_merge.target_resource_id,
                        lineage.path || resource_merge.target_resource_id,
                        lineage.depth + 1
                    FROM resource_merge
                    JOIN lineage
                      ON resource_merge.tenant_id = NEW.tenant_id
                     AND resource_merge.source_resource_id = lineage.resource_id
                    WHERE (NEW.id IS NULL OR resource_merge.id <> NEW.id)
                      AND resource_merge.target_resource_id <> ALL(lineage.path)
                      AND lineage.depth < 100
                )
                SELECT 1
                FROM lineage
                WHERE resource_id = NEW.source_resource_id
            ) THEN
                RAISE EXCEPTION
                    'resource_merge cycle detected for tenant %, source %, target %',
                    NEW.tenant_id,
                    NEW.source_resource_id,
                    NEW.target_resource_id
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'trg_resource_merge_prevent_cycle';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_resource_merge_prevent_cycle
        BEFORE INSERT OR UPDATE OF tenant_id, source_resource_id, target_resource_id
        ON resource_merge
        FOR EACH ROW
        EXECUTE FUNCTION prevent_resource_merge_cycle();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_resource_merge_prevent_cycle ON resource_merge")
    op.execute("DROP FUNCTION prevent_resource_merge_cycle()")
    op.drop_index("ix_resource_merge_tenant_merged_at", table_name="resource_merge")
    op.drop_index(
        "ix_resource_merge_tenant_target_merged_at",
        table_name="resource_merge",
    )
    op.drop_table("resource_merge")
    op.drop_index("ix_resource_alias_tenant_last_seen_at", table_name="resource_alias")
    op.drop_index("ix_resource_alias_tenant_alias_type", table_name="resource_alias")
    op.drop_index("ix_resource_alias_tenant_resource_id", table_name="resource_alias")
    op.drop_table("resource_alias")
