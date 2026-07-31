from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.time import utc_now
from app.models.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class Label(UUIDv7PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "label"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_label_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("btrim(key) <> ''", name="key_not_empty"),
        CheckConstraint("key = lower(key)", name="key_lowercase"),
        CheckConstraint("key = btrim(key)", name="key_trimmed"),
        CheckConstraint("btrim(value) <> ''", name="value_not_empty"),
        CheckConstraint("value = btrim(value)", name="value_trimmed"),
        CheckConstraint(
            "display_name IS NULL OR btrim(display_name) <> ''",
            name="display_name_not_empty",
        ),
        CheckConstraint(
            "description IS NULL OR btrim(description) <> ''",
            name="description_not_empty",
        ),
        CheckConstraint("color IS NULL OR btrim(color) <> ''", name="color_not_empty"),
        CheckConstraint(
            "color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'",
            name="color_hex_format",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_label_tenant_id_id"),
        UniqueConstraint("tenant_id", "key", "value", name="uq_label_tenant_id_key_value"),
        Index("ix_label_tenant_id_is_active", "tenant_id", "is_active"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    key: Mapped[str] = mapped_column(nullable=False)
    value: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(nullable=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    color: Mapped[Optional[str]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="labels")
    resource_assignments: Mapped[list["ResourceLabel"]] = relationship(
        back_populates="label",
        overlaps="label_assignments,resource",
        passive_deletes=True,
    )


class ResourceLabel(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "resource_label"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_label_resource_id_resource",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "label_id"],
            ["label.tenant_id", "label.id"],
            name="fk_resource_label_label_id_label",
            ondelete="RESTRICT",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_time_order"),
        CheckConstraint("source IS NULL OR btrim(source) <> ''", name="source_not_empty"),
        Index(
            "ix_resource_label_tenant_resource_label",
            "tenant_id",
            "resource_id",
            "label_id",
        ),
        Index("ix_resource_label_tenant_label_id", "tenant_id", "label_id"),
        Index("ix_resource_label_tenant_valid_to", "tenant_id", "valid_to"),
        Index(
            "uq_resource_label_current",
            "tenant_id",
            "resource_id",
            "label_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    label_id: Mapped[UUID] = mapped_column(nullable=False)
    valid_from: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    source: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    resource: Mapped["Resource"] = relationship(
        back_populates="label_assignments",
        overlaps="label,resource_assignments",
    )
    label: Mapped["Label"] = relationship(
        back_populates="resource_assignments",
        overlaps="label_assignments,resource",
    )
