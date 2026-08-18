"""Pydantic schemas owned by the HTTP transport layer."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer


def require_aware_datetime(value: datetime) -> datetime:
    """Reject naive datetimes without changing the accepted value."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(require_aware_datetime)]
ApiDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda value: str(value), return_type=str, when_used="json"),
]


class ApiSchema(BaseModel):
    """Base class for explicit transport schemas."""

    model_config = ConfigDict(
        from_attributes=False,
    )


class RootResponse(ApiSchema):
    service: str
    status: str


class StatusResponse(ApiSchema):
    status: str


class ResourceSummaryResponse(ApiSchema):
    resource_id: UUID
    tenant_id: UUID
    resource_type_id: UUID
    lifecycle_status_id: UUID
    canonical_name: str
    display_name: str | None
    primary_organization_id: UUID | None
    primary_ownership_role_id: UUID | None
    record_version: int
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ResourcePageResponse(ApiSchema):
    items: list[ResourceSummaryResponse]
    next_cursor: str | None
