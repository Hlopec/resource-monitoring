"""resource state history

Revision ID: 202607300007
Revises: 202607300006
Create Date: 2026-07-31 00:08:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.uuid import generate_uuid7

revision: str = "202607300007"
down_revision: str | None = "202607300006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


resource_state_table = sa.table(
    "resource_state",
    sa.column("tenant_id", postgresql.UUID(as_uuid=True)),
    sa.column("resource_id", postgresql.UUID(as_uuid=True)),
    sa.column("lifecycle_status_id", postgresql.UUID(as_uuid=True)),
    sa.column("criticality_id", postgresql.UUID(as_uuid=True)),
    sa.column("exposure_level_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_priority", sa.Integer()),
    sa.column("confidence_score", sa.Numeric(5, 4)),
    sa.column("valid_from", sa.DateTime(timezone=True)),
    sa.column("valid_to", sa.DateTime(timezone=True)),
    sa.column("source", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("id", postgresql.UUID(as_uuid=True)),
)


def upgrade() -> None:
    op.create_table(
        "resource_state",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lifecycle_status_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("criticality_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exposure_level_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "source_priority >= 0",
            name=op.f("ck_resource_state_source_priority_non_negative"),
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name=op.f("ck_resource_state_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_resource_state_valid_time_order"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR btrim(source) <> ''",
            name=op.f("ck_resource_state_source_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_state_resource_id_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lifecycle_status_id"],
            ["lifecycle_status.id"],
            name="fk_resource_state_lifecycle_status",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["criticality_id"],
            ["criticality.id"],
            name="fk_resource_state_criticality",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exposure_level_id"],
            ["exposure_level.id"],
            name="fk_resource_state_exposure_level",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_state")),
    )
    op.create_index(
        "ix_resource_state_tenant_resource_valid_from",
        "resource_state",
        ["tenant_id", "resource_id", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ix_resource_state_tenant_lifecycle_status",
        "resource_state",
        ["tenant_id", "lifecycle_status_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_state_tenant_criticality",
        "resource_state",
        ["tenant_id", "criticality_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_state_tenant_exposure_level",
        "resource_state",
        ["tenant_id", "exposure_level_id"],
        unique=False,
    )
    op.create_index(
        "ix_resource_state_tenant_valid_to",
        "resource_state",
        ["tenant_id", "valid_to"],
        unique=False,
    )
    op.create_index(
        "uq_resource_state_current",
        "resource_state",
        ["tenant_id", "resource_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    connection = op.get_bind()
    resources = connection.execute(
        sa.text(
            "SELECT tenant_id, id, lifecycle_status_id, criticality_id, "
            "exposure_level_id, source_priority, confidence_score, first_seen_at, "
            "created_at FROM resource ORDER BY tenant_id, id"
        )
    ).mappings()
    rows = [
        {
            "id": generate_uuid7(),
            "tenant_id": resource["tenant_id"],
            "resource_id": resource["id"],
            "lifecycle_status_id": resource["lifecycle_status_id"],
            "criticality_id": resource["criticality_id"],
            "exposure_level_id": resource["exposure_level_id"],
            "source_priority": resource["source_priority"],
            "confidence_score": resource["confidence_score"],
            "valid_from": resource["first_seen_at"],
            "valid_to": None,
            "source": "migration_backfill",
            "created_at": resource["created_at"],
        }
        for resource in resources
    ]
    if rows:
        op.bulk_insert(resource_state_table, rows)


def downgrade() -> None:
    op.drop_index("uq_resource_state_current", table_name="resource_state")
    op.drop_index("ix_resource_state_tenant_valid_to", table_name="resource_state")
    op.drop_index("ix_resource_state_tenant_exposure_level", table_name="resource_state")
    op.drop_index("ix_resource_state_tenant_criticality", table_name="resource_state")
    op.drop_index("ix_resource_state_tenant_lifecycle_status", table_name="resource_state")
    op.drop_index(
        "ix_resource_state_tenant_resource_valid_from",
        table_name="resource_state",
    )
    op.drop_table("resource_state")
