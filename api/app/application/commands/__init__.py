"""Immutable application command contracts."""

from app.application.commands.resources import (
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
    "AssignResourceClassificationCommand",
    "AssignResourceIdentifierCommand",
    "AssignResourceLabelCommand",
    "AssignResourceOwnershipCommand",
    "AssignResourceRelationshipCommand",
    "CreateResourceCommand",
    "EnsureResourceExistsCommand",
    "TransitionResourceStateCommand",
]
