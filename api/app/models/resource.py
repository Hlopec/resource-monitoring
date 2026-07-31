from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.time import utc_now
from app.models.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class Resource(UUIDv7PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_resource_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("btrim(canonical_name) <> ''", name="canonical_name_not_empty"),
        CheckConstraint("btrim(display_name) <> ''", name="display_name_not_empty"),
        CheckConstraint(
            "source_priority >= 0 AND source_priority <= 1000",
            name="source_priority_range",
        ),
        CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name="confidence_score_range",
        ),
        CheckConstraint("record_version > 0", name="record_version_positive"),
        CheckConstraint("first_seen_at <= last_seen_at", name="seen_at_order"),
        UniqueConstraint("tenant_id", "id", name="uq_resource_tenant_id_id"),
        Index("ix_resource_tenant_id_resource_type_id", "tenant_id", "resource_type_id"),
        Index("ix_resource_tenant_id_lifecycle_status_id", "tenant_id", "lifecycle_status_id"),
        Index("ix_resource_tenant_id_criticality_id", "tenant_id", "criticality_id"),
        Index("ix_resource_tenant_id_exposure_level_id", "tenant_id", "exposure_level_id"),
        Index("ix_resource_tenant_id_canonical_name", "tenant_id", "canonical_name"),
        Index("ix_resource_tenant_id_last_seen_at", "tenant_id", "last_seen_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("resource_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_name: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    lifecycle_status_id: Mapped[UUID] = mapped_column(
        ForeignKey("lifecycle_status.id", ondelete="RESTRICT"),
        nullable=False,
    )
    criticality_id: Mapped[UUID] = mapped_column(
        ForeignKey("criticality.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exposure_level_id: Mapped[UUID] = mapped_column(
        ForeignKey("exposure_level.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_priority: Mapped[int] = mapped_column(nullable=False, default=100)
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
    )
    first_seen_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    record_version: Mapped[int] = mapped_column(nullable=False, default=1)
    __mapper_args__ = {
        "version_id_col": record_version,
    }

    identifiers: Mapped[list["ResourceIdentifier"]] = relationship(
        back_populates="resource",
        passive_deletes=True,
    )
    ownerships: Mapped[list["ResourceOwnership"]] = relationship(
        back_populates="resource",
        overlaps="organization,resource_ownerships",
        passive_deletes=True,
    )
    outgoing_relationships: Mapped[list["ResourceRelationship"]] = relationship(
        "ResourceRelationship",
        primaryjoin=(
            "and_(Resource.tenant_id == ResourceRelationship.tenant_id, "
            "Resource.id == ResourceRelationship.source_resource_id)"
        ),
        foreign_keys="[ResourceRelationship.tenant_id, ResourceRelationship.source_resource_id]",
        back_populates="source_resource",
        overlaps="incoming_relationships,target_resource",
        passive_deletes=True,
    )
    incoming_relationships: Mapped[list["ResourceRelationship"]] = relationship(
        "ResourceRelationship",
        primaryjoin=(
            "and_(Resource.tenant_id == ResourceRelationship.tenant_id, "
            "Resource.id == ResourceRelationship.target_resource_id)"
        ),
        foreign_keys="[ResourceRelationship.tenant_id, ResourceRelationship.target_resource_id]",
        back_populates="target_resource",
        overlaps="outgoing_relationships,source_resource",
        passive_deletes=True,
    )
    classifications: Mapped[list["ResourceClassification"]] = relationship(
        back_populates="resource",
        passive_deletes=True,
    )
    label_assignments: Mapped[list["ResourceLabel"]] = relationship(
        back_populates="resource",
        overlaps="label,resource_assignments",
        passive_deletes=True,
    )
    state_history: Mapped[list["ResourceState"]] = relationship(
        back_populates="resource",
        passive_deletes=True,
    )
