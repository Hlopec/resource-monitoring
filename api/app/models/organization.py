from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class Organization(UUIDv7PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_organization_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "external_key",
            name="uq_organization_tenant_id_external_key",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_organization_id"],
            ["organization.tenant_id", "organization.id"],
            name="fk_organization_parent_organization_id_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("canonical_name <> ''", name="canonical_name_not_empty"),
        Index("ix_organization_tenant_id_status", "tenant_id", "status"),
        Index("ix_organization_tenant_id_canonical_name", "tenant_id", "canonical_name"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=False,
    )
    parent_organization_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    canonical_name: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    external_key: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    tenant: Mapped["Tenant"] = relationship(
        back_populates="organizations",
        overlaps="children,parent",
    )
    parent: Mapped[Optional["Organization"]] = relationship(
        remote_side=lambda: (Organization.tenant_id, Organization.id),
        back_populates="children",
        overlaps="organizations,tenant",
        passive_deletes=True,
    )
    children: Mapped[list["Organization"]] = relationship(
        back_populates="parent",
        overlaps="organizations,parent,tenant",
        passive_deletes=True,
    )
