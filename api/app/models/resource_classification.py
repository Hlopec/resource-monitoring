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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.time import utc_now
from app.models.mixins import UUIDv7PrimaryKeyMixin


class ResourceClassification(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "resource_classification"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_classification_resource_id_resource",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["classification_type_id", "classification_value_id"],
            ["classification_value.classification_type_id", "classification_value.id"],
            name="fk_resource_classification_type_value",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name="confidence_score_range",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_time_order"),
        CheckConstraint("source IS NULL OR btrim(source) <> ''", name="source_not_empty"),
        Index(
            "ix_resource_classification_tenant_resource_value",
            "tenant_id",
            "resource_id",
            "classification_value_id",
        ),
        Index(
            "ix_resource_classification_tenant_resource_type",
            "tenant_id",
            "resource_id",
            "classification_type_id",
        ),
        Index(
            "ix_resource_classification_tenant_value",
            "tenant_id",
            "classification_value_id",
        ),
        Index(
            "ix_resource_classification_tenant_type_value",
            "tenant_id",
            "classification_type_id",
            "classification_value_id",
        ),
        Index("ix_resource_classification_tenant_valid_to", "tenant_id", "valid_to"),
        Index(
            "uq_resource_classification_current_value",
            "tenant_id",
            "resource_id",
            "classification_value_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        Index(
            "uq_resource_classification_current_primary_type",
            "tenant_id",
            "resource_id",
            "classification_type_id",
            unique=True,
            postgresql_where=text("is_primary = true AND valid_to IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    classification_type_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "classification_type.id",
            name="fk_resource_classification_type",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    classification_value_id: Mapped[UUID] = mapped_column(nullable=False)
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
    )
    valid_from: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    source: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    resource: Mapped["Resource"] = relationship(back_populates="classifications")
    classification_type: Mapped["ClassificationType"] = relationship(
        overlaps="classification_value"
    )
    classification_value: Mapped["ClassificationValue"] = relationship(
        overlaps="classification_type"
    )
