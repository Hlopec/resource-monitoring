"""Application handler contracts and reference handlers."""

from app.application.handlers.protocols import CommandHandler, QueryHandler
from app.application.handlers.resources import (
    CreateResourceHandler,
    EnsureResourceExistsHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
    TransitionResourceStateHandler,
)

__all__ = [
    "CommandHandler",
    "CreateResourceHandler",
    "EnsureResourceExistsHandler",
    "GetResourceByCanonicalNameHandler",
    "GetResourceByIdHandler",
    "GetResourceDetailsHandler",
    "QueryHandler",
    "TransitionResourceStateHandler",
]
