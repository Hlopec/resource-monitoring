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


class ApiErrorDetail(ApiSchema):
    field: str
    message: str


class ApiError(ApiSchema):
    code: str
    message: str
    details: list[ApiErrorDetail]


class ApiErrorResponse(ApiSchema):
    error: ApiError


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


class ResourceStateResponse(ApiSchema):
    id: UUID
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID
    source_priority: int
    confidence_score: ApiDecimal
    valid_from: AwareDatetime
    source: str | None


class ResourceIdentifierResponse(ApiSchema):
    id: UUID
    identifier_type_id: UUID
    namespace: str | None
    normalized_value: str
    original_value: str
    is_primary: bool
    confidence_score: ApiDecimal
    valid_from: AwareDatetime


class ResourceOwnershipResponse(ApiSchema):
    id: UUID
    organization_id: UUID
    ownership_role_id: UUID
    is_primary: bool
    confidence_score: ApiDecimal
    valid_from: AwareDatetime
    source: str | None


class ResourceClassificationResponse(ApiSchema):
    id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    is_primary: bool
    confidence_score: ApiDecimal
    valid_from: AwareDatetime
    source: str | None


class ResourceLabelResponse(ApiSchema):
    id: UUID
    label_id: UUID
    valid_from: AwareDatetime
    source: str | None


class ResourceAliasResponse(ApiSchema):
    id: UUID
    alias_type: str
    alias_value: str
    normalized_value: str
    source: str | None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime


class ResourceMergeResponse(ApiSchema):
    id: UUID
    source_resource_id: UUID
    target_resource_id: UUID
    reason: str | None
    source: str | None
    merged_at: AwareDatetime


class ResourceDetailsResponse(ApiSchema):
    id: UUID
    tenant_id: UUID
    organization_id: UUID | None
    resource_type_id: UUID
    canonical_name: str
    display_name: str
    record_version: int
    created_at: AwareDatetime
    updated_at: AwareDatetime
    state: ResourceStateResponse | None
    identifiers: list[ResourceIdentifierResponse]
    ownership: list[ResourceOwnershipResponse]
    classifications: list[ResourceClassificationResponse]
    labels: list[ResourceLabelResponse]
    aliases: list[ResourceAliasResponse]
    outgoing_merge: ResourceMergeResponse | None


class ResourceStateHistoryResponse(ApiSchema):
    id: UUID
    lifecycle_status_id: UUID
    criticality_id: UUID
    exposure_level_id: UUID
    source_priority: int
    confidence_score: ApiDecimal
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None
    source: str | None


class ResourceOwnershipHistoryResponse(ApiSchema):
    id: UUID
    organization_id: UUID
    ownership_role_id: UUID
    is_primary: bool
    confidence_score: ApiDecimal
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None
    source: str | None


class ResourceLabelHistoryResponse(ApiSchema):
    id: UUID
    label_id: UUID
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None
    source: str | None


class ResourceClassificationHistoryResponse(ApiSchema):
    id: UUID
    classification_type_id: UUID
    classification_value_id: UUID
    is_primary: bool
    confidence_score: ApiDecimal
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None
    source: str | None


class ResourceIdentifierHistoryResponse(ApiSchema):
    id: UUID
    identifier_type_id: UUID
    namespace: str | None
    normalized_value: str
    original_value: str
    is_primary: bool
    confidence_score: ApiDecimal
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None


class ResourceHistoryResponse(ApiSchema):
    id: UUID
    tenant_id: UUID
    resource_type_id: UUID
    canonical_name: str
    display_name: str
    states: list[ResourceStateHistoryResponse]
    ownership: list[ResourceOwnershipHistoryResponse]
    labels: list[ResourceLabelHistoryResponse]
    classifications: list[ResourceClassificationHistoryResponse]
    identifiers: list[ResourceIdentifierHistoryResponse]
