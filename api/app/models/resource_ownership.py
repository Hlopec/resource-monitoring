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


class ResourceOwnership(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "resource_ownership"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_ownership_resource_id_resource",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id"],
            ["organization.tenant_id", "organization.id"],
            name="fk_resource_ownership_organization_id_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name="confidence_score_range",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_time_order"),
        CheckConstraint("source IS NULL OR btrim(source) <> ''", name="source_not_empty"),
        Index("ix_resource_ownership_tenant_id_resource_id", "tenant_id", "resource_id"),
        Index(
            "ix_resource_ownership_tenant_id_organization_id",
            "tenant_id",
            "organization_id",
        ),
        Index(
            "ix_resource_ownership_tenant_id_ownership_role_id",
            "tenant_id",
            "ownership_role_id",
        ),
        Index("ix_resource_ownership_tenant_id_valid_to", "tenant_id", "valid_to"),
        Index(
            "uq_resource_ownership_current",
            "tenant_id",
            "resource_id",
            "organization_id",
            "ownership_role_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        Index(
            "uq_resource_ownership_current_primary",
            "tenant_id",
            "resource_id",
            "ownership_role_id",
            unique=True,
            postgresql_where=text("is_primary = true AND valid_to IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    organization_id: Mapped[UUID] = mapped_column(nullable=False)
    ownership_role_id: Mapped[UUID] = mapped_column(
        ForeignKey("ownership_role.id", ondelete="RESTRICT"),
        nullable=False,
    )
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

    resource: Mapped["Resource"] = relationship(
        back_populates="ownerships",
        overlaps="organization,resource_ownerships",
    )
    organization: Mapped["Organization"] = relationship(
        back_populates="resource_ownerships",
        overlaps="ownerships,resource",
    )
    ownership_role: Mapped["OwnershipRole"] = relationship()
