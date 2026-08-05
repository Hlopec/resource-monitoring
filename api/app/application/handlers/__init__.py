"""Application handler contracts and reference handlers."""

from app.application.handlers.protocols import CommandHandler, QueryHandler
from app.application.handlers.resources import (
    EnsureResourceExistsHandler,
    GetResourceByIdHandler,
)

__all__ = [
    "CommandHandler",
    "EnsureResourceExistsHandler",
    "GetResourceByIdHandler",
    "QueryHandler",
]
