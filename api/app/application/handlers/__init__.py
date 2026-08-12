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
    MergeResourceHandler,
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
    "MergeResourceHandler",
    "QueryHandler",
    "TransitionResourceStateHandler",
]
