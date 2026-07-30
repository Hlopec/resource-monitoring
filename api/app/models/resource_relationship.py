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


class ResourceRelationship(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "resource_relationship"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_relationship_source_resource_id_resource",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_relationship_target_resource_id_resource",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "source_resource_id <> target_resource_id",
            name="source_resource_not_target_resource",
        ),
        CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name="confidence_score_range",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_time_order"),
        CheckConstraint("source IS NULL OR btrim(source) <> ''", name="source_not_empty"),
        Index(
            "ix_resource_relationship_tenant_id_source_resource_id",
            "tenant_id",
            "source_resource_id",
        ),
        Index(
            "ix_resource_relationship_tenant_id_target_resource_id",
            "tenant_id",
            "target_resource_id",
        ),
        Index(
            "ix_resource_relationship_tenant_id_relationship_type_id",
            "tenant_id",
            "relationship_type_id",
        ),
        Index(
            "ix_resource_relationship_tenant_source_type",
            "tenant_id",
            "source_resource_id",
            "relationship_type_id",
        ),
        Index(
            "ix_resource_relationship_tenant_target_type",
            "tenant_id",
            "target_resource_id",
            "relationship_type_id",
        ),
        Index("ix_resource_relationship_tenant_id_valid_to", "tenant_id", "valid_to"),
        Index(
            "uq_resource_relationship_current",
            "tenant_id",
            "source_resource_id",
            "target_resource_id",
            "relationship_type_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    source_resource_id: Mapped[UUID] = mapped_column(nullable=False)
    target_resource_id: Mapped[UUID] = mapped_column(nullable=False)
    relationship_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("relationship_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
    )
    valid_from: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    source: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    source_resource: Mapped["Resource"] = relationship(
        "Resource",
        primaryjoin=(
            "and_(ResourceRelationship.tenant_id == Resource.tenant_id, "
            "ResourceRelationship.source_resource_id == Resource.id)"
        ),
        foreign_keys="[ResourceRelationship.tenant_id, ResourceRelationship.source_resource_id]",
        back_populates="outgoing_relationships",
        overlaps="incoming_relationships,target_resource",
    )
    target_resource: Mapped["Resource"] = relationship(
        "Resource",
        primaryjoin=(
            "and_(ResourceRelationship.tenant_id == Resource.tenant_id, "
            "ResourceRelationship.target_resource_id == Resource.id)"
        ),
        foreign_keys="[ResourceRelationship.tenant_id, ResourceRelationship.target_resource_id]",
        back_populates="incoming_relationships",
        overlaps="outgoing_relationships,source_resource",
    )
    relationship_type: Mapped["RelationshipType"] = relationship()
