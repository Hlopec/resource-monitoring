from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.time import utc_now
from app.models.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class ResourceAlias(UUIDv7PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource_alias"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_alias_resource_id_resource",
            ondelete="RESTRICT",
        ),
        CheckConstraint("btrim(alias_type) <> ''", name="alias_type_not_empty"),
        CheckConstraint("btrim(alias_value) <> ''", name="alias_value_not_empty"),
        CheckConstraint(
            "btrim(normalized_value) <> ''",
            name="normalized_value_not_empty",
        ),
        CheckConstraint("source IS NULL OR btrim(source) <> ''", name="source_not_empty"),
        CheckConstraint("last_seen_at >= first_seen_at", name="seen_at_order"),
        UniqueConstraint(
            "tenant_id",
            "alias_type",
            "normalized_value",
            name="uq_resource_alias_tenant_alias_type_normalized_value",
        ),
        Index("ix_resource_alias_tenant_resource_id", "tenant_id", "resource_id"),
        Index("ix_resource_alias_tenant_alias_type", "tenant_id", "alias_type"),
        Index("ix_resource_alias_tenant_last_seen_at", "tenant_id", "last_seen_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    alias_type: Mapped[str] = mapped_column(nullable=False)
    alias_value: Mapped[str] = mapped_column(nullable=False)
    normalized_value: Mapped[str] = mapped_column(nullable=False)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    resource: Mapped["Resource"] = relationship(back_populates="aliases")
