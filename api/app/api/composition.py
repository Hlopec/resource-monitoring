"""API composition boundary for application handlers and persistence adapters."""

from app.application.ports import UnitOfWorkFactory
from app.persistence.sqlalchemy import SQLAlchemyUnitOfWork


def get_unit_of_work_factory() -> UnitOfWorkFactory:
    """Return the concrete Unit of Work factory for future route dependencies."""
    return SQLAlchemyUnitOfWork
