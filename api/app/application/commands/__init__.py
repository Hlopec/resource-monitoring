"""Immutable application command contracts."""

from app.application.commands.resources import (
    AssignResourceAliasCommand,
    AssignResourceClassificationCommand,
    AssignResourceIdentifierCommand,
    AssignResourceLabelCommand,
    AssignResourceOwnershipCommand,
    AssignResourceRelationshipCommand,
    CreateResourceCommand,
    EnsureResourceExistsCommand,
    TransitionResourceStateCommand,
)

__all__ = [
    "AssignResourceAliasCommand",
    "AssignResourceClassificationCommand",
    "AssignResourceIdentifierCommand",
    "AssignResourceLabelCommand",
    "AssignResourceOwnershipCommand",
    "AssignResourceRelationshipCommand",
    "CreateResourceCommand",
    "EnsureResourceExistsCommand",
    "TransitionResourceStateCommand",
]
