"""Tenant-scoped SQLAlchemy repository primitives."""

from __future__ import annotations

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import ExecutableOption

from app.persistence.sqlalchemy.repositories.base import SQLAlchemyRepository
from app.persistence.sqlalchemy.repositories.helpers import (
    apply_for_update,
    tenant_entity_select,
    tenant_select,
    with_options,
)

ModelT = TypeVar("ModelT")


class TenantScopedSQLAlchemyRepository(SQLAlchemyRepository[ModelT], Generic[ModelT]):
    """Base for tenant-owned repositories with centralized tenant predicates."""

    def __init__(self, session: Session, model_type: type[ModelT]) -> None:
        self._model_type = model_type
        tenant_select(model_type, _ZERO_UUID)
        tenant_entity_select(model_type, _ZERO_UUID, _ZERO_UUID)
        super().__init__(session)

    @property
    def model_type(self) -> type[ModelT]:
        return self._model_type

    def tenant_statement(self, tenant_id: UUID) -> Select[tuple[ModelT]]:
        """Build the base tenant-scoped statement for this repository model."""
        return tenant_select(self._model_type, tenant_id)

    def tenant_entity_statement(
        self,
        tenant_id: UUID,
        entity_id: UUID,
    ) -> Select[tuple[ModelT]]:
        """Build a tenant-scoped lookup by entity id."""
        return tenant_entity_select(self._model_type, tenant_id, entity_id)

    def get_tenant_entity(
        self,
        tenant_id: UUID,
        entity_id: UUID,
        *,
        for_update: bool = False,
        options: tuple[ExecutableOption, ...] = (),
    ) -> ModelT | None:
        """Return one tenant-owned entity by id without any unscoped fallback."""
        statement = self.tenant_entity_statement(tenant_id, entity_id)
        if options:
            statement = with_options(statement, *options)
        if for_update:
            statement = apply_for_update(statement)
        return self._scalar(statement)

    def exists_tenant_entity(self, tenant_id: UUID, entity_id: UUID) -> bool:
        """Return whether an entity exists inside an explicit tenant scope."""
        return self._exists(self.tenant_entity_statement(tenant_id, entity_id))


_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")
