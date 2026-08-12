"""Application handler contracts and reference handlers."""

from app.application.handlers.protocols import CommandHandler, QueryHandler
from app.application.handlers.resources import (
    AssignResourceAliasHandler,
    AssignResourceClassificationHandler,
    AssignResourceIdentifierHandler,
    AssignResourceLabelHandler,
    AssignResourceOwnershipHandler,
    AssignResourceRelationshipHandler,
    CreateResourceHandler,
    EnsureResourceExistsHandler,
    GetResourceByCanonicalNameHandler,
    GetResourceByIdHandler,
    GetResourceDetailsHandler,
    TransitionResourceStateHandler,
)

__all__ = [
    "AssignResourceAliasHandler",
    "AssignResourceClassificationHandler",
    "AssignResourceIdentifierHandler",
    "AssignResourceLabelHandler",
    "AssignResourceOwnershipHandler",
    "AssignResourceRelationshipHandler",
    "CommandHandler",
    "CreateResourceHandler",
    "EnsureResourceExistsHandler",
    "GetResourceByCanonicalNameHandler",
    "GetResourceByIdHandler",
    "GetResourceDetailsHandler",
    "QueryHandler",
    "TransitionResourceStateHandler",
]
