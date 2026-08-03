"""Read-only SQLAlchemy adapters for global managed catalogs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Generic, TypeVar, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.application.ports.catalogs import (
    ClassificationValueRepository,
    ManagedCatalogEntity,
    ManagedCatalogRepository,
)
from app.models import ClassificationValue
from app.persistence.sqlalchemy.repositories.helpers import entity_select

CatalogT = TypeVar("CatalogT", bound=ManagedCatalogEntity)


class SQLAlchemyManagedCatalogRepository(
    Generic[CatalogT],
    ManagedCatalogRepository[CatalogT],
):
    """Read-only repository for one global managed catalog model."""

    def __init__(
        self,
        session: Session,
        model_type: type[CatalogT],
    ) -> None:
        self._session = session
        self._model_type = model_type
        self._id = _required_mapped_attribute(model_type, "id")
        self._code = _required_mapped_attribute(model_type, "code")
        self._is_active = _required_mapped_attribute(model_type, "is_active")

    @property
    def session(self) -> Session:
        """Return the injected SQLAlchemy session for infrastructure tests."""
        return self._session

    @property
    def model_type(self) -> type[CatalogT]:
        """Return the catalog model this repository reads."""
        return self._model_type

    def get_by_id(self, catalog_id: UUID) -> CatalogT | None:
        return self._session.scalar(entity_select(self._model_type, catalog_id))

    def get_by_code(self, code: str) -> CatalogT | None:
        statement = (
            select(self._model_type)
            .where(self._code == code)
            .order_by(self._id.asc())
        )
        return self._session.scalar(statement)

    def list_active(self) -> Sequence[CatalogT]:
        statement = (
            select(self._model_type)
            .where(self._is_active.is_(True))
            .order_by(self._code.asc(), self._id.asc())
        )
        return list(self._session.scalars(statement))


class SQLAlchemyClassificationValueRepository(ClassificationValueRepository):
    """Read-only repository for classification values scoped by type."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._id = _required_mapped_attribute(ClassificationValue, "id")
        self._classification_type_id = _required_mapped_attribute(
            ClassificationValue,
            "classification_type_id",
        )
        self._code = _required_mapped_attribute(ClassificationValue, "code")
        self._is_active = _required_mapped_attribute(ClassificationValue, "is_active")

    @property
    def session(self) -> Session:
        """Return the injected SQLAlchemy session for infrastructure tests."""
        return self._session

    def get_by_id(self, catalog_id: UUID) -> ClassificationValue | None:
        return self._session.scalar(entity_select(ClassificationValue, catalog_id))

    def get_by_type_and_code(
        self,
        classification_type_id: UUID,
        code: str,
    ) -> ClassificationValue | None:
        statement = (
            select(ClassificationValue)
            .where(
                self._classification_type_id == classification_type_id,
                self._code == code,
            )
            .order_by(self._id.asc())
        )
        return self._session.scalar(statement)

    def list_active_for_type(
        self,
        classification_type_id: UUID,
    ) -> Sequence[ClassificationValue]:
        statement = (
            select(ClassificationValue)
            .where(
                self._classification_type_id == classification_type_id,
                self._is_active.is_(True),
            )
            .order_by(self._code.asc(), self._id.asc())
        )
        return list(self._session.scalars(statement))


def _required_mapped_attribute(
    model_type: type[object],
    attribute_name: str,
) -> InstrumentedAttribute[object]:
    attribute = getattr(model_type, attribute_name, None)
    if not isinstance(attribute, InstrumentedAttribute):
        raise TypeError(
            f"{model_type.__name__} does not expose required mapped attribute "
            f"{attribute_name!r}"
        )
    return cast(InstrumentedAttribute[object], attribute)
