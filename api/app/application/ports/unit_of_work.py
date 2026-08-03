"""Application-facing Unit of Work protocol."""

from types import TracebackType
from typing import Protocol, Self

from app.application.ports.organizations import OrganizationRepository
from app.application.ports.resources import ResourceRepository
from app.application.ports.tenants import TenantRepository


class UnitOfWork(Protocol):
    """Transactional boundary owned by one application command or use case.

    Concrete implementations enter a session/transaction on ``__enter__`` and
    close it on ``__exit__``. They roll back when an exception is raised and also
    when the context exits without an explicit successful ``commit()``.
    Repository instances exposed by a concrete Unit of Work share its session and
    must not commit independently.
    """

    tenants: TenantRepository
    organizations: OrganizationRepository
    resources: ResourceRepository

    def __enter__(self) -> Self:
        """Open the Unit of Work and return the active instance."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Close the Unit of Work, rolling back when required."""
        ...

    def commit(self) -> None:
        """Commit the current transaction explicitly."""
        ...

    def rollback(self) -> None:
        """Roll back the current transaction explicitly."""
        ...
