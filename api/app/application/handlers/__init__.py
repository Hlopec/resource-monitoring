"""Application handler contracts and reference handlers."""

from app.application.handlers.protocols import CommandHandler, QueryHandler
from app.application.handlers.resources import (
    EnsureResourceExistsHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
)

__all__ = [
    "CommandHandler",
    "EnsureResourceExistsHandler",
    "GetResourceByCanonicalNameHandler",
    "GetResourceByIdHandler",
    "GetResourceDetailsHandler",
    "QueryHandler",
]
