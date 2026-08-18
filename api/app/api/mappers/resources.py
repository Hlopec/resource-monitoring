"""Explicit Resource application-result to API-schema mappers."""

from app.api.schemas import ResourcePageResponse, ResourceSummaryResponse
from app.application.results import ResourcePageResult, ResourceSummaryResult


def resource_summary_response(
    result: ResourceSummaryResult,
) -> ResourceSummaryResponse:
    return ResourceSummaryResponse(
        resource_id=result.resource_id,
        tenant_id=result.tenant_id,
        resource_type_id=result.resource_type_id,
        lifecycle_status_id=result.lifecycle_status_id,
        canonical_name=result.canonical_name,
        display_name=result.display_name,
        primary_organization_id=result.primary_organization_id,
        primary_ownership_role_id=result.primary_ownership_role_id,
        record_version=result.record_version,
        first_seen_at=result.first_seen_at,
        last_seen_at=result.last_seen_at,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )


def resource_page_response(result: ResourcePageResult) -> ResourcePageResponse:
    return ResourcePageResponse(
        items=[resource_summary_response(item) for item in result.items],
        next_cursor=result.next_cursor,
    )
