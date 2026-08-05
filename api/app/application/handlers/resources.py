"""Reference resource handlers for application architecture tests."""

from __future__ import annotations

from app.application.commands import EnsureResourceExistsCommand
from app.application.errors import EntityNotFoundError
from app.application.ports import UnitOfWorkFactory
from app.application.queries import GetResourceByIdQuery
from app.application.results import ResourceReadResult


class GetResourceByIdHandler:
    """Read-only reference handler for tenant-scoped resource lookup."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(self, query: GetResourceByIdQuery) -> ResourceReadResult:
        """Return a resource projection or raise a technology-neutral miss."""
        with self._uow_factory() as uow:
            resource = uow.resources.get_by_id(query.tenant_id, query.resource_id)
            if resource is None:
                raise EntityNotFoundError("Resource not found")
            return ResourceReadResult(
                id=resource.id,
                tenant_id=resource.tenant_id,
                canonical_name=resource.canonical_name,
                display_name=resource.display_name,
            )


class EnsureResourceExistsHandler:
    """Reference command handler that validates resource presence."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def handle(self, command: EnsureResourceExistsCommand) -> None:
        """Validate resource presence and commit the successful command."""
        with self._uow_factory() as uow:
            if not uow.resources.exists(command.tenant_id, command.resource_id):
                raise EntityNotFoundError("Resource not found")
            uow.commit()
