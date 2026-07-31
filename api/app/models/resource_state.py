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
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.time import utc_now
from app.models.mixins import UUIDv7PrimaryKeyMixin


class ResourceState(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "resource_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_state_resource_id_resource",
            ondelete="RESTRICT",
        ),
        CheckConstraint("source_priority >= 0", name="source_priority_non_negative"),
        CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name="confidence_score_range",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_time_order"),
        CheckConstraint("source IS NULL OR btrim(source) <> ''", name="source_not_empty"),
        Index(
            "ix_resource_state_tenant_resource_valid_from",
            "tenant_id",
            "resource_id",
            "valid_from",
        ),
        Index("ix_resource_state_tenant_lifecycle_status", "tenant_id", "lifecycle_status_id"),
        Index("ix_resource_state_tenant_criticality", "tenant_id", "criticality_id"),
        Index("ix_resource_state_tenant_exposure_level", "tenant_id", "exposure_level_id"),
        Index("ix_resource_state_tenant_valid_to", "tenant_id", "valid_to"),
        Index(
            "uq_resource_state_current",
            "tenant_id",
            "resource_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    lifecycle_status_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "lifecycle_status.id",
            name="fk_resource_state_lifecycle_status",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    criticality_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "criticality.id",
            name="fk_resource_state_criticality",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    exposure_level_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "exposure_level.id",
            name="fk_resource_state_exposure_level",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_priority: Mapped[int] = mapped_column(nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    resource: Mapped["Resource"] = relationship(back_populates="state_history")
    lifecycle_status: Mapped["LifecycleStatus"] = relationship()
    criticality: Mapped["Criticality"] = relationship()
    exposure_level: Mapped["ExposureLevel"] = relationship()
