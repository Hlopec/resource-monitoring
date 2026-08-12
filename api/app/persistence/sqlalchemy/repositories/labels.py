"""SQLAlchemy implementation of the Label repository contract."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.application.ports.labels import LabelRepository
from app.models import Label
from app.persistence.sqlalchemy.repositories.tenant_scoped import (
    TenantScopedSQLAlchemyRepository,
)


class SQLAlchemyLabelRepository(
    TenantScopedSQLAlchemyRepository[Label],
    LabelRepository,
):
    """Tenant-scoped SQLAlchemy adapter for label definitions."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, Label)

    def get_by_id(
        self,
        tenant_id: UUID,
        label_id: UUID,
    ) -> Label | None:
        return self.get_tenant_entity(tenant_id, label_id)

    def get_by_key_value(
        self,
        tenant_id: UUID,
        key: str,
        value: str,
    ) -> Label | None:
        return self._scalar(
            self.tenant_statement(tenant_id)
            .where(Label.key == key, Label.value == value)
            .order_by(Label.key, Label.value, Label.id)
        )

    def exists_by_key_value(
        self,
        tenant_id: UUID,
        key: str,
        value: str,
    ) -> bool:
        return self._exists(
            self.tenant_statement(tenant_id).where(
                Label.key == key,
                Label.value == value,
            )
        )

    def list_active(
        self,
        tenant_id: UUID,
    ) -> Sequence[Label]:
        return self._scalars(
            self.tenant_statement(tenant_id)
            .where(Label.is_active.is_(True))
            .order_by(Label.key, Label.value, Label.id)
        )
