"""Immutable application query contracts."""

from app.application.queries.resources import (
    DEFAULT_RESOURCE_PAGE_SIZE,
    GetResourceByCanonicalNameQuery,
    GetResourceByIdQuery,
    GetResourceDetailsQuery,
    ListResourcesQuery,
    MAX_RESOURCE_PAGE_SIZE,
    MIN_RESOURCE_PAGE_SIZE,
    ResolveCanonicalResourceQuery,
)

__all__ = [
    "DEFAULT_RESOURCE_PAGE_SIZE",
    "GetResourceByCanonicalNameQuery",
    "GetResourceByIdQuery",
    "GetResourceDetailsQuery",
    "ListResourcesQuery",
    "MAX_RESOURCE_PAGE_SIZE",
    "MIN_RESOURCE_PAGE_SIZE",
    "ResolveCanonicalResourceQuery",
]
