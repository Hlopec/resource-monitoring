"""Session-bound primitives for internal SQLAlchemy repositories."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")
RepositoryT = TypeVar("RepositoryT", bound="SQLAlchemyRepository[Any]")


class SQLAlchemyRepository(Generic[ModelT]):
    """Minimal base for repositories bound to one active Unit of Work session.

    The repository never creates, commits, rolls back, or closes sessions. Flush
    is explicit so concrete repositories only call it when generated/default
    values, constraint validation, or dependent writes require database
    synchronization.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        """Return the injected SQLAlchemy session for infrastructure tests."""
        return self._session

    def add(self, entity: ModelT) -> None:
        """Attach an entity to the active Unit of Work session."""
        self._session.add(entity)

    def flush(self) -> None:
        """Flush pending work without committing or rolling back the transaction."""
        self._session.flush()

    def refresh(self, entity: ModelT) -> None:
        """Refresh an entity from the database when a concrete operation asks for it."""
        self._session.refresh(entity)

    def _scalar(self, statement: Select[tuple[ModelT]]) -> ModelT | None:
        return self._session.scalar(statement)

    def _scalars(self, statement: Select[tuple[ModelT]]) -> Sequence[ModelT]:
        return list(self._session.scalars(statement))

    def _exists(self, statement: Select[tuple[ModelT]]) -> bool:
        return bool(self._session.scalar(select(statement.exists())))


def bind_repository(
    repository_type: type[RepositoryT],
    session: Session,
) -> RepositoryT:
    """Construct a repository with the active Unit of Work session."""
    return repository_type(session)
