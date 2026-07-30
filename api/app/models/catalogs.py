from typing import Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class ResourceType(UUIDv7PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource_type"
    __table_args__ = (
        CheckConstraint("code <> ''", name="code_not_empty"),
        CheckConstraint("code = lower(code)", name="code_normalized"),
    )

    code: Mapped[str] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    parent_type_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("resource_type.id", ondelete="RESTRICT"),
        nullable=True,
    )
    category: Mapped[str] = mapped_column(nullable=False)
    schema_version: Mapped[int] = mapped_column(nullable=False, default=1)
    is_system: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    parent: Mapped[Optional["ResourceType"]] = relationship(
        remote_side=lambda: ResourceType.id,
        passive_deletes=True,
    )


class IdentifierType(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "identifier_type"
    __table_args__ = (
        CheckConstraint("code <> ''", name="code_not_empty"),
        CheckConstraint("code = lower(code)", name="code_normalized"),
    )

    code: Mapped[str] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    normalization_strategy: Mapped[str] = mapped_column(nullable=False)
    uniqueness_scope: Mapped[str] = mapped_column(nullable=False)
    is_case_sensitive: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_system: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class OwnershipRole(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "ownership_role"
    __table_args__ = (
        CheckConstraint("code <> ''", name="code_not_empty"),
        CheckConstraint("code = lower(code)", name="code_normalized"),
    )

    code: Mapped[str] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    is_system: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class RelationshipType(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "relationship_type"
    __table_args__ = (
        CheckConstraint("code <> ''", name="code_not_empty"),
        CheckConstraint("code = lower(code)", name="code_normalized"),
    )

    code: Mapped[str] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    inverse_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    source_type_constraint: Mapped[Optional[str]] = mapped_column(nullable=True)
    target_type_constraint: Mapped[Optional[str]] = mapped_column(nullable=True)
    is_directional: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_transitive: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_system: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class ClassificationType(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "classification_type"
    __table_args__ = (
        CheckConstraint("code <> ''", name="code_not_empty"),
        CheckConstraint("code = lower(code)", name="code_normalized"),
    )

    code: Mapped[str] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    is_system: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    values: Mapped[list["ClassificationValue"]] = relationship(
        back_populates="classification_type",
        passive_deletes=True,
    )


class ClassificationValue(UUIDv7PrimaryKeyMixin, Base):
    __tablename__ = "classification_value"
    __table_args__ = (
        UniqueConstraint(
            "classification_type_id",
            "code",
            name="uq_classification_value_classification_type_id_code",
        ),
        CheckConstraint("code <> ''", name="code_not_empty"),
        CheckConstraint("code = lower(code)", name="code_normalized"),
    )

    classification_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("classification_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    is_system: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    classification_type: Mapped[ClassificationType] = relationship(
        back_populates="values"
    )
