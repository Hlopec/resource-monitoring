"""Application handler contracts and reference handlers."""

from app.application.handlers.protocols import CommandHandler, QueryHandler
from app.application.handlers.resources import (
    AssignResourceIdentifierHandler,
    AssignResourceOwnershipHandler,
    CreateResourceHandler,
    EnsureResourceExistsHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
    TransitionResourceStateHandler,
)

__all__ = [
    "AssignResourceIdentifierHandler",
    "AssignResourceOwnershipHandler",
    "CommandHandler",
    "CreateResourceHandler",
    "EnsureResourceExistsHandler",
    "GetResourceByCanonicalNameHandler",
    "GetResourceByIdHandler",
    "GetResourceDetailsHandler",
    "QueryHandler",
    "TransitionResourceStateHandler",
]
