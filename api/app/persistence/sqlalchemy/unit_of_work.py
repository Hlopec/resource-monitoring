"""Concrete synchronous SQLAlchemy Unit of Work."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from types import TracebackType

from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]


class UnitOfWorkError(RuntimeError):
    """Base class for SQLAlchemy Unit of Work lifecycle misuse."""


class UnitOfWorkNotActiveError(UnitOfWorkError):
    """The Unit of Work has no active session."""


class UnitOfWorkStateError(UnitOfWorkError):
    """The Unit of Work is in a state that rejects the requested operation."""


class _UnitOfWorkState(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    CLOSED = "closed"


class SQLAlchemyUnitOfWork:
    """Single-use synchronous SQLAlchemy Unit of Work.

    The ``session`` property is a concrete persistence-facing escape hatch for
    future SQLAlchemy repositories. It is intentionally not part of the
    application-facing Unit of Work protocol.
    """

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        if session_factory is None:
            from app.db.session import SessionLocal

            session_factory = SessionLocal

        self._session_factory = session_factory
        self._session: Session | None = None
        self._state = _UnitOfWorkState.NEW

    def __enter__(self) -> SQLAlchemyUnitOfWork:
        if self._state is _UnitOfWorkState.ACTIVE:
            raise UnitOfWorkStateError("Unit of Work is already active")
        if self._state is not _UnitOfWorkState.NEW:
            raise UnitOfWorkStateError("Unit of Work instances are single-use")

        self._session = self._session_factory()
        self._state = _UnitOfWorkState.ACTIVE
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        session = self._session
        if session is not None:
            try:
                if exc_type is not None:
                    self._rollback_for_cleanup()
                elif self._state is not _UnitOfWorkState.COMMITTED:
                    self._rollback_for_cleanup()
            finally:
                session.close()
                self._session = None
                self._state = _UnitOfWorkState.CLOSED

        return False

    @property
    def session(self) -> Session:
        """Return the active SQLAlchemy session for infrastructure adapters."""
        session = self._require_session()
        if self._state is not _UnitOfWorkState.ACTIVE:
            raise UnitOfWorkNotActiveError("Unit of Work is not active")
        if not session.is_active:
            self._state = _UnitOfWorkState.FAILED
            raise UnitOfWorkStateError("Unit of Work transaction has failed")
        return session

    def commit(self) -> None:
        session = self._require_session()
        if self._state is _UnitOfWorkState.ROLLED_BACK:
            raise UnitOfWorkStateError("Cannot commit after rollback")
        if self._state is _UnitOfWorkState.COMMITTED:
            raise UnitOfWorkStateError("Unit of Work has already committed")
        if self._state is _UnitOfWorkState.FAILED or not session.is_active:
            self._state = _UnitOfWorkState.FAILED
            raise UnitOfWorkStateError("Cannot commit a failed transaction")
        if self._state is not _UnitOfWorkState.ACTIVE:
            raise UnitOfWorkNotActiveError("Unit of Work is not active")

        try:
            session.commit()
        except Exception:
            self._state = _UnitOfWorkState.FAILED
            raise

        self._state = _UnitOfWorkState.COMMITTED

    def rollback(self) -> None:
        session = self._require_session()
        if self._state is _UnitOfWorkState.COMMITTED:
            raise UnitOfWorkStateError("Cannot roll back after commit")
        if self._state is not _UnitOfWorkState.ROLLED_BACK:
            session.rollback()
            self._state = _UnitOfWorkState.ROLLED_BACK

    def _rollback_for_cleanup(self) -> None:
        if self._session is None:
            return
        if self._state is _UnitOfWorkState.COMMITTED:
            return
        self._session.rollback()
        if self._state is not _UnitOfWorkState.CLOSED:
            self._state = _UnitOfWorkState.ROLLED_BACK

    def _require_session(self) -> Session:
        if self._session is None:
            raise UnitOfWorkNotActiveError("Unit of Work is not active")
        if self._state is _UnitOfWorkState.CLOSED:
            raise UnitOfWorkNotActiveError("Unit of Work is closed")
        return self._session
