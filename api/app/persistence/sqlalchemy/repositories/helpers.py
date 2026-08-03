"""Small SQLAlchemy statement helpers for repository implementations."""

from __future__ import annotations

from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.base import ExecutableOption

ModelT = TypeVar("ModelT")


def entity_select(
    model_type: type[ModelT],
    entity_id: UUID,
) -> Select[tuple[ModelT]]:
    """Build a primary-key lookup statement for non-tenant-scoped models."""
    return select(model_type).where(_required_column(model_type, "id") == entity_id)


def tenant_select(
    model_type: type[ModelT],
    tenant_id: UUID,
) -> Select[tuple[ModelT]]:
    """Build a tenant-scoped statement for a tenant-owned model."""
    return select(model_type).where(_required_column(model_type, "tenant_id") == tenant_id)


def tenant_entity_select(
    model_type: type[ModelT],
    tenant_id: UUID,
    entity_id: UUID,
) -> Select[tuple[ModelT]]:
    """Build a tenant-scoped primary-key lookup statement."""
    return tenant_select(model_type, tenant_id).where(
        _required_column(model_type, "id") == entity_id
    )


def apply_for_update(statement: Select[tuple[ModelT]]) -> Select[tuple[ModelT]]:
    """Return a statement with explicit pessimistic locking enabled."""
    return statement.with_for_update()


def with_options(
    statement: Select[tuple[ModelT]],
    *options: ExecutableOption,
) -> Select[tuple[ModelT]]:
    """Apply explicit ORM loading options chosen by a concrete repository."""
    return statement.options(*options)


def _required_column(
    model_type: type[object],
    column_name: str,
) -> InstrumentedAttribute[Any]:
    column = getattr(model_type, column_name, None)
    if column is None:
        raise TypeError(
            f"{model_type.__name__} does not expose required column {column_name!r}"
        )
    return cast(InstrumentedAttribute[Any], column)
