"""Application-facing error taxonomy."""

from __future__ import annotations

from dataclasses import dataclass


class ApplicationError(Exception):
    """Base class for errors that application use cases may raise."""


@dataclass(frozen=True)
class ValidationFailure:
    """Technology-neutral validation failure detail."""

    field: str
    message: str


class EntityNotFoundError(ApplicationError):
    """A requested entity was not found within the caller's allowed scope."""

    def __init__(
        self,
        message: str,
        *,
        entity_type: str | None = None,
        lookup_field: str | None = None,
        lookup_value: object | None = None,
    ) -> None:
        super().__init__(message)
        self.entity_type = entity_type
        self.lookup_field = lookup_field
        self.lookup_value = lookup_value


class ConflictError(ApplicationError):
    """An operation conflicts with an existing invariant or state."""

    def __init__(
        self,
        message: str,
        *,
        entity_type: str | None = None,
        conflict_field: str | None = None,
        conflict_value: object | None = None,
        constraint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.entity_type = entity_type
        self.conflict_field = conflict_field
        self.conflict_value = conflict_value
        self.constraint = constraint


class ValidationError(ApplicationError):
    """Input command or query data failed application validation."""

    def __init__(
        self,
        message: str,
        *,
        failures: tuple[ValidationFailure, ...] = (),
    ) -> None:
        super().__init__(message)
        self.failures = failures


class ConcurrentModificationError(ConflictError):
    """An optimistic or transactional concurrency conflict was detected."""


class TenantBoundaryError(ApplicationError):
    """A tenant-scoped operation attempted to cross an explicit tenant boundary."""


class PersistenceError(ApplicationError):
    """A storage-layer failure after translation at the persistence boundary."""
