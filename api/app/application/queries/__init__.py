"""Immutable application query contracts."""

from app.application.queries.resources import (
    GetResourceByCanonicalNameQuery,
    GetResourceByIdQuery,
    GetResourceDetailsQuery,
)

__all__ = [
    "GetResourceByCanonicalNameQuery",
    "GetResourceByIdQuery",
    "GetResourceDetailsQuery",
]
