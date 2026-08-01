"""Label repository contract."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.models import Label


class LabelRepository(Protocol):
    """Tenant-aware persistence contract for label definitions."""

    def get_by_id(
        self,
        tenant_id: UUID,
        label_id: UUID,
    ) -> Label | None:
        """Return a label within tenant scope, or ``None`` when absent."""
        ...

    def get_by_key_value(
        self,
        tenant_id: UUID,
        key: str,
        value: str,
    ) -> Label | None:
        """Return a label by tenant-local canonical key and value."""
        ...

    def exists_by_key_value(
        self,
        tenant_id: UUID,
        key: str,
        value: str,
    ) -> bool:
        """Return whether a label key/value exists within tenant scope."""
        ...

    def list_active(
        self,
        tenant_id: UUID,
    ) -> Sequence[Label]:
        """Return active labels for a tenant."""
        ...

    def add(self, label: Label) -> None:
        """Add a label to the current Unit of Work."""
        ...
