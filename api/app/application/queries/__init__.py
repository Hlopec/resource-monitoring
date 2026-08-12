"""Immutable application query contracts."""

from app.application.queries.resources import (
    GetResourceByCanonicalNameQuery,
    GetResourceByIdQuery,
    GetResourceDetailsQuery,
    ResolveCanonicalResourceQuery,
)

__all__ = [
    "GetResourceByCanonicalNameQuery",
    "GetResourceByIdQuery",
    "GetResourceDetailsQuery",
    "ResolveCanonicalResourceQuery",
]
