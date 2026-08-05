"""Generic application handler protocols."""

from __future__ import annotations

from typing import Protocol, TypeVar

C = TypeVar("C")
Q = TypeVar("Q")
R = TypeVar("R", covariant=True)


class CommandHandler(Protocol[C, R]):
    """Handle one command using constructor-injected dependencies."""

    def handle(self, command: C) -> R:
        """Execute a command and return its result."""
        ...


class QueryHandler(Protocol[Q, R]):
    """Handle one read-only query using constructor-injected dependencies."""

    def handle(self, query: Q) -> R:
        """Execute a query and return its result."""
        ...
