from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column

from app.db.time import utc_now
from app.db.uuid import generate_uuid7


class UUIDv7PrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=generate_uuid7)

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("id", generate_uuid7())
        super().__init__(**kwargs)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
