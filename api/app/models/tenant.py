from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class Tenant(UUIDv7PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant"
    __table_args__ = (
        CheckConstraint("slug <> ''", name="slug_not_empty"),
        CheckConstraint("slug = lower(slug)", name="slug_normalized"),
    )

    slug: Mapped[str] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)

    organizations: Mapped[list["Organization"]] = relationship(
        back_populates="tenant",
        overlaps="children,parent",
        passive_deletes=True,
    )
