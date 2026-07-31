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
from app.models.mixins import UUIDv7PrimaryKeyMixin


class ResourceMerge(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "resource_merge"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_merge_source_resource_id_resource",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_merge_target_resource_id_resource",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "source_resource_id <> target_resource_id",
            name="source_resource_not_target_resource",
        ),
        CheckConstraint("reason IS NULL OR btrim(reason) <> ''", name="reason_not_empty"),
        CheckConstraint("source IS NULL OR btrim(source) <> ''", name="source_not_empty"),
        UniqueConstraint(
            "tenant_id",
            "source_resource_id",
            name="uq_resource_merge_tenant_source_resource_id",
        ),
        Index(
            "ix_resource_merge_tenant_target_merged_at",
            "tenant_id",
            "target_resource_id",
            "merged_at",
        ),
        Index("ix_resource_merge_tenant_merged_at", "tenant_id", "merged_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    source_resource_id: Mapped[UUID] = mapped_column(nullable=False)
    target_resource_id: Mapped[UUID] = mapped_column(nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    merged_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    source_resource: Mapped["Resource"] = relationship(
        "Resource",
        primaryjoin=(
            "and_(ResourceMerge.tenant_id == Resource.tenant_id, "
            "ResourceMerge.source_resource_id == Resource.id)"
        ),
        foreign_keys="[ResourceMerge.tenant_id, ResourceMerge.source_resource_id]",
        back_populates="outgoing_merge",
        overlaps="incoming_merges,target_resource",
    )
    target_resource: Mapped["Resource"] = relationship(
        "Resource",
        primaryjoin=(
            "and_(ResourceMerge.tenant_id == Resource.tenant_id, "
            "ResourceMerge.target_resource_id == Resource.id)"
        ),
        foreign_keys="[ResourceMerge.tenant_id, ResourceMerge.target_resource_id]",
        back_populates="incoming_merges",
        overlaps="outgoing_merge,source_resource",
    )
