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


class ResourceIdentifier(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "resource_identifier"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name="fk_resource_identifier_resource_id_resource",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "namespace IS NULL OR btrim(namespace) <> ''", name="namespace_not_empty"
        ),
        CheckConstraint(
            "btrim(normalized_value) <> ''", name="normalized_value_not_empty"
        ),
        CheckConstraint("btrim(original_value) <> ''", name="original_value_not_empty"),
        CheckConstraint("btrim(value_hash) <> ''", name="value_hash_not_empty"),
        CheckConstraint(
            "confidence_score >= 0.0000 AND confidence_score <= 1.0000",
            name="confidence_score_range",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_time_order"),
        Index("ix_resource_identifier_tenant_id_resource_id", "tenant_id", "resource_id"),
        Index(
            "ix_res_ident_tenant_type_hash",
            "tenant_id",
            "identifier_type_id",
            "value_hash",
        ),
        Index(
            "ix_res_ident_tenant_type_normalized",
            "tenant_id",
            "identifier_type_id",
            "normalized_value",
        ),
        Index("ix_resource_identifier_tenant_id_valid_to", "tenant_id", "valid_to"),
        Index(
            "uq_resource_identifier_current_value",
            "tenant_id",
            "identifier_type_id",
            text("COALESCE(namespace, '')"),
            "normalized_value",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        Index(
            "uq_resource_identifier_current_primary",
            "tenant_id",
            "resource_id",
            "identifier_type_id",
            unique=True,
            postgresql_where=text("is_primary = true AND valid_to IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    identifier_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("identifier_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    namespace: Mapped[Optional[str]] = mapped_column(nullable=True)
    normalized_value: Mapped[str] = mapped_column(nullable=False)
    original_value: Mapped[str] = mapped_column(nullable=False)
    value_hash: Mapped[str] = mapped_column(nullable=False)
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
    )
    valid_from: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    resource: Mapped["Resource"] = relationship(back_populates="identifiers")
