"""Application-facing error taxonomy."""


class ApplicationError(Exception):
    """Base class for errors that application use cases may raise."""


class EntityNotFoundError(ApplicationError):
    """A requested entity was not found within the caller's allowed scope."""


class ConflictError(ApplicationError):
    """An operation conflicts with an existing invariant or state."""


class ConcurrentModificationError(ConflictError):
    """An optimistic or transactional concurrency conflict was detected."""


class TenantBoundaryError(ApplicationError):
    """A tenant-scoped operation attempted to cross an explicit tenant boundary."""


class PersistenceError(ApplicationError):
    """A storage-layer failure after translation at the persistence boundary."""
